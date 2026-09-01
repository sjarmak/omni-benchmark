from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest

import omni_benchmark.r2_paired_schedule_cli as schedule_cli
from omni_benchmark.measure_review_catalog import canonical_catalog_bytes
from omni_benchmark.r2_paired_schedule import (
    CONTROL_CONDITION,
    EXPECTED_ATTEMPT_COUNT,
    EXPECTED_DATABASE_COUNT,
    EXPECTED_DEV_A_COUNT,
    EXPECTED_PAIR_COUNT,
    R2PairedScheduleError,
    SCHEDULE_SEED,
    build_r2_paired_schedule,
    validate_r2_paired_schedule,
    write_r2_paired_schedule,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _jsonl(records: list[dict[str, object]]) -> bytes:
    return b"".join(canonical_catalog_bytes(record) for record in records)


def _fixture_inputs() -> dict[str, bytes]:
    databases = ["alpha_large", "beta_large", "delta_large", "gamma_large"]
    assignments = {
        "alpha_large": ("alpha_1", "alpha_2", "alpha_3"),
        "beta_large": ("beta_1", "beta_2", "beta_3"),
        "delta_large": ("delta_1", "delta_2"),
        "gamma_large": ("gamma_1", "gamma_2"),
        "excluded_large": ("excluded_1", "excluded_2"),
    }
    public_manifest = _jsonl(
        [
            {
                "instance_id": instance_id,
                "query": "Public text is not a scheduling signal.",
                "selected_database": database,
            }
            for database, instance_ids in sorted(assignments.items())
            for instance_id in instance_ids
        ]
    )
    dev_a_ids = (
        "\n".join(sorted(id_ for ids in assignments.values() for id_ in ids)) + "\n"
    ).encode()
    target_config = canonical_catalog_bytes(
        {
            "databases": databases,
            "kind": "r2-public-evidence-measure-targets",
            "schema_version": 1,
        }
    )
    split_metadata = canonical_catalog_bytes(
        {
            "artifacts": {
                "dev_a_ids": {
                    "file": "dev_a_ids.txt",
                    "sha256": _sha256(dev_a_ids),
                }
            },
            "counts": {"dev_a": 12},
            "manifest": {
                "file": "eligible_questions.jsonl",
                "sha256": _sha256(public_manifest),
            },
            "schema_version": 1,
            "source": {
                "dataset": "public-fixture",
                "revision": "fixture-v1",
            },
        }
    )
    return {
        "dev_a_ids_bytes": dev_a_ids,
        "public_manifest_bytes": public_manifest,
        "split_metadata_bytes": split_metadata,
        "target_config_bytes": target_config,
    }


def _build(inputs: dict[str, bytes] | None = None, *, seed: str = SCHEDULE_SEED):
    return build_r2_paired_schedule(
        **(inputs or _fixture_inputs()),
        seed=seed,
        expected_dev_a_count=12,
        expected_pair_count=10,
        expected_database_count=4,
    )


def test_schedule_is_deterministic_complete_balanced_and_database_interleaved() -> None:
    first = _build()
    second = _build()
    different = _build(seed="different-public-schedule-seed")

    assert first == second
    assert first["kind"] == "r2-public-evidence-measures-paired-schedule"
    assert first["algorithm"] == {
        "database_order": "sha256",
        "first_arm_balance": "within_database_then_global",
        "name": "r2_database_round_robin_paired_v1",
        "pair_adjacency": True,
        "question_order_within_database": "sha256",
        "seed": SCHEDULE_SEED,
    }
    assert first["summary"]["pair_count"] == 10
    assert first["summary"]["attempt_count"] == 20
    assert first["summary"]["condition_attempt_counts"] == {
        "R2-C5B": 10,
        "R2-M1": 10,
    }
    assert first["summary"]["first_condition_counts"] == {
        "R2-C5B": 5,
        "R2-M1": 5,
    }
    assert len({pair["instance_id"] for pair in first["pairs"]}) == 10
    assert len({item["attempt_id"] for item in first["attempts"]}) == 20
    assert [pair["pair_id"] for pair in first["pairs"]] == first["manifest"][
        "ordered_pair_ids"
    ]
    assert [item["attempt_id"] for item in first["attempts"]] == first["manifest"][
        "ordered_attempt_ids"
    ]
    assert canonical_catalog_bytes(first) == canonical_catalog_bytes(second)
    assert (
        first["manifest"]["ordered_pair_ids"]
        != different["manifest"]["ordered_pair_ids"]
    )
    assert {pair["instance_id"] for pair in first["pairs"]} == {
        pair["instance_id"] for pair in different["pairs"]
    }

    by_database: dict[str, Counter[str]] = defaultdict(Counter)
    for pair in first["pairs"]:
        by_database[pair["database"]][pair["first_condition"]] += 1
    for counts in by_database.values():
        assert abs(counts["R2-C5B"] - counts["R2-M1"]) <= 1

    attempts_by_pair: dict[str, list[dict[str, object]]] = defaultdict(list)
    for attempt in first["attempts"]:
        attempts_by_pair[attempt["pair_id"]].append(attempt)
    for pair in first["pairs"]:
        attempts = attempts_by_pair[pair["pair_id"]]
        assert [item["condition"] for item in attempts] == [
            pair["first_condition"],
            pair["second_condition"],
        ]
        assert [item["within_pair_position"] for item in attempts] == [1, 2]
        assert attempts[1]["attempt_position"] == attempts[0]["attempt_position"] + 1

    rounds: dict[int, list[str]] = defaultdict(list)
    for pair in first["pairs"]:
        rounds[pair["database_round"]].append(pair["database"])
    database_order = rounds[1]
    assert len(database_order) == 4
    assert rounds[2] == database_order
    assert set(rounds[3]) == {"alpha_large", "beta_large"}


def test_schedule_binds_exact_public_inputs_without_question_content() -> None:
    inputs = _fixture_inputs()

    schedule = _build(inputs)

    assert schedule["source"] == {
        "dev_a_ids": {
            "path": "data/manifests/dev_a_ids.txt",
            "sha256": _sha256(inputs["dev_a_ids_bytes"]),
        },
        "development_split_metadata": {
            "path": "data/manifests/development_split_metadata.json",
            "sha256": _sha256(inputs["split_metadata_bytes"]),
        },
        "public_manifest": {
            "path": "data/manifests/eligible_questions.jsonl",
            "sha256": _sha256(inputs["public_manifest_bytes"]),
        },
        "target_configuration": {
            "path": "config/conditions/r2-public-evidence-measure-databases-v1.json",
            "sha256": _sha256(inputs["target_config_bytes"]),
        },
    }
    encoded = canonical_catalog_bytes(schedule)
    assert b"Public text is not a scheduling signal" not in encoded
    for forbidden in (
        b'"query"',
        b'"normal_query"',
        b'"gold_sql"',
        b'"correctness"',
        b'"outcome"',
    ):
        assert forbidden not in encoded


def test_validator_rejects_any_changed_frozen_schedule_content() -> None:
    inputs = _fixture_inputs()
    schedule = _build(inputs)
    content = canonical_catalog_bytes(schedule)

    assert (
        validate_r2_paired_schedule(
            content,
            **inputs,
            expected_dev_a_count=12,
            expected_pair_count=10,
            expected_database_count=4,
        )
        == schedule
    )
    changed = copy.deepcopy(schedule)
    changed["pairs"][0]["first_condition"] = (
        "R2-M1"
        if changed["pairs"][0]["first_condition"] == CONTROL_CONDITION
        else CONTROL_CONDITION
    )

    with pytest.raises(R2PairedScheduleError, match="does not reproduce"):
        validate_r2_paired_schedule(
            canonical_catalog_bytes(changed),
            **inputs,
            expected_dev_a_count=12,
            expected_pair_count=10,
            expected_database_count=4,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("public_hash", "public manifest hash"),
        ("dev_a_hash", "dev-A ID hash"),
        ("unknown_id", "must exist in the public manifest"),
        ("duplicate_id", "duplicate"),
        ("unsorted_ids", "sorted"),
        ("dev_a_count", "dev-A count"),
        ("target_shape", "target configuration shape"),
        ("target_order", "target databases must be unique and sorted"),
        ("target_count", "target database count"),
        ("public_duplicate", "duplicate instance_id"),
        ("public_json", "valid JSON"),
        ("protected", "protected field"),
        ("empty_target_stratum", "has no eligible dev-A questions"),
        ("odd_frame", "pair count must be even"),
    ],
)
def test_schedule_rejects_membership_provenance_and_boundary_failures(
    mutation: str, message: str
) -> None:
    inputs = _fixture_inputs()
    expected_dev_a_count = 12
    expected_pair_count = 10
    expected_database_count = 4
    if mutation in {"public_hash", "dev_a_hash", "dev_a_count"}:
        metadata = json.loads(inputs["split_metadata_bytes"])
        if mutation == "public_hash":
            metadata["manifest"]["sha256"] = "0" * 64
        elif mutation == "dev_a_hash":
            metadata["artifacts"]["dev_a_ids"]["sha256"] = "0" * 64
        else:
            metadata["counts"]["dev_a"] = 11
        inputs["split_metadata_bytes"] = canonical_catalog_bytes(metadata)
    elif mutation == "unknown_id":
        inputs["dev_a_ids_bytes"] = inputs["dev_a_ids_bytes"].replace(
            b"excluded_2", b"unknown_2"
        )
    elif mutation == "duplicate_id":
        inputs["dev_a_ids_bytes"] = inputs["dev_a_ids_bytes"].replace(
            b"excluded_2", b"excluded_1"
        )
    elif mutation == "unsorted_ids":
        lines = inputs["dev_a_ids_bytes"].splitlines()
        lines[0], lines[1] = lines[1], lines[0]
        inputs["dev_a_ids_bytes"] = b"\n".join(lines) + b"\n"
    elif mutation in {"target_shape", "target_order", "target_count"}:
        targets = json.loads(inputs["target_config_bytes"])
        if mutation == "target_shape":
            targets["question_path"] = "forbidden"
        elif mutation == "target_order":
            targets["databases"].reverse()
        else:
            targets["databases"].pop()
            expected_database_count = 4
        inputs["target_config_bytes"] = canonical_catalog_bytes(targets)
    elif mutation == "public_duplicate":
        first = inputs["public_manifest_bytes"].splitlines(keepends=True)[0]
        inputs["public_manifest_bytes"] += first
    elif mutation == "public_json":
        inputs["public_manifest_bytes"] = b"not-json\n"
    elif mutation == "protected":
        record = json.loads(inputs["public_manifest_bytes"].splitlines()[0])
        record["gold_sql"] = "SELECT 1"
        lines = inputs["public_manifest_bytes"].splitlines(keepends=True)
        inputs["public_manifest_bytes"] = canonical_catalog_bytes(record) + b"".join(
            lines[1:]
        )
    elif mutation == "empty_target_stratum":
        targets = json.loads(inputs["target_config_bytes"])
        targets["databases"][-1] = "unused_large"
        targets["databases"].sort()
        inputs["target_config_bytes"] = canonical_catalog_bytes(targets)
    else:
        expected_pair_count = 9

    with pytest.raises(R2PairedScheduleError, match=message):
        build_r2_paired_schedule(
            **inputs,
            expected_dev_a_count=expected_dev_a_count,
            expected_pair_count=expected_pair_count,
            expected_database_count=expected_database_count,
        )


