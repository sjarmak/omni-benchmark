"""Keep the trace schema version to exactly one definition site.

Before this file, ``omni_attempt._trace_fields`` and
``direct_sql_attempt._trace_fields`` each wrote the literal ``"trace-event-v2"``
into the run manifest, while ``autoresearch_artifacts._validate_trace_record``
compared that field against the ``TRACE_SCHEMA_VERSION`` constant. Three copies,
no link between them. Bumping the constant for a schema change would have left
both writers emitting the old string and every run failing its own artifact
validation at write time, which is the most expensive place to discover it.

The audit's SQLSTATE-retention item (bead omni-benchmark-bfb) is precisely such
a bump: the trace event is exact-set validated, so adding a field requires a new
version. This test makes that bump a one-line edit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from omni_benchmark.autoresearch_artifacts import TRACE_SCHEMA_VERSION

RUNTIME_PACKAGE = Path(__file__).parents[1] / "src/omni_benchmark"
DEFINITION_SITE = RUNTIME_PACKAGE / "autoresearch_artifacts.py"
_VERSION_LITERAL = re.compile(r"""["']trace-event-v\d+["']""")


def _runtime_modules() -> list[Path]:
    return sorted(RUNTIME_PACKAGE.rglob("*.py"))


def test_the_version_string_is_declared_once() -> None:
    """No runtime module may spell the version out for itself."""

    offenders = {
        path.relative_to(RUNTIME_PACKAGE).as_posix()
        for path in _runtime_modules()
        if path != DEFINITION_SITE
        and _VERSION_LITERAL.search(path.read_text(encoding="utf-8"))
    }
    assert offenders == set()


def test_the_definition_site_declares_it_exactly_once() -> None:
    matches = _VERSION_LITERAL.findall(DEFINITION_SITE.read_text(encoding="utf-8"))
    assert matches == [f'"{TRACE_SCHEMA_VERSION}"']


@pytest.mark.parametrize(
    "module_name", ["omni_attempt", "direct_sql_attempt", "direct_trace_validation"]
)
def test_the_writers_and_the_validator_import_the_constant(module_name: str) -> None:
    """Importing it is what keeps a bump from being a silent no-op here."""

    source = (RUNTIME_PACKAGE / f"{module_name}.py").read_text(encoding="utf-8")
    assert "TRACE_SCHEMA_VERSION" in source


def test_the_current_version_is_the_one_the_frozen_series_recorded() -> None:
    """A bump is a series change, so it must not pass unnoticed.

    ``docs/protocol-amendment-dev-tier-draft.md`` puts the trace schema inside a
    series pin: the sealed-final-v6 artifacts are trace-event-v2 and stay that
    way. Changing this constant means opening a new series and running a bridge
    round, so the assertion is deliberately a tripwire, not a style check.
    """

    assert TRACE_SCHEMA_VERSION == "trace-event-v2"
