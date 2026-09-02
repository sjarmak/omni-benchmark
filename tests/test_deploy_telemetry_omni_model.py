from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/deploy_telemetry_omni_model.py"
MODEL_DIR = Path(__file__).resolve().parents[1] / "config/telemetry_db/omni_model"


def _load():
    spec = importlib.util.spec_from_file_location("deploy_telemetry_omni_model", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _model_dir(tmp_path: Path) -> Path:
    root = tmp_path / "omni_model"
    (root / "neondb.telemetry").mkdir(parents=True)
    (root / "neondb.telemetry/attempt.view").write_text(
        "table_name: attempt\n", encoding="utf-8"
    )
    (root / "attempt_scored.topic").write_text(
        "base_view: neondb_telemetry__attempt\n", encoding="utf-8"
    )
    (root / "relationships").write_text("[]\n", encoding="utf-8")
    return root


class FakeRun:
    """Records omni invocations and replays canned JSON responses."""

    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    def __call__(
        self, command, input=None, capture_output=True, text=True, check=False
    ):
        self.calls.append((tuple(command), input))
        verb = command[6]
        if verb == "yaml-create":
            return subprocess.CompletedProcess(command, 0, '{"success": true}', "")
        response = self.responses[verb]
        if isinstance(response, subprocess.CompletedProcess):
            return response
        return subprocess.CompletedProcess(command, 0, json.dumps(response), "")


def _cli(module, profile: str = "p"):
    return module.OmniCli("omni", profile, sleep=lambda _seconds: None)


def _responses(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "list": {"records": [{"id": "model-1", "name": "omni-benchmark telemetry"}]},
        "create-branch": {"id": "branch-1"},
        "validate": [],
        "merge-branch": {"success": True},
    }
    return {**base, **overrides}


def test_model_files_are_named_by_posix_relative_path(tmp_path: Path) -> None:
    module = _load()
    files = module.model_files(_model_dir(tmp_path))
    assert [file.name for file in files] == [
        "attempt_scored.topic",
        "neondb.telemetry/attempt.view",
        "relationships",
    ]
    assert files[1].content == "table_name: attempt\n"


def test_model_files_rejects_missing_or_empty_directory(tmp_path: Path) -> None:
    module = _load()
    with pytest.raises(module.DeployError, match="missing"):
        module.model_files(tmp_path / "absent")
    (tmp_path / "empty").mkdir()
    with pytest.raises(module.DeployError, match="no files"):
        module.model_files(tmp_path / "empty")


def test_committed_model_directory_has_every_planned_file() -> None:
    module = _load()
    names = {file.name for file in module.model_files(MODEL_DIR)}
    expected_views = {
        "attempt",
        "score",
        "run",
        "question",
        "deployment",
        "sealed_aggregate",
        "attempt_label_latest",
        "trace_event",
        "action_evidence",
        "attempt_scored",
    }
    assert {f"neondb.telemetry/{view}.view" for view in expected_views} <= names
    assert {
        "model",
        "relationships",
        "attempt_scored.topic",
        "sealed_telemetry.topic",
        "trace.topic",
    } <= names


def test_dry_run_prints_plan_without_calling_omni(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    fake = FakeRun({})
    monkeypatch.setattr(module.subprocess, "run", fake)
    code = module.main(
        ["--model-dir", str(_model_dir(tmp_path)), "--branch-name", "b1"]
    )
    assert code == 0
    assert fake.calls == []
    out = capsys.readouterr().out
    assert "models create-branch <model-id> --name b1" in out
    assert "fileName=neondb.telemetry/attempt.view mode=combined" in out
    assert "merge-branch <model-id> b1" in out


def test_live_deploy_reuses_model_uploads_validates_and_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    fake = FakeRun(_responses())
    monkeypatch.setattr(module.subprocess, "run", fake)
    result = module.deploy(
        _cli(module, "benchmark-infra"),
        module.model_files(_model_dir(tmp_path)),
        "b1",
    )
    assert result.model_id == "model-1"
    assert result.branch_id == "branch-1"
    assert result.merged is True
    assert result.validation == []
    verbs = [call[0][6] for call in fake.calls]
    assert verbs == [
        "list",
        "create-branch",
        "yaml-create",
        "yaml-create",
        "yaml-create",
        "validate",
        "merge-branch",
    ]
    assert fake.calls[0][0][:5] == ("omni", "-p", "benchmark-infra", "-o", "json")
    upload = json.loads(fake.calls[2][1])
    assert upload == {
        "branchId": "branch-1",
        "commitMessage": module.COMMIT_MESSAGE,
        "fileName": "attempt_scored.topic",
        "mode": "combined",
        "yaml": "base_view: neondb_telemetry__attempt\n",
    }
    assert fake.calls[5][0][7:] == ("model-1", "--branchid", "branch-1")
    assert fake.calls[6][0][7:9] == ("model-1", "b1")


def test_live_deploy_creates_model_when_none_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    fake = FakeRun(
        _responses(**{"list": {"records": []}, "create": {"model": {"id": "m-new"}}})
    )
    monkeypatch.setattr(module.subprocess, "run", fake)
    result = module.deploy(_cli(module), module.model_files(_model_dir(tmp_path)), "b1")
    assert result.model_id == "m-new"
    create = json.loads(fake.calls[1][1])
    assert create == {
        "connectionId": module.CONNECTION_ID,
        "modelKind": "SHARED",
        "modelName": module.MODEL_NAME,
    }


def test_validation_issues_stop_before_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    issue = {"severity": "error", "message": "unknown field"}
    fake = FakeRun(_responses(validate=[issue]))
    monkeypatch.setattr(module.subprocess, "run", fake)
    result = module.deploy(_cli(module), module.model_files(_model_dir(tmp_path)), "b1")
    assert result.merged is False
    assert result.validation == [issue]
    assert "merge-branch" not in [call[0][6] for call in fake.calls]


def test_cli_failure_raises_with_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    failed = subprocess.CompletedProcess(("omni",), 1, "", "HTTP 404")
    fake = FakeRun(_responses(**{"create-branch": failed}))
    monkeypatch.setattr(module.subprocess, "run", fake)
    with pytest.raises(
        module.DeployError, match="create-branch failed \\(1\\) after 0 rate-limit"
    ):
        module.deploy(_cli(module), module.model_files(_model_dir(tmp_path)), "b1")


def test_duplicate_model_names_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    records = [
        {"id": "a", "name": module.MODEL_NAME},
        {"id": "b", "name": module.MODEL_NAME},
    ]
    fake = FakeRun(_responses(**{"list": {"records": records}}))
    monkeypatch.setattr(module.subprocess, "run", fake)
    with pytest.raises(module.DeployError, match="2 shared models"):
        module.find_shared_model(_cli(module))


def test_rate_limit_is_retried_with_paced_sleeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    outcomes = iter(
        [
            subprocess.CompletedProcess(
                ("omni",), 1, "", "Error: API returned HTTP 429"
            ),
            subprocess.CompletedProcess(("omni",), 0, "[]", ""),
            subprocess.CompletedProcess(("omni",), 0, "[]", ""),
        ]
    )
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: next(outcomes))
    sleeps: list[float] = []
    cli = module.OmniCli(
        "omni", "p", interval_seconds=0.5, retry_delays=(2.0,), sleep=sleeps.append
    )
    cli.run("models", "list")
    assert module.validate_branch(cli, "m", "b") == []
    assert sleeps == [2.0, 0.5, 0.5]


def test_rate_limit_retries_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    limited = subprocess.CompletedProcess(
        ("omni",), 1, "", "Error: API returned HTTP 429"
    )
    monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: limited)
    cli = module.OmniCli("omni", "p", retry_delays=(1.0, 1.0), sleep=lambda _s: None)
    with pytest.raises(module.DeployError, match="after 2 rate-limit retries: .*429"):
        cli.run("models", "validate", "m")


