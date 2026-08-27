from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.omni_probe_cli import probe_main

from tests.test_omni_probe_cli import (
    NeverCompleteClient,
    _environment,
    _observe_cli_version,
    _probe_arguments,
    _workspace,
)


def test_probe_applies_polling_controls_from_the_committed_c4_spec(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace, _ = _workspace(tmp_path)
    condition = workspace / "config" / "conditions" / "c4-production-v1.json"
    value = json.loads(condition.read_text())
    value["maximum_status_checks"] = 1
    value["poll_schedule_seconds"] = [0.125]
    condition.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "test: custom polling policy"],
        cwd=workspace,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    observed_delays: list[float] = []

    status = probe_main(
        _probe_arguments(workspace, commit),
        environment=_environment(workspace),
        client_factory=NeverCompleteClient,
        sleep=observed_delays.append,
        cli_version_observer=_observe_cli_version,
    )

    assert status == 0
    assert observed_delays == [0.125]
    assert json.loads(capsys.readouterr().out)["terminal_state"] == "POLL_EXHAUSTED"