def test_writer_is_append_only_mode_0600_and_canonical(tmp_path: Path) -> None:
    schedule = _build()
    destination = tmp_path / "r2-schedule.json"

    write_r2_paired_schedule(destination, schedule)

    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.read_bytes() == canonical_catalog_bytes(schedule)
    with pytest.raises(R2PairedScheduleError, match="already exists"):
        write_r2_paired_schedule(destination, schedule)


def test_cli_freezes_and_reports_only_bounded_schedule_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = _fixture_inputs()
    paths: dict[str, Path] = {}
    for name, content in inputs.items():
        path = tmp_path / name
        path.write_bytes(content)
        paths[name] = path
    output = tmp_path / "schedule.json"

    result = schedule_cli.main(
        [
            "--public-manifest",
            str(paths["public_manifest_bytes"]),
            "--dev-a-ids",
            str(paths["dev_a_ids_bytes"]),
            "--split-metadata",
            str(paths["split_metadata_bytes"]),
            "--target-config",
            str(paths["target_config_bytes"]),
            "--output",
            str(output),
            "--expected-dev-a-count",
            "12",
            "--expected-pair-count",
            "10",
            "--expected-database-count",
            "4",
        ]
    )

    assert result == 0
    assert output.stat().st_mode & 0o777 == 0o600
    assert validate_r2_paired_schedule(
        output.read_bytes(),
        **inputs,
        expected_dev_a_count=12,
        expected_pair_count=10,
        expected_database_count=4,
    )
    report = json.loads(capsys.readouterr().out)
    assert report == {
        "artifact_sha256": json.loads(output.read_bytes())["manifest"][
            "artifact_sha256"
        ],
        "attempt_count": 20,
        "database_count": 4,
        "first_condition_counts": {"R2-C5B": 5, "R2-M1": 5},
        "output": str(output),
        "pair_count": 10,
    }


