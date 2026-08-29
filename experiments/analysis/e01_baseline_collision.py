"""Audit whether the frozen public semantic baseline already implements E01.

The audit reads only committed public HKB, schema, mapping, bundle, and manifest
artifacts. It emits aggregate counts only: no database names, HKB identifiers,
SQL text, question identifiers, result values, or hidden annotations.
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

from omni_benchmark.semantic_bundle_publication import build_bundle_artifacts


MAX_PUBLIC_ARTIFACT_BYTES = 32 * 1024 * 1024


def _bytes(path: Path) -> bytes:
    metadata = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > MAX_PUBLIC_ARTIFACT_BYTES
    ):
        raise ValueError(f"unsafe or oversized public artifact: {path}")
    content = path.read_bytes()
    if len(content) != metadata.st_size:
        raise ValueError(f"public artifact changed while reading: {path}")
    return content


def _json(content: bytes) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _jsonl(content: bytes) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in content.splitlines()]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError("expected JSONL objects")
    return records


def _artifact_sets(workspace: Path) -> list[dict[str, Path]]:
    archeology = {
        "bundle": workspace / "semantic_models/public_bundle",
        "bundle_spec": workspace / "config/archeology_scan_public_bundle.json",
        "hkb": workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl",
        "mapping": workspace
        / "semantic_models/public_mapping/archeology_scan_large.mapping.jsonl",
        "mapping_manifest": workspace / "semantic_models/public_mapping/manifest.json",
        "schema": workspace
        / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl",
    }
    fanout = []
    baseline_root = workspace / "semantic_models/public_baseline"
    for root in sorted(path for path in baseline_root.iterdir() if path.is_dir()):
        database = root.name
        fanout.append(
            {
                "bundle": root / "bundle",
                "bundle_spec": root / "bundle.spec.json",
                "hkb": workspace
                / "semantic_models/public_ir"
                / f"{database}.hkb.jsonl",
                "mapping": root / "mapping" / f"{database}.mapping.jsonl",
                "mapping_manifest": root / "mapping/manifest.json",
                "schema": root / "schema_ir" / f"{database}.schema.jsonl",
            }
        )
    return [archeology, *fanout]


def audit(workspace: Path) -> dict[str, Any]:
    """Return a value-free aggregate audit of the public baseline's E01 contract."""
    artifact_sets = _artifact_sets(workspace.resolve(strict=True))
    compile_count = 0
    compiled_with_dependencies = 0
    dependency_edge_count = 0
    maximum_depth = 0
    regenerated_file_count = 0
    all_exact = True
    all_same_grain = True

    for paths in artifact_sets:
        bundle_spec = _bytes(paths["bundle_spec"])
        hkb_bytes = _bytes(paths["hkb"])
        mapping_bytes = _bytes(paths["mapping"])
        mapping_manifest = _bytes(paths["mapping_manifest"])
        schema_bytes = _bytes(paths["schema"])
        regenerated, regenerated_manifest = build_bundle_artifacts(
            bundle_spec,
            hkb_bytes,
            schema_bytes,
            mapping_bytes,
            mapping_manifest,
        )
        committed_manifest = _json(_bytes(paths["bundle"] / "manifest.json"))
        exact = committed_manifest == regenerated_manifest
        exact = exact and all(
            _bytes(paths["bundle"] / name) == content
            for name, content in regenerated.items()
        )
        all_exact = all_exact and exact
        regenerated_file_count += len(regenerated)

        hkb_index = {record["stable_id"]: record for record in _jsonl(hkb_bytes)}
        mapping_records = _jsonl(mapping_bytes)
        mapping_index = {record["hkb_stable_id"]: record for record in mapping_records}
        for mapping in mapping_records:
            if mapping.get("disposition") != "compile":
                continue
            compile_count += 1
            audit_record = mapping["dependency_audit"]
            redundant = set(audit_record["redundant_references"])
            dependencies = [
                dependency
                for dependency in mapping["dependency_hkb_stable_ids"]
                if dependency not in redundant
            ]
            if dependencies:
                compiled_with_dependencies += 1
                dependency_edge_count += len(dependencies)
            maximum_depth = max(
                maximum_depth,
                int(hkb_index[mapping["hkb_stable_id"]]["dependency_depth"]),
            )
            all_same_grain = all_same_grain and (
                mapping["dependency_mode"] == "same_grain"
                and all(
                    mapping_index[dependency]["disposition"] == "compile"
                    and mapping_index[dependency]["target_table_stable_id"]
                    == mapping["target_table_stable_id"]
                    for dependency in dependencies
                )
            )

    already_satisfies = (
        all_exact
        and all_same_grain
        and compiled_with_dependencies > 0
        and dependency_edge_count > 0
        and maximum_depth >= 2
    )
    return {
        "all_bundles_regenerate_exactly": all_exact,
        "all_compile_dependencies_same_grain": all_same_grain,
        "baseline_already_satisfies_e01": already_satisfies,
        "compile_count": compile_count,
        "compiled_with_dependencies": compiled_with_dependencies,
        "database_count": len(artifact_sets),
        "executable_dependency_edge_count": dependency_edge_count,
        "maximum_compiled_dependency_depth": maximum_depth,
        "regenerated_file_count": regenerated_file_count,
        "schema_version": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(audit(arguments.workspace), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
