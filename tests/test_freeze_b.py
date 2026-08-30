from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from omni_benchmark.freeze_b import (
    FreezeBError,
    FreezeBManifest,
    SealedRunManifest,
    schedule_sha256,
)
from omni_benchmark.scoring import scorer_metadata


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
COMMIT = "f" * 40
FREEZE_A_COMMIT = "1" * 40


def _condition(condition: str) -> dict[str, object]:
    semantic_sha: str | None = None if condition == "C1" else SHA_E
    harness_sha = {
        "C1": SHA_A,
        "C2": SHA_B,
        "C3": SHA_C,
        "C4": SHA_D,
    }[condition]
    return {
        "budget_id": "sealed-default-v1",
        "condition": condition,
        "harness_config_sha256": harness_sha,
        "instructions_sha256": SHA_B,
        "model": "managed-standard",
        "model_config_id": "frozen-final-v1",
        "prompt_sha256": SHA_C,
        "provider": "aws-bedrock",
        "runtime_policy_sha256": SHA_D,
        "semantic_model_ref": "none" if condition == "C1" else "export:final-v1",
        "semantic_model_sha256": semantic_sha,
    }


def _schedule_ids() -> tuple[str, ...]:
    return tuple(
        f"sealed:q-{question}:{condition}:{repetition}"
        for question in range(1, 102)
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    )


def _freeze_value(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "conditions": [_condition(condition) for condition in ("C1", "C2", "C3", "C4")],
        "database": {
            "libpq_version": "18.6",
            "postgresql_version": "18.6",
            "snapshot_manifest_sha256": SHA_A,
        },
        "expected_test_outputs": 1_212,
        "freeze_a_commit": FREEZE_A_COMMIT,
        "frozen_files": {
            "EVALUATION_PROTOCOL.md": SHA_A,
            "config/conditions/c1-direct-sql-v1.json": SHA_B,
            "config/conditions/c2-direct-sql-v1.json": SHA_C,
            "config/conditions/c3-direct-sql-v1.json": SHA_D,
            "config/conditions/c4-production-v1.json": SHA_E,
        },
        "kind": "freeze-b-manifest",
        "question_count": 101,
        "recorded_at": "2026-08-29T05:30:00Z",
        "repetitions": 3,
        "schedule": {
            "algorithm": "committed_block_interleaved_v1",
            "seed": "human-supplied-final-seed",
            "sha256": schedule_sha256(_schedule_ids()),
        },
        "schema_version": 1,
        "scorer": {
            "metadata": scorer_metadata(),
            "source_commit": COMMIT,
        },
        "system_commit": COMMIT,
    }
    return {**value, **overrides}


def _run_value(freeze: FreezeBManifest, **overrides: object) -> dict[str, object]:
    condition = freeze.condition("C4")
    value: dict[str, object] = {
        "budget_id": condition.budget_id,
        "cli_versions": {"omni": "1.1.2"},
        "condition": "C4",
        "finished_at": "2026-08-29T06:02:00Z",
        "freeze_b_sha256": freeze.sha256(),
        "generation_sha256": SHA_B,
        "harness_config_sha256": condition.harness_config_sha256,
        "instructions_sha256": condition.instructions_sha256,
        "kind": "sealed-run-manifest",
        "model": condition.model,
        "model_config_id": condition.model_config_id,
        "prompt_sha256": condition.prompt_sha256,
        "provider": condition.provider,
        "question_count": 101,
        "repetition": 1,
        "runtime_policy_sha256": condition.runtime_policy_sha256,
        "schedule_sha256": freeze.schedule_sha256,
        "schema_version": 1,
        "scope": "test",
        "semantic_model_ref": condition.semantic_model_ref,
        "semantic_model_sha256": condition.semantic_model_sha256,
        "software_versions": {"omni-benchmark": "0.1.0", "python": "3.11.15"},
        "started_at": "2026-08-29T06:00:00Z",
        "system_commit": freeze.system_commit,
    }
    return {**value, **overrides}


