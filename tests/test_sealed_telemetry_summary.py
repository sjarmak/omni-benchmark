from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
ANALYZER_PATH = ROOT / "experiments/analysis/sealed_telemetry_summary.py"
COMMITTED_SUMMARY = ROOT / "experiments/analysis/sealed-telemetry-summary-v1.json"
REAL_RUN_ROOT = ROOT / "runs/preserved/sealed-final-v6"

FORBIDDEN_OUTPUT_KEYS = {
    "question",
    "instance_id",
    "attempt_id",
    "generated_sql",
    "generated_query",
    "rows",
    "result",
    "result_hash",
    "score",
    "correctness",
    "correct",
    "gold",
    "gold_sql",
    "hidden_annotation",
}


def _analysis_module():
    spec = importlib.util.spec_from_file_location(
        "sealed_telemetry_summary", ANALYZER_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(condition: str, repetition: int, outcome: str) -> dict[str, object]:
    errored = outcome == "errored"
    record: dict[str, object] = {
        "condition": condition.upper(),
        "repetition": repetition,
        "generation_outcome": outcome,
        "failure_origin": "evaluated_system" if errored else None,
        "terminal_failure_class": "synthetic_failure" if errored else None,
        "latency_ms": 20_000 + repetition if errored else 10_000 + repetition,
        "token_source": "provider_reported",
        "token_usage": {
            "input_tokens": 200 if errored else 100,
            "output_tokens": 20 if errored else 10,
            "total_tokens": 220 if errored else 110,
        },
        "cost_source": "provider_reported",
        "cost_usd": 3.0 if errored else 1.0,
        "tool_call_count": 3 if errored else 1,
        "database_query_count": 0 if errored else 1,
        "telemetry_unavailable": [],
        # These sentinels prove that non-whitelisted content never reaches output.
        "question": "SHOULD_NOT_LEAK",
        "instance_id": "SHOULD_NOT_LEAK",
        "attempt_id": "SHOULD_NOT_LEAK",
        "generated_sql": "SHOULD_NOT_LEAK",
        "generated_query": "SHOULD_NOT_LEAK",
        "rows": ["SHOULD_NOT_LEAK"],
        "result_hash": "SHOULD_NOT_LEAK",
        "correctness": "SHOULD_NOT_LEAK",
        "gold_sql": "SHOULD_NOT_LEAK",
    }
    if condition == "c4":
        record["cost_source"] = "unavailable"
        record["cost_usd"] = None
        record["telemetry_unavailable"] = ["cost_usd", "model_version"]
    return record


def _write_run(root: Path, *, attempts_per_cohort: int = 2) -> None:
    for condition in ("c1", "c2", "c3", "c4"):
        for repetition in (1, 2, 3):
            cohort = root / "cohorts" / f"{condition}-r{repetition}"
            cohort.mkdir(parents=True)
            records = [
                _record(
                    condition, repetition, "answered" if index % 2 == 0 else "errored"
                )
                for index in range(attempts_per_cohort)
            ]
            cohort.joinpath("generation.jsonl").write_text(
                "".join(
                    json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )


def _walk_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested for child in value.values() for nested in _walk_keys(child)
        }
    if isinstance(value, list):
        return {nested for child in value for nested in _walk_keys(child)}
    return set()


def test_tukey_distribution_uses_median_of_halves() -> None:
    module = _analysis_module()

    assert module.tukey_distribution([4]) == {
        "observed": 1,
        "missing": 0,
        "median": 4.0,
        "tukey_iqr": {"q1": 4.0, "q3": 4.0},
    }
    assert module.tukey_distribution([1, 2, 3, 4, 5, 6, 7, 8, 9]) == {
        "observed": 9,
        "missing": 0,
        "median": 5.0,
        "tukey_iqr": {"q1": 2.5, "q3": 7.5},
    }
    assert module.tukey_distribution([], total=3) == {
        "observed": 0,
        "missing": 3,
        "median": None,
        "tukey_iqr": None,
    }
    with pytest.raises(module.SummaryError, match="smaller than observations"):
        module.tukey_distribution([1, 2], total=1)


def test_summary_is_aggregate_only_and_preserves_unavailability(tmp_path: Path) -> None:
    module = _analysis_module()
    run_root = tmp_path / "run"
    _write_run(run_root)

    summary = module.summarize_run(run_root, expected_per_cohort=2)

    assert summary["expected"] == {
        "attempts_per_cohort": 2,
        "attempts_per_condition": 6,
        "cohort_count": 12,
    }
    assert summary["conditions"]["C1"]["outcomes"] == {
        "answered": 3,
        "errored": 3,
        "refused": 0,
    }
    assert summary["conditions"]["C1"]["refusal"] == {
        "count": 0,
        "status": "observed",
    }
    assert summary["conditions"]["C1"]["telemetry"]["cost_usd"] == {
        "mean": 2.0,
        "missing": 0,
        "observed": 6,
        "status": "fully_observed",
        "total": 12.0,
    }
    assert summary["conditions"]["C4"]["refusal"] == {
        "count": None,
        "status": "unavailable",
    }
    assert summary["conditions"]["C4"]["outcomes"]["refused"] is None
    assert summary["conditions"]["C4"]["telemetry"]["cost_usd"] == {
        "missing": 6,
        "observed": 0,
        "status": "unavailable",
    }
    assert summary["conditions"]["C4"]["declared_unavailable"] == {
        "cost_usd": 6,
        "model_version": 6,
    }
    assert (
        summary["conditions"]["C1"]["outcome_resource_medians"]["answered"][
            "total_tokens"
        ]
        == 110.0
    )
    assert (
        summary["conditions"]["C1"]["outcome_resource_medians"]["errored"][
            "total_tokens"
        ]
        == 220.0
    )

    serialized = module.canonical_bytes(summary)
    assert b"SHOULD_NOT_LEAK" not in serialized
    assert not (_walk_keys(summary) & FORBIDDEN_OUTPUT_KEYS)
    assert len(summary["provenance"]["source_files"]) == 12
    assert all(
        not source["path"].startswith("/")
        for source in summary["provenance"]["source_files"]
    )

    payload = dict(summary)
    digest = payload.pop("aggregate_payload_sha256")
    assert hashlib.sha256(module.canonical_bytes(payload)).hexdigest() == digest


def test_partial_cost_coverage_never_emits_mean_or_total(tmp_path: Path) -> None:
    module = _analysis_module()
    run_root = tmp_path / "run"
    _write_run(run_root)
    path = run_root / "cohorts/c1-r1/generation.jsonl"
    records = [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
    ]
    records[0]["cost_source"] = "unavailable"
    records[0]["cost_usd"] = None
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    cost = module.summarize_run(run_root, expected_per_cohort=2)["conditions"]["C1"][
        "telemetry"
    ]["cost_usd"]

    assert cost == {
        "missing": 1,
        "observed": 5,
        "status": "partially_observed",
    }


@pytest.mark.parametrize("failure", ["missing_cohort", "wrong_count"])
def test_exact_cohort_shape_is_required(tmp_path: Path, failure: str) -> None:
    module = _analysis_module()
    run_root = tmp_path / "run"
    _write_run(run_root)
    target = run_root / "cohorts/c4-r3/generation.jsonl"
    if failure == "missing_cohort":
        target.unlink()
    else:
        target.write_text(target.read_text(encoding="utf-8").splitlines()[0] + "\n")

    with pytest.raises(module.SummaryError, match="c4-r3"):
        module.summarize_run(run_root, expected_per_cohort=2)


@pytest.mark.parametrize(
    "failure", ["condition", "repetition", "token_reconciliation", "failure_label"]
)
def test_invalid_whitelisted_telemetry_fails_closed(
    tmp_path: Path, failure: str
) -> None:
    module = _analysis_module()
    run_root = tmp_path / "run"
    _write_run(run_root)
    target = run_root / "cohorts/c1-r1/generation.jsonl"
    records = [
        json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()
    ]
    if failure == "condition":
        records[0]["condition"] = "C2"
    elif failure == "repetition":
        records[0]["repetition"] = 2
    elif failure == "token_reconciliation":
        records[0]["token_usage"]["total_tokens"] = 999
    else:
        records[1]["terminal_failure_class"] = None
    target.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(module.SummaryError):
        module.summarize_run(run_root, expected_per_cohort=2)


def test_expected_count_must_be_positive(tmp_path: Path) -> None:
    module = _analysis_module()

    with pytest.raises(module.SummaryError, match="must be positive"):
        module.summarize_run(tmp_path, expected_per_cohort=0)


def test_cli_emits_canonical_json_and_refuses_overwrite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _analysis_module()
    run_root = tmp_path / "run"
    output = tmp_path / "summary.json"
    _write_run(run_root)

    assert module.main([str(run_root), "--expected-per-cohort", "2"]) == 0
    stdout = capsys.readouterr().out.encode()
    assert stdout == module.canonical_bytes(json.loads(stdout))

    assert (
        module.main(
            [
                str(run_root),
                "--expected-per-cohort",
                "2",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.read_bytes() == stdout
    with pytest.raises(FileExistsError):
        module.main(
            [
                str(run_root),
                "--expected-per-cohort",
                "2",
                "--output",
                str(output),
            ]
        )


def test_committed_real_summary_is_safe_and_expected() -> None:
    module = _analysis_module()
    summary = json.loads(COMMITTED_SUMMARY.read_bytes())

    assert summary["expected"] == {
        "attempts_per_cohort": 89,
        "attempts_per_condition": 267,
        "cohort_count": 12,
    }
    assert {
        condition: value["attempt_count"]
        for condition, value in summary["conditions"].items()
    } == {
        "C1": 267,
        "C2": 267,
        "C3": 267,
        "C4": 267,
    }
    assert summary["conditions"]["C4"]["refusal"]["status"] == "unavailable"
    assert summary["conditions"]["C4"]["outcomes"]["refused"] is None
    assert summary["conditions"]["C4"]["telemetry"]["cost_usd"] == {
        "missing": 267,
        "observed": 0,
        "status": "unavailable",
    }
    assert not (_walk_keys(summary) & FORBIDDEN_OUTPUT_KEYS)
    assert COMMITTED_SUMMARY.read_bytes() == module.canonical_bytes(summary)


@pytest.mark.skipif(not REAL_RUN_ROOT.exists(), reason="preserved sealed run is local")
def test_real_sealed_artifact_reproduces_committed_summary() -> None:
    module = _analysis_module()

    generated = module.summarize_run(REAL_RUN_ROOT)

    assert generated == json.loads(COMMITTED_SUMMARY.read_bytes())
