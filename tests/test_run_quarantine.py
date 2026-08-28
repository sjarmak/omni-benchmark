from __future__ import annotations

import json
import re
from pathlib import Path


SHA256 = re.compile(r"[0-9a-f]{64}")


def test_interrupted_c4_manifest_binds_every_preserved_artifact() -> None:
    workspace = Path(__file__).resolve().parents[1]
    path = workspace / "experiments/quarantines/public-c4-baseline-v1-20260828.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["run_id"] == "public-c4-baseline-v1-20260828"
    assert manifest["status"] == "quarantined_non_scoreable"
    assert manifest["scoreable"] is False
    assert manifest["correctness_observed"] is False
    assert manifest["gold_accessed"] is False
    assert manifest["counts"] == {
        "answered_generation_records": 6,
        "dispatcher_failures": 2,
        "generation_records": 11,
        "transport_failure_generation_records": 5,
    }
    records = manifest["generation_records"]
    failures = manifest["dispatcher_failures"]
    assert len(records) == 11
    assert len(failures) == 2
    assert len({record["attempt_id"] for record in records}) == 11
    assert len({failure["attempt_id"] for failure in failures}) == 2
    assert all(SHA256.fullmatch(record["sha256"]) for record in records)
    assert all(SHA256.fullmatch(failure["sha256"]) for failure in failures)
    assert all(
        record["path"].startswith(
            "experiments/autoresearch/raw/public-c4-baseline-v1-20260828/"
        )
        for record in records
    )
    assert all(
        failure["path"].startswith(
            "experiments/autoresearch/raw/public-c4-baseline-v1-20260828/"
        )
        for failure in failures
    )
