from __future__ import annotations

import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).parents[1]


def test_prepare_schema_sources_script_exposes_fetch_command() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/prepare_schema_sources.py", "--help"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "build" in result.stdout
    assert "fetch" in result.stdout
    assert "inspect" in result.stdout
