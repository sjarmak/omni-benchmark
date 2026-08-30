from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.sealed_mvp_frame import (
    SealedMVPFrameError,
    generate_sealed_mvp_frame,
)


def _write_inputs(root: Path) -> tuple[Path, Path, Path]:
    eligible = root / "eligible.jsonl"
    test_ids = root / "test_ids.txt"
    config = root / "frame.json"
    records = [
        {
            "category": "Query",
            "instance_id": f"q-{index:03d}",
            "query": f"Public question {index}?",
            "selected_database": database,
        }
        for index, database in enumerate(
            ("kept_a", "blocked_a", "kept_b", "blocked_b", "kept_a"), start=1
        )
    ]
    eligible.write_bytes(
        b"".join(
            (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode()
            for record in records
        )
    )
    test_ids.write_text(
        "".join(f"q-{index:03d}\n" for index in range(1, 6)), encoding="utf-8"
    )
    config.write_text(
        json.dumps(
            {
                "decision_bead_id": "decision-1",
                "excluded_databases": ["blocked_a", "blocked_b"],
                "expected_question_count": 3,
                "kind": "sealed-mvp-frame-spec",
                "schema_version": 1,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return eligible, test_ids, config


def test_generate_frame_is_reproducible_and_identity_only(tmp_path: Path) -> None:
    eligible, test_ids, config = _write_inputs(tmp_path)
    ids_output = tmp_path / "sealed_mvp_ids.txt"
    metadata_output = tmp_path / "sealed_mvp_frame_metadata.json"

    result = generate_sealed_mvp_frame(
        eligible_manifest=eligible,
        test_ids_path=test_ids,
        config_path=config,
        ids_output=ids_output,
        metadata_output=metadata_output,
    )
    first_ids = ids_output.read_bytes()
    first_metadata = metadata_output.read_bytes()
    generate_sealed_mvp_frame(
        eligible_manifest=eligible,
        test_ids_path=test_ids,
        config_path=config,
        ids_output=ids_output,
        metadata_output=metadata_output,
    )

    assert first_ids == b"q-001\nq-003\nq-005\n"
    assert ids_output.read_bytes() == first_ids
    assert metadata_output.read_bytes() == first_metadata
    assert result["selected_count"] == 3
    assert result["excluded_count"] == 2
    assert result["selected_ids_sha256"] == hashlib.sha256(first_ids).hexdigest()
    assert "query" not in metadata_output.read_text(encoding="utf-8")


def test_generate_frame_rejects_protected_public_input(tmp_path: Path) -> None:
    eligible, test_ids, config = _write_inputs(tmp_path)
    record = json.loads(eligible.read_text(encoding="utf-8").splitlines()[0])
    record["gold_sql"] = "SELECT hidden"
    eligible.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(SealedMVPFrameError, match="protected"):
        generate_sealed_mvp_frame(
            eligible_manifest=eligible,
            test_ids_path=test_ids,
            config_path=config,
            ids_output=tmp_path / "ids.txt",
            metadata_output=tmp_path / "metadata.json",
        )


def test_generate_frame_fails_closed_on_count_drift(tmp_path: Path) -> None:
    eligible, test_ids, config = _write_inputs(tmp_path)
    value = json.loads(config.read_text(encoding="utf-8"))
    value["expected_question_count"] = 4
    config.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(SealedMVPFrameError, match="count"):
        generate_sealed_mvp_frame(
            eligible_manifest=eligible,
            test_ids_path=test_ids,
            config_path=config,
            ids_output=tmp_path / "ids.txt",
            metadata_output=tmp_path / "metadata.json",
        )


def test_committed_frame_regenerates_byte_identically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).parents[1]
    monkeypatch.chdir(root)
    ids_output = tmp_path / "sealed_mvp_ids.txt"
    metadata_output = tmp_path / "sealed_mvp_frame_metadata.json"

    generate_sealed_mvp_frame(
        eligible_manifest=Path("data/manifests/eligible_questions.jsonl"),
        test_ids_path=Path("data/manifests/test_ids.txt"),
        config_path=Path("config/sealed-mvp-frame-v1.json"),
        ids_output=ids_output,
        metadata_output=metadata_output,
    )

    assert (
        ids_output.read_bytes()
        == (root / "data/manifests/sealed_mvp_ids.txt").read_bytes()
    )
    assert (
        metadata_output.read_bytes()
        == (root / "data/manifests/sealed_mvp_frame_metadata.json").read_bytes()
    )
