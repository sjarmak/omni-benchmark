"""Receipt-gated sealed generation orchestration without scoring."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections import deque
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

from .artifact_store import ALLOWED_RAW_ROOTS
from .freeze_b import (
    CONDITIONS,
    EXPECTED_TEST_OUTPUTS,
    FreezeBCondition,
    FreezeBManifest,
)
from .freeze_b_record import (
    MAX_RUNTIME_SOURCE_BYTES,
    FreezeBRecordError,
    _committed_input,
    _relative_path,
    _runtime_source_bytes,
)
from .sealed_cohort_finalization import (
    SealedCohortResult,
    finalize_sealed_cohort,
)
from .sealed_execution_plan import SealedExecutionPlan
from .sealed_generation_staging import (
    SealedAttemptRepository,
    SealedGenerationStagingError,
    SealedPreparedAttempt,
    SealedStagedAttempt,
    _parse_timestamp,
    _validated_freeze,
    _validated_plan,
    prepare_sealed_attempt,
)
from .sealed_production_approval import (
    DecisionLoader,
    SealedProductionApproval,
    SealedProductionApprovalError,
    consume_sealed_production_approval,
    validate_sealed_production_approval,
)

_AUTHORITY_KEY = secrets.token_bytes(32)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_MONEY = Decimal("0.000001")

SEALED_RUNTIME_SOURCE_PATHS = (
    "sealed_tools/dispatch_sealed_generation.py",
    "src/omni_benchmark/sealed_cohort_finalization.py",
    "src/omni_benchmark/sealed_dispatch.py",
    "src/omni_benchmark/sealed_dispatch_cli.py",
    "src/omni_benchmark/sealed_direct_adapter.py",
    "src/omni_benchmark/sealed_direct_factory.py",
    "src/omni_benchmark/sealed_execution_plan.py",
    "src/omni_benchmark/sealed_generation_staging.py",
    "src/omni_benchmark/sealed_omni_adapter.py",
    "src/omni_benchmark/sealed_production_approval.py",
    "src/omni_benchmark/sealed_runtime_inputs.py",
)

RuntimeSourceVerifier = Callable[[Path, str], str]
AdapterFactory = Callable[[FreezeBCondition], "SealedConditionAdapter"]


class SealedDispatchError(RuntimeError):
    """Raised when a sealed dispatch cannot proceed without violating its gate."""


class SealedConditionAdapter(Protocol):
    """A condition-specific evaluated-system adapter constructed after approval."""

    condition_binding: FreezeBCondition

    def execute(self, prepared: SealedPreparedAttempt) -> "SealedAdapterResult": ...


@dataclass(frozen=True, slots=True)
class SealedAdapterResult:
    """One unscored evaluated-system generation returned by an adapter."""

    generation_record: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class SealedDispatchPolicy:
    """Immutable concurrency, wall-clock, cost, and version declaration."""

    maximum_concurrency: int
    maximum_wall_clock_seconds: int
    cost_ceiling_usd: str
    reservation_usd_by_condition: tuple[tuple[str, str], ...]
    software_versions: tuple[tuple[str, str], ...]
    cli_versions_by_condition: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]

    @classmethod
    def from_dict(cls, value: object) -> SealedDispatchPolicy:
        fields = {
            "cli_versions_by_condition",
            "cost_ceiling_usd",
            "maximum_concurrency",
            "maximum_wall_clock_seconds",
            "reservation_usd_by_condition",
            "software_versions",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise SealedDispatchError("sealed dispatch policy schema is invalid")
        reservations = value["reservation_usd_by_condition"]
        software = value["software_versions"]
        cli = value["cli_versions_by_condition"]
        if (
            not isinstance(reservations, Mapping)
            or not isinstance(software, Mapping)
            or not isinstance(cli, Mapping)
            or any(not isinstance(item, Mapping) for item in cli.values())
        ):
            raise SealedDispatchError("sealed dispatch policy schema is invalid")
        try:
            return cls.create(
                maximum_concurrency=value["maximum_concurrency"],
                maximum_wall_clock_seconds=value["maximum_wall_clock_seconds"],
                cost_ceiling_usd=value["cost_ceiling_usd"],
                reservation_usd_by_condition=dict(reservations),
                software_versions=dict(software),
                cli_versions_by_condition={
                    str(condition): dict(versions)
                    for condition, versions in cli.items()
                },
            )
        except (TypeError, ValueError) as error:
            raise SealedDispatchError(
                "sealed dispatch policy schema is invalid"
            ) from error

    @classmethod
    def create(
        cls,
        *,
        maximum_concurrency: int,
        maximum_wall_clock_seconds: int,
        cost_ceiling_usd: str,
        reservation_usd_by_condition: Mapping[str, str],
        software_versions: Mapping[str, str],
        cli_versions_by_condition: Mapping[str, Mapping[str, str]],
    ) -> SealedDispatchPolicy:
        value = cls(
            maximum_concurrency=maximum_concurrency,
            maximum_wall_clock_seconds=maximum_wall_clock_seconds,
            cost_ceiling_usd=cost_ceiling_usd,
            reservation_usd_by_condition=tuple(
                sorted(reservation_usd_by_condition.items())
            ),
            software_versions=tuple(sorted(software_versions.items())),
            cli_versions_by_condition=tuple(
                (condition, tuple(sorted(versions.items())))
                for condition, versions in sorted(cli_versions_by_condition.items())
            ),
        )
        return _validated_policy(value)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(_canonical_bytes(self.as_dict())).hexdigest()

    def as_dict(self) -> dict[str, object]:
        return {
            "cli_versions_by_condition": {
                condition: dict(versions)
                for condition, versions in self.cli_versions_by_condition
            },
            "cost_ceiling_usd": self.cost_ceiling_usd,
            "maximum_concurrency": self.maximum_concurrency,
            "maximum_wall_clock_seconds": self.maximum_wall_clock_seconds,
            "reservation_usd_by_condition": dict(self.reservation_usd_by_condition),
            "software_versions": dict(self.software_versions),
        }

    def reservation(self, condition: str) -> Decimal:
        try:
            return Decimal(dict(self.reservation_usd_by_condition)[condition])
        except (InvalidOperation, KeyError) as error:
            raise SealedDispatchError("sealed dispatch policy is invalid") from error

    def cli_versions(self, condition: str) -> dict[str, str]:
        try:
            return dict(dict(self.cli_versions_by_condition)[condition])
        except KeyError as error:
            raise SealedDispatchError("sealed dispatch policy is invalid") from error


@dataclass(frozen=True, slots=True)
class SealedDispatchPreflight:
    """Opaque read-only preflight authority for one exact dispatch state."""

    workspace: Path
    output_root: Path
    run_id: str
    plan: SealedExecutionPlan
    freeze_b: FreezeBManifest
    policy: SealedDispatchPolicy
    questions: tuple[tuple[str, str], ...] = field(repr=False)
    prepared: tuple[SealedPreparedAttempt, ...] = field(repr=False)
    observed: tuple[tuple[str, str], ...]
    approval: SealedProductionApproval = field(repr=False)
    runtime_sources_sha256: str
    _authorization: str = field(repr=False)

    def public_summary(self) -> dict[str, object]:
        reconciled = len(self.observed)
        return {
            "attempt_count": len(self.prepared),
            "control_commit": self.plan.control_commit,
            "freeze_b_sha256": self.freeze_b.sha256(),
            "live_execution": "not_started",
            "output_root": self.output_root.as_posix(),
            "pending_count": len(self.prepared) - reconciled,
            "plan_sha256": self.plan.sha256,
            "policy_sha256": self.policy.sha256,
            "reconciled_count": reconciled,
            "run_id": self.run_id,
            "runtime_sources_sha256": self.runtime_sources_sha256,
            "schedule_sha256": self.plan.schedule_sha256,
            "system_commit": self.plan.system_commit,
        }


@dataclass(frozen=True, slots=True)
class SealedDispatchReport:
    """Public hashes and counts for one no-score dispatch invocation."""

    attempt_count: int
    completed_this_run: int
    reconciled_count: int
    remaining_count: int
    maximum_observed_concurrency: int
    reserved_cost_usd: str
    cohorts: tuple[SealedCohortResult, ...]

    @property
    def cohort_manifest_paths(self) -> tuple[Path, ...]:
        return tuple(result.run_manifest_path for result in self.cohorts)

    def public_summary(self) -> dict[str, object]:
        return {
            "attempt_count": self.attempt_count,
            "cohort_count": len(self.cohorts),
            "completed_this_run": self.completed_this_run,
            "maximum_observed_concurrency": self.maximum_observed_concurrency,
            "reconciled_count": self.reconciled_count,
            "remaining_count": self.remaining_count,
            "reserved_cost_usd": self.reserved_cost_usd,
        }


def verify_sealed_runtime_sources(workspace: Path, system_commit: str) -> str:
    """Bind every loaded sealed-dispatch source byte to the frozen system commit."""
    root = _workspace_root(workspace)
    local_root = Path(__file__).resolve().parents[2]
    records = []
    try:
        for source_path in SEALED_RUNTIME_SOURCE_PATHS:
            committed = _committed_input(
                root,
                system_commit,
                source_path,
                maximum_bytes=MAX_RUNTIME_SOURCE_BYTES,
            )
            loaded_path = local_root / source_path
            loaded_sha256 = hashlib.sha256(
                _runtime_source_bytes(loaded_path)
            ).hexdigest()
            if loaded_sha256 != committed.sha256:
                raise SealedDispatchError(
                    "loaded sealed runtime source does not match the frozen system"
                )
            records.append({"path": source_path, "sha256": committed.sha256})
    except FreezeBRecordError as error:
        raise SealedDispatchError(
            "sealed runtime source verification failed"
        ) from error
    return hashlib.sha256(_canonical_bytes(records)).hexdigest()


def load_sealed_dispatch_policy(
    workspace: Path,
    *,
    system_commit: str,
    policy_path: Path,
    freeze_b: FreezeBManifest,
) -> SealedDispatchPolicy:
    """Load the canonical policy only from its frozen Git object at system S."""
    root = _workspace_root(workspace)
    try:
        relative = _relative_path(policy_path, "sealed dispatch policy path")
        committed = _committed_input(
            root,
            system_commit,
            relative,
            maximum_bytes=64 * 1024,
        )
        validated_freeze = _validated_freeze(freeze_b)
    except (FreezeBRecordError, SealedGenerationStagingError) as error:
        raise SealedDispatchError(
            "sealed dispatch policy could not be loaded"
        ) from error
    if (
        validated_freeze.system_commit != system_commit
        or dict(validated_freeze.frozen_files).get(relative) != committed.sha256
    ):
        raise SealedDispatchError("sealed dispatch policy is not frozen")
    try:
        value = json.loads(
            committed.content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SealedDispatchError("sealed dispatch policy is invalid JSON") from error
    policy = SealedDispatchPolicy.from_dict(value)
    if committed.content != _canonical_bytes(policy.as_dict()):
        raise SealedDispatchError("sealed dispatch policy is not canonical")
    return policy


def build_sealed_dispatch_binding(
    *,
    plan: SealedExecutionPlan,
    freeze_b: FreezeBManifest,
    policy: SealedDispatchPolicy,
    output_root: Path,
    run_id: str,
    runtime_sources_sha256: str,
) -> dict[str, object]:
    """Build the exact public binding a human production receipt must approve."""
    try:
        validated_plan = _validated_plan(plan)
        validated_freeze = _validated_freeze(freeze_b)
    except SealedGenerationStagingError as error:
        raise SealedDispatchError("sealed dispatch inputs are invalid") from error
    validated_policy = _validated_policy(policy)
    root = _validated_output_root(output_root)
    if (
        validated_plan.freeze_b_sha256 != validated_freeze.sha256()
        or validated_plan.system_commit != validated_freeze.system_commit
        or not isinstance(run_id, str)
        or _IDENTIFIER.fullmatch(run_id) is None
        or _SHA256.fullmatch(runtime_sources_sha256) is None
    ):
        raise SealedDispatchError("sealed dispatch binding is invalid")
    return {
        "attempt_count": EXPECTED_TEST_OUTPUTS,
        "conditions": list(CONDITIONS),
        "control_commit": validated_plan.control_commit,
        "cost_ceiling_usd": validated_policy.cost_ceiling_usd,
        "freeze_b_sha256": validated_freeze.sha256(),
        "maximum_concurrency": validated_policy.maximum_concurrency,
        "maximum_wall_clock_seconds": (validated_policy.maximum_wall_clock_seconds),
        "output_root": root.as_posix(),
        "plan_sha256": validated_plan.sha256,
        "policy_sha256": validated_policy.sha256,
        "run_id": run_id,
        "runtime_sources_sha256": runtime_sources_sha256,
        "schedule_sha256": validated_plan.schedule_sha256,
        "system_commit": validated_plan.system_commit,
    }


def preflight_sealed_dispatch(
    *,
    workspace: Path,
    output_root: Path,
    run_id: str,
    plan: SealedExecutionPlan,
    freeze_b: FreezeBManifest,
    questions: Mapping[str, str],
    policy: SealedDispatchPolicy,
    receipt_path: Path,
    now: datetime | None = None,
    decision_loader: DecisionLoader | None = None,
    runtime_source_verifier: RuntimeSourceVerifier = verify_sealed_runtime_sources,
) -> SealedDispatchPreflight:
    """Read and reconcile all inputs without writing or constructing adapters."""
    root = _workspace_root(workspace)
    validated_policy = _validated_policy(policy)
    base = _validated_output_root(output_root)
    try:
        validated_plan = _validated_plan(plan)
        validated_freeze = _validated_freeze(freeze_b)
    except SealedGenerationStagingError as error:
        raise SealedDispatchError("sealed dispatch inputs are invalid") from error
    try:
        runtime_sha256 = runtime_source_verifier(root, validated_plan.system_commit)
    except SealedDispatchError:
        raise
    except Exception as error:
        raise SealedDispatchError(
            "sealed runtime source verification failed"
        ) from error
    if _SHA256.fullmatch(runtime_sha256) is None:
        raise SealedDispatchError("sealed runtime source verification failed")
    binding = build_sealed_dispatch_binding(
        plan=validated_plan,
        freeze_b=validated_freeze,
        policy=validated_policy,
        output_root=base,
        run_id=run_id,
        runtime_sources_sha256=runtime_sha256,
    )
    question_map = _validated_questions(questions, validated_plan)
    repository = SealedAttemptRepository(root, base / "attempts")
    prepared: list[SealedPreparedAttempt] = []
    observed: list[tuple[str, str]] = []
    try:
        for planned in validated_plan.attempts:
            item = prepare_sealed_attempt(
                plan=validated_plan,
                freeze_b=validated_freeze,
                attempt_id=planned.attempt_id,
                question=question_map[planned.instance_id],
            )
            prepared.append(item)
            staged = repository.reconcile(item)
            if staged is not None:
                observed.append((item.attempt_id, staged.envelope_sha256))
    except SealedGenerationStagingError as error:
        raise SealedDispatchError(
            "sealed staged-attempt reconciliation failed"
        ) from error
    try:
        approval = validate_sealed_production_approval(
            root,
            receipt_path,
            binding,
            now=now,
            decision_loader=decision_loader,
        )
    except SealedProductionApprovalError as error:
        raise SealedDispatchError(
            "sealed production approval or runtime source binding is invalid"
        ) from error
    preflight = SealedDispatchPreflight(
        workspace=root,
        output_root=base,
        run_id=run_id,
        plan=validated_plan,
        freeze_b=validated_freeze,
        policy=validated_policy,
        questions=tuple(sorted(question_map.items())),
        prepared=tuple(prepared),
        observed=tuple(observed),
        approval=approval,
        runtime_sources_sha256=runtime_sha256,
        _authorization="",
    )
    object.__setattr__(preflight, "_authorization", _preflight_authorization(preflight))
    return preflight


def execute_sealed_dispatch(
    preflight: SealedDispatchPreflight,
    *,
    adapter_factories: Mapping[str, AdapterFactory],
    monotonic: Callable[[], float] = time.monotonic,
) -> SealedDispatchReport:
    """Consume approval, construct exact adapters, and stage unscored generations."""
    value = _validated_preflight(preflight)
    repository = SealedAttemptRepository(
        value.workspace, value.output_root / "attempts"
    )
    current = _reconcile_prepared(repository, value.prepared)
    if current != value.observed:
        raise SealedDispatchError("sealed staged state changed after preflight")
    pending = tuple(
        prepared
        for prepared in value.prepared
        if prepared.attempt_id not in dict(current)
    )
    required = sum(
        (value.policy.reservation(item.condition) for item in pending), Decimal(0)
    )
    ceiling = Decimal(value.policy.cost_ceiling_usd)
    if required > ceiling:
        raise SealedDispatchError("sealed pending attempts exceed the cost ceiling")
    try:
        consume_sealed_production_approval(
            value.workspace,
            value.output_root / "approvals",
            value.approval,
        )
    except SealedProductionApprovalError as error:
        raise SealedDispatchError(
            "sealed production approval consumption failed"
        ) from error
    adapters = _construct_adapters(value.freeze_b, adapter_factories)
    completed, maximum_observed, stopped = _run_pending(
        pending,
        repository=repository,
        adapters=adapters,
        maximum_concurrency=value.policy.maximum_concurrency,
        maximum_wall_clock_seconds=value.policy.maximum_wall_clock_seconds,
        monotonic=monotonic,
    )
    reconciled = _reconcile_prepared(repository, value.prepared)
    remaining = EXPECTED_TEST_OUTPUTS - len(reconciled)
    cohorts: tuple[SealedCohortResult, ...] = ()
    if remaining == 0:
        cohorts = _finalize_all(value, repository)
    elif not stopped:
        raise SealedDispatchError("sealed dispatch ended with missing attempts")
    return SealedDispatchReport(
        attempt_count=len(reconciled),
        completed_this_run=completed,
        reconciled_count=len(current),
        remaining_count=remaining,
        maximum_observed_concurrency=maximum_observed,
        reserved_cost_usd=_money(required),
        cohorts=cohorts,
    )


def _run_pending(
    pending: tuple[SealedPreparedAttempt, ...],
    *,
    repository: SealedAttemptRepository,
    adapters: Mapping[str, SealedConditionAdapter],
    maximum_concurrency: int,
    maximum_wall_clock_seconds: int,
    monotonic: Callable[[], float],
) -> tuple[int, int, bool]:
    queues: dict[str, deque[SealedPreparedAttempt]] = {}
    for prepared in pending:
        queues.setdefault(prepared.database, deque()).append(prepared)
    active_databases: set[str] = set()
    futures: dict[Future[SealedStagedAttempt], SealedPreparedAttempt] = {}
    completed = 0
    maximum_observed = 0
    deadline = monotonic() + maximum_wall_clock_seconds
    stopped = False

    def worker(prepared: SealedPreparedAttempt) -> SealedStagedAttempt:
        try:
            result = adapters[prepared.condition].execute(prepared)
        except Exception as error:
            raise SealedDispatchError(
                f"sealed adapter infrastructure failure: {prepared.attempt_id}"
            ) from error
        if type(result) is not SealedAdapterResult:
            raise SealedDispatchError("sealed adapter returned an invalid result")
        try:
            return repository.stage(prepared, result.generation_record)
        except SealedGenerationStagingError as error:
            raise SealedDispatchError(
                f"sealed adapter result could not be staged: {prepared.attempt_id}"
            ) from error

    with ThreadPoolExecutor(max_workers=maximum_concurrency) as pool:
        while any(queues.values()) or futures:
            while len(futures) < maximum_concurrency and monotonic() < deadline:
                selected = next(
                    (
                        database
                        for database, queue in queues.items()
                        if queue and database not in active_databases
                    ),
                    None,
                )
                if selected is None:
                    break
                prepared = queues[selected].popleft()
                future = pool.submit(worker, prepared)
                futures[future] = prepared
                active_databases.add(selected)
                maximum_observed = max(maximum_observed, len(futures))
            if not futures:
                stopped = any(queues.values())
                break
            done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda item: futures[item].attempt_id):
                prepared = futures.pop(future)
                active_databases.remove(prepared.database)
                try:
                    future.result()
                except SealedDispatchError:
                    for outstanding in futures:
                        outstanding.cancel()
                    raise
                completed += 1
    return completed, maximum_observed, stopped


def _construct_adapters(
    freeze_b: FreezeBManifest, factories: Mapping[str, AdapterFactory]
) -> dict[str, SealedConditionAdapter]:
    if set(factories) != set(CONDITIONS) or any(
        not callable(factory) for factory in factories.values()
    ):
        raise SealedDispatchError("sealed adapter factory set is invalid")
    adapters: dict[str, SealedConditionAdapter] = {}
    for condition in CONDITIONS:
        frozen = freeze_b.condition(condition)
        try:
            adapter = factories[condition](frozen)
        except Exception as error:
            raise SealedDispatchError("sealed adapter construction failed") from error
        if getattr(adapter, "condition_binding", None) != frozen or not callable(
            getattr(adapter, "execute", None)
        ):
            raise SealedDispatchError("sealed adapter identity does not match Freeze B")
        adapters[condition] = adapter
    return adapters


def _finalize_all(
    preflight: SealedDispatchPreflight, repository: SealedAttemptRepository
) -> tuple[SealedCohortResult, ...]:
    questions = dict(preflight.questions)
    results = []
    for condition in CONDITIONS:
        for repetition in (1, 2, 3):
            cohort = tuple(
                item
                for item in preflight.prepared
                if (item.condition, item.repetition) == (condition, repetition)
            )
            staged = tuple(repository.reconcile(item) for item in cohort)
            if any(item is None for item in staged):
                raise SealedDispatchError("sealed cohort is incomplete")
            records = tuple(
                json.loads(item.generation_record_bytes)  # type: ignore[union-attr]
                for item in staged
            )
            started_at = min(
                (str(record["started_at"]) for record in records), key=_parse_timestamp
            )
            finished_at = max(
                (str(record["finished_at"]) for record in records),
                key=_parse_timestamp,
            )
            try:
                result = finalize_sealed_cohort(
                    workspace=preflight.workspace,
                    output_root=preflight.output_root / "cohorts",
                    plan=preflight.plan,
                    freeze_b=preflight.freeze_b,
                    attempt_repository=repository,
                    condition=condition,
                    repetition=repetition,
                    questions={
                        item.instance_id: questions[item.instance_id] for item in cohort
                    },
                    software_versions=dict(preflight.policy.software_versions),
                    cli_versions=preflight.policy.cli_versions(condition),
                    started_at=started_at,
                    finished_at=finished_at,
                )
            except Exception as error:
                raise SealedDispatchError(
                    "sealed cohort finalization failed"
                ) from error
            results.append(result)
    return tuple(results)


def _validated_policy(value: object) -> SealedDispatchPolicy:
    if type(value) is not SealedDispatchPolicy:
        raise SealedDispatchError("sealed dispatch policy is invalid")
    if (
        type(value.maximum_concurrency) is not int
        or value.maximum_concurrency < 1
        or type(value.maximum_wall_clock_seconds) is not int
        or value.maximum_wall_clock_seconds < 1
        or tuple(condition for condition, _ in value.reservation_usd_by_condition)
        != tuple(CONDITIONS)
        or tuple(condition for condition, _ in value.cli_versions_by_condition)
        != tuple(CONDITIONS)
        or not value.software_versions
    ):
        raise SealedDispatchError("sealed dispatch policy is invalid")
    cost = _decimal_money(value.cost_ceiling_usd)
    if cost <= 0:
        raise SealedDispatchError("sealed dispatch policy is invalid")
    for _, reservation in value.reservation_usd_by_condition:
        if _decimal_money(reservation) <= 0:
            raise SealedDispatchError("sealed dispatch policy is invalid")
    version_groups = [value.software_versions]
    version_groups.extend(versions for _, versions in value.cli_versions_by_condition)
    if any(
        not versions
        or any(
            not isinstance(key, str)
            or not key
            or not isinstance(version, str)
            or not version
            for key, version in versions
        )
        for versions in version_groups
    ):
        raise SealedDispatchError("sealed dispatch policy is invalid")
    return value


def _validated_questions(value: object, plan: SealedExecutionPlan) -> dict[str, str]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not isinstance(question, str) or not question
        for key, question in value.items()
    ):
        raise SealedDispatchError("sealed public question map is invalid")
    result = dict(value)
    expected = {item.instance_id for item in plan.attempts}
    if set(result) != expected or len(expected) != 101:
        raise SealedDispatchError("sealed public question map is invalid")
    return result


def _validated_output_root(value: Path) -> Path:
    root = Path(value)
    if (
        root.is_absolute()
        or not root.parts
        or ".." in root.parts
        or not any(root.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS)
    ):
        raise SealedDispatchError("sealed dispatch output root is invalid")
    return root


def _validated_preflight(value: object) -> SealedDispatchPreflight:
    if type(value) is not SealedDispatchPreflight or not hmac.compare_digest(
        value._authorization, _preflight_authorization(value)
    ):
        raise SealedDispatchError("sealed dispatch preflight authority is invalid")
    return value


def _preflight_authorization(value: SealedDispatchPreflight) -> str:
    payload = {
        "approval": {
            "binding": dict(value.approval.binding),
            "decision_bead_id": value.approval.decision_bead_id,
            "nonce": value.approval.nonce,
            "receipt_sha256": value.approval.receipt_sha256,
        },
        "observed": list(value.observed),
        "output_root": value.output_root.as_posix(),
        "prepared": [item.binding_dict() for item in value.prepared],
        "plan_sha256": value.plan.sha256,
        "policy_sha256": value.policy.sha256,
        "questions": [
            {
                "instance_id": instance_id,
                "question_sha256": hashlib.sha256(question.encode()).hexdigest(),
            }
            for instance_id, question in value.questions
        ],
        "run_id": value.run_id,
        "runtime_sources_sha256": value.runtime_sources_sha256,
    }
    return hmac.new(
        _AUTHORITY_KEY, _canonical_bytes(payload), hashlib.sha256
    ).hexdigest()


def _reconcile_prepared(
    repository: SealedAttemptRepository,
    prepared: tuple[SealedPreparedAttempt, ...],
) -> tuple[tuple[str, str], ...]:
    observed = []
    try:
        for item in prepared:
            staged = repository.reconcile(item)
            if staged is not None:
                observed.append((item.attempt_id, staged.envelope_sha256))
    except SealedGenerationStagingError as error:
        raise SealedDispatchError(
            "sealed staged-attempt reconciliation failed"
        ) from error
    return tuple(observed)


def _workspace_root(workspace: Path) -> Path:
    absolute = workspace.absolute()
    try:
        resolved = workspace.resolve(strict=True)
    except OSError as error:
        raise SealedDispatchError("sealed dispatch workspace is unavailable") from error
    if absolute != resolved or workspace.is_symlink() or not resolved.is_dir():
        raise SealedDispatchError("sealed dispatch workspace is unsafe")
    return resolved


def _decimal_money(value: object) -> Decimal:
    try:
        parsed = Decimal(value)
        normalized = str(parsed.quantize(_MONEY))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise SealedDispatchError("sealed dispatch money value is invalid") from error
    if not parsed.is_finite() or normalized != value:
        raise SealedDispatchError("sealed dispatch money value is invalid")
    return parsed


def _money(value: Decimal) -> str:
    return str(value.quantize(_MONEY))


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SealedDispatchError("sealed dispatch policy has duplicate keys")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise SealedDispatchError(f"sealed dispatch policy forbids {value}")
