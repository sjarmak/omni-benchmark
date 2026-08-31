"""Cover the field-kind sidecar artifact and the boundary it must not cross.

The compiler's field-kind map is attribution evidence, not model input. Two
properties matter more than the totals: recompiling the committed specs must
reproduce the committed artifact byte for byte, and it must leave every byte
under ``semantic_models/`` alone, because those bytes were deployed and
custody-verified for a completed measurement.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_ARTIFACT = (
    REPOSITORY_ROOT / "experiments/analysis/semantic-field-kinds-v1.json"
)

#: Fields the protocol forbids at any nesting depth in a generation artifact.
FORBIDDEN_FIELDS = (
    "sol_sql",
    "gold_sql",
    "test_cases",
    "external_knowledge",
    "test_correctness",
    "gold_result",
    "expected_result",
)


def _module() -> Any:
    path = REPOSITORY_ROOT / "experiments/analysis/semantic_field_kinds.py"
    spec = importlib.util.spec_from_file_location("semantic_field_kinds", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(path for path in root.rglob("*") if path.is_file()):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def test_committed_inputs_classify_every_published_dimension() -> None:
    """Totals over the committed specs, including the empty unclassified set.

    ``unclassified_dimension_field_count`` is the tripwire: a source name bound
    to more than one column is excluded from the classification, so a nonzero
    count would mean a published dimension whose kind the artifact cannot state.
    """

    result = _module().field_kinds(REPOSITORY_ROOT)
    summary = {key: value for key, value in result.items() if key != "databases"}

    assert summary == {
        "artifact_kind": "semantic_field_kinds",
        "database_count": 18,
        "dimension_field_count": 599,
        "dimension_field_kind_counts": {
            "numeric": 317,
            "numeric_text": 59,
            "other": 97,
            "text": 126,
        },
        "reads": "committed public bundle specs, HKB IR, schema IR, and mappings",
        "schema_version": 1,
        "source_only_field_count": 1186,
        "unclassified_dimension_field_count": 0,
        "view_count": 127,
    }
    assert len({database["database"] for database in result["databases"]}) == 18


def test_recompilation_reproduces_the_committed_artifact_and_moves_no_bundle_byte(
    tmp_path: Path,
) -> None:
    """The acceptance criterion, checked literally on both halves."""

    semantic_models = REPOSITORY_ROOT / "semantic_models"
    before = _tree_digest(semantic_models)

    output = tmp_path / "field-kinds.json"
    arguments = ["--workspace", str(REPOSITORY_ROOT), "--output", str(output)]
    assert _module().main(arguments) == 0

    assert _tree_digest(semantic_models) == before
    assert output.read_bytes() == COMMITTED_ARTIFACT.read_bytes()
    assert list(tmp_path.iterdir()) == [output]


def test_committed_artifact_carries_no_forbidden_field() -> None:
    text = COMMITTED_ARTIFACT.read_text(encoding="utf-8")
    for field in FORBIDDEN_FIELDS:
        assert field not in text

    artifact = json.loads(text)
    view = artifact["databases"][0]["views"][0]
    assert set(view) == {
        "dimension_field_kinds",
        "source_only_field_kinds",
        "table_stable_id",
        "unclassified_dimension_fields",
        "view_name",
    }


def test_a_dimension_without_a_classification_is_reported_not_dropped() -> None:
    """The exclusion of ambiguous source names stays visible in the record."""

    module = _module()
    files = {"v.view": "dimensions:\n  classified: {}\n  ambiguous: {}\n"}
    view = {
        "file_name": "v.view",
        "table_stable_id": "db:table:t",
        "view_name": "v",
    }
    record = module._view_record(
        view, files, {"classified": "numeric", "spare": "text"}
    )

    assert record["dimension_field_kinds"] == {"classified": "numeric"}
    assert record["source_only_field_kinds"] == {"spare": "text"}
    assert record["unclassified_dimension_fields"] == ["ambiguous"]


def test_a_view_compiled_without_dimensions_is_refused() -> None:
    module = _module()
    with pytest.raises(ValueError, match="declares no dimensions"):
        module._view_dimensions({"v.view": "schema: public\n"}, "v.view")


def test_a_symlinked_public_input_is_refused(tmp_path: Path) -> None:
    """Public inputs are read by path; a link could point outside the workspace."""

    target = tmp_path / "real.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="unsafe or oversized"):
        _module()._bytes(link)
