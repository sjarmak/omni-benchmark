from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from omni_benchmark.artifact_store import ArtifactStore, ArtifactStoreError


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    return workspace


def test_store_creates_private_immutable_json_artifacts(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    store = ArtifactStore(workspace, Path("runs/smoke"))

    artifact = store.write_json(
        Path("attempts/c4/result.json"),
        {"schema_version": 1, "value": 42},
    )

    assert json.loads(artifact.path.read_text()) == {"schema_version": 1, "value": 42}
    assert stat.S_IMODE(artifact.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(artifact.path.parent.stat().st_mode) == 0o700
    assert artifact.path.stat().st_nlink == 1
    with pytest.raises(ArtifactStoreError, match="already exists"):
        store.write_json(
            Path("attempts/c4/result.json"),
            {"schema_version": 1, "value": 43},
        )


def test_store_rejects_unignored_or_unconfined_roots(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    with pytest.raises(ArtifactStoreError, match="gitignored"):
        ArtifactStore(workspace, Path("public/output"))
    with pytest.raises(ArtifactStoreError, match="confined relative path"):
        ArtifactStore(workspace, Path("../escape"))


def test_store_rejects_sensitive_content_instead_of_rewriting_results(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    store = ArtifactStore(
        workspace,
        Path("runs/smoke"),
        environment={"OMNI_API_TOKEN": "live-secret-value"},
    )

    with pytest.raises(ArtifactStoreError, match="sensitive content"):
        store.write_json(
            Path("attempts/c4/result.json"),
            {"schema_version": 1, "value": "live-secret-value"},
        )
    assert not (
        workspace / "runs" / "smoke" / "attempts" / "c4" / "result.json"
    ).exists()


def test_store_raw_byte_entry_point_cannot_bypass_content_policy(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    store = ArtifactStore(
        workspace,
        Path("runs/smoke"),
        environment={"OMNI_API_TOKEN": "live-secret-value"},
    )

    with pytest.raises(ArtifactStoreError, match="sensitive content"):
        store.write_bytes(Path("raw.txt"), b"live-secret-value")


def test_store_rejects_database_connection_url_from_environment(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    connection = "postgresql://benchmark:live-password@db.example/analytics"
    store = ArtifactStore(
        workspace,
        Path("runs/smoke"),
        environment={"DATABASE_URL": connection},
    )

    with pytest.raises(ArtifactStoreError, match="sensitive content"):
        store.write_bytes(Path("connection.txt"), connection.encode())


@pytest.mark.parametrize(
    "field",
    ["apiKey", "token", "credential", "credentials", "access_key", "auth"],
)
def test_store_rejects_sensitive_json_fields(tmp_path: Path, field: str) -> None:
    workspace = _workspace(tmp_path)
    store = ArtifactStore(workspace, Path("runs/smoke"))

    with pytest.raises(ArtifactStoreError, match="sensitive content"):
        store.write_json(Path("response.json"), {field: "opaque-value"})


def test_store_rejects_symlinked_parent(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "runs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ArtifactStoreError, match="secure artifact directory"):
        ArtifactStore(workspace, Path("runs/smoke"))


def test_store_can_require_a_brand_new_collision_free_root(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)

    store = ArtifactStore(
        workspace,
        Path("runs/fresh-attempt"),
        require_new_root=True,
    )

    assert (workspace / "runs" / "fresh-attempt").is_dir()
    store.write_json(Path("generation.json"), {"schema_version": 1})
    with pytest.raises(ArtifactStoreError, match="must not already exist"):
        ArtifactStore(
            workspace,
            Path("runs/fresh-attempt"),
            require_new_root=True,
        )


def test_store_binds_artifacts_to_the_exact_workspace_root(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    first = ArtifactStore(workspace, Path("runs/first"))
    second = ArtifactStore(workspace, Path("runs/second"))
    artifact = first.write_json(Path("value.json"), {"value": 1})

    assert first.relative_path(artifact) == Path("runs/first/value.json")
    assert first.root_identity != second.root_identity
    first.require_workspace(workspace)
    with pytest.raises(ArtifactStoreError, match="store root"):
        second.relative_path(artifact)
    with pytest.raises(ArtifactStoreError, match="publisher workspace"):
        first.require_workspace(tmp_path)


@pytest.mark.parametrize("constant", [float("nan"), float("inf"), float("-inf")])
def test_store_rejects_nonfinite_json(tmp_path: Path, constant: float) -> None:
    workspace = _workspace(tmp_path)
    store = ArtifactStore(workspace, Path("runs/nonfinite"))

    with pytest.raises(ArtifactStoreError, match="finite JSON"):
        store.write_json(Path("value.json"), {"value": constant})
    assert not (workspace / "runs/nonfinite/value.json").exists()
