"""Freeze-B-bound extraction of exactly the 101 held-out labels."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.sealed_test_release as release_module
from omni_benchmark.sealed_test_release import release_sealed_test_records
from tests.test_sealed_generation_staging import _plan, _workspace


def _source(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "outside-private.jsonl"
    records = [
        {
            "external_knowledge": [question],
            "instance_id": f"q-{question:03d}",
            "sol_sql": [f"SELECT {question}"],
            "test_cases": [],
        }
        for question in range(1, 102)
    ] + [
        {
            "external_knowledge": [999],
            "instance_id": "train-foreign",
            "sol_sql": ["PRIVATE TRAIN SQL"],
            "test_cases": [],
        }
    ]
    content = b"".join(
        (json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n").encode()
        for record in records
    )
    source.write_bytes(content)
    os.chmod(source, 0o600)
    return source, hashlib.sha256(content).hexdigest()


def test_release_projects_only_frozen_test_membership_and_normalizes_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze = _plan()
    source, digest = _source(tmp_path)
    monkeypatch.setattr(
        release_module, "load_sealed_execution_plan", lambda *a, **k: plan
    )
    monkeypatch.setattr(
        release_module,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )

    report = release_sealed_test_records(
        workspace,
        source=source,
        destination=Path("data/private/test/labels.jsonl"),
        expected_source_sha256=digest,
        control_commit=plan.control_commit,
        system_commit=plan.system_commit,
        freeze_b_path=Path("experiments/freeze-b.json"),
        schedule_path=Path("data/final-schedule.jsonl"),
        public_manifest_path=Path("data/manifests/eligible_questions.jsonl"),
    )

    assert report.released_count == 101
    assert report.ignored_count == 1
    output = workspace / "data/private/test/labels.jsonl"
    assert output.stat().st_mode & 0o777 == 0o600
    assert '"external_knowledge":["1"]' in output.read_text(encoding="utf-8")
    assert "PRIVATE TRAIN SQL" not in output.read_text(encoding="utf-8")


def test_source_hash_mismatch_publishes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze = _plan()
    source, _ = _source(tmp_path)
    monkeypatch.setattr(
        release_module, "load_sealed_execution_plan", lambda *a, **k: plan
    )
    monkeypatch.setattr(
        release_module,
        "load_freeze_b_control",
        lambda *a, **k: SimpleNamespace(manifest=freeze),
    )

    with pytest.raises(Exception, match="source SHA-256"):
        release_sealed_test_records(
            workspace,
            source=source,
            destination=Path("data/private/test/labels.jsonl"),
            expected_source_sha256="0" * 64,
            control_commit=plan.control_commit,
            system_commit=plan.system_commit,
            freeze_b_path=Path("experiments/freeze-b.json"),
            schedule_path=Path("data/final-schedule.jsonl"),
            public_manifest_path=Path("data/manifests/eligible_questions.jsonl"),
        )
    assert not (workspace / "data/private/test/labels.jsonl").exists()
