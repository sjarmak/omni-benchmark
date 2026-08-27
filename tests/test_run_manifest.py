from __future__ import annotations

import json
import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore
from omni_benchmark.run_manifest import (
    RunManifest,
    RunManifestError,
    read_bound_run_manifest,
    read_run_manifest,
)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
COMMIT = "e" * 40


def _value(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "budget_id": "standard-120s-v1",
        "cli_versions": {"omni": "1.1.2"},
        "condition": "C4",
        "controllable_seed": None,
        "finished_at": "2026-08-27T14:02:03Z",
        "generation_sha256": SHA_A,
        "git_commit": COMMIT,
        "harness_config_sha256": SHA_B,
        "instructions_sha256": SHA_C,
        "model": "managed-standard",
        "model_config_id": "omni-production-default",
        "prompt_sha256": SHA_D,
        "provider": "aws-bedrock",
        "repetition": 1,
        "schema_version": 2,
        "semantic_model_ref": "branch:public-benchmark-v1",
        "semantic_model_sha256": SHA_B,
        "scope": "dev-a",
        "software_versions": {"omni-benchmark": "0.1.0", "python": "3.11.9"},
        "started_at": "2026-08-27T14:00:00Z",
    }
    return {**value, **overrides}


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return workspace


def test_manifest_is_immutable_and_has_deterministic_canonical_json() -> None:
    manifest = RunManifest.from_dict(_value())

    assert manifest.condition == "C4"
    assert manifest.semantic_model_ref == "branch:public-benchmark-v1"
    assert manifest.semantic_model_sha256 == SHA_B
    assert manifest.software_versions == (
        ("omni-benchmark", "0.1.0"),
        ("python", "3.11.9"),
    )
    assert (
        manifest.canonical_bytes()
        == (
            json.dumps(
                _value(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            + "\n"
        ).encode()
    )
    with pytest.raises(FrozenInstanceError):
        manifest.condition = "C1"  # type: ignore[misc]
    with pytest.raises(TypeError):
        manifest.software_versions[0] = ("python", "0")  # type: ignore[index]


@pytest.mark.parametrize("condition", ["C1", "C2", "C3", "C4"])
@pytest.mark.parametrize("scope", ["train", "dev-a", "dev-b"])
def test_manifest_accepts_only_development_scopes_and_all_conditions(
    condition: str, scope: str
) -> None:
    manifest = RunManifest.from_dict(
        _value(condition=condition, scope=scope, controllable_seed=17)
    )

    assert manifest.condition == condition
    assert manifest.scope == scope
    assert manifest.controllable_seed == 17


@pytest.mark.parametrize("scope", ["test", "sealed-test", "DEV-A"])
def test_manifest_rejects_non_optimization_scopes(scope: str) -> None:
    with pytest.raises(RunManifestError, match="scope"):
        RunManifest.from_dict(_value(scope=scope))


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"unexpected": "value"}, "exact schema"),
        ({"condition": "C5"}, "condition"),
        ({"repetition": 0}, "repetition"),
        ({"repetition": True}, "repetition"),
        ({"controllable_seed": True}, "controllable_seed"),
        ({"generation_sha256": "A" * 64}, "generation_sha256"),
        ({"harness_config_sha256": "short"}, "harness_config_sha256"),
        ({"git_commit": "f" * 39}, "git_commit"),
        ({"prompt_sha256": "g" * 64}, "prompt_sha256"),
        ({"semantic_model_ref": "contains spaces"}, "semantic_model_ref"),
        ({"semantic_model_sha256": "short"}, "semantic_model_sha256"),
        (
            {"semantic_model_sha256": None},
            "",
        ),
        ({"schema_version": True}, "schema_version"),
        ({"schema_version": 1}, "schema_version"),
        ({"software_versions": {}}, "software_versions"),
        ({"cli_versions": {"omni": ""}}, "cli_versions"),
        (
            {"started_at": "2026-08-27T14:02:04Z"},
            "finished_at",
        ),
        ({"finished_at": "2026-08-27 14:02:03"}, "finished_at"),
    ],
)
def test_manifest_rejects_malformed_schema(
    overrides: dict[str, object], match: str
) -> None:
    if match:
        with pytest.raises(RunManifestError, match=match):
            RunManifest.from_dict(_value(**overrides))
    else:
        assert RunManifest.from_dict(_value(**overrides)).semantic_model_sha256 is None


def test_manifest_rejects_live_credentials_and_common_secret_shapes() -> None:
    with pytest.raises(RunManifestError, match="sensitive"):
        RunManifest.from_dict(
            _value(model_config_id="config-live-secret"),
            environment={"OMNI_API_TOKEN": "live-secret"},
        )
    with pytest.raises(RunManifestError, match="sensitive"):
        RunManifest.from_dict(_value(model="Bearer abcdefghijklmnopqrstuvwxyz"))


