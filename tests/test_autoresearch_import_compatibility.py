"""Compatibility checks for symbols retained after module extraction."""

from omni_benchmark import (
    autoresearch_artifacts,
    autoresearch_lifecycle,
    autoresearch_runs,
    autoresearch_smoke,
)


def test_run_validation_module_reexports_extracted_artifact_symbols() -> None:
    """Existing callers keep receiving the canonical extracted objects."""
    names = (
        "MAX_RESULT_ARTIFACT_BYTES",
        "RESULT_ARTIFACT_FIELDS",
        "TRACE_EVENT_FIELDS",
        "TRACE_FAILURE_TERMINAL_STATES",
        "TRACE_ROOTS",
        "TRACE_SUCCESS_TERMINAL_STATES",
    )

    for name in names:
        assert getattr(autoresearch_runs, name) is getattr(autoresearch_artifacts, name)


def test_run_validation_module_reexports_telemetry_smoke_validator() -> None:
    """The legacy import resolves without introducing an import cycle."""
    from omni_benchmark.autoresearch_runs import validate_telemetry_smoke

    assert validate_telemetry_smoke is autoresearch_smoke.validate_telemetry_smoke


def test_ledger_module_reexports_ledger_check_type() -> None:
    """LedgerCheck remains importable from its former public module."""
    from omni_benchmark.autoresearch_ledger import LedgerCheck

    assert LedgerCheck is autoresearch_lifecycle.LedgerCheck
