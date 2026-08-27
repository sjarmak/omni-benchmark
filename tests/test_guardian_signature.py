"""Adversarial tests for guardian-owned checkpoint artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from omni_benchmark.autoresearch_config import AutoresearchError
from omni_benchmark.autoresearch_guardian import (
    validate_dev_b_receipt,
    validate_taxonomy,
)


def _run_openssl(*arguments: str) -> None:
    subprocess.run(
        ["openssl", *arguments],
        check=True,
        capture_output=True,
        timeout=20,
    )


def _guardian_material(tmp_path: Path, payload: bytes) -> tuple[Path, Path, str]:
    private_key = tmp_path.parent / f"{tmp_path.name}-guardian-private.pem"
    public_key = tmp_path / "guardian-public.pem"
    signature = tmp_path / "receipt.sig"
    receipt = tmp_path / "receipt.json"
    receipt.write_bytes(payload)
    _run_openssl(
        "genpkey",
        "-algorithm",
        "RSA",
        "-pkeyopt",
        "rsa_keygen_bits:2048",
        "-out",
        str(private_key),
    )
    _run_openssl(
        "pkey",
        "-in",
        str(private_key),
        "-pubout",
        "-out",
        str(public_key),
    )
    _run_openssl(
        "dgst",
        "-sha256",
        "-sign",
        str(private_key),
        "-out",
        str(signature),
        str(receipt),
    )
    return public_key, signature, hashlib.sha256(public_key.read_bytes()).hexdigest()


def _receipt(candidate_digest: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "dev-b-checkpoint-receipt",
        "receipt_id": "checkpoint-1",
        "guardian": "synthetic-test-guardian",
        "created_at": "2026-08-27T12:00:00Z",
        "candidate_run_sha256": candidate_digest,
        "outputs_sha256": "c" * 64,
        "scorer_version": "synthetic-test-scorer-v1",
        "question_count": 1,
        "correct_count": 1,
        "wrong_answer_count": 0,
        "refused_or_error_count": 0,
    }


def _validate(
    tmp_path: Path,
    receipt: dict[str, object],
    *,
    candidate_digest: str,
    expected_key_digest: str | None = None,
) -> dict[str, object]:
    payload = json.dumps(receipt, sort_keys=True).encode()
    public_key, signature, key_digest = _guardian_material(tmp_path, payload)
    config = SimpleNamespace(workspace=tmp_path, expected_dev_b_count=1)
    return validate_dev_b_receipt(
        config,
        tmp_path / "receipt.json",
        candidate_run_sha256=candidate_digest,
        signature_path=signature,
        public_key_path=public_key,
        expected_public_key_sha256=expected_key_digest or key_digest,
    )


def test_receipt_requires_valid_signature_from_pinned_guardian_key(
    tmp_path: Path,
) -> None:
    candidate_digest = "a" * 64

    validated = _validate(
        tmp_path,
        _receipt(candidate_digest),
        candidate_digest=candidate_digest,
    )

    assert validated["signature_verified"] is True
    assert validated["guardian_public_key_sha256"]


def test_receipt_rejects_payload_changed_after_signature(tmp_path: Path) -> None:
    candidate_digest = "a" * 64
    payload = json.dumps(_receipt(candidate_digest), sort_keys=True).encode()
    public_key, signature, key_digest = _guardian_material(tmp_path, payload)
    receipt_path = tmp_path / "receipt.json"
    changed = {
        **_receipt(candidate_digest),
        "correct_count": 0,
        "wrong_answer_count": 1,
    }
    receipt_path.write_text(json.dumps(changed, sort_keys=True))
    config = SimpleNamespace(workspace=tmp_path, expected_dev_b_count=1)

    with pytest.raises(AutoresearchError, match="signature verification failed"):
        validate_dev_b_receipt(
            config,
            receipt_path,
            candidate_run_sha256=candidate_digest,
            signature_path=signature,
            public_key_path=public_key,
            expected_public_key_sha256=key_digest,
        )


def test_receipt_rejects_unpinned_guardian_key(tmp_path: Path) -> None:
    candidate_digest = "a" * 64

    with pytest.raises(AutoresearchError, match="public key does not match"):
        _validate(
            tmp_path,
            _receipt(candidate_digest),
            candidate_digest=candidate_digest,
            expected_key_digest="f" * 64,
        )


@pytest.mark.parametrize(
    "taxonomy",
    [
        {
            "categories": [{"name": "join", "count": 1, "primary_source": "model"}],
            "summary": "not part of the frozen public schema",
        },
        {
            "categories": [
                {
                    "name": "join",
                    "count": 1,
                    "primary_source": "model",
                    "examples": ["question-1"],
                }
            ]
        },
    ],
)
def test_taxonomy_schema_rejects_unknown_fields_recursively(
    tmp_path: Path, taxonomy: dict[str, object]
) -> None:
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy))

    with pytest.raises(AutoresearchError, match="invalid schema"):
        validate_taxonomy(path, expected_count=1)


def test_taxonomy_rejects_hidden_fields_before_accepting_nested_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "taxonomy.json"
    path.write_text(
        json.dumps(
            {
                "categories": [{"name": "join", "count": 1, "primary_source": "model"}],
                "diagnostic": {"external_knowledge": ["hidden-node"]},
            }
        )
    )

    with pytest.raises(AutoresearchError, match="forbidden field"):
        validate_taxonomy(path, expected_count=1)


def test_taxonomy_accepts_only_a_complete_aggregate_partition(tmp_path: Path) -> None:
    path = tmp_path / "taxonomy.json"
    payload = {
        "categories": [
            {"name": "join", "count": 1, "primary_source": "semantic model"},
            {"name": "compiler", "count": 0, "primary_source": "harness"},
        ]
    }
    path.write_text(json.dumps(payload))

    assert (
        validate_taxonomy(path, expected_count=1)
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    ("taxonomy", "message"),
    [
        ({"categories": "join"}, "array"),
        ({"categories": []}, "must not be empty"),
        (
            {"categories": [{"name": " ", "count": 1, "primary_source": "model"}]},
            "name",
        ),
        (
            {
                "categories": [
                    {"name": "join", "count": 1, "primary_source": "model"},
                    {"name": "join", "count": 0, "primary_source": "harness"},
                ]
            },
            "unique",
        ),
        (
            {"categories": [{"name": "join", "count": -1, "primary_source": "model"}]},
            "non-negative",
        ),
        (
            {"categories": [{"name": "join", "count": 1, "primary_source": " "}]},
            "primary_source",
        ),
        (
            {"categories": [{"name": "join", "count": 2, "primary_source": "model"}]},
            "exceed",
        ),
    ],
)
def test_taxonomy_rejects_invalid_aggregate_values(
    tmp_path: Path, taxonomy: dict[str, object], message: str
) -> None:
    path = tmp_path / "taxonomy.json"
    path.write_text(json.dumps(taxonomy))

    with pytest.raises(AutoresearchError, match=message):
        validate_taxonomy(path, expected_count=1)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"unexpected": "field"}, "invalid schema"),
        ({"schema_version": 2}, "version or kind"),
        ({"schema_version": True}, "version or kind"),
        ({"outputs_sha256": "not-a-digest"}, "SHA-256 digest"),
        ({"candidate_run_sha256": "b" * 64}, "does not match"),
        ({"correct_count": -1, "wrong_answer_count": 2}, "non-negative"),
        ({"question_count": 2, "correct_count": 2}, "exactly cover"),
        ({"question_count": True}, "question_count"),
    ],
)
def test_authenticated_receipt_still_requires_strict_aggregate_schema(
    tmp_path: Path, mutation: dict[str, object], message: str
) -> None:
    candidate_digest = "a" * 64
    receipt = {**_receipt(candidate_digest), **mutation}

    with pytest.raises(AutoresearchError, match=message):
        _validate(tmp_path, receipt, candidate_digest=candidate_digest)
