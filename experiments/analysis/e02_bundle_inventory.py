"""Aggregate the opt-in public-only E02 candidate bundles."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

import yaml

from omni_benchmark.semantic_bundle import (
    compile_e02_relationship_bundle,
    compile_semantic_bundle,
)


MAX_PUBLIC_ARTIFACT_BYTES = 64 * 1024 * 1024


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


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(_bytes(path))
    if not isinstance(value, dict):
        raise ValueError("expected a public JSON object")
    return value


def _jsonl(path: Path) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in _bytes(path).splitlines()]
    if not records or any(not isinstance(record, dict) for record in records):
        raise ValueError("expected public JSONL objects")
    return records


def _artifact_sets(workspace: Path) -> list[tuple[Path, Path, Path, Path]]:
    sets = [
        (
            workspace / "config/archeology_scan_public_bundle.json",
            workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl",
            workspace
            / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl",
            workspace
            / "semantic_models/public_mapping/archeology_scan_large.mapping.jsonl",
        )
    ]
    baseline = workspace / "semantic_models/public_baseline"
    for root in sorted(path for path in baseline.iterdir() if path.is_dir()):
        database = root.name
        sets.append(
            (
                root / "bundle.spec.json",
                workspace / "semantic_models/public_ir" / f"{database}.hkb.jsonl",
                root / "schema_ir" / f"{database}.schema.jsonl",
                root / "mapping" / f"{database}.mapping.jsonl",
            )
        )
    return sets


def inventory(workspace: Path) -> dict[str, Any]:
    bundles = []
    disposition_changes = 0
    for spec_path, hkb_path, schema_path, mapping_path in _artifact_sets(
        workspace.resolve(strict=True)
    ):
        spec = _json(spec_path)
        hkb = _jsonl(hkb_path)
        schema = _jsonl(schema_path)
        mapping = _jsonl(mapping_path)
        baseline = compile_semantic_bundle(spec, hkb, schema, mapping)
        candidate = compile_e02_relationship_bundle(spec, hkb, schema, mapping)
        disposition_changes += int(
            baseline.manifest["semantic_elements"]
            != candidate.manifest["semantic_elements"]
        )
        bundles.append(candidate)

    return {
        "bundle_file_count": sum(len(bundle.files) for bundle in bundles),
        "database_count": len(bundles),
        "metric_disposition_changes": disposition_changes,
        "relationship_count": sum(
            len(bundle.manifest["relationship_contracts"]) for bundle in bundles
        ),
        "relationship_database_count": sum(
            bool(bundle.manifest["relationship_contracts"]) for bundle in bundles
        ),
        "schema_version": 1,
        "topic_with_join_count": sum(
            bool(yaml.safe_load(content).get("joins"))
            for bundle in bundles
            for name, content in bundle.files.items()
            if name.endswith(".topic")
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(inventory(arguments.workspace), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
