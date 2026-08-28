from __future__ import annotations

import copy
import hashlib
import json

import pytest

from omni_benchmark.direct_runtime_binding import (
    DirectBudgetIdentity,
    DirectContextIdentity,
    DirectDatabaseIdentity,
    DirectModelIdentity,
    DirectQuestionIdentity,
    DirectRuntimeBinding,
    DirectRuntimeIdentityError,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _question() -> dict[str, object]:
    question = "Which public sites have the best scan quality?"
    return {
        "instance_id": "archeology_scan_1",
        "public_manifest_path": "data/manifests/eligible_questions.jsonl",
        "public_manifest_sha256": SHA_A,
        "public_record_sha256": SHA_B,
        "question": question,
        "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
        "scope": "dev-a",
        "scope_ids_path": "data/manifests/dev_a_ids.txt",
        "scope_ids_sha256": SHA_C,
        "selected_database": "archeology_scan_large",
    }


def _database() -> dict[str, object]:
    return {
        "backend": "postgresql",
        "connection_target_sha256": SHA_A,
        "content_sha256": SHA_B,
        "database_record_sha256": SHA_C,
        "deployment_identity_sha256": SHA_D,
        "inventory_sha256": SHA_E,
        "physical_database": "neondb",
        "postgres_server_version_num": 180000,
        "runtime_role": "omni_benchmark_reader",
        "schema_sha256": SHA_F,
        "selected_database": "archeology_scan_large",
    }


def _model() -> dict[str, object]:
    return {
        "adapter": "claude-code-restricted-mcp",
        "adapter_version": "1.0.0",
        "executable_sha256": SHA_A,
        "executable_version": "2.1.250",
        "model": "claude-opus-4-6",
        "provider": "anthropic-first-party",
        "system_prompt_sha256": SHA_B,
        "transport_config_sha256": SHA_C,
    }


def _budget() -> dict[str, object]:
    return {
        "budget_id": "direct-sql-production-v1",
        "maximum_turns": 12,
        "per_turn_max_cost_usd": 5.0,
        "per_turn_timeout_seconds": 120.0,
    }


def _context() -> DirectContextIdentity:
    return DirectContextIdentity.from_components(
        condition="C1",
        selected_database="archeology_scan_large",
        component_sha256={
            "condition_config": SHA_A,
            "instructions": SHA_B,
            "prompt": SHA_C,
            "schema": SHA_D,
        },
        environment={},
    )


def _binding_dict() -> dict[str, object]:
    question = DirectQuestionIdentity.from_dict(_question(), environment={})
    database = DirectDatabaseIdentity.from_dict(_database(), environment={})
    model = DirectModelIdentity.from_dict(_model(), environment={})
    budget = DirectBudgetIdentity.from_dict(_budget(), environment={})
    binding = DirectRuntimeBinding.from_parts(
        system_commit="1" * 40,
        run_id="baseline-001",
        repetition=1,
        condition="C1",
        question=question,
        context=_context(),
        database=database,
        model=model,
        budget=budget,
        environment={},
    )
    return binding.as_dict()


def _replace_context(value: dict[str, object], **changes: str) -> None:
    context = value["context"]
    assert isinstance(context, dict)
    replacement = DirectContextIdentity.from_components(
        condition=changes.get("condition", context["condition"]),  # type: ignore[arg-type]
        selected_database=changes.get(
            "selected_database",
            context["selected_database"],  # type: ignore[arg-type]
        ),
        component_sha256=context["component_sha256"],  # type: ignore[arg-type]
        environment={},
    )
    value["context"] = replacement.as_dict()


def test_runtime_binding_is_frozen_canonical_and_deterministic() -> None:
    first = DirectRuntimeBinding.from_dict(_binding_dict(), environment={})
    reordered = dict(reversed(tuple(_binding_dict().items())))
    second = DirectRuntimeBinding.from_dict(reordered, environment={})

    assert first == second
    assert first.attempt_id == "baseline-001:archeology_scan_1:C1:1"
    assert first.sha256() == second.sha256()
    assert (
        first.canonical_bytes()
        == (
            json.dumps(
                first.as_dict(),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
    )
    with pytest.raises(AttributeError):
        first.run_id = "changed"  # type: ignore[misc]


def test_context_digest_is_derived_from_exact_sorted_components() -> None:
    first = _context()
    second = DirectContextIdentity.from_components(
        condition="C1",
        selected_database="archeology_scan_large",
        component_sha256=dict(reversed(first.component_sha256)),
        environment={},
    )

    assert first == second
    assert first.context_sha256 == second.context_sha256
    assert DirectContextIdentity.from_dict(first.as_dict(), environment={}) == first

    forged = first.as_dict()
    forged["context_sha256"] = SHA_F
    with pytest.raises(DirectRuntimeIdentityError, match="context_sha256"):
        DirectContextIdentity.from_dict(forged, environment={})


@pytest.mark.parametrize(
    ("factory", "value"),
    [
        (DirectQuestionIdentity.from_dict, _question()),
        (DirectDatabaseIdentity.from_dict, _database()),
        (DirectModelIdentity.from_dict, _model()),
        (DirectBudgetIdentity.from_dict, _budget()),
        (DirectRuntimeBinding.from_dict, _binding_dict()),
    ],
)
def test_identities_reject_non_exact_schemas(factory: object, value: object) -> None:
    extra = copy.deepcopy(value)
    assert isinstance(extra, dict)
    extra["unexpected"] = "field"
    with pytest.raises(DirectRuntimeIdentityError, match="exact schema"):
        factory(extra, environment={})  # type: ignore[operator]

    missing = copy.deepcopy(value)
    missing.pop(next(iter(missing)))
    with pytest.raises(DirectRuntimeIdentityError, match="exact schema"):
        factory(missing, environment={})  # type: ignore[operator]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_identity_rejects_nonfinite_content_recursively(invalid: float) -> None:
    value = _binding_dict()
    value["budget"]["per_turn_max_cost_usd"] = invalid  # type: ignore[index]

    with pytest.raises(DirectRuntimeIdentityError, match="finite JSON"):
        DirectRuntimeBinding.from_dict(value, environment={})


def test_identity_rejects_live_secrets_recursively() -> None:
    value = _binding_dict()
    value["model"]["adapter"] = "fixture-live-secret"  # type: ignore[index]

    with pytest.raises(DirectRuntimeIdentityError, match="sensitive content"):
        DirectRuntimeBinding.from_dict(
            value,
            environment={"BENCHMARK_TOKEN": "fixture-live-secret"},
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda value: _replace_context(value, condition="C2"),
            "context condition",
        ),
        (
            lambda value: value["database"].__setitem__(
                "selected_database", "other_large"
            ),
            "database identity",
        ),
        (
            lambda value: _replace_context(value, selected_database="other_large"),
            "context database",
        ),
        (lambda value: value.__setitem__("attempt_id", "forged"), "attempt_id"),
    ],
)
def test_runtime_binding_rejects_cross_identity_mismatches(
    mutator: object, message: str
) -> None:
    value = _binding_dict()
    mutator(value)  # type: ignore[operator]

    with pytest.raises(DirectRuntimeIdentityError, match=message):
        DirectRuntimeBinding.from_dict(value, environment={})


@pytest.mark.parametrize(
    ("factory", "value", "message"),
    [
        (
            DirectQuestionIdentity.from_dict,
            {**_question(), "question_sha256": SHA_A},
            "question_sha256",
        ),
        (
            DirectQuestionIdentity.from_dict,
            {**_question(), "scope": "test"},
            "scope",
        ),
        (
            DirectDatabaseIdentity.from_dict,
            {**_database(), "backend": "mysql"},
            "backend",
        ),
        (
            DirectDatabaseIdentity.from_dict,
            {**_database(), "postgres_server_version_num": True},
            "server version",
        ),
        (
            DirectModelIdentity.from_dict,
            {**_model(), "executable_sha256": "not-a-digest"},
            "SHA-256",
        ),
        (
            DirectBudgetIdentity.from_dict,
            {**_budget(), "maximum_turns": 0},
            "maximum_turns",
        ),
        (
            DirectBudgetIdentity.from_dict,
            {**_budget(), "per_turn_timeout_seconds": 0.0},
            "timeout",
        ),
    ],
)
def test_identity_field_validation(
    factory: object, value: object, message: str
) -> None:
    with pytest.raises(DirectRuntimeIdentityError, match=message):
        factory(value, environment={})  # type: ignore[operator]


def test_runtime_binding_rejects_ambiguous_attempt_identifiers() -> None:
    value = _binding_dict()
    value["run_id"] = "run:ambiguous"
    value["attempt_id"] = "run:ambiguous:archeology_scan_1:C1:1"

    with pytest.raises(DirectRuntimeIdentityError, match="run_id"):
        DirectRuntimeBinding.from_dict(value, environment={})
