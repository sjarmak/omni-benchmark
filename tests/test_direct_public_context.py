from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from omni_benchmark.direct_public_context import (
    MAX_HKB_MATCHES,
    MAX_HKB_PAYLOAD_BYTES,
    MAX_SEMANTIC_MATCHES,
    MAX_SEMANTIC_PAYLOAD_BYTES,
    DirectPublicContextError,
    _rank_public_records,
    load_direct_public_tools,
)
from omni_benchmark.direct_public_search import (
    MAX_SCHEMA_MATCHES,
    MAX_SCHEMA_PAYLOAD_BYTES,
)


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_json(path: Path, value: object) -> bytes:
    content = json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> bytes:
    content = b"".join(_canonical(record) for record in records)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _git(workspace: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        capture_output=True,
        check=True,
        text=True,
    )
    return completed.stdout.strip()


def _mutate_captured_record(
    callback: Callable[[str], object],
    *,
    identifying_key: str,
    identifying_value: str,
    field: str,
    replacement: str,
) -> bool:
    """Model an attacker mutating dictionaries reachable from a callback closure."""
    closure_values = tuple(
        cell.cell_contents for cell in getattr(callback, "__closure__", None) or ()
    )
    for captured in (*closure_values, *getattr(callback, "args", ())):
        candidates = captured if isinstance(captured, tuple) else (captured,)
        for item in candidates:
            if (
                isinstance(item, dict)
                and item.get(identifying_key) == identifying_value
            ):
                item[field] = replacement
                return True
    return False


def _condition(condition: str) -> dict[str, object]:
    hkb = "semantic_models/public_ir/manifest.json" if condition == "C2" else None
    bundle = (
        "semantic_models/public_bundle/manifest.json" if condition == "C3" else None
    )
    knowledge = {
        "C1": "public_schema",
        "C2": "public_schema_and_searchable_public_hkb",
        "C3": "public_schema_and_searchable_omni_semantic_bundle",
    }[condition]
    return {
        "condition": condition,
        "execution": "direct_sql_harness",
        "hkb_access": "searchable" if condition == "C2" else "none",
        "hkb_manifest": hkb,
        "knowledge": knowledge,
        "question_specific_hidden_annotations": False,
        "runtime_oracle_context": False,
        "schema_access": "inspect",
        "schema_manifest": "semantic_models/public_schema_ir/manifest.json",
        "semantic_enforcement": "none",
        "semantic_model_access": "searchable" if condition == "C3" else "none",
        "semantic_model_manifest": bundle,
    }


