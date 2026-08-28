from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from omni_benchmark import schema_ir
from omni_benchmark.schema_ddl import SchemaDDLDataError, parse_public_ddl
from omni_benchmark.schema_ir import SchemaIRDataError, generate_public_schema_ir


DATASET = "birdsql/livesqlbench-large-v1"
REVISION = "a418e108d5cbb4cf9b783a928eff5e924ad2460d"
DATABASE = "alpha_large"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _git_blob_oid(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _source(kind: str, content: bytes) -> dict[str, object]:
    suffix = {
        "column_meanings": "column_meaning_base.json",
        "schema": "schema.txt",
    }[kind]
    return {
        "database": DATABASE,
        "kind": kind,
        "path": f"{DATABASE}/{DATABASE}_{suffix}",
        "oid": _git_blob_oid(content),
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def _write_public_sources(
    tmp_path: Path,
    *,
    id_definition: str = "id bigint DEFAULT nextval('sequence,one'::regclass)",
    meaning_id_column: str = "id",
    meaning_table: str = "first_table",
    payload_type: str = "jsonb",
    primary_key_sql: str = "PRIMARY KEY (id),\n",
    schema_override: bytes | None = None,
) -> tuple[Path, Path, Path]:
    schema = (
        schema_override
        or (
            "CREATE TABLE first_table (\n"
            f"{id_definition},\n"
            f'"Payload" {payload_type} NULL,\n'
            f"{primary_key_sql}"
            'FOREIGN KEY (id) REFERENCES "SecondTable" (name)\n);\n\n'
            "First 3 rows:\n"
            '{"gold_sql": "CREATE TABLE leaked(answer text)", "private_key": 7}\n'
            "...\n\n\n"
            'CREATE TABLE "SecondTable" (\nname bigint NULL\n);\n\n'
            "First 3 rows:\nvalue\n...\n"
        ).encode()
    )
    meanings = json.dumps(
        {
            f"{DATABASE}|{meaning_table}|{meaning_id_column}": "BIGINT. Identifier.",
            f"{DATABASE}|{meaning_table}|Payload": {
                "column_meaning": "JSONB payload.",
                "fields_meaning": {
                    "flat/key": "TEXT. Flat field.",
                    "nested": {"leaf": "REAL. Nested field."},
                    "numeric": {"0": "TEXT. Numeric object key."},
                    "sequence": ["TEXT. First item.", "TEXT. Second item."],
                },
            },
            f"{DATABASE}|SecondTable|name": "BIGINT. Name.",
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode()
    source_root = tmp_path / "source"
    database_root = source_root / DATABASE
    database_root.mkdir(parents=True)
    (database_root / f"{DATABASE}_schema.txt").write_bytes(schema)
    (database_root / f"{DATABASE}_column_meaning_base.json").write_bytes(meanings)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": DATASET,
                "revision": REVISION,
                "files": [
                    _source("schema", schema),
                    _source("column_meanings", meanings),
                ],
            }
        )
    )
    hkb_ir = tmp_path / f"{DATABASE}.hkb.jsonl"
    hkb_ir.write_text('{"record_kind":"public_hkb"}\n')
    hkb_sha256 = hashlib.sha256(hkb_ir.read_bytes()).hexdigest()
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "public-hkb-intermediate-representation",
                "source": {
                    "dataset": DATASET,
                    "revision": REVISION,
                    "inventory_sha256": "a" * 64,
                },
                "counts": {"databases": 1},
                "databases": {
                    DATABASE: {
                        "counts": {"entries": 1},
                        "ir_file": hkb_ir.name,
                        "ir_sha256": hkb_sha256,
                        "source_file": f"{DATABASE}/{DATABASE}_kb.jsonl",
                        "source_oid": "b" * 40,
                        "source_sha256": "c" * 64,
                        "source_size": 1,
                    }
                },
            }
        )
    )
    return source_root, inventory, hkb_ir


def _records(output_root: Path, database: str = DATABASE) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (output_root / f"{database}.schema.jsonl").read_text().splitlines()
    ]


