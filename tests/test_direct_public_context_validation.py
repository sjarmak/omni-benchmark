from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_benchmark.direct_public_context import (
    DirectPublicContextError,
    load_direct_public_tools,
)
from tests.test_direct_public_context import (
    _fixture_repo,
    _git,
    _sha256,
    _write_semantic_set_manifest,
    _write_json,
    _write_jsonl,
)


def test_hkb_rejects_a_dependency_closure_that_is_not_in_the_public_ir(
    tmp_path: Path,
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    hkb_path = workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"
    records = [json.loads(line) for line in hkb_path.read_text().splitlines()]
    records[-1]["dependency_closure_stable_ids"].append("archeology_scan_large:hkb:999")
    content = _write_jsonl(hkb_path, records)
    manifest_path = workspace / "semantic_models/public_ir/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["databases"]["archeology_scan_large"]["ir_sha256"] = _sha256(content)
    _write_json(manifest_path, manifest)
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "invalid public HKB closure")

    with pytest.raises(DirectPublicContextError, match="missing record"):
        load_direct_public_tools(
            workspace,
            _git(workspace, "rev-parse", "HEAD"),
            "archeology_scan_large",
            "C2",
        )


def test_schema_rejects_a_column_that_references_a_missing_table(
    tmp_path: Path,
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    schema_path = (
        workspace
        / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl"
    )
    records = [json.loads(line) for line in schema_path.read_text().splitlines()]
    records[1]["table_stable_id"] = "archeology_scan_large:table:missing"
    content = _write_jsonl(schema_path, records)
    manifest_path = workspace / "semantic_models/public_schema_ir/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["output"]["sha256"] = _sha256(content)
    _write_json(manifest_path, manifest)
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "invalid public schema reference")

    with pytest.raises(DirectPublicContextError, match="missing table"):
        load_direct_public_tools(
            workspace,
            _git(workspace, "rev-parse", "HEAD"),
            "archeology_scan_large",
            "C1",
        )


def test_semantic_bundle_rejects_a_manifest_non_model_file(
    tmp_path: Path,
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    manifest_path = workspace / "semantic_models/public_bundle/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["file"] = "mapping-ledger.json"
    _write_json(manifest_path, manifest)
    _write_semantic_set_manifest(workspace)
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "invalid semantic bundle file")

    with pytest.raises(DirectPublicContextError, match="file list"):
        load_direct_public_tools(
            workspace,
            _git(workspace, "rev-parse", "HEAD"),
            "archeology_scan_large",
            "C3",
        )


def test_hkb_rejects_missing_direct_dependency_even_when_closure_is_unchanged(
    tmp_path: Path,
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    hkb_path = workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"
    records = [json.loads(line) for line in hkb_path.read_text().splitlines()]
    records[-1]["dependency_stable_ids"].append("archeology_scan_large:hkb:999")
    content = _write_jsonl(hkb_path, records)
    manifest_path = workspace / "semantic_models/public_ir/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["databases"]["archeology_scan_large"]["ir_sha256"] = _sha256(content)
    _write_json(manifest_path, manifest)
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "invalid direct HKB dependency")

    with pytest.raises(DirectPublicContextError, match="dependency"):
        load_direct_public_tools(
            workspace,
            _git(workspace, "rev-parse", "HEAD"),
            "archeology_scan_large",
            "C2",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("cycle", "cycle"),
        ("inexact_closure", "closure"),
        ("wrong_depth", "depth"),
    ],
)
def test_hkb_rejects_dependency_graph_inconsistency(
    tmp_path: Path, mutation: str, message: str
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    hkb_path = workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"
    records = [json.loads(line) for line in hkb_path.read_text().splitlines()]
    if mutation == "cycle":
        records[0]["dependency_stable_ids"] = ["archeology_scan_large:hkb:3"]
        records[0]["dependency_closure_stable_ids"] = ["archeology_scan_large:hkb:3"]
        records[0]["dependency_depth"] = 1
    elif mutation == "inexact_closure":
        records[-1]["dependency_closure_stable_ids"] = ["archeology_scan_large:hkb:0"]
    else:
        records[-1]["dependency_depth"] = 2
    content = _write_jsonl(hkb_path, records)
    manifest_path = workspace / "semantic_models/public_ir/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["databases"]["archeology_scan_large"]["ir_sha256"] = _sha256(content)
    _write_json(manifest_path, manifest)
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", f"invalid public HKB {mutation}")

    with pytest.raises(DirectPublicContextError, match=message):
        load_direct_public_tools(
            workspace,
            _git(workspace, "rev-parse", "HEAD"),
            "archeology_scan_large",
            "C2",
        )