def _fixture_repo(tmp_path: Path, *, secret: str | None = None) -> tuple[Path, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)

    schema_records: list[dict[str, object]] = [
        {
            "database": "archeology_scan_large",
            "identifier": {
                "canonical_sql": "scan",
                "name": "scan",
                "quoted": False,
            },
            "primary_key_column_stable_ids": [
                "archeology_scan_large:column:scan:scan_id"
            ],
            "provenance": {
                "content": ["public_schema"],
                "intervention": "mechanical_baseline_transformation",
            },
            "record_kind": "table",
            "schema_version": 1,
            "source_ordinal": 0,
            "stable_id": "archeology_scan_large:table:scan",
            "unique_keys": [],
        },
        {
            "database": "archeology_scan_large",
            "declared_type_sql": "BIGINT",
            "default_expression_sql": None,
            "description": secret or "Public scan identifier.",
            "identifier": {
                "canonical_sql": "scan_id",
                "name": "scan_id",
                "quoted": False,
            },
            "nullable": False,
            "provenance": {
                "content": ["public_schema", "public_column_metadata"],
                "intervention": "mechanical_baseline_transformation",
            },
            "record_kind": "column",
            "schema_version": 1,
            "source_ordinal": 0,
            "stable_id": "archeology_scan_large:column:scan:scan_id",
            "structured_leaf_stable_ids": [],
            "table_stable_id": "archeology_scan_large:table:scan",
        },
        {
            "database": "archeology_scan_large",
            "declared_type_sql": "JSONB",
            "default_expression_sql": None,
            "description": "Public scan measurements.",
            "identifier": {
                "canonical_sql": "metrics",
                "name": "metrics",
                "quoted": False,
            },
            "nullable": True,
            "provenance": {
                "content": ["public_schema", "public_column_metadata"],
                "intervention": "mechanical_baseline_transformation",
            },
            "record_kind": "column",
            "schema_version": 1,
            "source_ordinal": 1,
            "stable_id": "archeology_scan_large:column:scan:metrics",
            "structured_leaf_stable_ids": [
                "archeology_scan_large:structured-leaf:scan:metrics:k:Resolution"
            ],
            "table_stable_id": "archeology_scan_large:table:scan",
        },
        {
            "column_stable_id": "archeology_scan_large:column:scan:metrics",
            "data_json_pointer": "/Resolution",
            "database": "archeology_scan_large",
            "depth_first_ordinal": 0,
            "description": "Resolution in millimeters.",
            "path": [{"key": "Resolution", "kind": "object_key", "ordinal": 0}],
            "provenance": {
                "content": ["public_column_metadata"],
                "intervention": "mechanical_baseline_transformation",
            },
            "record_kind": "structured_leaf",
            "schema_version": 1,
            "stable_id": (
                "archeology_scan_large:structured-leaf:scan:metrics:k:Resolution"
            ),
        },
        {
            "database": "archeology_scan_large",
            "identifier": {
                "canonical_sql": "field_team",
                "name": "field_team",
                "quoted": False,
            },
            "primary_key_column_stable_ids": [],
            "provenance": {
                "content": ["public_schema"],
                "intervention": "mechanical_baseline_transformation",
            },
            "record_kind": "table",
            "schema_version": 1,
            "source_ordinal": 1,
            "stable_id": "archeology_scan_large:table:field_team",
            "unique_keys": [],
        },
        {
            "database": "archeology_scan_large",
            "declared_type_sql": "TEXT",
            "default_expression_sql": None,
            "description": "Public field-team name.",
            "identifier": {
                "canonical_sql": "team_name",
                "name": "team_name",
                "quoted": False,
            },
            "nullable": False,
            "provenance": {
                "content": ["public_schema", "public_column_metadata"],
                "intervention": "mechanical_baseline_transformation",
            },
            "record_kind": "column",
            "schema_version": 1,
            "source_ordinal": 0,
            "stable_id": "archeology_scan_large:column:field_team:team_name",
            "structured_leaf_stable_ids": [],
            "table_stable_id": "archeology_scan_large:table:field_team",
        },
    ]
    schema_path = (
        workspace
        / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl"
    )
    schema_content = _write_jsonl(schema_path, schema_records)
    _write_json(
        workspace / "semantic_models/public_schema_ir/manifest.json",
        {
            "counts": {
                "columns": 3,
                "foreign_keys": 0,
                "primary_keys": 1,
                "structured_columns": 1,
                "structured_leaves": 1,
                "tables": 2,
            },
            "database": "archeology_scan_large",
            "intentional_exclusions": [],
            "kind": "public-schema-intermediate-representation",
            "output": {
                "file": schema_path.name,
                "sha256": _sha256(schema_content),
            },
            "schema_version": 1,
            "source": {"dataset": "public-synthetic-archeology"},
            "validation": {"status": "passed"},
        },
    )

    hkb_records: list[dict[str, object]] = []
    for hkb_id, knowledge, dependencies, closure, depth in (
        (0, "Scan Resolution Index", [], [], 0),
        (1, "Scan Coverage Effectiveness", [], [], 0),
        (
            3,
            "Premium Scan Quality",
            ["archeology_scan_large:hkb:0", "archeology_scan_large:hkb:1"],
            ["archeology_scan_large:hkb:0", "archeology_scan_large:hkb:1"],
            1,
        ),
    ):
        hkb_records.append(
            {
                "database": "archeology_scan_large",
                "definition": f"Public definition for {knowledge}.",
                "dependency_closure_stable_ids": closure,
                "dependency_depth": depth,
                "dependency_ids": [
                    int(item.rsplit(":", 1)[1]) for item in dependencies
                ],
                "dependency_stable_ids": dependencies,
                "description": f"Business meaning for {knowledge}.",
                "hkb_id": hkb_id,
                "knowledge": knowledge,
                "provenance": {
                    "content": "public_hkb",
                    "intervention": "mechanical_baseline_transformation",
                },
                "representability": {"status": "unassessed"},
                "schema_version": 1,
                "source_dependency_encoding": (
                    "dependency_list" if dependencies else "sentinel_minus_one"
                ),
                "source_type": "calculation_knowledge",
                "stable_id": f"archeology_scan_large:hkb:{hkb_id}",
            }
        )
    hkb_path = workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"
    hkb_content = _write_jsonl(hkb_path, hkb_records)
    _write_json(
        workspace / "semantic_models/public_ir/manifest.json",
        {
            "counts": {"databases": 1, "entries": 3},
            "databases": {
                "archeology_scan_large": {
                    "counts": {"entries": 3},
                    "ir_file": hkb_path.name,
                    "ir_sha256": _sha256(hkb_content),
                    "source_file": "public-synthetic-archeology-kb.jsonl",
                    "source_oid": "0" * 40,
                    "source_sha256": "1" * 64,
                    "source_size": 1,
                }
            },
            "kind": "public-hkb-intermediate-representation",
            "schema_version": 1,
            "source": {"dataset": "public-synthetic-archeology"},
        },
    )

    view_content = (
        "label: Public Scans\n"
        "description: Public modeled scan semantics.\n"
        "catalog: archeology_scan_large\n"
        "schema: public\n"
        "table_name: scan\n"
        "dimensions:\n"
        "  premium_scan_quality:\n"
        "    label: Premium Scan Quality\n"
        "    description: Public governed premium-quality definition.\n"
        "    sql: ${scan_resolution_index} > 7\n"
        "    ai_context: Use this modeled field; do not reconstruct it.\n"
    ).encode()
    topic_content = (
        "base_view: archeology_scan_large_public__scan\n"
        "label: Public Scans\n"
        "description: Public modeled scan topic.\n"
        "fields:\n"
        "- archeology_scan_large_public__scan.*\n"
        "ai_context: Use the modeled premium_scan_quality field.\n"
    ).encode()
    bundle_dir = workspace / "semantic_models/public_bundle"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "archeology_scan_large.public__scan.view").write_bytes(view_content)
    (bundle_dir / "scan_semantics.topic").write_bytes(topic_content)
    _write_json(
        bundle_dir / "manifest.json",
        {
            "database": "archeology_scan_large",
            "files": [
                {
                    "file": "archeology_scan_large.public__scan.view",
                    "sha256": _sha256(view_content),
                    "size_bytes": len(view_content),
                },
                {
                    "file": "scan_semantics.topic",
                    "sha256": _sha256(topic_content),
                    "size_bytes": len(topic_content),
                },
            ],
            "kind": "public-omni-semantic-bundle",
            "schema_version": 1,
            "semantic_elements": [
                {
                    "loss_codes": ["LOSS-LEDGER-DECOY"],
                    "mapping": "MAPPING-LEDGER-DECOY",
                    "raw_hkb": "RAW-HKB-DECOY",
                }
            ],
            "source": {"mapping": {"sha256": "2" * 64}},
            "validation": {"public_inputs_only": True, "status": "passed"},
        },
    )

    for condition in ("C1", "C2", "C3"):
        _write_json(
            workspace / f"config/conditions/{condition.lower()}-direct-sql-v1.json",
            _condition(condition),
        )
    _write_json(
        workspace / "config/instructions/direct-sql-v1.json",
        {
            "adapter_instruction": (
                "Use only condition-specific public reference tools and read-only "
                "Query SQL; refuse when public information is insufficient."
            ),
            "question_specific_hidden_annotations": False,
            "runtime_oracle_context": False,
        },
    )
    prompt = workspace / "config/prompts/direct-sql-v1.txt"
    prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text("{question}\n", encoding="utf-8")

    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.name", "Public Fixture")
    _git(workspace, "config", "user.email", "public-fixture@example.invalid")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "public synthetic fixture")
    return workspace, _git(workspace, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("condition", "has_hkb", "has_semantic"),
    [("C1", False, False), ("C2", True, False), ("C3", False, True)],
)
def test_condition_scoped_tools_preserve_exact_information_isolation(
    tmp_path: Path, condition: str, has_hkb: bool, has_semantic: bool
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    tools = load_direct_public_tools(
        workspace, commit, "archeology_scan_large", condition
    )

    assert tools.inspect_schema is not None
    assert (tools.search_hkb is not None) is has_hkb
    assert (tools.search_semantic_model is not None) is has_semantic
    assert tools.identity.condition == condition
    components = dict(tools.identity.component_sha256)
    assert components["schema"]
    assert ("hkb" in components) is has_hkb
    assert ("semantic_manifest" in components) is has_semantic
    assert len(tools.identity.context_sha256) == 64
    assert tools.render_question("Public question") == "Public question"


def test_schema_search_is_selective_deterministic_compact_and_bounded(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    tools = load_direct_public_tools(workspace, commit, "archeology_scan_large", "C1")

    first = tools.inspect_schema("resolution measurements")
    second = tools.inspect_schema("resolution measurements")
    payload = first.payload

    assert first == second
    assert first.context_sha256 == tools.identity.context_sha256
    assert first.capability == "inspect_schema"
    assert payload["kind"] == "public-schema-search"
    assert payload["database"] == "archeology_scan_large"
    assert payload["query"] == "resolution measurements"
    assert payload["truncated"] is False
    assert payload["tables"] == [
        {
            "canonical_sql": "scan",
            "columns": [
                {
                    "canonical_sql": "scan_id",
                    "declared_type_sql": "BIGINT",
                    "description": "Public scan identifier.",
                    "name": "scan_id",
                    "nullable": False,
                    "quoted": False,
                    "stable_id": "archeology_scan_large:column:scan:scan_id",
                    "structured_leaves": [],
                },
                {
                    "canonical_sql": "metrics",
                    "declared_type_sql": "JSONB",
                    "description": "Public scan measurements.",
                    "name": "metrics",
                    "nullable": True,
                    "quoted": False,
                    "stable_id": "archeology_scan_large:column:scan:metrics",
                    "structured_leaves": [
                        {
                            "data_json_pointer": "/Resolution",
                            "description": "Resolution in millimeters.",
                            "stable_id": (
                                "archeology_scan_large:structured-leaf:scan:"
                                "metrics:k:Resolution"
                            ),
                        }
                    ],
                },
            ],
            "foreign_keys": [],
            "name": "scan",
            "primary_key_column_stable_ids": [
                "archeology_scan_large:column:scan:scan_id"
            ],
            "quoted": False,
            "stable_id": "archeology_scan_large:table:scan",
            "unique_keys": [],
        }
    ]
    assert payload["retrieved_schema_stable_ids"] == [
        "archeology_scan_large:column:scan:metrics",
        "archeology_scan_large:column:scan:scan_id",
        "archeology_scan_large:structured-leaf:scan:metrics:k:Resolution",
        "archeology_scan_large:table:scan",
    ]
    assert len(payload["tables"]) <= MAX_SCHEMA_MATCHES
    assert len(_canonical(payload)) <= MAX_SCHEMA_PAYLOAD_BYTES


def test_schema_search_returns_deterministic_empty_result(tmp_path: Path) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    tools = load_direct_public_tools(workspace, commit, "archeology_scan_large", "C1")

    result = tools.inspect_schema("unmatchedlexeme")

    assert result.payload["tables"] == []
    assert result.payload["retrieved_schema_stable_ids"] == []
    assert result.payload["truncated"] is False


def test_hkb_search_returns_direct_matches_with_dependency_closure_provenance(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    tools = load_direct_public_tools(workspace, commit, "archeology_scan_large", "C2")
    assert tools.search_hkb is not None

    first = tools.search_hkb("premium quality")
    second = tools.search_hkb("premium quality")
    payload = first.payload

    assert first == second
    assert first.context_sha256 == tools.identity.context_sha256
    assert first.capability == "search_hkb"
    assert payload["kind"] == "public-hkb-search"
    assert payload["truncated"] is False
    assert payload["matches"][0]["stable_id"] == "archeology_scan_large:hkb:3"
    assert payload["matches"][0]["retrieval_role"] == "direct_match"
    assert payload["matches"][0]["dependency_stable_ids"] == [
        "archeology_scan_large:hkb:0",
        "archeology_scan_large:hkb:1",
    ]
    assert [item["stable_id"] for item in payload["dependencies"]] == [
        "archeology_scan_large:hkb:0",
        "archeology_scan_large:hkb:1",
    ]
    assert all(
        item["required_by"] == ["archeology_scan_large:hkb:3"]
        and item["retrieval_role"] == "dependency_closure"
        for item in payload["dependencies"]
    )
    assert payload["retrieved_hkb_stable_ids"] == [
        "archeology_scan_large:hkb:0",
        "archeology_scan_large:hkb:1",
        "archeology_scan_large:hkb:3",
    ]
    assert len(payload["matches"]) <= MAX_HKB_MATCHES
    assert len(_canonical(payload)) <= MAX_HKB_PAYLOAD_BYTES
    assert first.semantic_objects == ()


def test_public_search_uses_fts5_bm25_with_canonical_order_tiebreaker() -> None:
    records = (
        {"text": "premium quality filler words"},
        {"text": "premium premium premium premium quality quality quality quality"},
        {"text": "same"},
        {"text": "same"},
    )

    ranked = _rank_public_records(records, ("premium", "quality"), ("text",))
    tied = _rank_public_records(records[2:], ("same",), ("text",))

    assert ranked[:2] == (records[1], records[0])
    assert tied == records[2:]


def test_c3_search_reads_only_actual_bundle_files_and_emits_semantic_objects(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    tools = load_direct_public_tools(workspace, commit, "archeology_scan_large", "C3")
    assert tools.search_semantic_model is not None

    result = tools.search_semantic_model("premium quality")
    ai_context_result = tools.search_semantic_model("reconstruct")
    payload = result.payload
    encoded = json.dumps(payload, sort_keys=True)

    assert result.context_sha256 == tools.identity.context_sha256
    assert result.capability == "search_semantic_model"
    assert payload["kind"] == "public-omni-semantic-search"
    assert payload["matches"][0] == {
        "ai_context": "Use this modeled field; do not reconstruct it.",
        "description": "Public governed premium-quality definition.",
        "label": "Premium Scan Quality",
        "object_id": ("archeology_scan_large_public__scan.premium_scan_quality"),
        "object_kind": "dimension",
        "source_file": "archeology_scan_large.public__scan.view",
        "sql": "${scan_resolution_index} > 7",
    }
    assert result.semantic_objects[0] == (
        "archeology_scan_large_public__scan.premium_scan_quality"
    )
    assert result.semantic_objects[0] in ai_context_result.semantic_objects
    assert "RAW-HKB-DECOY" not in encoded
    assert "MAPPING-LEDGER-DECOY" not in encoded
    assert "LOSS-LEDGER-DECOY" not in encoded
    assert "hkb_stable_id" not in encoded
    assert "loss_codes" not in encoded
    assert len(payload["matches"]) <= MAX_SEMANTIC_MATCHES
    assert len(_canonical(payload)) <= MAX_SEMANTIC_PAYLOAD_BYTES


def test_context_rejects_unsafe_queries_and_committed_public_content(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    tools = load_direct_public_tools(
        workspace,
        commit,
        "archeology_scan_large",
        "C2",
        environment={"PUBLIC_API_TOKEN": "live-secret-value"},
    )
    assert tools.search_hkb is not None

    with pytest.raises(DirectPublicContextError, match="sensitive"):
        tools.search_hkb("find live-secret-value")

    unsafe_workspace, unsafe_commit = _fixture_repo(
        tmp_path / "unsafe", secret="live-secret-value"
    )
    with pytest.raises(DirectPublicContextError, match="sensitive"):
        load_direct_public_tools(
            unsafe_workspace,
            unsafe_commit,
            "archeology_scan_large",
            "C1",
            environment={"PUBLIC_API_TOKEN": "live-secret-value"},
        )


def test_context_rejects_uncommitted_changes_and_manifest_hash_mismatch(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    schema_path = (
        workspace
        / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl"
    )
    schema_path.write_bytes(schema_path.read_bytes() + b"\n")

    with pytest.raises(DirectPublicContextError, match="system commit"):
        load_direct_public_tools(workspace, commit, "archeology_scan_large", "C1")

    mismatch_workspace, _ = _fixture_repo(tmp_path / "mismatch")
    manifest_path = (
        mismatch_workspace / "semantic_models/public_schema_ir/manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output"]["sha256"] = "f" * 64
    _write_json(manifest_path, manifest)
    _git(mismatch_workspace, "add", str(manifest_path.relative_to(mismatch_workspace)))
    _git(mismatch_workspace, "commit", "-qm", "corrupt declared digest")
    mismatch_commit = _git(mismatch_workspace, "rev-parse", "HEAD")

    with pytest.raises(DirectPublicContextError, match="SHA-256"):
        load_direct_public_tools(
            mismatch_workspace,
            mismatch_commit,
            "archeology_scan_large",
            "C1",
        )


def test_context_rejects_invalid_condition_and_prompt_contract(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    with pytest.raises(DirectPublicContextError, match="condition"):
        load_direct_public_tools(workspace, commit, "archeology_scan_large", "C4")

    prompt_path = workspace / "config/prompts/direct-sql-v1.txt"
    prompt_path.write_text("prefix {question}\n", encoding="utf-8")
    _git(workspace, "add", str(prompt_path.relative_to(workspace)))
    _git(workspace, "commit", "-qm", "invalid prompt")
    bad_commit = _git(workspace, "rev-parse", "HEAD")

    with pytest.raises(DirectPublicContextError, match="prompt"):
        load_direct_public_tools(workspace, bad_commit, "archeology_scan_large", "C1")


@pytest.mark.parametrize("query", ["", ".-", "x" * 513])
def test_search_rejects_empty_nonlexical_and_oversized_queries(
    tmp_path: Path, query: str
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    tools = load_direct_public_tools(workspace, commit, "archeology_scan_large", "C2")
    assert tools.search_hkb is not None

    with pytest.raises(DirectPublicContextError, match="query"):
        tools.search_hkb(query)


def test_search_returns_a_deterministic_empty_result_and_rejects_unsafe_question(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    tools = load_direct_public_tools(
        workspace,
        commit,
        "archeology_scan_large",
        "C3",
        environment={"PUBLIC_API_TOKEN": "live-secret-value"},
    )
    assert tools.search_semantic_model is not None

    result = tools.search_semantic_model("unmatchedlexeme")

    assert result.payload["matches"] == []
    assert result.payload["truncated"] is False
    assert result.semantic_objects == ()
    with pytest.raises(DirectPublicContextError, match="question"):
        tools.render_question("")
    with pytest.raises(DirectPublicContextError, match="sensitive"):
        tools.render_question("live-secret-value")
