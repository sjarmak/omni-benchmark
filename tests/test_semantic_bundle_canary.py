from __future__ import annotations

import json
from pathlib import Path

import yaml

from omni_benchmark.semantic_bundle import compile_semantic_bundle


ROOT = Path(__file__).resolve().parents[1]


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_public_canary_bundle_materializes_only_approved_same_grain_semantics() -> None:
    spec = json.loads(
        (ROOT / "config/archeology_scan_public_bundle.json").read_text(encoding="utf-8")
    )
    bundle = compile_semantic_bundle(
        spec,
        _jsonl(ROOT / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"),
        _jsonl(
            ROOT / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl"
        ),
        _jsonl(
            ROOT / "semantic_models/public_mapping/archeology_scan_large.mapping.jsonl"
        ),
    )

    assert len(bundle.files) == 14
    assert len(bundle.manifest["semantic_elements"]) == 24
    kinds = [item["kind"] for item in bundle.manifest["semantic_elements"]]
    assert kinds.count("derived_dimension") == 14
    assert kinds.count("field_context") == 10
    assert all(item["loss_codes"] for item in bundle.manifest["semantic_elements"])
    assert bundle.manifest["validation"]["joins_generated"] is False
    for name, content in bundle.files.items():
        document = yaml.safe_load(content)
        assert "relationships" not in document, name
        if name.endswith(".topic"):
            assert document["joins"] == {}, name
        else:
            assert "joins" not in document, name


def test_public_canary_keeps_structured_json_parser_metadata_out_of_sql() -> None:
    spec = json.loads(
        (ROOT / "config/archeology_scan_public_bundle.json").read_text(encoding="utf-8")
    )
    bundle = compile_semantic_bundle(
        spec,
        _jsonl(ROOT / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"),
        _jsonl(
            ROOT / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl"
        ),
        _jsonl(
            ROOT / "semantic_models/public_mapping/archeology_scan_large.mapping.jsonl"
        ),
    )

    marked_fields = [
        field
        for field in spec["physical_fields"]
        if field.get("omni_parser_mode") == "do_not_parse"
    ]
    assert len(marked_fields) == 16
    assert all(
        "structured-leaf" in field["schema_stable_id"] for field in marked_fields
    )
    assert all("sql" in field for field in marked_fields)

    emitted_sql = [
        dimension["sql"]
        for name, content in bundle.files.items()
        if name.endswith(".view")
        for dimension in yaml.safe_load(content)["dimensions"].values()
        if "sql" in dimension
    ]
    assert all(not sql.startswith("-- DO NOT PARSE\n") for sql in emitted_sql)
    marked_sql = {field["sql"] for field in marked_fields}
    assert marked_sql.issubset(emitted_sql)
    derived_sql = {field["sql"] for field in spec["derived_fields"]}
    assert derived_sql.issubset(emitted_sql)
    assert all(not sql.startswith("-- DO NOT PARSE\n") for sql in derived_sql)


def test_public_canary_bundle_preserves_recursive_same_grain_dependencies() -> None:
    spec = json.loads(
        (ROOT / "config/archeology_scan_public_bundle.json").read_text(encoding="utf-8")
    )
    bundle = compile_semantic_bundle(
        spec,
        _jsonl(ROOT / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"),
        _jsonl(
            ROOT / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl"
        ),
        _jsonl(
            ROOT / "semantic_models/public_mapping/archeology_scan_large.mapping.jsonl"
        ),
    )
    pointcloud = yaml.safe_load(
        bundle.files["archeology_scan_large.public__pointcloud.view"]
    )
    fields = list(pointcloud["dimensions"])

    assert fields.index("scan_resolution_index") < fields.index("scan_quality_score")
    assert fields.index("scan_coverage_effectiveness") < fields.index(
        "scan_quality_score"
    )
    assert fields.index("scan_quality_score") < fields.index("is_premium_quality_scan")
    assert (
        "${scan_resolution_index}"
        in pointcloud["dimensions"]["scan_quality_score"]["sql"]
    )
    assert (
        "${scan_quality_score}"
        in pointcloud["dimensions"]["is_premium_quality_scan"]["sql"]
    )
