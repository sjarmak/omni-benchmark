from __future__ import annotations

import hashlib
import json
import subprocess
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

import pytest

import omni_benchmark.sealed_dispatch as dispatch_module
from omni_benchmark.sealed_dispatch import (
    SealedAdapterResult,
    SealedDispatchError,
    SealedDispatchPolicy,
    build_sealed_dispatch_binding,
    execute_sealed_dispatch,
    preflight_sealed_dispatch,
    verify_sealed_runtime_sources,
)
from tests.test_sealed_generation_staging import _plan, _record, _workspace


NOW = datetime(2026, 8, 29, 8, 0, tzinfo=timezone.utc)
RUNTIME_SHA256 = "9" * 64


def _questions() -> dict[str, str]:
    return {
        f"q-{question:03d}": f"Public synthetic question {question}?"
        for question in range(1, 102)
    }


def _policy(
    *, cost_ceiling_usd: str = "121.200000", maximum_concurrency: int = 4
) -> SealedDispatchPolicy:
    return SealedDispatchPolicy.create(
        maximum_concurrency=maximum_concurrency,
        maximum_wall_clock_seconds=43_200,
        cost_ceiling_usd=cost_ceiling_usd,
        reservation_usd_by_condition={
            "C1": "0.100000",
            "C2": "0.100000",
            "C3": "0.100000",
            "C4": "0.100000",
        },
        software_versions={"omni-benchmark": "0.1.0", "python": "3.11.15"},
        cli_versions_by_condition={
            condition: {"synthetic": "1.0.0"} for condition in ("C1", "C2", "C3", "C4")
        },
    )