def test_real_workspace_schedule_is_exact_complete_and_deterministic() -> None:
    inputs = {
        "public_manifest_bytes": (
            REPOSITORY_ROOT / "data/manifests/eligible_questions.jsonl"
        ).read_bytes(),
        "dev_a_ids_bytes": (
            REPOSITORY_ROOT / "data/manifests/dev_a_ids.txt"
        ).read_bytes(),
        "split_metadata_bytes": (
            REPOSITORY_ROOT / "data/manifests/development_split_metadata.json"
        ).read_bytes(),
        "target_config_bytes": (
            REPOSITORY_ROOT
            / "config/conditions/r2-public-evidence-measure-databases-v1.json"
        ).read_bytes(),
    }

    first = build_r2_paired_schedule(**inputs)
    second = build_r2_paired_schedule(**inputs)

    assert first == second
    assert first["summary"]["pair_count"] == EXPECTED_PAIR_COUNT == 136
    assert first["summary"]["attempt_count"] == EXPECTED_ATTEMPT_COUNT == 272
    assert first["summary"]["database_count"] == EXPECTED_DATABASE_COUNT == 16
    assert first["summary"]["dev_a_count"] == EXPECTED_DEV_A_COUNT == 154
    assert first["summary"]["first_condition_counts"] == {
        "R2-C5B": 68,
        "R2-M1": 68,
    }
    assert sum(first["summary"]["pair_count_by_database"].values()) == 136
    assert len(first["manifest"]["ordered_pair_ids"]) == 136
    assert len(first["manifest"]["ordered_attempt_ids"]) == 272
    assert canonical_catalog_bytes(first) == canonical_catalog_bytes(second)
