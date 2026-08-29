from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.omni_semantic_deployment import (
    OmniSemanticDeploymentError,
    build_semantic_deployment_plan,
    verify_semantic_deployment_readback,
)


VIEW_NAME = "archeology_scan_large.public__pointcloud.view"
VIEW_PATH = "archeology_scan_large.public/pointcloud.view"
TOPIC_NAME = "pointcloud_semantics.topic"
VIEW = """label: Point Cloud
description: Public point-cloud records.
catalog: archeology_scan_large
schema: public
table_name: pointcloud
dimensions:
  scan_resolution_mm:
    label: Scan Resolution
    sql: CAST(${cloud_metrics} AS DOUBLE PRECISION)
"""
TOPIC = """base_view: archeology_scan_large_public__pointcloud
label: Point Cloud
fields:
- archeology_scan_large_public__pointcloud.*
"""
RELATIONSHIPS = """- join_from_view: archeology_scan_large_public__pointcloud
  join_to_view: archeology_scan_large_public__sites
  join_type: always_left
  on_sql: ${archeology_scan_large_public__pointcloud.site_id} = ${archeology_scan_large_public__sites.id}
  relationship_type: many_to_one
  reversible: false
"""


def _manifest(files: dict[str, bytes]) -> dict[str, object]:
    return {
        "database": "archeology_scan_large",
        "files": [
            {
                "file": name,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for name, content in files.items()
        ],
        "kind": "public-omni-semantic-bundle",
        "schema_version": 1,
    }


def _bundle(tmp_path: Path, files: dict[str, bytes] | None = None) -> Path:
    root = tmp_path / "bundle"
    root.mkdir(parents=True)
    content = files or {VIEW_NAME: VIEW.encode(), TOPIC_NAME: TOPIC.encode()}
    for name, value in content.items():
        (root / name).write_bytes(value)
    (root / "manifest.json").write_text(
        json.dumps(_manifest(content), sort_keys=True), encoding="utf-8"
    )
    return root


def _readback() -> dict[str, str]:
    return {
        VIEW_PATH: """# Reference this view as archeology_scan_large_public__pointcloud
dimensions:
  scan_resolution_mm:
    sql: CAST(${cloud_metrics} AS DOUBLE PRECISION)
    label: Scan Resolution
description: Public point-cloud records.
label: Point Cloud
""",
        TOPIC_NAME: """fields:
- archeology_scan_large_public__pointcloud.*
label: Point Cloud
base_view: archeology_scan_large_public__pointcloud""",
    }


def test_plan_authenticates_and_maps_every_repository_bundle_file() -> None:
    root = Path(__file__).parents[1] / "semantic_models/public_bundle"

    plan = build_semantic_deployment_plan(root)

    manifest = json.loads((root / "manifest.json").read_text())
    assert len(plan.files) == len(manifest["files"]) == 14
    assert (
        plan.manifest_sha256
        == hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
    )
    mapped = {item.local_name: item.remote_path for item in plan.files}
    assert mapped[VIEW_NAME] == VIEW_PATH
    assert mapped[TOPIC_NAME] == TOPIC_NAME
    assert set(mapped) == {item["file"] for item in manifest["files"]}


def test_plan_accepts_and_verifies_exact_global_relationship_sequence(
    tmp_path: Path,
) -> None:
    files = {
        VIEW_NAME: VIEW.encode(),
        TOPIC_NAME: TOPIC.encode(),
        "relationships": RELATIONSHIPS.encode(),
    }
    root = _bundle(tmp_path, files)

    plan = build_semantic_deployment_plan(root)

    mapped = {item.local_name: item.remote_path for item in plan.files}
    assert mapped["relationships"] == "relationships"
    readback = _readback()
    readback["relationships"] = RELATIONSHIPS
    verify_semantic_deployment_readback(plan, readback)


def test_plan_still_rejects_a_sequence_for_a_topic(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path,
        {VIEW_NAME: VIEW.encode(), TOPIC_NAME: b"- not-a-topic\n"},
    )

    with pytest.raises(OmniSemanticDeploymentError, match="mapping"):
        build_semantic_deployment_plan(root)


def test_plan_requires_a_sequence_for_global_relationships(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path,
        {
            VIEW_NAME: VIEW.encode(),
            TOPIC_NAME: TOPIC.encode(),
            "relationships": b"not: a-sequence\n",
        },
    )

    with pytest.raises(OmniSemanticDeploymentError, match="sequence"):
        build_semantic_deployment_plan(root)


def test_plan_rejects_unbounded_global_relationship_sql(tmp_path: Path) -> None:
    root = _bundle(
        tmp_path,
        {
            VIEW_NAME: VIEW.encode(),
            TOPIC_NAME: TOPIC.encode(),
            "relationships": RELATIONSHIPS.replace(
                "${archeology_scan_large_public__pointcloud.site_id} = ${archeology_scan_large_public__sites.id}",
                "1 = 1",
            ).encode(),
        },
    )

    with pytest.raises(OmniSemanticDeploymentError, match="on_sql"):
        build_semantic_deployment_plan(root)


@pytest.mark.parametrize("change", ["digest", "size", "missing", "extra"])
def test_plan_rejects_manifest_or_local_file_mismatch(
    tmp_path: Path, change: str
) -> None:
    root = _bundle(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    if change == "digest":
        manifest["files"][0]["sha256"] = "f" * 64
    elif change == "size":
        manifest["files"][0]["size_bytes"] += 1
    elif change == "missing":
        (root / VIEW_NAME).unlink()
    else:
        (root / "unexpected.topic").write_text("label: Extra\n", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(OmniSemanticDeploymentError, match="(manifest|file|hash|size)"):
        build_semantic_deployment_plan(root)


@pytest.mark.parametrize(
    "name",
    [
        "../escape.view",
        "nested/escape.topic",
        "nested\\escape.topic",
        "pointcloud.yaml",
        "db.public_pointcloud.view",
        "db.public__point.cloud.view",
        "db..public__pointcloud.view",
    ],
)
def test_plan_rejects_path_confusion_and_malformed_names(
    tmp_path: Path, name: str
) -> None:
    root = _bundle(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"][0]["file"] = name
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(OmniSemanticDeploymentError, match="(name|path|suffix|view)"):
        build_semantic_deployment_plan(root)


def test_plan_rejects_duplicate_local_names_and_remote_case_collisions(
    tmp_path: Path,
) -> None:
    root = _bundle(tmp_path)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"].append(dict(manifest["files"][0]))
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OmniSemanticDeploymentError, match="duplicate"):
        build_semantic_deployment_plan(root)

    collision_root = _bundle(
        tmp_path / "collision",
        {"Metric.topic": b"label: First\n", "metric.topic": b"label: Second\n"},
    )
    with pytest.raises(OmniSemanticDeploymentError, match="collision"):
        build_semantic_deployment_plan(collision_root)


def test_readback_allows_only_safe_yaml_semantics_and_view_projection(
    tmp_path: Path,
) -> None:
    plan = build_semantic_deployment_plan(_bundle(tmp_path))

    verify_semantic_deployment_readback(plan, _readback())


def test_readback_accepts_utf8_bytes_and_terminal_newline_serialization(
    tmp_path: Path,
) -> None:
    plan = build_semantic_deployment_plan(_bundle(tmp_path))
    readback = {
        path: value.rstrip("\n").encode("utf-8") for path, value in _readback().items()
    }

    verify_semantic_deployment_readback(plan, readback)


@pytest.mark.parametrize("change", ["missing", "extra", "identity", "content"])
def test_readback_rejects_any_unpermitted_difference(
    tmp_path: Path, change: str
) -> None:
    plan = build_semantic_deployment_plan(_bundle(tmp_path))
    readback = _readback()
    if change == "missing":
        del readback[TOPIC_NAME]
    elif change == "extra":
        readback["extra.topic"] = "label: Extra\n"
    elif change == "identity":
        readback[VIEW_PATH] += "catalog: archeology_scan_large\n"
    else:
        readback[VIEW_PATH] = readback[VIEW_PATH].replace(
            "Public point-cloud records.", "Changed description."
        )

    with pytest.raises(OmniSemanticDeploymentError, match="readback"):
        verify_semantic_deployment_readback(plan, readback)


@pytest.mark.parametrize(
    "content",
    [
        "label: First\nlabel: Second\n",
        "label: !!python/object/apply:os.system ['echo unsafe']\n",
    ],
)
def test_readback_rejects_duplicate_keys_and_unsafe_yaml(
    tmp_path: Path, content: str
) -> None:
    plan = build_semantic_deployment_plan(_bundle(tmp_path))
    readback = _readback()
    readback[TOPIC_NAME] = content

    with pytest.raises(OmniSemanticDeploymentError, match="YAML"):
        verify_semantic_deployment_readback(plan, readback)


def test_readback_semantic_comparison_preserves_scalar_types(tmp_path: Path) -> None:
    typed_topic = TOPIC + "limit: 1.0\n"
    root = _bundle(
        tmp_path, {VIEW_NAME: VIEW.encode(), TOPIC_NAME: typed_topic.encode()}
    )
    plan = build_semantic_deployment_plan(root)
    readback = _readback()
    readback[TOPIC_NAME] += "\nlimit: 1\n"

    with pytest.raises(OmniSemanticDeploymentError, match="semantic content"):
        verify_semantic_deployment_readback(plan, readback)


def test_plan_rejects_duplicate_manifest_keys_and_unsafe_local_yaml(
    tmp_path: Path,
) -> None:
    root = _bundle(tmp_path)
    (root / "manifest.json").write_text(
        '{"database":"a","database":"b","files":[],'
        '"kind":"public-omni-semantic-bundle","schema_version":1}',
        encoding="utf-8",
    )
    with pytest.raises(OmniSemanticDeploymentError, match="duplicate"):
        build_semantic_deployment_plan(root)

    root = _bundle(tmp_path / "unsafe")
    unsafe = b"label: First\nlabel: Second\n"
    (root / TOPIC_NAME).write_bytes(unsafe)
    manifest = _manifest({VIEW_NAME: VIEW.encode(), TOPIC_NAME: unsafe})
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(OmniSemanticDeploymentError, match="YAML"):
        build_semantic_deployment_plan(root)


def test_plan_rejects_local_view_identity_that_disagrees_with_file_name(
    tmp_path: Path,
) -> None:
    changed = VIEW.replace("schema: public", "schema: private").encode()
    root = _bundle(tmp_path, {VIEW_NAME: changed, TOPIC_NAME: TOPIC.encode()})

    with pytest.raises(OmniSemanticDeploymentError, match="view identity"):
        build_semantic_deployment_plan(root)


def test_plan_preserves_case_sensitive_physical_table_for_normalized_view_name(
    tmp_path: Path,
) -> None:
    normalized_name = "archeology_scan_large.public__api_endpoint.view"
    case_sensitive_view = VIEW.replace(
        "table_name: pointcloud", "table_name: API_Endpoint"
    ).encode()
    root = _bundle(
        tmp_path,
        {normalized_name: case_sensitive_view, TOPIC_NAME: TOPIC.encode()},
    )

    plan = build_semantic_deployment_plan(root)

    mapped = {item.local_name: item.remote_path for item in plan.files}
    assert mapped[normalized_name] == ("archeology_scan_large.public/api_endpoint.view")


def test_plan_qualifies_flat_view_from_authenticated_document_identity(
    tmp_path: Path,
) -> None:
    flat_name = "pointcloud.view"
    root = _bundle(tmp_path, {flat_name: VIEW.encode(), TOPIC_NAME: TOPIC.encode()})

    plan = build_semantic_deployment_plan(root)

    mapped = {item.local_name: item.remote_path for item in plan.files}
    assert mapped[flat_name] == VIEW_PATH


def test_plan_rejects_symlinks_and_a_view_catalog_mismatch(tmp_path: Path) -> None:
    root = _bundle(tmp_path)
    target = root.parent / "target.yaml"
    target.write_text(TOPIC, encoding="utf-8")
    (root / TOPIC_NAME).unlink()
    (root / TOPIC_NAME).symlink_to(target)
    with pytest.raises(OmniSemanticDeploymentError, match="regular file"):
        build_semantic_deployment_plan(root)

    mismatch = _bundle(
        tmp_path / "catalog",
        {"other.public__pointcloud.view": VIEW.encode(), TOPIC_NAME: TOPIC.encode()},
    )
    with pytest.raises(OmniSemanticDeploymentError, match="catalog"):
        build_semantic_deployment_plan(mismatch)


def test_plan_rejects_a_symlink_as_the_bundle_root(tmp_path: Path) -> None:
    real_root = _bundle(tmp_path / "real")
    linked_root = tmp_path / "linked-bundle"
    linked_root.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(OmniSemanticDeploymentError, match="bundle root.*symlink"):
        build_semantic_deployment_plan(linked_root)
