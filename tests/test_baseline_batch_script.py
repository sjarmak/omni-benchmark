from pathlib import Path


def test_baseline_batch_script_invokes_the_projection_entrypoint() -> None:
    script = Path("scripts/baseline_batch.py").read_text(encoding="utf-8")

    assert "baseline_batch_main" in script
    assert "execute_authenticated" not in script
    assert 'if __name__ == "__main__"' in script
