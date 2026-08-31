"""Record the field-kind classification the public bundle compiler makes.

The compiler classifies every modeled field as numeric, text, numeric_text,
other, or unknown, uses that classification to decide numeric coercion, and then
keeps it only in local state. This command recompiles the committed bundle specs
and writes the classification out as a sidecar artifact, so an analysis can ask
which kinds of fields a governed condition had available on a given database.

Recompilation is deterministic from committed public inputs, so the artifact can
be produced for the frozen series retroactively. It reads semantic_models and
writes nothing there: no deployed or custody-verified byte moves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import yaml

from omni_benchmark.semantic_bundle import compile_semantic_bundle


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


def _json(content: bytes) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("expected a public JSON object")
    return value


def _jsonl(content: bytes) -> list[dict[str, Any]]:
    records = [json.loads(line) for line in content.splitlines()]
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


def _view_dimensions(files: dict[str, str], file_name: str) -> set[str]:
    document = yaml.safe_load(files[file_name])
    if not isinstance(document, dict) or not isinstance(
        document.get("dimensions"), dict
    ):
        raise ValueError(f"compiled view {file_name} declares no dimensions")
    return set(document["dimensions"])


def _view_record(
    view: dict[str, Any], files: dict[str, str], kinds: dict[str, str]
) -> dict[str, Any]:
    exposed = _view_dimensions(files, str(view["file_name"]))
    return {
        "dimension_field_kinds": {
            name: kind for name, kind in sorted(kinds.items()) if name in exposed
        },
        "source_only_field_kinds": {
            name: kind for name, kind in sorted(kinds.items()) if name not in exposed
        },
        "table_stable_id": str(view["table_stable_id"]),
        # A dimension the compiler emitted without classifying it. Expected to
        # stay empty: source names bound to more than one column are excluded
        # from the classification, and this makes that gap visible if it ever
        # reaches a published field.
        "unclassified_dimension_fields": sorted(exposed - set(kinds)),
        "view_name": str(view["view_name"]),
    }


def _database_record(
    spec_path: Path, hkb_path: Path, schema_path: Path, mapping_path: Path
) -> dict[str, Any]:
    spec_bytes = _bytes(spec_path)
    hkb_bytes = _bytes(hkb_path)
    schema_bytes = _bytes(schema_path)
    mapping_bytes = _bytes(mapping_path)
    spec = _json(spec_bytes)
    bundle = compile_semantic_bundle(
        spec,
        _jsonl(hkb_bytes),
        _jsonl(schema_bytes),
        _jsonl(mapping_bytes),
    )
    views = {str(view["table_stable_id"]): view for view in spec["views"]}
    records = [
        _view_record(views[table_id], bundle.files, kinds)
        for table_id, kinds in sorted(bundle.field_kinds.items())
    ]
    return {
        "database": str(spec["database"]),
        "dimension_field_kind_counts": _kind_counts(records),
        "source": {
            "bundle_spec": {"sha256": hashlib.sha256(spec_bytes).hexdigest()},
            "hkb_ir": {"sha256": hashlib.sha256(hkb_bytes).hexdigest()},
            "mapping": {"sha256": hashlib.sha256(mapping_bytes).hexdigest()},
            "schema_ir": {"sha256": hashlib.sha256(schema_bytes).hexdigest()},
        },
        "views": records,
    }


def _kind_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for kind in record["dimension_field_kinds"].values():
            counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def field_kinds(workspace: Path) -> dict[str, Any]:
    """Recompile every committed bundle spec and collect its field kinds."""
    databases = [
        _database_record(*paths)
        for paths in _artifact_sets(workspace.resolve(strict=True))
    ]
    views = [view for database in databases for view in database["views"]]
    return {
        "artifact_kind": "semantic_field_kinds",
        "database_count": len(databases),
        "databases": databases,
        "dimension_field_count": sum(
            len(view["dimension_field_kinds"]) for view in views
        ),
        "dimension_field_kind_counts": _kind_counts(views),
        "reads": "committed public bundle specs, HKB IR, schema IR, and mappings",
        "schema_version": 1,
        "source_only_field_count": sum(
            len(view["source_only_field_kinds"]) for view in views
        ),
        "unclassified_dimension_field_count": sum(
            len(view["unclassified_dimension_fields"]) for view in views
        ),
        "view_count": len(views),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args(argv)

    content = (
        json.dumps(
            field_kinds(arguments.workspace),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    )
    if arguments.output is not None:
        arguments.output.write_text(content, encoding="utf-8")
    else:
        print(content.rstrip("\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