def _ddl_source(ddl: str) -> bytes:
    return f"{ddl.rstrip()}\n\nFirst 3 rows:\n...\n".encode()


def test_postgres_identifier_identity_folds_only_unquoted_names() -> None:
    unquoted = parse_public_ddl(
        _ddl_source("CREATE TABLE FOO (\nBAR BIGINT\n);"), DATABASE
    )[0]
    quoted = parse_public_ddl(
        _ddl_source('CREATE TABLE "foo" (\n"bar" BIGINT\n);'), DATABASE
    )[0]

    assert unquoted.identifier == schema_ir.IdentifierDefinition(
        name="foo", quoted=False, canonical_sql="FOO"
    )
    assert unquoted.columns[0].identifier == schema_ir.IdentifierDefinition(
        name="bar", quoted=False, canonical_sql="BAR"
    )
    assert quoted.identifier == schema_ir.IdentifierDefinition(
        name="foo", quoted=True, canonical_sql='"foo"'
    )
    assert quoted.columns[0].identifier == schema_ir.IdentifierDefinition(
        name="bar", quoted=True, canonical_sql='"bar"'
    )


def test_public_ddl_repairs_unquoted_leading_digit_column_identifier() -> None:
    source = _ddl_source(
        "CREATE TABLE measurements (\n3d_point_uncertainty_mm REAL NULL\n);"
    )

    table = parse_public_ddl(source, DATABASE)[0]

    assert table.columns[0].identifier == schema_ir.IdentifierDefinition(
        name="3d_point_uncertainty_mm",
        quoted=True,
        canonical_sql='"3d_point_uncertainty_mm"',
    )
    assert "3d_point_uncertainty_mm REAL NULL" in table.ddl
    assert '"3d_point_uncertainty_mm" REAL NULL' not in table.ddl


@pytest.mark.parametrize(
    ("ddl", "message"),
    [
        (
            "CREATE TABLE public.foo (\nid BIGINT\n);",
            "CREATE TABLE name must not be schema-qualified",
        ),
        (
            "CREATE TABLE foo (\n"
            "id BIGINT,\n"
            "FOREIGN KEY (id) REFERENCES public.bar (id)\n"
            ");",
            "FOREIGN KEY target must not be schema-qualified",
        ),
    ],
)
def test_schema_qualified_table_identity_fails_closed(ddl: str, message: str) -> None:
    with pytest.raises(SchemaDDLDataError, match=message):
        parse_public_ddl(_ddl_source(ddl), DATABASE)