def _receipt(
    path: Path,
    binding: Mapping[str, object],
    *,
    decision_id: str = "omni-benchmark-sealed-approval-1",
    nonce: str = "2" * 64,
) -> tuple[dict[str, object], object]:
    value = {
        "approved_at": "2026-08-29T07:55:00Z",
        "binding": dict(binding),
        "decision_bead_id": decision_id,
        "expires_at": "2026-08-29T08:30:00Z",
        "kind": "sealed-production-human-approval",
        "nonce": nonce,
        "schema_version": 1,
    }
    content = (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode()
    path.write_bytes(content)
    path.chmod(0o600)
    issue = {
        "close_reason": "Responded",
        "closed_at": "2026-08-29T07:55:00Z",
        "id": decision_id,
        "issue_type": "decision",
        "labels": ["human"],
        "status": "closed",
    }

    def decision(_workspace: Path, observed_id: str):
        assert observed_id == decision_id
        return issue, ("Response: " + content.decode().strip(),)

    return value, decision


class _Adapter:
    def __init__(
        self,
        condition_binding: object,
        *,
        state: dict[str, object],
        fail_after: int | None = None,
    ) -> None:
        self.condition_binding = condition_binding
        self._state = state
        self._fail_after = fail_after

    def execute(self, prepared):  # type: ignore[no-untyped-def]
        lock = self._state["lock"]
        assert isinstance(lock, type(threading.Lock()))
        with lock:
            calls = self._state["calls"]
            assert isinstance(calls, list)
            calls.append(prepared.attempt_id)
            active = self._state["active"]
            assert isinstance(active, set)
            assert prepared.database not in active
            active.add(prepared.database)
            self._state["maximum_active"] = max(
                int(self._state["maximum_active"]), len(active)
            )
            call_number = len(calls)
        try:
            if self._fail_after is not None and call_number == self._fail_after:
                raise RuntimeError("synthetic infrastructure interruption")
            return SealedAdapterResult(
                generation_record=_record(
                    prepared, output=f"SELECT '{prepared.instance_id}'"
                )
            )
        finally:
            with lock:
                active = self._state["active"]
                assert isinstance(active, set)
                active.remove(prepared.database)


def _state() -> dict[str, object]:
    return {
        "active": set(),
        "calls": [],
        "lock": threading.Lock(),
        "maximum_active": 0,
    }


def _preflight(
    workspace: Path,
    *,
    policy: SealedDispatchPolicy | None = None,
    output_root: Path = Path("runs/sealed-final-v1"),
    receipt_name: str = "approval.json",
    receipt_changes: Mapping[str, object] | None = None,
):  # type: ignore[no-untyped-def]
    plan, freeze = _plan()
    chosen_policy = _policy() if policy is None else policy
    binding = build_sealed_dispatch_binding(
        plan=plan,
        freeze_b=freeze,
        policy=chosen_policy,
        output_root=output_root,
        run_id="sealed-final-v1",
        runtime_sources_sha256=RUNTIME_SHA256,
    )
    if receipt_changes:
        binding.update(receipt_changes)
    receipt_path = workspace / receipt_name
    _, decision = _receipt(
        receipt_path,
        binding,
        decision_id=f"omni-benchmark-sealed-{Path(receipt_name).stem}",
        nonce=hashlib.sha256(receipt_name.encode()).hexdigest(),
    )
    return preflight_sealed_dispatch(
        workspace=workspace,
        output_root=output_root,
        run_id="sealed-final-v1",
        plan=plan,
        freeze_b=freeze,
        questions=_questions(),
        policy=chosen_policy,
        receipt_path=receipt_path,
        now=NOW,
        decision_loader=decision,
        runtime_source_verifier=lambda _workspace, _commit: RUNTIME_SHA256,
    )


def _factories(freeze, state, *, fail_after=None):  # type: ignore[no-untyped-def]
    return {
        condition: (
            lambda frozen, condition=condition: _Adapter(
                frozen,
                state=state,
                fail_after=fail_after if condition == "C1" else None,
            )
        )
        for condition in ("C1", "C2", "C3", "C4")
    }


def test_synthetic_dispatch_stages_1212_and_finalizes_twelve_cohorts(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    preflight = _preflight(workspace)
    state = _state()

    report = execute_sealed_dispatch(
        preflight,
        adapter_factories=_factories(preflight.freeze_b, state),
    )

    assert report.attempt_count == 1_212
    assert report.completed_this_run == 1_212
    assert report.reconciled_count == 0
    assert report.remaining_count == 0
    assert report.reserved_cost_usd == "121.200000"
    assert len(report.cohorts) == 12
    assert {result.attempt_count for result in report.cohorts} == {101}
    assert len(state["calls"]) == 1_212  # type: ignore[arg-type]
    assert 1 < report.maximum_observed_concurrency <= 4
    assert int(state["maximum_active"]) <= 4
    assert all(path.exists() for path in report.cohort_manifest_paths)


def test_receipt_or_runtime_failure_precedes_writes_and_adapter_construction(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    plan, freeze = _plan()
    policy = _policy()
    binding = build_sealed_dispatch_binding(
        plan=plan,
        freeze_b=freeze,
        policy=policy,
        output_root=Path("runs/sealed-final-v1"),
        run_id="sealed-final-v1",
        runtime_sources_sha256=RUNTIME_SHA256,
    )
    binding["plan_sha256"] = "0" * 64
    receipt_path = workspace / "bad.json"
    _, decision = _receipt(receipt_path, binding)

    with pytest.raises(SealedDispatchError, match="approval"):
        preflight_sealed_dispatch(
            workspace=workspace,
            output_root=Path("runs/sealed-final-v1"),
            run_id="sealed-final-v1",
            plan=plan,
            freeze_b=freeze,
            questions=_questions(),
            policy=policy,
            receipt_path=receipt_path,
            now=NOW,
            decision_loader=decision,
            runtime_source_verifier=lambda _workspace, _commit: RUNTIME_SHA256,
        )
    assert not (workspace / "runs").exists()

    receipt_path.unlink()
    binding["plan_sha256"] = plan.sha256
    _, decision = _receipt(receipt_path, binding)
    with pytest.raises(SealedDispatchError, match="runtime source"):
        preflight_sealed_dispatch(
            workspace=workspace,
            output_root=Path("runs/sealed-final-v1"),
            run_id="sealed-final-v1",
            plan=plan,
            freeze_b=freeze,
            questions=_questions(),
            policy=policy,
            receipt_path=receipt_path,
            now=NOW,
            decision_loader=decision,
            runtime_source_verifier=lambda _workspace, _commit: "8" * 64,
        )
    assert not (workspace / "runs").exists()


def test_budget_admission_fails_before_consumption_or_calls(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    preflight = _preflight(
        workspace,
        policy=_policy(cost_ceiling_usd="121.100000"),
    )
    state = _state()

    with pytest.raises(SealedDispatchError, match="cost ceiling"):
        execute_sealed_dispatch(
            preflight,
            adapter_factories=_factories(preflight.freeze_b, state),
        )

    assert state["calls"] == []
    assert not (workspace / "runs").exists()


def test_adapter_identity_mismatch_consumes_receipt_but_makes_no_calls(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    preflight = _preflight(workspace)
    state = _state()
    wrong = preflight.freeze_b.condition("C2")
    factories = _factories(preflight.freeze_b, state)
    factories["C1"] = lambda _frozen: _Adapter(wrong, state=state)

    with pytest.raises(SealedDispatchError, match="identity"):
        execute_sealed_dispatch(preflight, adapter_factories=factories)

    assert state["calls"] == []
    markers = list((workspace / "runs/sealed-final-v1/approvals").glob("*.json"))
    assert len(markers) == 1


def test_wall_clock_stop_is_bounded_and_receipt_cannot_be_replayed(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    preflight = _preflight(workspace)
    state = _state()
    ticks = iter((0.0, 50_000.0))

    report = execute_sealed_dispatch(
        preflight,
        adapter_factories=_factories(preflight.freeze_b, state),
        monotonic=lambda: next(ticks, 50_000.0),
    )

    assert report.attempt_count == 0
    assert report.remaining_count == 1_212
    assert report.cohorts == ()
    assert state["calls"] == []
    with pytest.raises(SealedDispatchError, match="consumption"):
        execute_sealed_dispatch(
            preflight,
            adapter_factories=_factories(preflight.freeze_b, state),
        )


def test_infrastructure_interruption_stages_successes_and_fresh_receipt_resumes(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    first = _preflight(workspace, receipt_name="first.json")
    first_state = _state()

    with pytest.raises(SealedDispatchError, match="infrastructure"):
        execute_sealed_dispatch(
            first,
            adapter_factories=_factories(first.freeze_b, first_state, fail_after=5),
        )
    completed = len(
        list((workspace / "runs/sealed-final-v1/attempts").rglob("attempt.json"))
    )
    assert 0 < completed < 1_212

    second = _preflight(workspace, receipt_name="second.json")
    second_state = _state()
    report = execute_sealed_dispatch(
        second,
        adapter_factories=_factories(second.freeze_b, second_state),
    )

    assert report.reconciled_count == completed
    assert report.completed_this_run == 1_212 - completed
    assert len(second_state["calls"]) == 1_212 - completed  # type: ignore[arg-type]
    assert report.remaining_count == 0


def test_dispatch_module_has_no_scoring_or_gold_dependency() -> None:
    source = Path(dispatch_module.__file__).read_text(encoding="utf-8")
    assert "sealed_scoring" not in source
    assert "sealed_batch" not in source
    assert "gold" not in source.lower()


def test_runtime_source_digest_requires_loaded_bytes_at_system_commit(
    tmp_path: Path,
) -> None:
    source_root = Path(dispatch_module.__file__).resolve().parents[2]
    workspace = tmp_path / "frozen"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "synthetic@example.invalid"],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Synthetic Test"],
        cwd=workspace,
        check=True,
    )
    for relative in dispatch_module.SEALED_RUNTIME_SOURCE_PATHS:
        destination = workspace / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source_root / relative).read_bytes())
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "frozen"], cwd=workspace, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    digest = verify_sealed_runtime_sources(workspace, commit)
    assert len(digest) == 64

    source = workspace / dispatch_module.SEALED_RUNTIME_SOURCE_PATHS[0]
    source.write_bytes(source.read_bytes() + b"# committed substitution\n")
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "substitute"], cwd=workspace, check=True)
    changed_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    with pytest.raises(SealedDispatchError, match="does not match"):
        verify_sealed_runtime_sources(workspace, changed_commit)
