from pathlib import Path


def test_baseline_continuation_script_invokes_the_entrypoint() -> None:
    script = Path("scripts/baseline_continuation.py").read_text(encoding="utf-8")

    assert "baseline_continuation_main" in script
