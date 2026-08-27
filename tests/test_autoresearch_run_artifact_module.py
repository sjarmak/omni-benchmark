"""Architecture characterization for run-artifact validation."""

from pathlib import Path

from omni_benchmark import autoresearch_runs


def test_run_artifact_validation_modules_remain_focused() -> None:
    """Keep the public constant import stable and both modules below 800 lines."""
    source_root = Path(__file__).parents[1] / "src" / "omni_benchmark"

    assert autoresearch_runs.TRACE_SCHEMA_VERSION == "trace-event-v2"
    for filename in ("autoresearch_runs.py", "autoresearch_artifacts.py"):
        source = (source_root / filename).read_text(encoding="utf-8")
        assert len(source.splitlines()) < 800
