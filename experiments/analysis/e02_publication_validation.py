"""Publish and authenticate every E02 candidate in ephemeral local storage."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from omni_benchmark.omni_semantic_deployment import build_semantic_deployment_plan
from omni_benchmark.semantic_bundle_publication import (
    publish_e02_bundle_artifacts,
)


def _artifact_sets(
    workspace: Path,
) -> list[tuple[str, Path, Path, Path, Path, Path]]:
    sets = [
        (
            "archeology_scan_large",
            workspace / "config/archeology_scan_public_bundle.json",
            workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl",
            workspace
            / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl",
            workspace
            / "semantic_models/public_mapping/archeology_scan_large.mapping.jsonl",
            workspace / "semantic_models/public_mapping/manifest.json",
        )
    ]
    baseline = workspace / "semantic_models/public_baseline"
    for root in sorted(path for path in baseline.iterdir() if path.is_dir()):
        database = root.name
        sets.append(
            (
                database,
                root / "bundle.spec.json",
                workspace / "semantic_models/public_ir" / f"{database}.hkb.jsonl",
                root / "schema_ir" / f"{database}.schema.jsonl",
                root / "mapping" / f"{database}.mapping.jsonl",
                root / "mapping/manifest.json",
            )
        )
    return sets


def validate(workspace: Path) -> dict[str, object]:
    artifact_sets = _artifact_sets(workspace.resolve(strict=True))
    manifest_hashes: list[str] = []
    file_count = 0
    relationship_count = 0
    deployment_plan_count = 0
    with tempfile.TemporaryDirectory(prefix="omni-e02-publication-") as temporary:
        output_root = Path(temporary)
        for database, spec, hkb, schema, mapping, mapping_manifest in artifact_sets:
            output = output_root / database
            manifest = publish_e02_bundle_artifacts(
                spec, hkb, schema, mapping, mapping_manifest, output
            )
            plan = build_semantic_deployment_plan(output)
            manifest_hashes.append(
                hashlib.sha256((output / "manifest.json").read_bytes()).hexdigest()
            )
            file_count += len(plan.files)
            relationship_count += len(manifest["relationship_contracts"])
            deployment_plan_count += 1
    candidate_set = ("\n".join(sorted(manifest_hashes)) + "\n").encode()
    return {
        "candidate_set_sha256": hashlib.sha256(candidate_set).hexdigest(),
        "database_count": len(artifact_sets),
        "deployment_plan_count": deployment_plan_count,
        "file_count": file_count,
        "relationship_count": relationship_count,
        "schema_version": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(validate(arguments.workspace), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
