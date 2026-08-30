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


def _source(tmp_path: Path, question_count: int = 101) -> tuple[Path, str]:
    source = tmp_path / "outside-private.jsonl"
    records = [
        {
            "external_knowledge": [question],
            "instance_id": f"q-{question:03d}",
            "sol_sql": [f"SELECT {question}"],
            "test_cases": [],
        }
        for question in range(1, question_count + 1)
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
        test_ids_path=Path("data/manifests/sealed_mvp_ids.txt"),
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
            test_ids_path=Path("data/manifests/sealed_mvp_ids.txt"),
        )
    assert not (workspace / "data/private/test/labels.jsonl").exists()


def test_release_accepts_the_frozen_89_question_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze = _plan(89)
    source, digest = _source(tmp_path, 89)
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
        test_ids_path=Path("data/manifests/sealed_mvp_ids.txt"),
    )

    assert report.released_count == 89
    assert report.ignored_count == 1


def test_release_cli_requires_and_forwards_selected_test_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    monkeypatch.setattr(
        release_module, "_require_exact_control_checkout", lambda *args: None
    )
    calls = {}

    def release_records(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.update(kwargs)
        return SimpleNamespace(as_dict=lambda: {"status": "released"})

    monkeypatch.setattr(release_module, "release_sealed_test_records", release_records)

    status = release_module.sealed_test_release_main(
        [
            "--workspace",
            str(workspace),
            "--source",
            str(tmp_path / "outside-private.jsonl"),
            "--expected-source-sha256",
            "a" * 64,
            "--control-commit",
            "f" * 40,
            "--system-commit",
            "e" * 40,
            "--freeze-b",
            "experiments/freeze-b.json",
            "--schedule",
            "data/final-schedule.jsonl",
            "--public-manifest",
            "data/manifests/eligible_questions.jsonl",
            "--test-ids",
            "data/manifests/sealed_mvp_ids.txt",
            "--release-sealed-test",
        ]
    )

    assert status == 0
    assert calls["test_ids_path"] == Path("data/manifests/sealed_mvp_ids.txt")
