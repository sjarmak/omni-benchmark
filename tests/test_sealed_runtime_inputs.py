from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from omni_benchmark.freeze_b import FreezeBManifest
from omni_benchmark.freeze_b_record import record_freeze_b
from omni_benchmark.sealed_runtime_inputs import (
    SealedRuntimeInputError,
    load_sealed_runtime_inputs,
)
from tests.test_freeze_b_record import RECORDED_AT, _repository


def _manifest(repo: Path, commit: str) -> FreezeBManifest:
    return record_freeze_b(
        repo,
        system_commit=commit,
        input_spec_path=Path("config/freeze-b-input.json"),
        recorded_at=RECORDED_AT,
        destination=Path("experiments/freeze-b.json"),
    ).manifest


def test_loads_all_exact_runtime_paths_from_system_git_objects(tmp_path: Path) -> None:
    repo, commit, _ = _repository(tmp_path)
    manifest = _manifest(repo, commit)
    (repo / "config/conditions/c1.json").write_text(
        '{"condition":"dirty-substitution"}\n', encoding="utf-8"
    )

    inputs = load_sealed_runtime_inputs(
        repo,
        system_commit=commit,
        input_spec_path=Path("config/freeze-b-input.json"),
        freeze_b=manifest,
    )

    assert inputs.system_commit == commit
    assert inputs.freeze_a_commit == manifest.freeze_a_commit
    assert inputs.database_snapshot_path == Path("data/database-snapshot.json")
    assert [item.condition for item in inputs.conditions] == ["C1", "C2", "C3", "C4"]
    assert inputs.condition("C1").harness_config_path == Path(
        "config/conditions/c1.json"
    )
    assert inputs.condition("C1").semantic_model_path is None
    assert inputs.condition("C3").semantic_model_path == Path("models/c3-export.json")
    assert inputs.condition("C4").freeze_b_condition == manifest.condition("C4")
    assert (
        inputs.input_spec_sha256
        == dict(manifest.frozen_files)["config/freeze-b-input.json"]
    )


def test_rejects_condition_identity_or_frozen_digest_substitution(
    tmp_path: Path,
) -> None:
    repo, commit, _ = _repository(tmp_path)
    manifest = _manifest(repo, commit)
    value = manifest.as_dict()
    value["conditions"][0]["provider"] = "substituted-provider"
    substituted = FreezeBManifest.from_dict(value)

    with pytest.raises(SealedRuntimeInputError, match="condition"):
        load_sealed_runtime_inputs(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            freeze_b=substituted,
        )

    frozen = dict(manifest.frozen_files)
    frozen["config/final-prompt.txt"] = "0" * 64
    wrong_digest = replace(manifest, frozen_files=tuple(sorted(frozen.items())))
    with pytest.raises(SealedRuntimeInputError, match="frozen|digest"):
        load_sealed_runtime_inputs(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            freeze_b=wrong_digest,
        )


def test_rejects_wrong_commit_path_or_database_snapshot(tmp_path: Path) -> None:
    repo, commit, _ = _repository(tmp_path)
    manifest = _manifest(repo, commit)

    with pytest.raises(SealedRuntimeInputError, match="system commit"):
        load_sealed_runtime_inputs(
            repo,
            system_commit="0" * 40,
            input_spec_path=Path("config/freeze-b-input.json"),
            freeze_b=manifest,
        )
    with pytest.raises(SealedRuntimeInputError, match="input spec"):
        load_sealed_runtime_inputs(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/missing.json"),
            freeze_b=manifest,
        )

    value = manifest.as_dict()
    value["database"]["snapshot_manifest_sha256"] = "1" * 64
    wrong_database = FreezeBManifest.from_dict(value)
    with pytest.raises(SealedRuntimeInputError, match="database snapshot"):
        load_sealed_runtime_inputs(
            repo,
            system_commit=commit,
            input_spec_path=Path("config/freeze-b-input.json"),
            freeze_b=wrong_database,
        )


def test_runtime_input_value_is_strict_and_condition_lookup_fails_closed(
    tmp_path: Path,
) -> None:
    repo, commit, _ = _repository(tmp_path)
    inputs = load_sealed_runtime_inputs(
        repo,
        system_commit=commit,
        input_spec_path=Path("config/freeze-b-input.json"),
        freeze_b=_manifest(repo, commit),
    )

    with pytest.raises(SealedRuntimeInputError, match="condition"):
        inputs.condition("C5")
    assert json.loads(inputs.public_summary_json())["condition_count"] == 4
