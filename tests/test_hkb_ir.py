from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark.hkb_ir import (
    HKBDataError,
    compile_hkb_database,
    generate_public_hkb_ir,
    parse_hkb_jsonl,
)


REVISION = "a418e108d5cbb4cf9b783a928eff5e924ad2460d"
DATASET = "birdsql/livesqlbench-large-v1"


def _row(
    hkb_id: int,
    *,
    name: str | None = None,
    dependencies: int | list[int] = -1,
    source_type: str = "calculation_knowledge",
) -> dict[str, object]:
    return {
        "id": hkb_id,
        "knowledge": name or f"Knowledge {hkb_id}",
        "description": f"Description {hkb_id}",
        "definition": f"Definition {hkb_id}",
        "type": source_type,
        "children_knowledge": dependencies,
    }


def _jsonl(*rows: dict[str, object]) -> bytes:
    return b"".join(
        (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        for row in rows
    )


def _git_blob_oid(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def test_parse_and_compile_preserves_dependency_provenance() -> None:
    content = _jsonl(
        _row(0, name="Base", dependencies=-1),
        _row(1, name="Intermediate", dependencies=[0]),
        _row(2, name="Composite", dependencies=[1, 0]),
        _row(3, name="Standalone", dependencies=[]),
    )

    entries = parse_hkb_jsonl(
        content,
        database="example_large",
        source_file="example_large/example_large_kb.jsonl",
    )
    compiled = compile_hkb_database(
        entries,
        dataset=DATASET,
        revision=REVISION,
        source_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert [entry["stable_id"] for entry in compiled] == [
        "example_large:hkb:0",
        "example_large:hkb:1",
        "example_large:hkb:2",
        "example_large:hkb:3",
    ]
    composite = compiled[2]
    assert composite["dependency_ids"] == [1, 0]
    assert composite["dependency_stable_ids"] == [
        "example_large:hkb:1",
        "example_large:hkb:0",
    ]
    assert composite["dependency_closure_stable_ids"] == [
        "example_large:hkb:0",
        "example_large:hkb:1",
    ]
    assert composite["dependency_depth"] == 2
    assert composite["representability"] == {
        "status": "unassessed",
        "reason": "semantic_mapping_not_attempted",
    }
    assert composite["provenance"]["content"] == "public_hkb"
    assert (
        composite["provenance"]["intervention"] == "mechanical_baseline_transformation"
    )
    assert composite["provenance"]["transformation_class"] == "mechanical"
    assert composite["provenance"]["source"] == {
        "dataset": DATASET,
        "revision": REVISION,
        "file": "example_large/example_large_kb.jsonl",
        "file_sha256": hashlib.sha256(content).hexdigest(),
        "line": 3,
        "record_sha256": entries[2].record_sha256,
    }


@pytest.mark.parametrize("empty_dependencies", [-1, []])
def test_no_dependency_encodings_normalize_to_empty_tuple(
    empty_dependencies: int | list[int],
) -> None:
    entries = parse_hkb_jsonl(
        _jsonl(_row(0, dependencies=empty_dependencies)),
        database="example_large",
        source_file="example_large/example_large_kb.jsonl",
    )

    assert entries[0].dependency_ids == ()


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ((_row(0), _row(0)), "duplicate HKB id 0"),
        ((_row(0, dependencies=[9]),), "references missing HKB id 9"),
        ((_row(0, dependencies=[0]),), "self dependency"),
        (
            (_row(0, dependencies=[1]), _row(1, dependencies=[0])),
            "dependency cycle",
        ),
        ((_row(0, dependencies=[1, 1]), _row(1)), "duplicate dependency id 1"),
    ],
)
def test_graph_validation_rejects_invalid_dependencies(
    rows: tuple[dict[str, object], ...], message: str
) -> None:
    entries = parse_hkb_jsonl(
        _jsonl(*rows),
        database="example_large",
        source_file="example_large/example_large_kb.jsonl",
    )

    with pytest.raises(HKBDataError, match=message):
        compile_hkb_database(
            entries,
            dataset=DATASET,
            revision=REVISION,
            source_sha256="a" * 64,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda row: {**row, "sol_sql": []}, "unknown fields: sol_sql"),
        (
            lambda row: {
                key: value for key, value in row.items() if key != "definition"
            },
            "missing fields: definition",
        ),
        (lambda row: {**row, "id": True}, "id must be a non-negative integer"),
        (lambda row: {**row, "knowledge": ""}, "knowledge must be a non-empty string"),
        (
            lambda row: {**row, "children_knowledge": None},
            "children_knowledge must be -1 or a list",
        ),
        (
            lambda row: {**row, "children_knowledge": [-1]},
            "dependency IDs must be non-negative integers",
        ),
        (lambda row: {**row, "type": "metric"}, "unsupported type metric"),
    ],
)
def test_parser_rejects_schema_drift_and_private_fields(
    mutate: object, message: str
) -> None:
    row = mutate(_row(0))  # type: ignore[operator]

    with pytest.raises(HKBDataError, match=message):
        parse_hkb_jsonl(
            _jsonl(row),
            database="example_large",
            source_file="example_large/example_large_kb.jsonl",
        )


