from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from omni_benchmark.semantic_bundle_publication import build_bundle_artifacts


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_ROOT = ROOT / "semantic_models/public_bundle"
PROTECTED_KEYS = frozenset(
    {
        "expected_result",
        "external_knowledge",
        "gold_result",
        "gold_sql",
        "oracle_hint",
        "oracle_sql",
        "sol_sql",
        "test_case",
        "test_cases",
        "test_correctness",
    }
)


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(_keys(item) for item in value.values()), set())
    if isinstance(value, list):
        return set().union(*(_keys(item) for item in value), set())
    return set()


def test_committed_public_bundle_regenerates_byte_for_byte() -> None:
    files, manifest = build_bundle_artifacts(
        (ROOT / "config/archeology_scan_public_bundle.json").read_bytes(),
        (
            ROOT / "semantic_models/public_ir/archeology_scan_large.hkb.jsonl"
        ).read_bytes(),
        (
            ROOT / "semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl"
        ).read_bytes(),
        (
            ROOT / "semantic_models/public_mapping/archeology_scan_large.mapping.jsonl"
        ).read_bytes(),
        (ROOT / "semantic_models/public_mapping/manifest.json").read_bytes(),
    )

    assert json.loads((BUNDLE_ROOT / "manifest.json").read_bytes()) == manifest
    assert hashlib.sha256((BUNDLE_ROOT / "manifest.json").read_bytes()).hexdigest() == (
        "ba441ace28dc730508bf8de1771b18a61e83eec5050f8d44a4643bc83cfbe76d"
    )
    assert {path.name for path in BUNDLE_ROOT.iterdir()} == {
        *files,
        "manifest.json",
    }
    for name, expected in files.items():
        assert (BUNDLE_ROOT / name).read_bytes() == expected


def test_committed_public_bundle_is_public_only_and_no_join() -> None:
    manifest = json.loads((BUNDLE_ROOT / "manifest.json").read_bytes())

    assert manifest["source"] == {
        "bundle_spec": {
            "sha256": "a3151e6a9981907e533db9da5e51e5df871bc669786c9da1319d1a91757a2312"
        },
        "hkb_ir": {
            "sha256": "c6b20ec0e101f080712255645554cea2685deca7929a8c6d4c3391aeecf92d37"
        },
        "mapping": {
            "sha256": "a54234cf768619bd15260a87ff3cd55765d006eaa4bd20bc05fd427ed24eeae6"
        },
        "mapping_manifest": {
            "sha256": "33d8c5de2852cb5fb73117e4b60fa0dfc729f0762b519c0f7ce1fedc22803c22"
        },
        "schema_ir": {
            "sha256": "e2044dc11b055e08046153de8c9cec9d121f037391d5b757c8cd071dd607162f"
        },
    }
    assert manifest["validation"] == {
        "all_compile_mappings_materialized": True,
        "hidden_annotations_used": False,
        "joins_generated": False,
        "public_inputs_only": True,
        "status": "passed",
    }
    environment = yaml.safe_load(
        (BUNDLE_ROOT / "archeology_scan_large.public__environment.view").read_text()
    )
    classification_sql = environment["dimensions"][
        "environmental_condition_classification"
    ]["sql"]
    assert "${is_optimal_scanning_condition}" in classification_sql
    assert PROTECTED_KEYS.isdisjoint(_keys(manifest))
    assert len(manifest["semantic_elements"]) == 24