def test_private_canonical_run_json_round_trip(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    manifest = RunManifest.from_dict(_value())
    store = ArtifactStore(workspace, Path("runs/r-001"))
    artifact = store.write_json(Path("run.json"), manifest.as_dict())

    loaded = read_run_manifest(workspace, Path("runs/r-001/run.json"))

    assert loaded == manifest
    assert artifact.sha256 == manifest.sha256()
    assert stat.S_IMODE(artifact.path.stat().st_mode) == 0o600


def test_bound_manifest_matches_generation_identity_and_expected_hash(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    manifest = RunManifest.from_dict(_value())
    store = ArtifactStore(workspace, Path("runs/r-001"))
    artifact = store.write_json(Path("run.json"), manifest.as_dict())

    loaded = read_bound_run_manifest(
        workspace,
        Path("runs/r-001/run.json"),
        expected_sha256=artifact.sha256,
        generation_sha256=SHA_A,
        condition="C4",
        scope="dev-a",
        repetition=1,
        provider="aws-bedrock",
        model="managed-standard",
        started_at="2026-08-27T14:00:00Z",
        finished_at="2026-08-27T14:02:03Z",
    )

    assert loaded == manifest


@pytest.mark.parametrize(
    ("override", "match"),
    [
        ({"expected_sha256": SHA_B}, "expected SHA-256"),
        ({"generation_sha256": SHA_B}, "generation"),
        ({"condition": "C1"}, "condition"),
        ({"scope": "train"}, "scope"),
        ({"repetition": 2}, "repetition"),
        ({"provider": "anthropic"}, "provider"),
        ({"model": "other-model"}, "model"),
        ({"started_at": "2026-08-27T13:59:59Z"}, "timestamps"),
        ({"finished_at": "2026-08-27T14:02:04Z"}, "timestamps"),
    ],
)
def test_bound_manifest_rejects_generation_mismatch(
    tmp_path: Path,
    override: dict[str, object],
    match: str,
) -> None:
    workspace = _workspace(tmp_path)
    manifest = RunManifest.from_dict(_value())
    artifact = ArtifactStore(workspace, Path("runs/r-001")).write_json(
        Path("run.json"), manifest.as_dict()
    )
    arguments: dict[str, object] = {
        "expected_sha256": artifact.sha256,
        "generation_sha256": SHA_A,
        "condition": "C4",
        "scope": "dev-a",
        "repetition": 1,
        "provider": "aws-bedrock",
        "model": "managed-standard",
        "started_at": "2026-08-27T14:00:00Z",
        "finished_at": "2026-08-27T14:02:03Z",
    }

    with pytest.raises(RunManifestError, match=match):
        read_bound_run_manifest(
            workspace,
            Path("runs/r-001/run.json"),
            **{**arguments, **override},  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "path",
    [
        Path("public/run.json"),
        Path("runs/r-001/other.json"),
        Path("../runs/r-001/run.json"),
    ],
)
def test_reader_rejects_wrong_paths(tmp_path: Path, path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(RunManifestError, match="path"):
        read_run_manifest(workspace, path)


def test_reader_rejects_non_private_noncanonical_and_linked_files(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    target = workspace / "runs" / "r-001" / "run.json"
    target.parent.mkdir(parents=True)
    (workspace / "runs").chmod(0o700)
    target.parent.chmod(0o700)
    target.write_text(json.dumps(_value(), indent=2), encoding="utf-8")
    target.chmod(0o644)

    with pytest.raises(RunManifestError, match="private regular file"):
        read_run_manifest(workspace, Path("runs/r-001/run.json"))

    target.chmod(0o600)
    with pytest.raises(RunManifestError, match="canonical JSON"):
        read_run_manifest(workspace, Path("runs/r-001/run.json"))

    target.write_bytes(RunManifest.from_dict(_value()).canonical_bytes())
    linked = workspace / "runs" / "r-002" / "run.json"
    linked.parent.mkdir(parents=True)
    linked.parent.chmod(0o700)
    os.link(target, linked)
    with pytest.raises(RunManifestError, match="private regular file"):
        read_run_manifest(workspace, Path("runs/r-002/run.json"))


def test_reader_rejects_symlink_and_sensitive_content(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "run.json"
    outside.write_bytes(RunManifest.from_dict(_value()).canonical_bytes())
    outside.chmod(0o600)
    linked = workspace / "runs" / "r-001" / "run.json"
    linked.parent.mkdir(parents=True)
    (workspace / "runs").chmod(0o700)
    linked.parent.chmod(0o700)
    linked.symlink_to(outside)

    with pytest.raises(RunManifestError, match="private regular file"):
        read_run_manifest(workspace, Path("runs/r-001/run.json"))

    linked.unlink()
    sensitive = _value(model_config_id="contains-live-secret")
    linked.write_bytes(
        (
            json.dumps(
                sensitive, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            + "\n"
        ).encode()
    )
    linked.chmod(0o600)
    with pytest.raises(RunManifestError, match="sensitive"):
        read_run_manifest(
            workspace,
            Path("runs/r-001/run.json"),
            environment={"OMNI_API_TOKEN": "live-secret"},
        )
