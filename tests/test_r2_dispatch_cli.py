"""Only the top-level paired dispatcher may expose the R2 live boundary."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.r2_dispatch_cli as cli


COMMIT = "a" * 40
SHA = "b" * 64


def _arguments() -> list[str]:
    return [
        "--workspace",
        ".",
        "--system-commit",
        COMMIT,
        "--output-root",
        "runs/r2-v1",
        "--control-run-id",
        "r2-c5b-v1",
        "--treatment-run-id",
        "r2-m1-v1",
        "--control-deployment-run-id",
        "r2-c5b-deployment-v1",
        "--treatment-deployment-run-id",
        "r2-m1-deployment-v1",
        "--control-deployment-root",
        "experiments/deployments/r2-c5b-deployment-v1",
        "--treatment-deployment-root",
        "experiments/deployments/r2-m1-deployment-v1",
        "--control-projected-attempt-cost-usd",
        "1",
        "--treatment-projected-attempt-cost-usd",
        "1",
        "--budget-policy-sha256",
        SHA,
        "--budget-id",
        "r2-budget-v1",
        "--freeze-a-commit",
        "c" * 40,
        "--maximum-wall-clock-seconds",
        "100",
    ]


def test_dry_preflight_is_provider_inert_and_needs_no_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setattr(cli, "_load_execution_plan", lambda _: object())
    monkeypatch.setattr(
        cli,
        "prepare_r2_dispatch_inputs",
        lambda **kwargs: (
            observed.update(kwargs=kwargs)
            or SimpleNamespace(public_summary=lambda: {"live_execution": "not_started"})
        ),
    )
    monkeypatch.setattr(
        cli,
        "authorize_r2_dispatch",
        lambda *_args, **_kwargs: pytest.fail("dry preflight must not read a receipt"),
    )
    monkeypatch.setattr(
        cli,
        "R2LiveExecutor",
        lambda **_kwargs: pytest.fail("dry preflight must not construct an executor"),
    )

    assert cli.r2_dispatch_main(_arguments()) == 0
    assert json.loads(capsys.readouterr().out) == {"live_execution": "not_started"}
    assert observed["kwargs"]["deployment_roots"] == {
        "R2-C5B": Path("experiments/deployments/r2-c5b-deployment-v1"),
        "R2-M1": Path("experiments/deployments/r2-m1-deployment-v1"),
    }


def test_live_series_requires_receipt_and_defers_executor_to_dispatcher(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = object()
    preflight = SimpleNamespace(
        inputs=SimpleNamespace(workspace=Path("."), plan=object(), policy=object())
    )
    executor = object()
    monkeypatch.setattr(cli, "_load_execution_plan", lambda _: object())
    monkeypatch.setattr(cli, "prepare_r2_dispatch_inputs", lambda **_: inputs)
    with pytest.raises(cli.R2DispatchCliError, match="receipt"):
        cli.r2_dispatch_main([*_arguments(), "--execute-live-series"])

    monkeypatch.setattr(
        cli,
        "authorize_r2_dispatch",
        lambda value, **kwargs: (
            preflight
            if value is inputs and kwargs["receipt_path"] == Path("approval.json")
            else pytest.fail("wrong preflight")
        ),
    )
    constructed: list[dict[str, object]] = []
    monkeypatch.setattr(
        cli,
        "R2LiveExecutor",
        lambda **kwargs: constructed.append(kwargs) or executor,
    )

    def execute(value: object, *, executor_builder):  # type: ignore[no-untyped-def]
        assert value is preflight
        assert constructed == []
        assert executor_builder(preflight) is executor
        return SimpleNamespace(public_summary=lambda: {"remaining_count": 0})

    monkeypatch.setattr(cli, "execute_r2_dispatch", execute)
    assert (
        cli.r2_dispatch_main(
            [
                *_arguments(),
                "--execute-live-series",
                "--human-approval-receipt",
                "approval.json",
            ],
            environment={
                "OMNI_PROFILE": "fixture",
                "OMNI_BASE_URL": "https://example.omniapp.co",
            },
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {"remaining_count": 0}


def test_live_environment_fails_before_dispatch_can_consume_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = object()
    preflight = object()
    monkeypatch.setattr(cli, "_load_execution_plan", lambda _: object())
    monkeypatch.setattr(cli, "prepare_r2_dispatch_inputs", lambda **_: inputs)
    monkeypatch.setattr(
        cli, "authorize_r2_dispatch", lambda *_args, **_kwargs: preflight
    )
    monkeypatch.setattr(
        cli,
        "prepare_r2_live_environment",
        lambda _environment: (_ for _ in ()).throw(
            cli.R2LiveExecutorError("R2 executor requires the Omni base URL")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "execute_r2_dispatch",
        lambda *_args, **_kwargs: pytest.fail(
            "dispatcher must not consume an approval before environment validation"
        ),
    )

    with pytest.raises(cli.R2LiveExecutorError, match="base URL"):
        cli.r2_dispatch_main(
            [
                *_arguments(),
                "--execute-live-series",
                "--human-approval-receipt",
                "approval.json",
            ],
            environment={"OMNI_PROFILE": "fixture"},
        )


def test_entrypoint_sanitizes_unexpected_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "r2_dispatch_main",
        lambda: (_ for _ in ()).throw(RuntimeError("Bearer provider-secret")),
    )
    assert cli.r2_dispatch_entrypoint() == 1
    error = capsys.readouterr().err
    assert "provider-secret" not in error
    assert "internal error" in error


def test_attempt_leaf_stays_dry_only() -> None:
    content = Path("src/omni_benchmark/r2_attempt_cli.py").read_text(encoding="utf-8")
    assert "--execute-live-series" not in content
    assert "--human-approval-receipt" not in content