def test_parser_rejects_blank_and_malformed_jsonl() -> None:
    with pytest.raises(HKBDataError, match="blank JSONL record"):
        parse_hkb_jsonl(
            _jsonl(_row(0)) + b"\n",
            database="example_large",
            source_file="example_large/example_large_kb.jsonl",
        )
    with pytest.raises(HKBDataError, match="not valid JSON"):
        parse_hkb_jsonl(
            b"{bad json}\n",
            database="example_large",
            source_file="example_large/example_large_kb.jsonl",
        )
    duplicate_id = _jsonl(_row(0)).replace(b'"id":0', b'"id":0,"id":1')
    with pytest.raises(HKBDataError, match="duplicate JSON field id"):
        parse_hkb_jsonl(
            duplicate_id,
            database="example_large",
            source_file="example_large/example_large_kb.jsonl",
        )
    surrogate = (
        json.dumps({**_row(0), "definition": "\ud800"}, ensure_ascii=True) + "\n"
    ).encode()
    with pytest.raises(HKBDataError, match="definition must contain valid Unicode"):
        parse_hkb_jsonl(
            surrogate,
            database="example_large",
            source_file="example_large/example_large_kb.jsonl",
        )


def test_parser_preserves_public_text_and_handles_noncontiguous_forward_ids() -> None:
    rows = (
        _row(7, name="Shared name", dependencies=[11]),
        {
            **_row(11, name="Shared name", dependencies=-1),
            "description": "Café δ",
            "definition": "  first line\nsecond line  ",
        },
    )
    content = _jsonl(*rows).replace(b"\n", b"\r\n").removesuffix(b"\r\n")

    entries = parse_hkb_jsonl(
        content,
        database="example_large",
        source_file="example_large/example_large_kb.jsonl",
    )
    compiled = compile_hkb_database(
        entries,
        dataset=DATASET,
        revision=REVISION,
        source_sha256=hashlib.sha256(content).hexdigest(),
    )

    assert [record["hkb_id"] for record in compiled] == [7, 11]
    assert [record["knowledge"] for record in compiled] == [
        "Shared name",
        "Shared name",
    ]
    assert compiled[1]["description"] == "Café δ"
    assert compiled[1]["definition"] == "  first line\nsecond line  "
    assert compiled[0]["dependency_closure_stable_ids"] == ["example_large:hkb:11"]


def _write_source(root: Path, database: str, rows: bytes) -> tuple[str, int]:
    relative = f"{database}/{database}_kb.jsonl"
    path = root / relative
    path.parent.mkdir(parents=True)
    path.write_bytes(rows)
    return hashlib.sha256(rows).hexdigest(), len(rows)


def _write_inventory(path: Path, files: list[dict[str, object]]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": DATASET,
                "revision": REVISION,
                "files": files,
            }
        )
    )


def test_generation_is_deterministic_and_hash_binds_every_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    alpha = _jsonl(_row(1, dependencies=[0]), _row(0))
    beta = _jsonl(
        _row(0, source_type="domain_knowledge", dependencies=[]),
        _row(1, source_type="value_illustration", dependencies=[0]),
    )
    alpha_hash, alpha_size = _write_source(source, "alpha_large", alpha)
    beta_hash, beta_size = _write_source(source, "beta_large", beta)
    inventory = tmp_path / "inventory.json"
    _write_inventory(
        inventory,
        [
            {
                "database": "beta_large",
                "path": "beta_large/beta_large_kb.jsonl",
                "oid": _git_blob_oid(beta),
                "size": beta_size,
                "sha256": beta_hash,
            },
            {
                "database": "alpha_large",
                "path": "alpha_large/alpha_large_kb.jsonl",
                "oid": _git_blob_oid(alpha),
                "size": alpha_size,
                "sha256": alpha_hash,
            },
        ],
    )
    output_a = tmp_path / "out-a"
    output_b = tmp_path / "out-b"

    manifest_a = generate_public_hkb_ir(source, inventory, output_a)
    manifest_b = generate_public_hkb_ir(source, inventory, output_b)

    assert manifest_a == manifest_b
    assert (output_a / "manifest.json").read_bytes() == (
        output_b / "manifest.json"
    ).read_bytes()
    assert sorted(path.name for path in output_a.glob("*.hkb.jsonl")) == [
        "alpha_large.hkb.jsonl",
        "beta_large.hkb.jsonl",
    ]
    for database, database_manifest in manifest_a["databases"].items():
        output = output_a / database_manifest["ir_file"]
        assert (
            hashlib.sha256(output.read_bytes()).hexdigest()
            == database_manifest["ir_sha256"]
        )
        records = [json.loads(line) for line in output.read_text().splitlines()]
        assert [record["hkb_id"] for record in records] == sorted(
            record["hkb_id"] for record in records
        )
        assert all(record["database"] == database for record in records)
    assert manifest_a["counts"] == {
        "databases": 2,
        "entries": 4,
        "calculation_knowledge": 2,
        "domain_knowledge": 1,
        "value_illustration": 1,
        "no_dependency_sentinel_minus_one": 1,
        "no_dependency_empty_list": 1,
        "entries_with_dependencies": 2,
        "dependency_edges": 2,
        "maximum_dependency_depth": 1,
    }


