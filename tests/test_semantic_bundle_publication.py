from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.semantic_bundle_publication import (
    SemanticBundlePublicationError,
    build_bundle_artifacts,
    build_e02_bundle_artifacts,
    publish_bundle_artifacts,
    publish_e02_bundle_artifacts,
)
from omni_benchmark.omni_semantic_deployment import build_semantic_deployment_plan

from tests.test_semantic_bundle import (
    _e02_inputs,
    _hkb_records,
    _mapping_records,
    _schema_records,
    _spec,
)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def _jsonl_bytes(records: list[dict[str, object]]) -> bytes:
    return b"".join(_json_bytes(record) for record in records)


def _inputs() -> tuple[bytes, bytes, bytes, bytes, bytes]:
    spec = _json_bytes(_spec())
    hkb = _jsonl_bytes(_hkb_records())
    schema = _jsonl_bytes(_schema_records())
    mapping = _jsonl_bytes(_mapping_records())
    manifest = _json_bytes(
        {
            "counts": {
                "dispositions": {"compile": 1, "context_only": 1},
                "hkb_nodes": 2,
            },
            "database": "db",
            "kind": "public-hkb-semantic-mapping",
            "output": {
                "file": "db.mapping.jsonl",
                "sha256": hashlib.sha256(mapping).hexdigest(),
            },
            "source": {
                "dataset": "public/example",
                "hkb_ir": {
                    "manifest_sha256": "a" * 64,
                    "sha256": hashlib.sha256(hkb).hexdigest(),
                },
                "mapping_spec": {"sha256": "b" * 64},
                "revision": "public-revision",
                "schema_ir": {
                    "manifest_sha256": "c" * 64,
                    "sha256": hashlib.sha256(schema).hexdigest(),
                },
            },
            "schema_version": 1,
            "validation": {
                "all_hkb_nodes_classified_once": True,
                "all_schema_bindings_resolve": True,
                "hidden_annotations_used": False,
                "public_inputs_only": True,
                "status": "passed",
            },
        }
    )
    return spec, hkb, schema, mapping, manifest


def _e02_publication_inputs() -> tuple[bytes, bytes, bytes, bytes, bytes]:
    spec_value, schema_value = _e02_inputs()
    _, hkb, _, mapping, manifest = _inputs()
    spec = _json_bytes(spec_value)
    schema = _jsonl_bytes(schema_value)
    parsed_manifest = json.loads(manifest)
    parsed_manifest["source"]["schema_ir"]["sha256"] = hashlib.sha256(
        schema
    ).hexdigest()
    return spec, hkb, schema, mapping, _json_bytes(parsed_manifest)


def test_build_e02_bundle_artifacts_hash_binds_relationship_candidate() -> None:
    baseline_files, _ = build_bundle_artifacts(*_e02_publication_inputs())
    files, manifest = build_e02_bundle_artifacts(*_e02_publication_inputs())

    assert "relationships" not in baseline_files
    assert "relationships" in files
    assert manifest["validation"]["relationship_contracts_public_only"] is True
    relationship_record = next(
        record for record in manifest["files"] if record["file"] == "relationships"
    )
    assert (
        relationship_record["sha256"]
        == hashlib.sha256(files["relationships"]).hexdigest()
    )


def test_publish_e02_bundle_is_locally_deployment_ready(tmp_path: Path) -> None:
    paths = []
    for index, content in enumerate(_e02_publication_inputs()):
        path = tmp_path / f"e02-input-{index}.json"
        path.write_bytes(content)
        paths.append(path)
    output = tmp_path / "e02-bundle"

    manifest = publish_e02_bundle_artifacts(*paths, output)
    plan = build_semantic_deployment_plan(output)

    assert any(item.local_name == "relationships" for item in plan.files)
    assert (
        plan.manifest_sha256
        == hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
    )
    assert json.loads((output / "manifest.json").read_bytes()) == manifest


