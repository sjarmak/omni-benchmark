"""CLI security boundary for frozen-baseline dev-A scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from omni_benchmark.dev_a_baseline_scoring import DevABaselineScoringError
from omni_benchmark.dev_a_baseline_scoring_cli import (
    _selection_path,
    dev_a_baseline_scoring_entrypoint,
    dev_a_baseline_scoring_main,
)


def test_selection_path_is_confined_to_autoresearch_state() -> None:
    assert _selection_path(
        Path("experiments/autoresearch/state/public-c4-baseline-v4-freeze.json")
    ) == Path("experiments/autoresearch/state/public-c4-baseline-v4-freeze.json")
    with pytest.raises(DevABaselineScoringError, match="selection path"):
        _selection_path(Path("../private-selection.json"))


def test_cli_accepts_separate_artifact_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    custody = tmp_path / "custody"
    artifacts = tmp_path / "artifacts"
    custody.mkdir()
    artifacts.mkdir()
    captured: dict[str, object] = {}

    def prepare(workspace: Path, **kwargs: object) -> object:
        captured["workspace"] = workspace
        captured.update(kwargs)
        raise DevABaselineScoringError("stop after argument capture")

    monkeypatch.setattr(
        "omni_benchmark.dev_a_baseline_scoring_cli.prepare_dev_a_baseline_plan",
        prepare,
    )
    with pytest.raises(DevABaselineScoringError, match="argument capture"):
        dev_a_baseline_scoring_main(
            [
                "--workspace",
                str(custody),
                "--artifact-workspace",
                str(artifacts),
                "--freeze-a-commit",
                "a" * 40,
                "--expected-selection-sha256",
                "b" * 64,
                "--expected-release-sha256",
                "c" * 64,
                "--expected-official-scoreable-questions",
                "85",
                "--expected-sensitivity-scoreable-questions",
                "85",
                "--output-root",
                "experiments/autoresearch/raw/score-v1",
            ],
            environment={
                "OMNI_BENCHMARK_SCORER_ADMIN_DSN": "host=admin",
                "OMNI_BENCHMARK_SCORER_EXECUTION_DSN": "host=execution",
            },
        )

    assert captured["workspace"] == custody.resolve()
    assert captured["artifact_workspace"] == artifacts


def test_cli_requires_in_memory_dsn_environment(tmp_path: Path) -> None:
    with pytest.raises(DevABaselineScoringError, match="SCORER_ADMIN_DSN") as captured:
        dev_a_baseline_scoring_main(
            [
                "--workspace",
                str(tmp_path),
                "--freeze-a-commit",
                "a" * 40,
                "--expected-selection-sha256",
                "b" * 64,
                "--expected-release-sha256",
                "c" * 64,
                "--expected-official-scoreable-questions",
                "122",
                "--expected-sensitivity-scoreable-questions",
                "121",
                "--output-root",
                "experiments/autoresearch/raw/score-v1",
            ],
            environment={},
        )

    assert "host=" not in str(captured.value)
    assert "password=" not in str(captured.value)


def test_cli_rejects_dsn_in_command_line() -> None:
    with pytest.raises(SystemExit):
        dev_a_baseline_scoring_main(
            ["--admin-dsn", "host=secret.example password=do-not-print"],
            environment={},
        )


def test_entrypoint_sanitizes_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failed() -> int:
        raise RuntimeError("candidate SQL and secret result must not print")

    monkeypatch.setattr(
        "omni_benchmark.dev_a_baseline_scoring_cli.dev_a_baseline_scoring_main",
        failed,
    )

    assert dev_a_baseline_scoring_entrypoint() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "dev-A baseline scoring failed: internal scorer error\n"
