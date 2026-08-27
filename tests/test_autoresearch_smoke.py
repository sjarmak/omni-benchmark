from __future__ import annotations

import hashlib
import json
from pathlib import Path

import omni_benchmark.autoresearch_cli as autoresearch_cli
import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.autoresearch import (
    AutoresearchError,
    validate_run,
    validate_telemetry_smoke,
)
from omni_benchmark.autoresearch_smoke import TelemetrySmokeBundle
from omni_benchmark.run_manifest import RunManifest

from .test_autoresearch_boundaries import (
    configured_workspace as configured_workspace,
)
from .test_autoresearch_boundaries import (
    load_fixture_config,
    run_record,
    unscored_record,
    write_jsonl,
)


def test_validate_run_accepts_structured_public_diagnostic_trace(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    records = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    records[1].update(
        {
            "actual_result_hash": "a" * 64,
            "actual_result_status": "executed",
            "question": "Question for train_2",
            "failure_category": "join path",
            "public_hkb_nodes": ["node.public"],
            "semantic_objects_available": ["topic.orders"],
            "semantic_objects_retrieved": ["topic.orders"],
            "compiler_status": "ok",
            "compiler_failure_class": None,
            "validation_status": "failed",
            "validation_failure_class": "shape",
            "execution_status": "ok",
            "execution_failure_class": None,
            "prior_experiment_ids": ["exp-000"],
            "prior_experiments": ["exp-000"],
        }
    )
    path = workspace / "runs" / "trace.jsonl"
    write_jsonl(path, records)

    assert (
        validate_run(load_fixture_config(configured_workspace), path).question_count
        == 2
    )


def test_validate_run_rejects_nested_diagnostic_smuggling(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    records = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    records[0]["compiler_diagnostics"] = {"oracle_sql": "DO-NOT-LEAK"}
    path = workspace / "runs" / "smuggled.jsonl"
    write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="forbidden field") as error:
        validate_run(load_fixture_config(configured_workspace), path)

    assert "DO-NOT-LEAK" not in str(error.value)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tool_call_count", -1, "tool_call_count"),
        ("database_query_count", 1.5, "database_query_count"),
        ("retry_count", True, "retry_count"),
        ("validation_attempt_count", "one", "validation_attempt_count"),
        ("condition", "C5", "condition"),
        ("started_at", "today", "started_at"),
        ("repetition", 0, "repetition"),
        (
            "token_usage",
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 99},
            "total_tokens",
        ),
        ("generation_outcome", "correct", "generation_outcome"),
        ("token_source", "guessed", "token_source"),
        ("tool_calls_by_name", [{"name": "query", "count": -1}], "tool_calls_by_name"),
    ],
)
def test_validate_run_rejects_invalid_telemetry(
    configured_workspace: tuple[Path, Path],
    field: str,
    value: object,
    message: str,
) -> None:
    workspace, _ = configured_workspace
    records = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    records[0][field] = value
    path = workspace / "runs" / "bad-telemetry.jsonl"
    write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match=message):
        validate_run(load_fixture_config(configured_workspace), path)


def test_validate_run_requires_explicit_reason_for_unavailable_telemetry(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    records = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    records[0]["tool_call_count"] = None
    path = workspace / "runs" / "unexplained-missing.jsonl"
    write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="telemetry_unavailable"):
        validate_run(load_fixture_config(configured_workspace), path)

    records[0]["telemetry_unavailable"] = ["tool_call_count"]
    records[0]["tool_calls_by_name"] = []
    write_jsonl(path, records)
    assert (
        validate_run(load_fixture_config(configured_workspace), path).question_count
        == 2
    )