def test_generation_is_deterministic_row_free_and_provenance_preserving(
    tmp_path: Path,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(tmp_path)
    output_a = tmp_path / "output-a"
    output_b = tmp_path / "output-b"

    manifest_a = generate_public_schema_ir(
        source_root,
        inventory,
        output_a,
        database=DATABASE,
        companion_hkb_ir=hkb_ir,
    )
    manifest_b = generate_public_schema_ir(
        source_root,
        inventory,
        output_b,
        database=DATABASE,
        companion_hkb_ir=hkb_ir,
    )

    assert manifest_a == manifest_b
    assert (output_a / "manifest.json").read_bytes() == (
        output_b / "manifest.json"
    ).read_bytes()
    assert (output_a / f"{DATABASE}.schema.jsonl").read_bytes() == (
        output_b / f"{DATABASE}.schema.jsonl"
    ).read_bytes()
    assert manifest_a["counts"] == {
        "columns": 3,
        "foreign_keys": 1,
        "primary_keys": 1,
        "structured_columns": 1,
        "structured_leaves": 5,
        "tables": 2,
    }
    assert (
        manifest_a["source"]["companion_hkb_ir"]["sha256"]
        == hashlib.sha256(hkb_ir.read_bytes()).hexdigest()
    )
    assert manifest_a["source"]["companion_hkb_ir"]["manifest_sha256"] == (
        hashlib.sha256((hkb_ir.parent / "manifest.json").read_bytes()).hexdigest()
    )
    assert manifest_a["validation"] == {
        "all_ddl_columns_have_meanings": True,
        "all_key_references_resolve": True,
        "all_meanings_resolve_to_ddl_columns": True,
        "sample_rows_emitted": 0,
        "stable_ids_unique": True,
        "status": "passed",
    }
    records = _records(output_a)
    assert [record["record_kind"] for record in records] == [
        "table",
        "column",
        "column",
        "structured_leaf",
        "structured_leaf",
        "structured_leaf",
        "structured_leaf",
        "structured_leaf",
        "foreign_key",
        "table",
        "column",
    ]
    serialized = json.dumps(records)
    assert "gold_sql" not in serialized
    assert "private_key" not in serialized
    assert "CREATE TABLE leaked" not in serialized

    first_table = records[0]
    assert first_table["stable_id"] == f"{DATABASE}:table:first_table"
    assert first_table["identifier"] == {
        "canonical_sql": "first_table",
        "name": "first_table",
        "quoted": False,
    }
    assert "ddl" not in first_table
    assert first_table["primary_key_column_stable_ids"] == [
        f"{DATABASE}:column:first_table:id"
    ]
    assert first_table["provenance"]["content"] == ["public_schema"]
    assert first_table["provenance"]["intervention"] == (
        "mechanical_baseline_transformation"
    )
    assert first_table["provenance"]["transformation_class"] == "mechanical"

    identifier = next(
        record
        for record in records
        if record["record_kind"] == "column" and record["identifier"]["name"] == "id"
    )
    assert identifier["declared_type_sql"] == "BIGINT"
    assert identifier["nullable"] is False
    assert identifier["default_expression_sql"] == (
        "NEXTVAL(CAST('sequence,one' AS REGCLASS))"
    )
    payload = next(
        record
        for record in records
        if record["record_kind"] == "column"
        and record["identifier"]["name"] == "Payload"
    )
    assert payload["identifier"]["quoted"] is True
    assert payload["description"] == "JSONB payload."
    assert "column_stable_id" not in payload
    assert "structured" not in payload
    assert len(payload["structured_leaf_stable_ids"]) == 5
    assert payload["provenance"]["content"] == [
        "public_schema",
        "public_column_metadata",
    ]
    fields = [
        record for record in records if record["record_kind"] == "structured_leaf"
    ]
    assert [
        [segment.get("key", segment.get("index")) for segment in field["path"]]
        for field in fields
    ] == [
        ["flat/key"],
        ["nested", "leaf"],
        ["numeric", "0"],
        ["sequence", 0],
        ["sequence", 1],
    ]
    assert fields[0]["data_json_pointer"] == "/flat~1key"
    assert fields[2]["path"][-1]["kind"] == "object_key"
    assert fields[3]["path"][-1]["kind"] == "array_index"
    assert fields[2]["stable_id"].endswith("k:numeric/k:0")
    assert fields[3]["stable_id"].endswith("k:sequence/i:0")
    assert len({field["stable_id"] for field in fields}) == 5
    assert "%2F" in fields[0]["stable_id"]
    assert all(field["column_stable_id"] == payload["stable_id"] for field in fields)
    assert all(
        field["provenance"]["sources"][0]["source_key"]
        == f"{DATABASE}|first_table|Payload"
        for field in fields
    )

    relationship = next(
        record for record in records if record["record_kind"] == "foreign_key"
    )
    assert relationship["source_column_stable_ids"] == [
        f"{DATABASE}:column:first_table:id"
    ]
    assert relationship["target_column_stable_ids"] == [
        f"{DATABASE}:column:SecondTable:name"
    ]
    assert relationship["stable_id"].startswith(f"{DATABASE}:foreign-key:sha256:")
    second_table = next(
        record
        for record in records
        if record["record_kind"] == "table"
        and record["identifier"]["name"] == "SecondTable"
    )
    assert second_table["identifier"] == {
        "canonical_sql": '"SecondTable"',
        "name": "SecondTable",
        "quoted": True,
    }


def test_generation_rejects_column_metadata_for_unknown_table(tmp_path: Path) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(
        tmp_path,
        meaning_table="missing_table",
    )

    with pytest.raises(SchemaIRDataError, match="unknown DDL table missing_table"):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )


