from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from omni_benchmark.run_quarantine import is_quarantined_run, quarantined_attempt


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


def test_spent_v2_authorization_and_pre_answer_failures_are_quarantined() -> None:
    workspace = Path(__file__).resolve().parents[1]
    run_id = "public-c4-baseline-v2"
    path = workspace / f"experiments/quarantines/{run_id}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["run_id"] == run_id
    assert manifest["run_root"] == f"experiments/autoresearch/raw/{run_id}"
    assert manifest["status"] == "quarantined_non_scoreable"
    assert manifest["scoreable"] is False
    assert manifest["correctness_observed"] is False
    assert manifest["gold_accessed"] is False
    assert manifest["counts"] == {
        "approval_consumption_records": 1,
        "dispatcher_failures": 3,
        "generation_records": 0,
    }
    assert manifest["generation_records"] == []
    failures = manifest["dispatcher_failures"]
    assert [failure["sha256"] for failure in failures] == [
        "534605ae972afaa90c6953d406638618b7b7b3bf0e61bd162a3a15dc954ffb77",
        "bdc7df5a5b06bbfe3e2378e89c7ae912395b5e34ea318179d945a85b4be38c31",
        "36a4df3bda7f0882a264070fa48dd24b7604bf66924685ba8c95c8b68b30b490",
    ]
    assert all(failure["failure_kind"] == "child_exit" for failure in failures)
    assert all(failure["returncode"] == 1 for failure in failures)
    assert all(
        failure["stderr_sha256"]
        == "da92545f8bb4de27489c9e01d8b21caf02be7b9ade28d9fa9baac1eba73d2c55"
        for failure in failures
    )
    approval = manifest["approval_consumption"]
    assert approval == {
        "decision_bead_id": "omni-benchmark-ei0.4.2.1",
        "path": (
            "experiments/approvals/c4-production/"
            "d9869dfc57a4c8fc1ef536644228fd6f858b841d18af5ccd3262bfbdd42e0ed2."
            "consumed.json"
        ),
        "receipt_sha256": (
            "d9869dfc57a4c8fc1ef536644228fd6f858b841d18af5ccd3262bfbdd42e0ed2"
        ),
        "sha256": ("5f3603f4f0ba2a71cce0a996d7cd4cae6d54bd9fa388232f02140dc5e27f02ba"),
    }
    assert is_quarantined_run(run_id)
    assert quarantined_attempt(f"{run_id}:archeology_scan_1:C4:1")


def test_spent_v3_authorization_and_http_429_interruption_are_quarantined() -> None:
    workspace = Path(__file__).resolve().parents[1]
    run_id = "public-c4-baseline-v3"
    path = workspace / f"experiments/quarantines/{run_id}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["run_id"] == run_id
    assert manifest["run_root"] == f"experiments/autoresearch/raw/{run_id}"
    assert manifest["status"] == "quarantined_non_scoreable"
    assert manifest["scoreable"] is False
    assert manifest["correctness_observed"] is False
    assert manifest["gold_accessed"] is False
    assert manifest["counts"] == {
        "answered_generation_records": 12,
        "approval_consumption_records": 1,
        "dispatcher_failures": 1,
        "errored_generation_records": 6,
        "generation_records": 18,
    }
    assert manifest["artifact_inventory"] == {
        "file_count": 85,
        "forbidden_field_occurrences": 0,
        "mode": "0600",
        "sha256": ("a060042bc053dee03af7c67f7672ea95fc62ae37abadff1ccb788bd2dec65588"),
    }
    records = manifest["generation_records"]
    assert len(records) == 18
    assert len({record["attempt_id"] for record in records}) == 18
    assert Counter(record["generation_outcome"] for record in records) == {
        "answered": 12,
        "errored": 6,
    }
    assert all(SHA256.fullmatch(record["sha256"]) for record in records)
    assert all(
        record["path"].startswith(f"experiments/autoresearch/raw/{run_id}/")
        for record in records
    )
    assert manifest["dispatcher_failures"] == [
        {
            "attempt_id": "public-c4-baseline-v3:cross_border_17:C4:1",
            "failure_kind": "child_exit",
            "path": (
                "experiments/autoresearch/raw/public-c4-baseline-v3/"
                "cross_border_large/c4/"
                ".failed-cross_border_17-r1-dcd65cc25cca8921/failure.json"
            ),
            "returncode": 1,
            "sha256": (
                "8d29256298554263d16eb0e6dc079bfb79ca1af3f2ae8501ace2d5dfa2a9915c"
            ),
            "stderr_sha256": (
                "4d0716e29ee966ee9a2068052261c5e77382f980cc528945cc6f30f1303378bf"
            ),
            "terminal_failure_class": "dispatcher_http_429_whoami",
        }
    ]
    assert manifest["approval_consumption"] == {
        "decision_bead_id": "omni-benchmark-ei0.4.2.3",
        "path": (
            "experiments/approvals/c4-production/"
            "6f139bea9803a20d337bdb1ba1ee1325236c4b3953d181d75d5ed63b48136416."
            "consumed.json"
        ),
        "receipt_sha256": (
            "6f139bea9803a20d337bdb1ba1ee1325236c4b3953d181d75d5ed63b48136416"
        ),
        "sha256": "aabaee2c35e2b23f8b84594d6872c14f137e26b245f124b16261840bcd7c3ea9",
    }
    assert is_quarantined_run(run_id)
    assert quarantined_attempt(f"{run_id}:cross_border_17:C4:1")
