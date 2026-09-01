"""Receipt-gated paired R2 orchestration without correctness access."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import omni_benchmark.r2_dispatch as dispatch
from omni_benchmark.baseline_batch_live import DeploymentTarget
from omni_benchmark.measure_review_catalog import canonical_catalog_bytes
from omni_benchmark.r2_execution import (
    R2AttemptArtifacts,
    R2ExecutionPlan,
    R2PlannedAttempt,
    write_r2_attempt_artifacts,
)
from omni_benchmark.r2_production_approval import R2ProductionApprovalError
from omni_benchmark.r2_paired_schedule import (
    CONTROL_CONDITION,
    TREATMENT_CONDITION,
)


SHA = tuple(character * 64 for character in "123456789abcdef")
COMMIT = "a" * 40


def _attempt(
    position: int, condition: str, instance_id: str, database: str = "sample_large"
) -> R2PlannedAttempt:
    directory = "r2-c5b" if condition == CONTROL_CONDITION else "r2-m1"
    return R2PlannedAttempt(
        attempt_id=f"r2attempt-{position}",
        attempt_position=position,
        condition=condition,
        database=database,
        deployment_identity=f"livesqlbench-{database}-{directory}-v1",
        deployment_run_id=f"{directory}-deployment-v1",
        instance_id=instance_id,
        output_root=Path(
            f"runs/r2-series/{directory}/{database}/{position:03d}-r2attempt-{position}"
        ),
        pair_id=f"r2pair-{instance_id}",
        pair_position=(position + 1) // 2,
        repetition=1,
        run_id=f"{directory}-run-v1",
        semantic_model_sha256=SHA[0] if condition == CONTROL_CONDITION else SHA[1],
        within_pair_position=1 if position % 2 else 2,
    )


def _plan() -> R2ExecutionPlan:
    return R2ExecutionPlan(
        attempts=(
            _attempt(1, CONTROL_CONDITION, "q-1"),
            _attempt(2, TREATMENT_CONDITION, "q-1"),
            _attempt(3, TREATMENT_CONDITION, "q-2"),
            _attempt(4, CONTROL_CONDITION, "q-2"),
        ),
        balanced_ai_settings_sha256=SHA[2],
        budget_policy_sha256=SHA[3],
        bundle_manifest_sha256=SHA[4],
        bundle_set_sha256=SHA[5],
        harness_config_sha256=SHA[6],
        instructions_sha256=SHA[7],
        output_root=Path("runs/r2-series"),
        projected_arm_cost_usd={CONTROL_CONDITION: "2", TREATMENT_CONDITION: "3"},
        projected_total_cost_usd="5",
        prompt_sha256=SHA[8],
        schedule_sha256=SHA[9],
        system_commit=COMMIT,
    )


def _policy() -> dispatch.R2DispatchPolicy:
    return dispatch.R2DispatchPolicy.create(
        budget_id="r2-budget-v1",
        freeze_a_commit="b" * 40,
        maximum_wall_clock_seconds=43200,
    )


def _opportunity(count: int = 2) -> dispatch.R2OpportunityGate:
    return dispatch.R2OpportunityGate(
        artifact_sha256=SHA[10],
        external_sha256=SHA[11],
        opportunity_question_count=count,
    )


def _targets(plan: R2ExecutionPlan | None = None) -> dispatch.R2DeploymentGate:
    selected = _plan() if plan is None else plan
    by_condition: dict[str, dict[str, DeploymentTarget]] = {}
    sha256: dict[str, str] = {}
    for index, condition in enumerate((CONTROL_CONDITION, TREATMENT_CONDITION)):
        attempt = next(
            item for item in selected.attempts if item.condition == condition
        )
        by_condition[condition] = {
            attempt.database: DeploymentTarget(
                branch_id=attempt.deployment_identity,
                model_id=attempt.deployment_identity,
                semantic_model_sha256=attempt.semantic_model_sha256,
            )
        }
        sha256[condition] = SHA[12 + index]
    return dispatch.R2DeploymentGate.create(by_condition, sha256)


def _cleanup(confirmed: bool = True) -> dispatch.R2CleanupGate:
    return dispatch.R2CleanupGate(
        bead_id="omni-benchmark-ei0.10.16",
        closed_at="2026-09-01T19:00:00Z" if confirmed else None,
        confirmed=confirmed,
    )


def _inputs(tmp_path: Path, **changes: object) -> dispatch.R2DispatchInputs:
    (tmp_path / ".git").mkdir(exist_ok=True)
    arguments = {
        "workspace": tmp_path,
        "plan": _plan(),
        "policy": _policy(),
        "deployment_roots": {
            CONTROL_CONDITION: Path("experiments/deployments/r2-c5b-deployment-v1"),
            TREATMENT_CONDITION: Path("experiments/deployments/r2-m1-deployment-v1"),
        },
        "opportunity_loader": lambda *_: _opportunity(),
        "deployment_loader": lambda *_args, **_kwargs: _targets(),
        "cleanup_loader": lambda *_: _cleanup(),
        "runtime_verifier": lambda *_: SHA[14],
    }
    arguments.update(changes)
    return dispatch.prepare_r2_dispatch_inputs(**arguments)


def _approval(binding: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(
        approved_at=datetime(2026, 9, 1, 20, 0, tzinfo=timezone.utc),
        binding=binding,
        decision_bead_id="omni-benchmark-r2-action-1",
        expires_at=datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc),
        nonce="f" * 64,
        receipt_sha256=SHA[0],
    )


def _record(attempt: R2PlannedAttempt) -> dict[str, object]:
    return {
        "attempt_id": attempt.attempt_id,
        "condition": attempt.condition,
        "cost_unavailable_reason": "job_api_does_not_report_cost",
        "cost_usd": None,
        "database": attempt.database,
        "generation_outcome": "errored",
        "instance_id": attempt.instance_id,
        "latency_ms": 1.0,
        "partition": "dev-a",
        "repetition": 1,
        "run_id": attempt.run_id,
        "terminal_failure_class": "no_answer_insufficient_context",
    }


def test_provider_inert_inputs_bind_every_live_gate(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    binding = inputs.binding

    assert binding["attempt_count"] == 4
    assert binding["conditions"] == [CONTROL_CONDITION, TREATMENT_CONDITION]
    assert binding["execution_plan_sha256"] == _plan().sha256
    assert binding["opportunity_map_sha256"] == SHA[11]
    assert binding["source_cleanup_bead_id"] == "omni-benchmark-ei0.10.16"
    assert binding["deployment_sha256"] == {
        CONTROL_CONDITION: SHA[12],
        TREATMENT_CONDITION: SHA[13],
    }
    assert binding["maximum_concurrency"] == 1
    assert binding["reconciled_count"] == 0
    assert binding["reconciled_attempts_sha256"] == hashlib.sha256(b"[]\n").hexdigest()
    encoded = json.dumps(inputs.public_summary(), sort_keys=True).lower()
    for forbidden in ("question", "query", "credential", "correctness", "result"):
        assert forbidden not in encoded


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"opportunity_loader": lambda *_: _opportunity(0)}, "empty"),
        ({"cleanup_loader": lambda *_: _cleanup(False)}, "cleanup"),
        ({"runtime_verifier": lambda *_: "invalid"}, "runtime"),
    ],
)
def test_inputs_fail_closed_before_receipt_on_missing_prerequisite(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    with pytest.raises(dispatch.R2DispatchError, match=message):
        _inputs(tmp_path, **change)


def test_inputs_reject_either_deployment_drift(tmp_path: Path) -> None:
    plan = _plan()
    gate = _targets(plan)
    changed = {
        condition: dict(targets)
        for condition, targets in gate.targets_by_condition.items()
    }
    attempt = plan.attempts[0]
    changed[attempt.condition][attempt.database] = DeploymentTarget(
        branch_id="wrong",
        model_id=attempt.deployment_identity,
        semantic_model_sha256=attempt.semantic_model_sha256,
    )
    drift = dispatch.R2DeploymentGate.create(changed, gate.sha256_by_condition)

    with pytest.raises(dispatch.R2DispatchError, match="deployment"):
        _inputs(tmp_path, deployment_loader=lambda *_args, **_kwargs: drift)


def test_authorization_validates_receipt_without_constructing_executor(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    observed: dict[str, object] = {}

    preflight = dispatch.authorize_r2_dispatch(
        inputs,
        receipt_path=tmp_path / "approval.json",
        approval_validator=lambda workspace, path, binding, **kwargs: (
            observed.update(workspace=workspace, path=path, binding=binding)
            or _approval(binding)
        ),
    )

    assert preflight.public_summary()["pending_count"] == 4
    assert observed["binding"] == inputs.binding
    assert preflight.public_summary()["live_execution"] == "not_started"


def test_execution_consumes_before_builder_and_preserves_frozen_order(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    preflight = dispatch.authorize_r2_dispatch(
        inputs,
        receipt_path=tmp_path / "approval.json",
        approval_validator=lambda _workspace, _path, binding, **_kwargs: _approval(
            binding
        ),
    )
    events: list[str] = []

    class Executor:
        def execute(
            self, attempt: R2PlannedAttempt, target: DeploymentTarget
        ) -> R2AttemptArtifacts:
            assert target.branch_id == attempt.deployment_identity
            events.append(attempt.attempt_id)
            return write_r2_attempt_artifacts(
                tmp_path,
                plan=inputs.plan,
                attempt_id=attempt.attempt_id,
                record=_record(attempt),
            )

    report = dispatch.execute_r2_dispatch(
        preflight,
        approval_consumer=lambda *_args: (
            events.append("consumed") or tmp_path / "consumed.json"
        ),
        executor_builder=lambda _: events.append("built") or Executor(),
        finalizer=lambda *_args, **_kwargs: (
            events.append("finalized")
            or SimpleNamespace(
                manifest_path=tmp_path / "finalized.json",
                manifest_sha256=SHA[1],
            )
        ),
        monotonic=iter(range(20)).__next__,
    )

    assert events == [
        "consumed",
        "built",
        "r2attempt-1",
        "r2attempt-2",
        "r2attempt-3",
        "r2attempt-4",
        "finalized",
    ]
    assert report.completed_this_run == 4
    assert report.reconciled_count == 4
    assert report.remaining_count == 0
    assert report.finalization_manifest_sha256 == SHA[1]


def test_state_change_after_preflight_fails_before_receipt_consumption(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    preflight = dispatch.authorize_r2_dispatch(
        inputs,
        receipt_path=tmp_path / "approval.json",
        approval_validator=lambda _workspace, _path, binding, **_kwargs: _approval(
            binding
        ),
    )
    attempt = inputs.plan.attempts[0]
    destination = tmp_path / attempt.output_root
    destination.mkdir(parents=True)
    (destination / "partial.txt").write_text("drift", encoding="utf-8")
    consumed = False

    def consume(*_args: object) -> Path:
        nonlocal consumed
        consumed = True
        return tmp_path / "consumed.json"

    with pytest.raises(dispatch.R2DispatchError, match="state changed"):
        dispatch.execute_r2_dispatch(
            preflight,
            approval_consumer=consume,
            executor_builder=lambda _: pytest.fail("executor must not be built"),
        )
    assert not consumed


def test_wall_clock_stop_never_reorders_or_retries(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, policy=replace(_policy(), maximum_wall_clock_seconds=1))
    preflight = dispatch.authorize_r2_dispatch(
        inputs,
        receipt_path=tmp_path / "approval.json",
        approval_validator=lambda _workspace, _path, binding, **_kwargs: _approval(
            binding
        ),
    )
    executed: list[str] = []

    class Executor:
        def execute(
            self, attempt: R2PlannedAttempt, _target: DeploymentTarget
        ) -> R2AttemptArtifacts:
            executed.append(attempt.attempt_id)
            return write_r2_attempt_artifacts(
                tmp_path,
                plan=inputs.plan,
                attempt_id=attempt.attempt_id,
                record=_record(attempt),
            )

    ticks = iter((0.0, 0.5, 1.1, 1.2))
    report = dispatch.execute_r2_dispatch(
        preflight,
        approval_consumer=lambda *_: tmp_path / "consumed.json",
        executor_builder=lambda _: Executor(),
        monotonic=ticks.__next__,
    )

    assert executed == ["r2attempt-1"]
    assert report.remaining_count == 3
    assert report.finalization_manifest_sha256 is None


def test_executor_failure_is_terminal_for_the_invocation(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    preflight = dispatch.authorize_r2_dispatch(
        inputs,
        receipt_path=tmp_path / "approval.json",
        approval_validator=lambda _workspace, _path, binding, **_kwargs: _approval(
            binding
        ),
    )

    class Executor:
        def execute(self, attempt: R2PlannedAttempt, _target: DeploymentTarget) -> None:
            raise RuntimeError(f"secret failure {attempt.attempt_id}")

    with pytest.raises(dispatch.R2DispatchError, match="r2attempt-1") as captured:
        dispatch.execute_r2_dispatch(
            preflight,
            approval_consumer=lambda *_: tmp_path / "consumed.json",
            executor_builder=lambda _: Executor(),
        )
    assert "secret failure" not in str(captured.value)


def test_consumption_builder_and_finalizer_failures_are_sanitized(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    preflight = dispatch.authorize_r2_dispatch(
        inputs,
        receipt_path=tmp_path / "approval.json",
        approval_validator=lambda _workspace, _path, binding, **_kwargs: _approval(
            binding
        ),
    )
    with pytest.raises(dispatch.R2DispatchError, match="consumption"):
        dispatch.execute_r2_dispatch(
            preflight,
            approval_consumer=lambda *_: (_ for _ in ()).throw(
                R2ProductionApprovalError("secret")
            ),
            executor_builder=lambda _: pytest.fail("builder must not run"),
        )
    with pytest.raises(dispatch.R2DispatchError, match="construction"):
        dispatch.execute_r2_dispatch(
            preflight,
            approval_consumer=lambda *_: tmp_path / "consumed.json",
            executor_builder=lambda _: (_ for _ in ()).throw(RuntimeError("secret")),
        )

    class Executor:
        def execute(
            self, attempt: R2PlannedAttempt, _target: DeploymentTarget
        ) -> R2AttemptArtifacts:
            return write_r2_attempt_artifacts(
                tmp_path,
                plan=inputs.plan,
                attempt_id=attempt.attempt_id,
                record=_record(attempt),
            )

    with pytest.raises(dispatch.R2DispatchError, match="finalization"):
        dispatch.execute_r2_dispatch(
            preflight,
            approval_consumer=lambda *_: tmp_path / "consumed.json",
            executor_builder=lambda _: Executor(),
            finalizer=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("secret")
            ),
            monotonic=iter(range(20)).__next__,
        )


def test_committed_opportunity_loader_requires_reproduction_and_nonempty_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b'{"fixture":true}\n'
    artifact = {
        "manifest": {"artifact_sha256": SHA[0]},
        "summary": {
            "eligible_question_count": 136,
            "opportunity_question_count": 2,
        },
    }
    monkeypatch.setattr(dispatch.r2_execution, "_git_root", lambda _: tmp_path)
    monkeypatch.setattr(
        dispatch.r2_execution, "_canonical_git_commit", lambda _root, value: value
    )
    monkeypatch.setattr(
        dispatch.r2_execution, "_committed_archive", lambda *_: b"archive"
    )

    def extract(_content: bytes, destination: Path) -> None:
        paths = {
            dispatch.OPPORTUNITY_MAP_PATH: content,
            dispatch.ACCEPTED_CATALOG_PATH: b"catalog",
            dispatch.PUBLIC_MANIFEST_PATH: b"manifest",
            dispatch.DEV_A_IDS_PATH: b"ids",
            dispatch.OPPORTUNITY_SOURCE_WORKBOOK_PATH: b"source-workbook",
            dispatch.OPPORTUNITY_WORKBOOK_PATH: b"adjudicated-workbook",
            dispatch.OPPORTUNITY_INSTRUCTIONS_PATH: b"instructions",
            dispatch.OPPORTUNITY_PROSPECTIVE_PROPOSAL_PATH: b"prospective-proposal",
            dispatch.OPPORTUNITY_PROSPECTIVE_APPROVAL_PATH: b"prospective-approval",
            dispatch.OPPORTUNITY_CORRECTIVE_PROPOSAL_PATH: b"corrective-proposal",
            dispatch.OPPORTUNITY_CORRECTIVE_APPROVAL_PATH: b"corrective-approval",
            dispatch.OPPORTUNITY_PROVENANCE_PATH: b"provenance",
            dispatch.OPPORTUNITY_OUTPUT_ADOPTION_PATH: b"output-adoption",
        }
        for relative, value in paths.items():
            path = destination / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)

    monkeypatch.setattr(dispatch.r2_execution, "_extract_committed_archive", extract)
    monkeypatch.setattr(
        dispatch,
        "validate_agent_adjudicated_measure_opportunity_map",
        lambda *args: artifact,
    )

    gate = dispatch.load_committed_r2_opportunity_gate(tmp_path, _plan())

    assert gate.external_sha256 == hashlib.sha256(content).hexdigest()
    assert gate.artifact_sha256 == SHA[0]
    assert gate.opportunity_question_count == 2


def test_deployment_loader_preserves_generated_ids_and_private_name_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan()
    roots = {
        CONTROL_CONDITION: Path("experiments/deployments/control"),
        TREATMENT_CONDITION: Path("experiments/deployments/treatment"),
    }

    def verify(root: Path, run_id: str, databases: set[str], **_kwargs: object):
        condition = CONTROL_CONDITION if root.name == "control" else TREATMENT_CONDITION
        attempt = next(item for item in plan.attempts if item.condition == condition)
        assert run_id == attempt.deployment_run_id
        assert databases == {attempt.database}
        return {
            attempt.database: DeploymentTarget(
                branch_id=f"branch-id-{condition}",
                model_id=f"model-id-{condition}",
                semantic_model_sha256=attempt.semantic_model_sha256,
            )
        }

    monkeypatch.setattr(dispatch, "verify_deployment_gate", verify)
    for condition, root in roots.items():
        attempt = next(item for item in plan.attempts if item.condition == condition)
        path = tmp_path / root / f"{attempt.deployment_run_id}.{attempt.database}.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps(
                {
                    "branch_name": attempt.deployment_identity,
                    "model_name": attempt.deployment_identity,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)

    gate = dispatch.load_r2_deployment_gate(tmp_path, plan, roots)

    control = gate.targets_by_condition[CONTROL_CONDITION]["sample_large"]
    assert control.branch_id == f"branch-id-{CONTROL_CONDITION}"
    assert control.branch_name == plan.attempts[0].deployment_identity
    dispatch._validate_deployments(plan, gate)

    record = next((tmp_path / roots[CONTROL_CONDITION]).glob("*.json"))
    record.chmod(0o644)
    with pytest.raises(dispatch.R2DispatchError, match="unavailable"):
        dispatch.load_r2_deployment_gate(tmp_path, plan, roots)


def test_deployment_roots_cannot_escape_the_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dispatch,
        "verify_deployment_gate",
        lambda *_args, **_kwargs: pytest.fail("unsafe root must fail first"),
    )
    with pytest.raises(dispatch.R2DispatchError, match="root"):
        dispatch.load_r2_deployment_gate(
            tmp_path,
            _plan(),
            {
                CONTROL_CONDITION: Path("/tmp/outside"),
                TREATMENT_CONDITION: Path("experiments/deployments/treatment"),
            },
        )


def test_cleanup_and_runtime_default_loaders_use_only_public_control_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = {
        "closed_at": "2026-09-01T20:00:00Z",
        "id": dispatch.CLEANUP_BEAD_ID,
        "issue_type": "task",
        "labels": ["human"],
        "status": "closed",
    }
    calls: list[dict[str, object]] = []
    monkeypatch.setenv("OMNI_API_TOKEN", "must-not-reach-bd")
    monkeypatch.setenv("DOLTHUB_TOKEN", "must-not-reach-local-bd")

    def run(*_args: object, **kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps([issue]).encode())

    monkeypatch.setattr(dispatch.subprocess, "run", run)
    gate = dispatch.load_r2_cleanup_gate(tmp_path, dispatch.CLEANUP_BEAD_ID)
    assert gate.confirmed is True
    environment = calls[0]["env"]
    assert isinstance(environment, dict)
    assert "OMNI_API_TOKEN" not in environment
    assert "DOLTHUB_TOKEN" not in environment
    assert "PATH" in environment

    observed: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        dispatch,
        "verify_probe_system_commit",
        lambda workspace, commit: observed.append((workspace, commit)),
    )
    monkeypatch.setattr(
        dispatch,
        "git_output",
        lambda workspace, *args: observed.append((workspace, *args)) or b"tree\n",
    )
    digest = dispatch.verify_r2_runtime_sources(tmp_path, COMMIT)
    assert digest == hashlib.sha256(b"tree\n").hexdigest()
    assert observed[0] == (tmp_path, COMMIT)


def test_dispatch_freeze_v3_binds_agent_opportunity_gate_and_exact_code() -> None:
    root = Path(__file__).resolve().parents[1]
    path = (
        root
        / "experiments/r2-public-evidence-measures/r2-paired-dispatch-freeze-v3.json"
    )
    content = path.read_bytes()
    value = json.loads(content)

    assert content == canonical_catalog_bytes(value)
    assert value["kind"] == "r2-paired-dispatch-freeze"
    assert value["schema_version"] == 1
    assert value["dispatch_contract_version"] == "r2_paired_dispatch_v3"
    assert value["required_artifacts"]["opportunity_map"] == {
        "path": (
            "experiments/r2-public-evidence-measures/measure-opportunity-map-v1.json"
        ),
        "sha256": ("b834ebb7e2a033a85c0befc6eeba5949d40b71f5c3643da2ddb5f35c66afe279"),
    }
    assert value["required_artifacts"]["adjudicated_workbook"]["sha256"] == (
        "4fa3efe45034ca3115179ce4f682fb5a64d211d77429dc9680d22900fc94540a"
    )
    assert all(
        "validated.csv" not in artifact["path"]
        for artifact in value["required_artifacts"].values()
    )
    for item in value["files"]:
        file_content = (root / item["path"]).read_bytes()
        assert item == {
            "path": item["path"],
            "sha256": hashlib.sha256(file_content).hexdigest(),
            "size_bytes": len(file_content),
        }
    digest_source = copy.deepcopy(value)
    digest_source["manifest"].pop("artifact_sha256")
    assert value["manifest"] == {
        "artifact_sha256": hashlib.sha256(
            canonical_catalog_bytes(digest_source)
        ).hexdigest()
    }
    assert value["supersedes"] == {
        "internal_artifact_sha256": (
            "f7c40b54e36648ab5badef13db4fbdfedb03d08d95378427835f67ebf632c862"
        ),
        "path": (
            "experiments/r2-public-evidence-measures/r2-paired-dispatch-freeze-v2.json"
        ),
        "sha256": ("a574f66a2b1e3b1ea591bd23e873e25b9fb398483c1a9470ad028e5be069b657"),
    }