def test_generation_resolves_metadata_case_to_unquoted_ddl_identifiers(
    tmp_path: Path,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(
        tmp_path,
        meaning_id_column="ID",
        meaning_table="First_Table",
    )

    generate_public_schema_ir(
        source_root,
        inventory,
        tmp_path / "output",
        database=DATABASE,
        companion_hkb_ir=hkb_ir,
    )

    first_table = next(
        record
        for record in _records(tmp_path / "output")
        if record["stable_id"] == f"{DATABASE}:table:first_table"
    )
    identifier = next(
        record
        for record in _records(tmp_path / "output")
        if record["stable_id"] == f"{DATABASE}:column:first_table:id"
    )
    assert first_table["identifier"]["quoted"] is False
    assert identifier["description"] == "BIGINT. Identifier."
    assert identifier["provenance"]["sources"][1]["source_key"] == (
        f"{DATABASE}|First_Table|ID"
    )


def test_generation_does_not_casefold_metadata_to_quoted_identifier(
    tmp_path: Path,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(
        tmp_path,
        meaning_table="FIRST_TABLE",
        schema_override=(
            'CREATE TABLE "First_Table" (\nid bigint\n);\n\nFirst 3 rows:\n...\n'
        ).encode(),
    )

    with pytest.raises(
        SchemaIRDataError,
        match="column metadata references unknown DDL table FIRST_TABLE",
    ):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )


def test_generation_rejects_structured_meaning_on_non_json_column(
    tmp_path: Path,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(
        tmp_path,
        payload_type="text",
    )

    with pytest.raises(SchemaIRDataError, match="structured meaning.*JSON"):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )


def test_generation_rejects_unpinned_database_and_unexpected_output(
    tmp_path: Path,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(tmp_path)

    with pytest.raises(SchemaIRDataError, match="not present in schema inventory"):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database="missing_large",
            companion_hkb_ir=hkb_ir,
        )

    output = tmp_path / "output"
    output.mkdir()
    (output / "unexpected.txt").write_text("reject")
    with pytest.raises(SchemaIRDataError, match="unexpected entries"):
        generate_public_schema_ir(
            source_root,
            inventory,
            output,
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )


def test_generation_fails_closed_on_unsupported_column_constraint(
    tmp_path: Path,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(
        tmp_path,
        id_definition="id bigint CHECK (id > 0)",
    )

    with pytest.raises(SchemaIRDataError, match="unsupported column constraint"):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )


def test_inline_primary_key_is_effectively_non_nullable(tmp_path: Path) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(
        tmp_path,
        id_definition="id bigint PRIMARY KEY",
        primary_key_sql="",
    )

    generate_public_schema_ir(
        source_root,
        inventory,
        tmp_path / "output",
        database=DATABASE,
        companion_hkb_ir=hkb_ir,
    )

    identifier = next(
        record
        for record in _records(tmp_path / "output")
        if record["record_kind"] == "column" and record["identifier"]["name"] == "id"
    )
    assert identifier["nullable"] is False


def test_generation_sanitizes_malformed_ddl_before_sample_rows(tmp_path: Path) -> None:
    secret = "ROW_SECRET_SENTINEL"
    malformed = (
        f"CREATE TABLE first_table (\nid bigint\nFirst 3 rows:\n{secret}\n);\n...\n"
    ).encode()
    source_root, inventory, hkb_ir = _write_public_sources(
        tmp_path,
        schema_override=malformed,
    )

    with pytest.raises(SchemaIRDataError) as raised:
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )
    assert secret not in str(raised.value)


def test_generation_authenticates_companion_hkb_against_manifest(
    tmp_path: Path,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(tmp_path)
    hkb_ir.write_text('{"record_kind":"tampered"}\n')

    with pytest.raises(SchemaIRDataError, match="companion HKB IR SHA-256 mismatch"):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )


