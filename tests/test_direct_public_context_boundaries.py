from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from omni_benchmark.direct_runtime_binding import DirectContextIdentity
from omni_benchmark.direct_public_context import (
    DirectPublicContextError,
    load_direct_public_tools,
)
from tests.test_direct_public_context import (
    _fixture_repo,
    _git,
    _sha256,
    _write_json,
    _write_jsonl,
)


@pytest.mark.parametrize(
    ("condition", "expected_components"),
    [
        (
            "C1",
            {
                "condition_config",
                "instructions",
                "prompt",
                "schema",
                "schema_manifest",
            },
        ),
        (
            "C2",
            {
                "condition_config",
                "hkb",
                "hkb_manifest",
                "instructions",
                "prompt",
                "schema",
                "schema_manifest",
            },
        ),
        (
            "C3",
            {
                "condition_config",
                "instructions",
                "prompt",
                "schema",
                "schema_manifest",
                "semantic_manifest",
            },
        ),
    ],
)
def test_public_tools_expose_exact_database_bound_context_identity(
    tmp_path: Path,
    condition: str,
    expected_components: set[str],
) -> None:
    workspace, commit = _fixture_repo(tmp_path)

    tools = load_direct_public_tools(
        workspace, commit, "archeology_scan_large", condition
    )

    assert type(tools.identity) is DirectContextIdentity
    assert tools.identity.condition == condition
    assert tools.identity.selected_database == "archeology_scan_large"
    assert set(dict(tools.identity.component_sha256)) == expected_components
    assert DirectContextIdentity.from_dict(
        tools.identity.as_dict(), environment={}
    ) == (tools.identity)
    with pytest.raises(FrozenInstanceError):
        tools.identity.selected_database = "other_database"  # type: ignore[misc]


def test_context_identity_changes_with_committed_schema_manifest_provenance(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    before = load_direct_public_tools(
        workspace, commit, "archeology_scan_large", "C1"
    ).identity
    manifest_path = workspace / "semantic_models/public_schema_ir/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source"]["public_revision"] = "second-public-revision"
    _write_json(manifest_path, manifest)
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "change public schema provenance")

    after = load_direct_public_tools(
        workspace,
        _git(workspace, "rev-parse", "HEAD"),
        "archeology_scan_large",
        "C1",
    ).identity

    assert (
        dict(before.component_sha256)["schema"]
        == dict(after.component_sha256)["schema"]
    )
    assert (
        dict(before.component_sha256)["schema_manifest"]
        != dict(after.component_sha256)["schema_manifest"]
    )
    assert before.context_sha256 != after.context_sha256


def test_context_identity_changes_with_committed_hkb_manifest_provenance(
    tmp_path: Path,
) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    before = load_direct_public_tools(
        workspace, commit, "archeology_scan_large", "C2"
    ).identity
    manifest_path = workspace / "semantic_models/public_ir/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["source"]["dataset"] = "second-public-synthetic-archeology"
    _write_json(manifest_path, manifest)
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "change public HKB provenance")

    after = load_direct_public_tools(
        workspace,
        _git(workspace, "rev-parse", "HEAD"),
        "archeology_scan_large",
        "C2",
    ).identity

    assert dict(before.component_sha256)["hkb"] == dict(after.component_sha256)["hkb"]
    assert (
        dict(before.component_sha256)["hkb_manifest"]
        != dict(after.component_sha256)["hkb_manifest"]
    )
    assert before.context_sha256 != after.context_sha256


def test_c2_callback_rejects_nested_hidden_label_in_committed_provenance(
    tmp_path: Path,
) -> None:
    workspace, _ = _fixture_repo(tmp_path)
    hkb_path = workspace / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"
    records = [json.loads(line) for line in hkb_path.read_text().splitlines()]
    records[-1]["provenance"]["external_knowledge"] = [3]
    content = _write_jsonl(hkb_path, records)
    manifest_path = workspace / "semantic_models/public_ir/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["databases"]["archeology_scan_large"]["ir_sha256"] = _sha256(content)
    _write_json(manifest_path, manifest)
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "nested hidden-label adversary")
    tools = load_direct_public_tools(
        workspace,
        _git(workspace, "rev-parse", "HEAD"),
        "archeology_scan_large",
        "C2",
    )
    assert tools.search_hkb is not None

    with pytest.raises(DirectPublicContextError, match="forbidden"):
        tools.search_hkb("premium quality")


def test_search_results_do_not_expose_mutable_cached_context(tmp_path: Path) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    c1 = load_direct_public_tools(workspace, commit, "archeology_scan_large", "C1")
    c2 = load_direct_public_tools(workspace, commit, "archeology_scan_large", "C2")
    c3 = load_direct_public_tools(workspace, commit, "archeology_scan_large", "C3")
    assert c2.search_hkb is not None
    assert c3.search_semantic_model is not None

    first_schema = c1.inspect_schema("resolution measurements")
    pristine_schema = json.loads(json.dumps(first_schema.payload))
    first_schema.payload["tables"][0]["name"] = "mutated"
    assert c1.inspect_schema("resolution measurements").payload == pristine_schema

    first_hkb = c2.search_hkb("premium quality")
    pristine_hkb = json.loads(json.dumps(first_hkb.payload))
    first_hkb.payload["matches"][0]["provenance"]["content"] = "mutated"
    assert c2.search_hkb("premium quality").payload == pristine_hkb

    first_semantic = c3.search_semantic_model("premium quality")
    pristine_semantic = json.loads(json.dumps(first_semantic.payload))
    first_semantic.payload["matches"][0]["label"] = "mutated"
    assert c3.search_semantic_model("premium quality").payload == pristine_semantic


def test_schema_search_is_identical_across_direct_conditions(tmp_path: Path) -> None:
    workspace, commit = _fixture_repo(tmp_path)
    payloads = []

    for condition in ("C1", "C2", "C3"):
        tools = load_direct_public_tools(
            workspace, commit, "archeology_scan_large", condition
        )
        payloads.append(tools.inspect_schema("resolution measurements").payload)

    assert payloads[0] == payloads[1] == payloads[2]
