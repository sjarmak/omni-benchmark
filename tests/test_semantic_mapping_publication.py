from __future__ import annotations

import hashlib
import json

import pytest

from omni_benchmark.semantic_mapping_publication import (
    SemanticMappingPublicationError,
    build_mapping_artifacts,
    publish_mapping_artifacts,
)
from omni_benchmark.semantic_mapping_cli import main


DATABASE = "alpha_large"
TABLE = f"{DATABASE}:table:measurements"
COLUMN = f"{DATABASE}:column:measurements:value"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True) + "\n").encode()


def _inputs() -> tuple[bytes, bytes, bytes, bytes]:
    hkb = _json_bytes(
        {
            "database": DATABASE,
            "dependency_stable_ids": [],
            "hkb_id": 0,
            "stable_id": f"{DATABASE}:hkb:0",
        }
    )
    schema = b"".join(
        [
            _json_bytes(
                {"database": DATABASE, "record_kind": "table", "stable_id": TABLE}
            ),
            _json_bytes(
                {
                    "database": DATABASE,
                    "record_kind": "column",
                    "stable_id": COLUMN,
                    "table_stable_id": TABLE,
                }
            ),
        ]
    )
    spec = _json_bytes(
        {
            "database": DATABASE,
            "records": [
                {
                    "bindings": [
                        {"alias": "VALUE", "confidence": "exact", "role": "value"}
                    ],
                    "dependency_audit": {
                        "missing_ids": [],
                        "redundant_ids": [],
                    },
                    "dependency_mode": "same_grain",
                    "disposition": "compile",
                    "hkb_id": 0,
                    "loss_codes": ["omni_expression_support_unverified"],
                    "notes": "Public-only test mapping.",
                    "relationship_requirements": [],
                    "representation": "numeric_derived_dimension",
                    "semantic_name": "metric_0",
                    "target_alias": "TABLE",
                }
            ],
            "schema_aliases": {"TABLE": TABLE, "VALUE": COLUMN},
            "schema_version": 1,
        }
    )
    schema_manifest = _json_bytes(
        {
            "database": DATABASE,
            "kind": "public-schema-intermediate-representation",
            "output": {
                "file": f"{DATABASE}.schema.jsonl",
                "sha256": hashlib.sha256(schema).hexdigest(),
            },
            "source": {
                "companion_hkb_ir": {
                    "manifest_sha256": "a" * 64,
                    "sha256": hashlib.sha256(hkb).hexdigest(),
                },
                "dataset": "public-dataset",
                "revision": "public-revision",
            },
        }
    )
    return spec, hkb, schema, schema_manifest


def _inputs_with_database(database: str) -> tuple[bytes, bytes, bytes, bytes]:
    spec_bytes, hkb_bytes, schema, manifest_bytes = _inputs()

    def replace(value: str) -> str:
        return value.replace(DATABASE, database)

    spec = json.loads(spec_bytes, parse_int=int)
    spec = json.loads(replace(json.dumps(spec)))
    hkb = json.loads(replace(hkb_bytes.decode()))
    schema_records = [
        json.loads(replace(line)) for line in schema.decode().splitlines()
    ]
    schema = b"".join(_json_bytes(record) for record in schema_records)
    manifest = json.loads(replace(manifest_bytes.decode()))
    hkb_content = _json_bytes(hkb)
    manifest["output"]["sha256"] = hashlib.sha256(schema).hexdigest()
    manifest["source"]["companion_hkb_ir"]["sha256"] = hashlib.sha256(
        hkb_content
    ).hexdigest()
    return _json_bytes(spec), hkb_content, schema, _json_bytes(manifest)


def test_build_mapping_artifacts_binds_all_public_inputs() -> None:
    output, manifest = build_mapping_artifacts(*_inputs())

    assert manifest["counts"]["dispositions"] == {"compile": 1}
    assert manifest["output"]["sha256"] == hashlib.sha256(output).hexdigest()
    assert (
        manifest["source"]["mapping_spec"]["sha256"]
        == hashlib.sha256(_inputs()[0]).hexdigest()
    )
    assert manifest["validation"]["hidden_annotations_used"] is False


def test_build_mapping_artifacts_rejects_source_hash_mismatch() -> None:
    spec, hkb, schema, manifest = _inputs()
    tampered = json.loads(manifest)
    tampered["output"]["sha256"] = "0" * 64

    with pytest.raises(SemanticMappingPublicationError, match="schema IR hash"):
        build_mapping_artifacts(spec, hkb, schema, _json_bytes(tampered))


def test_publish_mapping_artifacts_is_reproducible(tmp_path) -> None:
    names = ("spec.json", "hkb.jsonl", "schema.jsonl", "schema-manifest.json")
    paths = [tmp_path / name for name in names]
    for path, content in zip(paths, _inputs(), strict=True):
        path.write_bytes(content)
    output_root = tmp_path / "output"

    first = publish_mapping_artifacts(*paths, output_root)
    second = publish_mapping_artifacts(*paths, output_root)

    assert first == second
    assert (output_root / first["output"]["file"]).is_file()
    assert json.loads((output_root / "manifest.json").read_bytes()) == first


def test_mapping_cli_builds_public_artifacts(tmp_path, capsys) -> None:
    names = ("spec.json", "hkb.jsonl", "schema.jsonl", "schema-manifest.json")
    paths = [tmp_path / name for name in names]
    for path, content in zip(paths, _inputs(), strict=True):
        path.write_bytes(content)
    output_root = tmp_path / "output"

    result = main(
        [
            "--spec",
            str(paths[0]),
            "--hkb-ir",
            str(paths[1]),
            "--schema-ir",
            str(paths[2]),
            "--schema-manifest",
            str(paths[3]),
            "--output-root",
            str(output_root),
        ]
    )

    assert result == 0
    assert json.loads(capsys.readouterr().out)["database"] == DATABASE


@pytest.mark.parametrize("path_kind", ["parent", "absolute"])
def test_publication_rejects_unsafe_output_name_before_writing(
    tmp_path, path_kind: str
) -> None:
    database = (
        "../escaped" if path_kind == "parent" else str(tmp_path / "absolute-escaped")
    )
    inputs = _inputs_with_database(database)
    names = ("spec.json", "hkb.jsonl", "schema.jsonl", "schema-manifest.json")
    paths = [tmp_path / name for name in names]
    for path, content in zip(paths, inputs, strict=True):
        path.write_bytes(content)
    escaped = tmp_path / (
        "absolute-escaped.mapping.jsonl"
        if path_kind == "absolute"
        else "escaped.mapping.jsonl"
    )
    escaped.write_text("sentinel", encoding="utf-8")

    with pytest.raises(SemanticMappingPublicationError, match="safe file name"):
        publish_mapping_artifacts(*paths, tmp_path / "output")

    assert escaped.read_text(encoding="utf-8") == "sentinel"