def test_validate_run_requires_trace_reason_when_capture_is_unavailable(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    records = [
        run_record("train_1", outcome="correct"),
        run_record("train_2", outcome="wrong_answer"),
    ]
    records[0].update(
        {
            "trace_captured": False,
            "trace_degraded_reason": None,
            "trace_path": None,
            "trace_sha256": None,
            "trace_schema_version": None,
        }
    )
    path = workspace / "runs" / "missing-trace.jsonl"
    write_jsonl(path, records)

    with pytest.raises(AutoresearchError, match="trace_degraded_reason"):
        validate_run(load_fixture_config(configured_workspace), path)

    records[0]["trace_degraded_reason"] = "provider does not expose raw events"
    write_jsonl(path, records)
    assert (
        validate_run(load_fixture_config(configured_workspace), path).question_count
        == 2
    )


def telemetry_smoke_bundle(
    workspace: Path,
    condition: str,
    *,
    instance_id: str = "train_1",
    run_id: str = "smoke",
    repetition: int = 1,
    scope: str = "train",
) -> TelemetrySmokeBundle:
    record = unscored_record(instance_id, partition=scope)
    record.update(
        {
            "attempt_id": f"{run_id}:{instance_id}:{condition}:{repetition}",
            "condition": condition,
            "repetition": repetition,
            "run_id": run_id,
        }
    )
    store = ArtifactStore(workspace, Path(f"runs/smoke-{condition.lower()}"))
    generation = store.write_jsonl(Path("generation.jsonl"), [record])
    manifest = RunManifest.from_dict(
        {
            "budget_id": "smoke-v1",
            "cli_versions": {"omni": "1.1.2"},
            "condition": condition,
            "controllable_seed": None,
            "finished_at": str(record["finished_at"]),
            "generation_sha256": generation.sha256,
            "git_commit": "e" * 40,
            "harness_config_sha256": "b" * 64,
            "instructions_sha256": "c" * 64,
            "model": "test-model",
            "model_config_id": "test-config",
            "prompt_sha256": "d" * 64,
            "provider": "test-provider",
            "repetition": repetition,
            "schema_version": 2,
            "semantic_model_ref": "branch:test-model-v1",
            "semantic_model_sha256": None,
            "scope": scope,
            "software_versions": {"omni-benchmark": "0.1.0"},
            "started_at": str(record["started_at"]),
        }
    )
    stored_manifest = store.write_json(Path("run.json"), manifest.as_dict())
    return TelemetrySmokeBundle(
        condition=condition,
        generation_path=generation.path,
        run_manifest_path=stored_manifest.path,
        expected_run_manifest_sha256=stored_manifest.sha256,
    )


def test_telemetry_smoke_requires_one_valid_attempt_per_condition(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    bundles = [
        telemetry_smoke_bundle(workspace, condition)
        for condition in ("C1", "C2", "C3", "C4")
    ]

    result = validate_telemetry_smoke(
        load_fixture_config(configured_workspace), bundles, scope="train"
    )

    assert result["conditions"] == ["C1", "C2", "C3", "C4"]
    assert result["scope"] == "train"
    assert result["generation_sha256_by_condition"] == {
        bundle.condition: hashlib.sha256(
            bundle.generation_path.read_bytes()
        ).hexdigest()
        for bundle in bundles
    }
    assert result["run_manifest_sha256_by_condition"] == {
        bundle.condition: bundle.expected_run_manifest_sha256 for bundle in bundles
    }

    bundles[3].run_manifest_path.unlink()
    with pytest.raises(AutoresearchError, match="private regular file"):
        validate_telemetry_smoke(
            load_fixture_config(configured_workspace), bundles, scope="train"
        )


def test_telemetry_smoke_requires_matched_question_run_and_repetition(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    bundles = [
        telemetry_smoke_bundle(
            workspace,
            condition,
            instance_id="train_1" if index < 3 else "train_2",
        )
        for index, condition in enumerate(("C1", "C2", "C3", "C4"))
    ]

    with pytest.raises(AutoresearchError, match="same question, run, and repetition"):
        validate_telemetry_smoke(
            load_fixture_config(configured_workspace), bundles, scope="train"
        )


def test_telemetry_smoke_rejects_substituted_condition_manifest(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    bundles = [
        telemetry_smoke_bundle(workspace, condition)
        for condition in ("C1", "C2", "C3", "C4")
    ]
    substituted = [
        *bundles[:2],
        TelemetrySmokeBundle(
            condition="C3",
            generation_path=bundles[2].generation_path,
            run_manifest_path=bundles[1].run_manifest_path,
            expected_run_manifest_sha256=bundles[1].expected_run_manifest_sha256,
        ),
        bundles[3],
    ]

    with pytest.raises(
        AutoresearchError, match="run manifest .* does not match generation"
    ):
        validate_telemetry_smoke(
            load_fixture_config(configured_workspace), substituted, scope="train"
        )


def test_telemetry_smoke_requires_exactly_one_bundle_per_condition(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    bundles = [
        telemetry_smoke_bundle(workspace, condition)
        for condition in ("C1", "C2", "C3", "C4")
    ]

    with pytest.raises(AutoresearchError, match="four individually bound"):
        validate_telemetry_smoke(
            load_fixture_config(configured_workspace), bundles[:3], scope="train"
        )
    duplicate = [*bundles[:3], bundles[2]]
    with pytest.raises(AutoresearchError, match="duplicate condition bundle"):
        validate_telemetry_smoke(
            load_fixture_config(configured_workspace), duplicate, scope="train"
        )


def test_telemetry_smoke_accepts_only_train_or_dev_a_scope(
    configured_workspace: tuple[Path, Path],
) -> None:
    workspace, _ = configured_workspace
    bundles = [
        telemetry_smoke_bundle(workspace, condition, scope="dev-a")
        for condition in ("C1", "C2", "C3", "C4")
    ]

    result = validate_telemetry_smoke(
        load_fixture_config(configured_workspace), bundles, scope="dev-a"
    )

    assert result["scope"] == "dev-a"
    with pytest.raises(AutoresearchError, match="scope must be train or dev-a"):
        validate_telemetry_smoke(
            load_fixture_config(configured_workspace), bundles, scope="dev-b"
        )


def telemetry_smoke_cli_arguments() -> list[str]:
    arguments = [
        "--workspace",
        "/workspace",
        "--config",
        "/workspace/config/autoresearch.json",
        "--freeze-a-commit",
        "a" * 40,
        "telemetry-smoke",
        "--scope",
        "dev-a",
    ]
    for condition in ("C1", "C2", "C3", "C4"):
        arguments.extend(
            [
                "--bundle",
                condition,
                f"runs/{condition}/generation.jsonl",
                f"runs/{condition}/run.json",
                condition[-1] * 64,
            ]
        )
    return arguments


def test_telemetry_smoke_cli_requires_and_forwards_four_bound_bundles(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sentinel_config = object()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        autoresearch_cli, "load_config", lambda *args, **kwargs: sentinel_config
    )

    def fake_validate(
        config: object,
        bundles: list[TelemetrySmokeBundle],
        *,
        scope: str,
    ) -> dict[str, object]:
        captured.update({"config": config, "bundles": bundles, "scope": scope})
        return {"conditions": [bundle.condition for bundle in bundles]}

    monkeypatch.setattr(autoresearch_cli, "validate_telemetry_smoke", fake_validate)

    assert autoresearch_cli.main(telemetry_smoke_cli_arguments()) == 0

    assert captured["config"] is sentinel_config
    assert captured["scope"] == "dev-a"
    assert [bundle.condition for bundle in captured["bundles"]] == [
        "C1",
        "C2",
        "C3",
        "C4",
    ]
    assert json.loads(capsys.readouterr().out)["status"] == "validated"
