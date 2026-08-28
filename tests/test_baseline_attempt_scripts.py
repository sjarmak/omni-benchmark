from pathlib import Path


def test_baseline_attempt_scripts_invoke_the_scoped_adapters() -> None:
    direct = Path("scripts/baseline_direct_attempt.py").read_text(encoding="utf-8")
    omni = Path("scripts/baseline_omni_attempt.py").read_text(encoding="utf-8")

    assert "baseline_direct_probe_main" in direct
    assert "baseline_omni_probe_main" in omni
    assert 'if __name__ == "__main__"' in direct
    assert 'if __name__ == "__main__"' in omni