def test_build_bundle_artifacts_authenticates_sources_and_hashes_every_file() -> None:
    files, manifest = build_bundle_artifacts(*_inputs())

    assert tuple(files) == (
        "db.public__pointcloud.view",
        "pointcloud_semantics.topic",
    )
    assert manifest["kind"] == "public-omni-semantic-bundle"
    assert (
        manifest["source"]["bundle_spec"]["sha256"]
        == hashlib.sha256(_inputs()[0]).hexdigest()
    )
    assert (
        manifest["source"]["mapping_manifest"]["sha256"]
        == hashlib.sha256(_inputs()[4]).hexdigest()
    )
    for record in manifest["files"]:
        assert record["sha256"] == hashlib.sha256(files[record["file"]]).hexdigest()


def test_build_bundle_artifacts_rejects_mapping_hash_mismatch() -> None:
    spec, hkb, schema, mapping, manifest = _inputs()
    changed = mapping.replace(b"resolution_index", b"different_index", 1)

    with pytest.raises(
        SemanticBundlePublicationError, match="mapping hash does not match manifest"
    ):
        build_bundle_artifacts(spec, hkb, schema, changed, manifest)


def test_build_bundle_artifacts_rejects_protected_mapping_manifest_field() -> None:
    spec, hkb, schema, mapping, manifest = _inputs()
    parsed = json.loads(manifest)
    parsed["diagnostics"] = {"test_correctness": "DO-NOT-INSPECT"}

    with pytest.raises(
        SemanticBundlePublicationError, match="protected field test_correctness"
    ):
        build_bundle_artifacts(spec, hkb, schema, mapping, _json_bytes(parsed))


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda manifest: manifest.update({"schema_version": 2}),
            "unsupported mapping manifest schema_version",
        ),
        (
            lambda manifest: manifest["validation"].update(
                {"hidden_annotations_used": True}
            ),
            "mapping manifest validation is not trusted",
        ),
        (
            lambda manifest: manifest["source"].pop("dataset"),
            "mapping source dataset",
        ),
    ),
)
def test_build_bundle_artifacts_rejects_untrusted_mapping_manifest(
    mutation: object, message: str
) -> None:
    spec, hkb, schema, mapping, manifest = _inputs()
    parsed = json.loads(manifest)
    mutation(parsed)

    with pytest.raises(SemanticBundlePublicationError, match=message):
        build_bundle_artifacts(spec, hkb, schema, mapping, _json_bytes(parsed))


def test_publish_bundle_artifacts_writes_exact_flat_bundle(
    tmp_path: Path,
) -> None:
    paths = []
    for index, content in enumerate(_inputs()):
        path = tmp_path / f"input-{index}.json"
        path.write_bytes(content)
        paths.append(path)
    output = tmp_path / "bundle"

    manifest = publish_bundle_artifacts(*paths, output)

    assert sorted(path.name for path in output.iterdir()) == [
        "db.public__pointcloud.view",
        "manifest.json",
        "pointcloud_semantics.topic",
    ]
    assert json.loads((output / "manifest.json").read_text()) == manifest


def test_publish_bundle_artifacts_rejects_unexpected_existing_output(
    tmp_path: Path,
) -> None:
    paths = []
    for index, content in enumerate(_inputs()):
        path = tmp_path / f"input-{index}.json"
        path.write_bytes(content)
        paths.append(path)
    output = tmp_path / "bundle"
    output.mkdir()
    (output / "stale.view").write_text("stale", encoding="utf-8")

    with pytest.raises(
        SemanticBundlePublicationError, match="unexpected entries: stale.view"
    ):
        publish_bundle_artifacts(*paths, output)


def test_publish_bundle_artifacts_rejects_symlinked_input(tmp_path: Path) -> None:
    paths = []
    for index, content in enumerate(_inputs()):
        path = tmp_path / f"input-{index}.json"
        path.write_bytes(content)
        paths.append(path)
    link = tmp_path / "link.json"
    link.symlink_to(paths[0])

    with pytest.raises(SemanticBundlePublicationError, match="regular.*file"):
        publish_bundle_artifacts(link, *paths[1:], tmp_path / "bundle")