def test_generation_validates_hkb_manifest_before_opening_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(tmp_path)
    manifest_path = hkb_ir.parent / "manifest.json"
    manifest_path.unlink()
    reads: list[Path] = []
    original_read = schema_ir.read_regular_file

    def tracked_read(path: Path, *, maximum_bytes: int) -> bytes:
        reads.append(path)
        if path == hkb_ir:
            raise AssertionError("HKB payload opened before its manifest was trusted")
        return original_read(path, maximum_bytes=maximum_bytes)

    monkeypatch.setattr(schema_ir, "read_regular_file", tracked_read)

    with pytest.raises(SchemaIRDataError):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )

    assert reads == [manifest_path]


def test_generation_rejects_incompatible_or_duplicate_hkb_manifest(
    tmp_path: Path,
) -> None:
    source_root, inventory, hkb_ir = _write_public_sources(tmp_path)
    manifest_path = hkb_ir.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest_path.write_text(
        json.dumps(
            {
                **manifest,
                "source": {**manifest["source"], "revision": "0" * 40},
            }
        )
    )

    with pytest.raises(SchemaIRDataError, match="revision mismatch"):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "revision-output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )

    _, _, hkb_ir = _write_public_sources(tmp_path / "duplicate")
    manifest_path = hkb_ir.parent / "manifest.json"
    manifest_path.write_text(
        manifest_path.read_text().replace(
            '"schema_version": 1',
            '"schema_version": 1, "schema_version": 1',
            1,
        )
    )
    with pytest.raises(SchemaIRDataError, match="duplicate JSON field schema_version"):
        generate_public_schema_ir(
            tmp_path / "duplicate/source",
            tmp_path / "duplicate/inventory.json",
            tmp_path / "duplicate-output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )


def test_generation_normalizes_pathological_ddl_parser_failure(tmp_path: Path) -> None:
    nested_type = "ARRAY<" * 500 + "BIGINT" + ">" * 500
    schema = (
        f"CREATE TABLE first_table (\nid {nested_type}\n);\n\nFirst 3 rows:\n...\n"
    ).encode()
    source_root, inventory, hkb_ir = _write_public_sources(
        tmp_path,
        schema_override=schema,
    )

    with pytest.raises(SchemaIRDataError, match="cannot parse DDL table"):
        generate_public_schema_ir(
            source_root,
            inventory,
            tmp_path / "output",
            database=DATABASE,
            companion_hkb_ir=hkb_ir,
        )


@pytest.mark.skipif(
    not (
        REPOSITORY_ROOT / "data/raw/livesqlbench-large-v1/schema/archeology_scan_large"
    ).exists(),
    reason="requires fetched pinned public schema sources",
)
def test_real_canary_schema_ir_has_expected_public_source_counts(
    tmp_path: Path,
) -> None:
    database = "archeology_scan_large"
    manifest = generate_public_schema_ir(
        REPOSITORY_ROOT / "data/raw/livesqlbench-large-v1/schema",
        REPOSITORY_ROOT / "config/public_schema_sources.json",
        tmp_path / "output",
        database=database,
        companion_hkb_ir=(
            REPOSITORY_ROOT / "semantic_models/public_ir" / f"{database}.hkb.jsonl"
        ),
    )

    assert manifest["counts"] == {
        "columns": 959,
        "foreign_keys": 77,
        "primary_keys": 51,
        "structured_columns": 12,
        "structured_leaves": 92,
        "tables": 51,
    }
    records = _records(tmp_path / "output", database)
    assert len(records) == 1179
    project_expenses = next(
        record
        for record in records
        if record["stable_id"] == f"{database}:table:ProjectExpenses"
    )
    assert project_expenses["identifier"]["quoted"] is True
    skill_code = next(
        record
        for record in records
        if record["stable_id"] == f"{database}:column:skills:SkillCode"
    )
    assert skill_code["identifier"] == {
        "canonical_sql": '"SkillCode"',
        "name": "SkillCode",
        "quoted": True,
    }
    assert all(
        not {"sol_sql", "gold_sql", "external_knowledge", "test_cases"}.intersection(
            record
        )
        for record in records
    )