def test_generation_rejects_hash_mismatch_and_unexpected_source_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    content = _jsonl(_row(0))
    _, size = _write_source(source, "alpha_large", content)
    inventory = tmp_path / "inventory.json"
    _write_inventory(
        inventory,
        [
            {
                "database": "alpha_large",
                "path": "alpha_large/alpha_large_kb.jsonl",
                "oid": _git_blob_oid(content),
                "size": size,
                "sha256": "0" * 64,
            }
        ],
    )

    with pytest.raises(HKBDataError, match="SHA-256 mismatch"):
        generate_public_hkb_ir(source, inventory, tmp_path / "output")

    _write_inventory(
        inventory,
        [
            {
                "database": "alpha_large",
                "path": "../escape.jsonl",
                "oid": "a" * 40,
                "size": size,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    )
    with pytest.raises(HKBDataError, match="canonical HKB path"):
        generate_public_hkb_ir(source, inventory, tmp_path / "output")


def test_compilation_rejects_mixed_source_files() -> None:
    first = parse_hkb_jsonl(
        _jsonl(_row(0)),
        database="example_large",
        source_file="example_large/first_kb.jsonl",
    )[0]
    second = parse_hkb_jsonl(
        _jsonl(_row(1)),
        database="example_large",
        source_file="example_large/second_kb.jsonl",
    )[0]

    with pytest.raises(HKBDataError, match="cannot mix source files"):
        compile_hkb_database(
            (first, second),
            dataset=DATASET,
            revision=REVISION,
            source_sha256="a" * 64,
        )


def test_generation_rejects_symlinked_source_file(tmp_path: Path) -> None:
    content = _jsonl(_row(0))
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(content)
    source = tmp_path / "source"
    source_file = source / "alpha_large" / "alpha_large_kb.jsonl"
    source_file.parent.mkdir(parents=True)
    source_file.symlink_to(outside)
    inventory = tmp_path / "inventory.json"
    _write_inventory(
        inventory,
        [
            {
                "database": "alpha_large",
                "path": "alpha_large/alpha_large_kb.jsonl",
                "oid": _git_blob_oid(content),
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        ],
    )

    with pytest.raises(HKBDataError, match="must be a regular non-symlink file"):
        generate_public_hkb_ir(source, inventory, tmp_path / "output")


def test_generation_rejects_unsafe_or_contaminated_output_root(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    content = _jsonl(_row(0))
    source_hash, source_size = _write_source(source, "alpha_large", content)
    inventory = tmp_path / "inventory.json"
    _write_inventory(
        inventory,
        [
            {
                "database": "alpha_large",
                "path": "alpha_large/alpha_large_kb.jsonl",
                "oid": _git_blob_oid(content),
                "size": source_size,
                "sha256": source_hash,
            }
        ],
    )
    contaminated = tmp_path / "contaminated"
    contaminated.mkdir()
    (contaminated / "test_gold.jsonl").write_text("must stay out")
    with pytest.raises(HKBDataError, match="unexpected entries: test_gold.jsonl"):
        generate_public_hkb_ir(source, inventory, contaminated)

    target = tmp_path / "target"
    target.mkdir()
    symlink = tmp_path / "output-link"
    symlink.symlink_to(target, target_is_directory=True)
    with pytest.raises(
        HKBDataError, match="output root must be a non-symlink directory"
    ):
        generate_public_hkb_ir(source, inventory, symlink)

    regular_file = tmp_path / "output-file"
    regular_file.write_text("not a directory")
    with pytest.raises(
        HKBDataError, match="output root must be a non-symlink directory"
    ):
        generate_public_hkb_ir(source, inventory, regular_file)
