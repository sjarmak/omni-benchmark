"""Pure, provenance-preserving LiveSQLBench HKB intermediate representation."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from omni_benchmark.hkb_inventory import (
    HKBInventoryError,
    HKBSourceFile,
    HKBSourceInventory,
    git_blob_oid,
    load_hkb_source_inventory,
)
from omni_benchmark.hkb_io import (
    HKBFileSafetyError,
    prepare_safe_parent,
    publish_flat_files,
    read_relative_regular_file,
)


class HKBDataError(ValueError):
    """Raised when public HKB bytes or their graph violate the frozen contract."""


HKB_TYPES = frozenset(
    {"calculation_knowledge", "domain_knowledge", "value_illustration"}
)
HKB_FIELDS = frozenset(
    {
        "id",
        "knowledge",
        "description",
        "definition",
        "type",
        "children_knowledge",
    }
)


@dataclass(frozen=True)
class HKBEntry:
    """One strictly parsed, immutable public HKB record."""

    database: str
    hkb_id: int
    knowledge: str
    description: str
    definition: str
    source_type: str
    dependency_ids: tuple[int, ...]
    source_dependency_encoding: str
    source_file: str
    source_line: int
    record_sha256: str

    @property
    def stable_id(self) -> str:
        return f"{self.database}:hkb:{self.hkb_id}"


def _require_exact_fields(record: Mapping[str, Any], line_number: int) -> None:
    missing = sorted(HKB_FIELDS - record.keys())
    unknown = sorted(record.keys() - HKB_FIELDS)
    if missing:
        raise HKBDataError(f"line {line_number}: missing fields: {', '.join(missing)}")
    if unknown:
        raise HKBDataError(f"line {line_number}: unknown fields: {', '.join(unknown)}")


def _require_text(record: Mapping[str, Any], field: str, line_number: int) -> str:
    value = record[field]
    if not isinstance(value, str) or not value:
        raise HKBDataError(f"line {line_number}: {field} must be a non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise HKBDataError(
            f"line {line_number}: {field} must contain valid Unicode scalar text"
        ) from error
    return value


def _parse_dependencies(value: Any, line_number: int) -> tuple[tuple[int, ...], str]:
    if value == -1 and not isinstance(value, bool):
        return (), "sentinel_minus_one"
    if not isinstance(value, list):
        raise HKBDataError(
            f"line {line_number}: children_knowledge must be -1 or a list"
        )
    if not value:
        return (), "empty_list"
    if any(
        not isinstance(item, int) or isinstance(item, bool) or item < 0
        for item in value
    ):
        raise HKBDataError(
            f"line {line_number}: dependency IDs must be non-negative integers"
        )
    return tuple(value), "dependency_list"


def _parse_record(
    raw: Any,
    *,
    database: str,
    source_file: str,
    line_number: int,
    record_bytes: bytes,
) -> HKBEntry:
    if not isinstance(raw, dict):
        raise HKBDataError(f"line {line_number}: record must be a JSON object")
    _require_exact_fields(raw, line_number)
    hkb_id = raw["id"]
    if not isinstance(hkb_id, int) or isinstance(hkb_id, bool) or hkb_id < 0:
        raise HKBDataError(f"line {line_number}: id must be a non-negative integer")
    source_type = _require_text(raw, "type", line_number)
    if source_type not in HKB_TYPES:
        raise HKBDataError(f"line {line_number}: unsupported type {source_type}")
    dependencies, encoding = _parse_dependencies(raw["children_knowledge"], line_number)
    return HKBEntry(
        database=database,
        hkb_id=hkb_id,
        knowledge=_require_text(raw, "knowledge", line_number),
        description=_require_text(raw, "description", line_number),
        definition=_require_text(raw, "definition", line_number),
        source_type=source_type,
        dependency_ids=dependencies,
        source_dependency_encoding=encoding,
        source_file=source_file,
        source_line=line_number,
        record_sha256=hashlib.sha256(record_bytes).hexdigest(),
    )


def _strict_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise HKBDataError(f"duplicate JSON field {key}")
        value[key] = item
    return value


def _decode_record_line(raw_line: bytes, source_file: str, line_number: int) -> str:
    try:
        line = raw_line.decode("utf-8")
    except UnicodeError as error:
        raise HKBDataError(
            f"cannot decode {source_file} line {line_number} as UTF-8: {error}"
        ) from error
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith(("\r", "\n")):
        return line[:-1]
    return line


def parse_hkb_jsonl(
    content: bytes, *, database: str, source_file: str
) -> tuple[HKBEntry, ...]:
    """Strictly parse one public HKB JSONL object without interpreting its text."""

    if not isinstance(database, str) or not database:
        raise HKBDataError("database must be a non-empty string")
    if not isinstance(source_file, str) or not source_file:
        raise HKBDataError("source_file must be a non-empty string")
    raw_lines = content.splitlines(keepends=True)
    if not raw_lines:
        raise HKBDataError(f"{source_file} contains no HKB records")
    entries: list[HKBEntry] = []
    for line_number, raw_line in enumerate(raw_lines, start=1):
        line = _decode_record_line(raw_line, source_file, line_number)
        if not line.strip():
            raise HKBDataError(f"line {line_number}: blank JSONL record")
        try:
            raw = json.loads(line, object_pairs_hook=_strict_json_object)
        except json.JSONDecodeError as error:
            raise HKBDataError(
                f"line {line_number}: not valid JSON: {error.msg}"
            ) from error
        entries.append(
            _parse_record(
                raw,
                database=database,
                source_file=source_file,
                line_number=line_number,
                record_bytes=raw_line,
            )
        )
    return tuple(entries)


def _index_entries(entries: Sequence[HKBEntry]) -> dict[int, HKBEntry]:
    if not entries:
        raise HKBDataError("cannot compile an empty HKB database")
    database = entries[0].database
    source_file = entries[0].source_file
    indexed: dict[int, HKBEntry] = {}
    for entry in entries:
        if entry.database != database:
            raise HKBDataError("one HKB compilation cannot mix databases")
        if entry.source_file != source_file:
            raise HKBDataError("one HKB compilation cannot mix source files")
        if entry.hkb_id in indexed:
            raise HKBDataError(f"duplicate HKB id {entry.hkb_id} in {database}")
        indexed[entry.hkb_id] = entry
    return indexed


def _validate_direct_dependencies(indexed: Mapping[int, HKBEntry]) -> None:
    for entry in indexed.values():
        seen: set[int] = set()
        for dependency_id in entry.dependency_ids:
            if dependency_id == entry.hkb_id:
                raise HKBDataError(f"HKB id {entry.hkb_id} has a self dependency")
            if dependency_id in seen:
                raise HKBDataError(
                    f"HKB id {entry.hkb_id} has duplicate dependency id {dependency_id}"
                )
            if dependency_id not in indexed:
                raise HKBDataError(
                    f"HKB id {entry.hkb_id} references missing HKB id {dependency_id}"
                )
            seen.add(dependency_id)


def _resolve_graph(
    indexed: Mapping[int, HKBEntry],
) -> tuple[dict[int, int], dict[int, tuple[int, ...]]]:
    depths: dict[int, int] = {}
    closures: dict[int, tuple[int, ...]] = {}
    visiting: list[int] = []

    def visit(hkb_id: int) -> tuple[int, tuple[int, ...]]:
        if hkb_id in depths:
            return depths[hkb_id], closures[hkb_id]
        if hkb_id in visiting:
            cycle = visiting[visiting.index(hkb_id) :] + [hkb_id]
            raise HKBDataError(
                "dependency cycle: " + " -> ".join(str(item) for item in cycle)
            )
        visiting.append(hkb_id)
        child_results = [visit(item) for item in indexed[hkb_id].dependency_ids]
        closure = _merge_dependency_closures(
            indexed[hkb_id].dependency_ids, child_results
        )
        depth = 0 if not child_results else 1 + max(item[0] for item in child_results)
        visiting.pop()
        depths[hkb_id] = depth
        closures[hkb_id] = closure
        return depth, closure

    for hkb_id in sorted(indexed):
        visit(hkb_id)
    return depths, closures


def _merge_dependency_closures(
    dependency_ids: tuple[int, ...],
    child_results: list[tuple[int, tuple[int, ...]]],
) -> tuple[int, ...]:
    merged: list[int] = []
    seen: set[int] = set()
    for dependency_id, (_, child_closure) in zip(
        dependency_ids, child_results, strict=True
    ):
        for item in (*child_closure, dependency_id):
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return tuple(merged)


def _compiled_entry(
    entry: HKBEntry,
    *,
    dataset: str,
    revision: str,
    source_sha256: str,
    depth: int,
    closure: tuple[int, ...],
) -> dict[str, Any]:
    prefix = f"{entry.database}:hkb:"
    return {
        "schema_version": 1,
        "stable_id": entry.stable_id,
        "database": entry.database,
        "hkb_id": entry.hkb_id,
        "knowledge": entry.knowledge,
        "description": entry.description,
        "definition": entry.definition,
        "source_type": entry.source_type,
        "dependency_ids": list(entry.dependency_ids),
        "dependency_stable_ids": [f"{prefix}{item}" for item in entry.dependency_ids],
        "dependency_closure_stable_ids": [f"{prefix}{item}" for item in closure],
        "dependency_depth": depth,
        "source_dependency_encoding": entry.source_dependency_encoding,
        "representability": {
            "status": "unassessed",
            "reason": "semantic_mapping_not_attempted",
        },
        "provenance": {
            "content": "public_hkb",
            "intervention": "mechanical_baseline_transformation",
            "transformation_class": "mechanical",
            "source": {
                "dataset": dataset,
                "revision": revision,
                "file": entry.source_file,
                "file_sha256": source_sha256,
                "line": entry.source_line,
                "record_sha256": entry.record_sha256,
            },
        },
    }


def compile_hkb_database(
    entries: Sequence[HKBEntry],
    *,
    dataset: str,
    revision: str,
    source_sha256: str,
) -> list[dict[str, Any]]:
    """Resolve one HKB dependency DAG into deterministic public IR records."""

    indexed = _index_entries(entries)
    _validate_direct_dependencies(indexed)
    depths, closures = _resolve_graph(indexed)
    return [
        _compiled_entry(
            indexed[hkb_id],
            dataset=dataset,
            revision=revision,
            source_sha256=source_sha256,
            depth=depths[hkb_id],
            closure=closures[hkb_id],
        )
        for hkb_id in sorted(indexed)
    ]


def _canonical_json(value: Any, *, pretty: bool = False) -> bytes:
    separators = None if pretty else (",", ":")
    text = json.dumps(
        value,
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=separators,
        sort_keys=True,
    )
    return (text + "\n").encode("utf-8")


def _read_verified_source(root: Path, item: HKBSourceFile) -> bytes:
    try:
        content = read_relative_regular_file(
            root, item.path, maximum_bytes=item.size + 1
        )
    except HKBFileSafetyError as error:
        raise HKBDataError(str(error)) from error
    if len(content) != item.size:
        raise HKBDataError(f"size mismatch for {item.path}")
    observed = hashlib.sha256(content).hexdigest()
    if observed != item.sha256:
        raise HKBDataError(f"SHA-256 mismatch for {item.path}")
    if git_blob_oid(content) != item.oid:
        raise HKBDataError(f"Git blob OID mismatch for {item.path}")
    return content


def _database_counts(records: Sequence[Mapping[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter(record["source_type"] for record in records)
    counts["entries"] = len(records)
    counts["no_dependency_sentinel_minus_one"] = sum(
        record["source_dependency_encoding"] == "sentinel_minus_one"
        for record in records
    )
    counts["no_dependency_empty_list"] = sum(
        record["source_dependency_encoding"] == "empty_list" for record in records
    )
    counts["entries_with_dependencies"] = sum(
        bool(record["dependency_ids"]) for record in records
    )
    counts["dependency_edges"] = sum(
        len(record["dependency_ids"]) for record in records
    )
    counts["maximum_dependency_depth"] = max(
        record["dependency_depth"] for record in records
    )
    return counts


def _compile_inventory(
    source_root: Path, inventory: HKBSourceInventory
) -> tuple[dict[str, bytes], dict[str, Any]]:
    outputs: dict[str, bytes] = {}
    databases: dict[str, Any] = {}
    aggregate: Counter[str] = Counter()
    for item in inventory.files:
        content = _read_verified_source(source_root, item)
        entries = parse_hkb_jsonl(
            content, database=item.database, source_file=item.path
        )
        records = compile_hkb_database(
            entries,
            dataset=inventory.dataset,
            revision=inventory.revision,
            source_sha256=item.sha256,
        )
        output_name = f"{item.database}.hkb.jsonl"
        output = b"".join(_canonical_json(record) for record in records)
        counts = _database_counts(records)
        aggregate.update(
            {
                key: value
                for key, value in counts.items()
                if key != "maximum_dependency_depth"
            }
        )
        aggregate["maximum_dependency_depth"] = max(
            aggregate["maximum_dependency_depth"], counts["maximum_dependency_depth"]
        )
        outputs[output_name] = output
        databases[item.database] = {
            "source_file": item.path,
            "source_oid": item.oid,
            "source_size": item.size,
            "source_sha256": item.sha256,
            "ir_file": output_name,
            "ir_sha256": hashlib.sha256(output).hexdigest(),
            "counts": dict(sorted(counts.items())),
        }
    aggregate["databases"] = len(inventory.files)
    return outputs, {
        "schema_version": 1,
        "kind": "public-hkb-intermediate-representation",
        "source": {
            "dataset": inventory.dataset,
            "revision": inventory.revision,
            "inventory_sha256": inventory.inventory_sha256,
        },
        "counts": dict(sorted(aggregate.items())),
        "databases": databases,
    }


def _publish_ir(
    output_root: Path, outputs: Mapping[str, bytes], manifest: bytes
) -> None:
    try:
        prepare_safe_parent(output_root)
    except HKBFileSafetyError as error:
        raise HKBDataError(str(error)) from error
    with tempfile.TemporaryDirectory(
        prefix=".public-hkb-ir-", dir=output_root.parent
    ) as temporary:
        staging = Path(temporary)
        for name, content in outputs.items():
            (staging / name).write_bytes(content)
        (staging / "manifest.json").write_bytes(manifest)
        names = (*sorted(outputs), "manifest.json")
        try:
            publish_flat_files(staging, output_root, names)
        except HKBFileSafetyError as error:
            raise HKBDataError(str(error)) from error


def generate_public_hkb_ir(
    source_root: Path | str,
    inventory_path: Path | str,
    output_root: Path | str,
) -> dict[str, Any]:
    """Generate and hash-bind the public-only HKB IR for every inventory file."""

    try:
        inventory = load_hkb_source_inventory(inventory_path)
    except HKBInventoryError as error:
        raise HKBDataError(str(error)) from error
    outputs, manifest = _compile_inventory(Path(source_root), inventory)
    _publish_ir(Path(output_root), outputs, _canonical_json(manifest, pretty=True))
    return manifest