def test_freeze_b_manifest_is_exact_canonical_and_immutable() -> None:
    manifest = FreezeBManifest.from_dict(_freeze_value())

    assert manifest.question_count == 101
    assert manifest.expected_test_outputs == 1_212
    assert manifest.condition("C3").semantic_model_sha256 == SHA_E
    assert manifest.condition("C4").semantic_model_sha256 == SHA_E
    assert manifest.condition("C1").semantic_model_sha256 is None
    assert (
        manifest.canonical_bytes()
        == (
            json.dumps(
                _freeze_value(),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
    )
    with pytest.raises(FrozenInstanceError):
        manifest.system_commit = "0" * 40  # type: ignore[misc]


def test_freeze_b_accepts_and_binds_matched_89_question_frame() -> None:
    schedule_ids = tuple(
        f"sealed:q-{question}:{condition}:{repetition}"
        for question in range(1, 90)
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    )
    freeze = FreezeBManifest.from_dict(
        _freeze_value(
            question_count=89,
            expected_test_outputs=1_068,
            schedule={
                "algorithm": "committed_block_interleaved_v1",
                "seed": "human-supplied-final-seed",
                "sha256": schedule_sha256(schedule_ids),
            },
        )
    )

    assert freeze.question_count == 89
    assert freeze.expected_test_outputs == 1_068
    run = SealedRunManifest.from_dict(
        _run_value(freeze, question_count=89), freeze_b=freeze
    )
    assert run.question_count == 89


def test_freeze_b_rejects_output_count_inconsistent_with_frame() -> None:
    with pytest.raises(FreezeBError, match="expected_test_outputs"):
        FreezeBManifest.from_dict(
            _freeze_value(question_count=89, expected_test_outputs=1_212)
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(question_count=0), "question_count"),
        (lambda value: value.update(repetitions=2), "repetitions"),
        (
            lambda value: value.update(expected_test_outputs=404),
            "expected_test_outputs",
        ),
        (lambda value: value.update(system_commit="f" * 39), "system_commit"),
        (
            lambda value: value["schedule"].update(sha256="A" * 64),  # type: ignore[union-attr]
            "schedule sha256",
        ),
        (
            lambda value: value["conditions"][2].update(semantic_model_sha256=None),  # type: ignore[index,union-attr]
            "C3 semantic_model_sha256",
        ),
        (
            lambda value: value["conditions"][3].update(semantic_model_sha256=None),  # type: ignore[index,union-attr]
            "C4 semantic_model_sha256",
        ),
        (
            lambda value: value["conditions"][0].update(semantic_model_sha256=SHA_A),  # type: ignore[index,union-attr]
            "C1 semantic_model_sha256",
        ),
        (
            lambda value: value["conditions"].reverse(),  # type: ignore[union-attr]
            "condition order",
        ),
        (
            lambda value: value["scorer"].update(source_commit="2" * 40),  # type: ignore[union-attr]
            "scorer source_commit",
        ),
        (
            lambda value: value["scorer"]["metadata"]["official_soft_ex"].update(
                version="changed"
            ),  # type: ignore[index,union-attr]
            "scorer metadata",
        ),
        (
            lambda value: value.update(frozen_files={"../escape": SHA_A}),
            "frozen file path",
        ),
    ],
)
def test_freeze_b_manifest_rejects_incomplete_or_mutable_bindings(
    mutate,  # type: ignore[no-untyped-def]
    message: str,
) -> None:
    value = _freeze_value()
    mutate(value)

    with pytest.raises(FreezeBError, match=message):
        FreezeBManifest.from_dict(value)


def test_sealed_run_manifest_is_test_only_and_matches_freeze_b() -> None:
    freeze = FreezeBManifest.from_dict(_freeze_value())
    run = SealedRunManifest.from_dict(_run_value(freeze), freeze_b=freeze)

    assert run.scope == "test"
    assert run.condition == "C4"
    assert run.semantic_model_sha256 == freeze.condition("C4").semantic_model_sha256
    assert len(run.sha256()) == 64


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"scope": "dev-a"}, "scope"),
        ({"freeze_b_sha256": SHA_A}, "freeze_b_sha256"),
        ({"schedule_sha256": SHA_A}, "schedule_sha256"),
        ({"system_commit": "2" * 40}, "system_commit"),
        ({"condition": "C3"}, "condition specification"),
        ({"semantic_model_sha256": None}, "semantic_model_sha256"),
        ({"harness_config_sha256": SHA_E}, "harness_config_sha256"),
        ({"question_count": 100}, "question_count"),
        ({"repetition": 4}, "repetition"),
    ],
)
def test_sealed_run_manifest_rejects_any_freeze_mismatch(
    overrides: dict[str, object], message: str
) -> None:
    freeze = FreezeBManifest.from_dict(_freeze_value())

    with pytest.raises(FreezeBError, match=message):
        SealedRunManifest.from_dict(_run_value(freeze, **overrides), freeze_b=freeze)