def test_find_shared_model_bounds_the_listing_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    fake = FakeRun(_responses())
    monkeypatch.setattr(module.subprocess, "run", fake)
    assert module.find_shared_model(_cli(module)) == "model-1"
    assert fake.calls[0][0][7:] == (
        "--connectionid",
        module.CONNECTION_ID,
        "--modelkind",
        "SHARED",
        "--name",
        module.MODEL_NAME,
    )


def test_unexhausted_model_page_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    listing = {
        "pageInfo": {"hasNextPage": True, "nextCursor": "c2"},
        "records": [{"id": "other", "name": "unrelated model"}],
    }
    fake = FakeRun(_responses(**{"list": listing}))
    monkeypatch.setattr(module.subprocess, "run", fake)
    with pytest.raises(module.DeployError, match="has more pages"):
        module.find_shared_model(_cli(module))


def test_exhausted_model_page_without_match_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    listing = {"pageInfo": {"hasNextPage": False, "nextCursor": None}, "records": []}
    fake = FakeRun(_responses(**{"list": listing}))
    monkeypatch.setattr(module.subprocess, "run", fake)
    assert module.find_shared_model(_cli(module)) is None


def test_missing_omni_binary_raises_deploy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError(2, "No such file or directory", "/nonexistent/omni")

    monkeypatch.setattr(module.subprocess, "run", _explode)
    cli = module.OmniCli("/nonexistent/omni", "p", sleep=lambda _s: None)
    with pytest.raises(module.DeployError, match="cannot run the omni CLI"):
        cli.run("models", "list")


def test_missing_omni_binary_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(13, "Permission denied", "/nonexistent/omni")

    monkeypatch.setattr(module.subprocess, "run", _explode)
    argv = [
        "--live",
        "--omni",
        "/nonexistent/omni",
        "--model-dir",
        str(_model_dir(tmp_path)),
        "--branch-name",
        "b1",
    ]
    with pytest.raises(module.DeployError):
        module.main(argv)
