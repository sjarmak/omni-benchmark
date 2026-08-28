"""Resumable, budget-bounded orchestration for public-only baseline attempts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from collections import Counter, deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .artifact_store import ALLOWED_RAW_ROOTS
from .autoresearch_metrics import median_iqr
from .omni_probe_preflight import OmniProbePreflightError, committed_spec
from .omni_result_adapter import reject_forbidden_keys
from .run_manifest import RunManifest, RunManifestError

BASELINE_CONDITIONS = ("C1", "C2", "C3", "C4")
_TRAIN_IDS_PATH = Path("data/manifests/train_ids.txt")
_ELIGIBLE_MANIFEST_PATH = Path("data/manifests/eligible_questions.jsonl")
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}")
_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40,64}")
_MAX_PRIVATE_FILE_BYTES = 16 * 1024 * 1024
_SCORED_FIELDS = frozenset({"accuracy", "correctness", "outcome", "scored_outcome"})


class BaselineBatchError(RuntimeError):
    """Safe failure raised before an attempt is rerun or a budget is weakened."""


@dataclass(frozen=True, slots=True)
class BaselineAttempt:
    """Public identity for one unscored question-condition invocation."""

    condition: str
    database: str
    instance_id: str
    repetition: int
    run_id: str

    def __post_init__(self) -> None:
        if self.condition not in BASELINE_CONDITIONS:
            raise BaselineBatchError("baseline condition is invalid")
        for value, name in (
            (self.database, "database"),
            (self.instance_id, "instance ID"),
            (self.run_id, "run ID"),
        ):
            if (
                not isinstance(value, str)
                or _IDENTIFIER_PATTERN.fullmatch(value) is None
            ):
                raise BaselineBatchError(f"baseline {name} is invalid")
        if type(self.repetition) is not int or self.repetition != 1:
            raise BaselineBatchError("public baseline repetition must be one")

    @property
    def attempt_id(self) -> str:
        return f"{self.run_id}:{self.instance_id}:{self.condition}:{self.repetition}"

    def canonical_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "condition": self.condition,
            "database": self.database,
            "instance_id": self.instance_id,
            "repetition": self.repetition,
            "run_id": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class BaselineSchedule:
    """Derived schedule bound to committed public manifest inputs."""

    attempts: tuple[BaselineAttempt, ...]
    eligible_manifest_sha256: str
    source_commit: str
    train_ids_sha256: str

    def __post_init__(self) -> None:
        if not self.attempts:
            raise BaselineBatchError("baseline schedule must not be empty")
        attempt_ids = tuple(attempt.attempt_id for attempt in self.attempts)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise BaselineBatchError("baseline schedule contains duplicate attempts")
        if _COMMIT_PATTERN.fullmatch(self.source_commit) is None:
            raise BaselineBatchError("baseline source commit is invalid")
        for digest in (self.eligible_manifest_sha256, self.train_ids_sha256):
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise BaselineBatchError("baseline source digest is invalid")

    @property
    def sha256(self) -> str:
        payload = {
            "attempts": [attempt.canonical_dict() for attempt in self.attempts],
            "eligible_manifest_sha256": self.eligible_manifest_sha256,
            "source_commit": self.source_commit,
            "train_ids_sha256": self.train_ids_sha256,
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class CostProjection:
    attempt_count: int
    cost_ceiling_usd: str
    method: str
    observed_attempt_cost_usd: str
    projected_cost_usd: str
    projected_over_ceiling: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "attempt_count": self.attempt_count,
            "cost_ceiling_usd": self.cost_ceiling_usd,
            "method": self.method,
            "observed_attempt_cost_usd": self.observed_attempt_cost_usd,
            "projected_cost_usd": self.projected_cost_usd,
            "projected_over_ceiling": self.projected_over_ceiling,
        }


@dataclass(frozen=True, slots=True)
class BatchBudget:
    """Hard batch ceiling with a reservation for every in-flight attempt."""

    cost_ceiling_usd: float
    attempt_cost_ceiling_usd: float

    def __post_init__(self) -> None:
        for value, name in (
            (self.cost_ceiling_usd, "cost ceiling"),
            (self.attempt_cost_ceiling_usd, "attempt cost ceiling"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise BaselineBatchError(f"batch {name} must be positive and finite")
        if self.attempt_cost_ceiling_usd > self.cost_ceiling_usd:
            raise BaselineBatchError("attempt cost ceiling exceeds batch cost ceiling")


@dataclass(frozen=True, slots=True)
class AttemptObservation:
    attempt: BaselineAttempt
    cost_usd: float | None
    database_query_count: int | None
    generation_outcome: str
    latency_ms: float
    retry_count: int | None
    terminal_failure_class: str | None
    token_count: int | None
    tool_call_count: int | None
    validation_attempt_count: int | None


@dataclass(frozen=True, slots=True)
class BatchTelemetry:
    cost_unavailable_count: int
    database_query_count: int | None
    iqr_latency_ms: float | None
    median_latency_ms: float | None
    retry_count: int | None
    token_count: int | None
    tool_call_count: int | None
    total_cost_usd: float | None
    validation_attempt_count: int | None

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "cost_unavailable_count": self.cost_unavailable_count,
            "database_query_count": self.database_query_count,
            "iqr_latency_ms": self.iqr_latency_ms,
            "median_latency_ms": self.median_latency_ms,
            "retry_count": self.retry_count,
            "token_count": self.token_count,
            "tool_call_count": self.tool_call_count,
            "total_cost_usd": self.total_cost_usd,
            "validation_attempt_count": self.validation_attempt_count,
        }


@dataclass(frozen=True, slots=True)
class BaselineBatchReport:
    budget_stop_reason: str | None
    completed_this_run: int
    failure_classes_by_condition: Mapping[str, Mapping[str, int]]
    maximum_observed_concurrency: int
    outcome_counts: Mapping[str, int]
    reconciled_before_run: int
    remaining_attempts: int
    schedule_attempts: int
    schedule_sha256: str
    status: str
    telemetry: BatchTelemetry

    def as_dict(self) -> dict[str, object]:
        return {
            "budget_stop_reason": self.budget_stop_reason,
            "completed_this_run": self.completed_this_run,
            "failure_classes_by_condition": {
                condition: dict(values)
                for condition, values in self.failure_classes_by_condition.items()
            },
            "maximum_observed_concurrency": self.maximum_observed_concurrency,
            "outcome_counts": dict(self.outcome_counts),
            "reconciled_before_run": self.reconciled_before_run,
            "remaining_attempts": self.remaining_attempts,
            "schedule_attempts": self.schedule_attempts,
            "schedule_sha256": self.schedule_sha256,
            "status": self.status,
            "telemetry": self.telemetry.as_dict(),
        }


AttemptExecutor = Callable[[BaselineAttempt, Path], None]


def load_committed_baseline_schedule(
    workspace: Path, commit: str, *, run_id: str
) -> BaselineSchedule:
    """Derive all 231 x 4 attempts from committed public-only inputs."""
    try:
        resolved = workspace.resolve(strict=True)
        train_spec = committed_spec(resolved, commit, _TRAIN_IDS_PATH)
        eligible_spec = committed_spec(resolved, commit, _ELIGIBLE_MANIFEST_PATH)
        train_ids = _parse_train_ids(train_spec.content)
        databases = _parse_public_databases(eligible_spec.content)
    except (OSError, UnicodeError, OmniProbePreflightError) as error:
        raise BaselineBatchError(
            "committed public baseline inputs are unavailable"
        ) from error
    if len(train_ids) != 231:
        raise BaselineBatchError("public baseline schedule requires 231 train IDs")
    missing = tuple(
        instance_id for instance_id in train_ids if instance_id not in databases
    )
    if missing:
        raise BaselineBatchError("train IDs are missing from the public manifest")
    selected_databases = {databases[instance_id] for instance_id in train_ids}
    if len(selected_databases) != 18:
        raise BaselineBatchError("public baseline schedule must span 18 databases")
    attempts = tuple(
        BaselineAttempt(
            condition=condition,
            database=databases[instance_id],
            instance_id=instance_id,
            repetition=1,
            run_id=run_id,
        )
        for instance_id in train_ids
        for condition in BASELINE_CONDITIONS
    )
    return BaselineSchedule(
        attempts=attempts,
        eligible_manifest_sha256=eligible_spec.sha256,
        source_commit=commit,
        train_ids_sha256=train_spec.sha256,
    )


def project_baseline_cost(
    schedule: BaselineSchedule,
    *,
    observed_attempt_cost_usd: str,
    cost_ceiling_usd: str,
) -> CostProjection:
    """Project a transparent uniform-cost scenario without invoking a provider."""
    observed = _positive_decimal(observed_attempt_cost_usd, "observed attempt cost")
    ceiling = _positive_decimal(cost_ceiling_usd, "cost ceiling")
    projected = observed * len(schedule.attempts)
    return CostProjection(
        attempt_count=len(schedule.attempts),
        cost_ceiling_usd=_money(ceiling),
        method="uniform_observed_attempt_scenario",
        observed_attempt_cost_usd=_money(observed),
        projected_cost_usd=_money(projected),
        projected_over_ceiling=projected > ceiling,
    )


class ImmutableAttemptRepository:
    """Reconcile existing one-attempt artifacts without overwriting or retrying."""

    def __init__(self, workspace: Path, output_root: Path) -> None:
        self._workspace = workspace.resolve(strict=True)
        root = Path(output_root)
        if root.is_absolute() or ".." in root.parts or not root.parts:
            raise BaselineBatchError("baseline output root must be confined")
        if not any(root.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS):
            raise BaselineBatchError("baseline output root must be a raw-run path")
        self._output_root = root
        self._validate_output_root()

    def attempt_root(self, attempt: BaselineAttempt) -> Path:
        self._validate_output_root()
        return (
            self._workspace
            / self._output_root
            / attempt.database
            / attempt.condition.lower()
            / f"{attempt.instance_id}-r{attempt.repetition}"
        )

    def _validate_output_root(self) -> None:
        candidate = self._workspace / self._output_root
        try:
            resolved = candidate.resolve(strict=False)
        except OSError as error:
            raise BaselineBatchError("baseline output root is unavailable") from error
        if resolved != candidate:
            raise BaselineBatchError("baseline output root must not contain a symlink")

    def reconcile(
        self, attempt: BaselineAttempt, *, expected_commit: str
    ) -> AttemptObservation | None:
        root = self.attempt_root(attempt)
        if not os.path.lexists(root):
            return None
        try:
            metadata = root.stat(follow_symlinks=False)
            if root.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
                raise BaselineBatchError("attempt root is not a regular directory")
            generation = _read_private_file(root / "generation.jsonl")
            manifest_bytes = _read_private_file(root / "run.json")
            record = _one_generation_record(generation)
            manifest_value = json.loads(manifest_bytes)
            manifest = RunManifest.from_dict(manifest_value, environment={})
            return _reconciled_observation(
                attempt,
                record,
                manifest,
                hashlib.sha256(generation).hexdigest(),
                expected_commit,
            )
        except (
            BaselineBatchError,
            JsonValueError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            RunManifestError,
            TypeError,
            ValueError,
        ) as error:
            raise BaselineBatchError(
                f"existing attempt is incomplete or invalid: {attempt.attempt_id}"
            ) from error


def run_baseline_batch(
    schedule: BaselineSchedule,
    *,
    repository: ImmutableAttemptRepository,
    executor: AttemptExecutor,
    maximum_concurrency: int,
    budget: BatchBudget,
) -> BaselineBatchReport:
    """Run pending attempts with one in-flight attempt per isolated database."""
    if type(maximum_concurrency) is not int or maximum_concurrency < 1:
        raise BaselineBatchError("maximum concurrency must be a positive integer")
    observations, pending = _reconcile_schedule(schedule, repository)
    reconciled_count = len(observations)
    spent = _observed_cost(observations, budget)
    queues = _database_queues(pending)
    active_databases: set[str] = set()
    futures: dict[Future[None], BaselineAttempt] = {}
    completed_this_run = 0
    maximum_observed = 0
    stopped = False

    with ThreadPoolExecutor(max_workers=maximum_concurrency) as pool:
        while _remaining(queues) or futures:
            while len(futures) < maximum_concurrency:
                attempt = _next_attempt(queues, active_databases)
                if attempt is None:
                    break
                reserved = len(futures) * budget.attempt_cost_ceiling_usd
                if (
                    spent + reserved + budget.attempt_cost_ceiling_usd
                    > budget.cost_ceiling_usd
                ):
                    break
                queues[attempt.database].popleft()
                future = pool.submit(
                    executor, attempt, repository.attempt_root(attempt)
                )
                futures[future] = attempt
                active_databases.add(attempt.database)
                maximum_observed = max(maximum_observed, len(futures))
            if not futures:
                stopped = _remaining(queues) > 0
                break
            done, _ = wait(tuple(futures), return_when=FIRST_COMPLETED)
            for future in sorted(done, key=lambda item: futures[item].attempt_id):
                attempt = futures.pop(future)
                active_databases.remove(attempt.database)
                try:
                    future.result()
                except Exception as error:
                    raise BaselineBatchError(
                        f"attempt executor failed: {attempt.attempt_id}"
                    ) from error
                observation = repository.reconcile(
                    attempt, expected_commit=schedule.source_commit
                )
                if observation is None:
                    raise BaselineBatchError(
                        "attempt executor produced no immutable artifact"
                    )
                cost = _hard_budget_cost(observation, budget)
                spent += cost
                observations.append(observation)
                completed_this_run += 1

    remaining = _remaining(queues)
    return _batch_report(
        schedule,
        observations=tuple(observations),
        reconciled_count=reconciled_count,
        completed_this_run=completed_this_run,
        maximum_observed=maximum_observed,
        remaining=remaining,
        stopped=stopped,
    )


def _parse_train_ids(content: bytes) -> tuple[str, ...]:
    values = tuple(line.strip() for line in content.decode("utf-8").splitlines())
    if any(_IDENTIFIER_PATTERN.fullmatch(value) is None for value in values):
        raise BaselineBatchError("train IDs contain an invalid identifier")
    if len(set(values)) != len(values):
        raise BaselineBatchError("train IDs contain duplicates")
    return values


def _parse_public_databases(content: bytes) -> dict[str, str]:
    records: dict[str, str] = {}
    for line in content.decode("utf-8").splitlines():
        value = json.loads(line)
        if not isinstance(value, dict) or value.get("category") != "Query":
            raise BaselineBatchError("eligible manifest contains a non-Query row")
        instance_id = value.get("instance_id")
        database = value.get("selected_database")
        if not isinstance(instance_id, str) or not isinstance(database, str):
            raise BaselineBatchError("eligible manifest identity is invalid")
        if instance_id in records:
            raise BaselineBatchError("eligible manifest contains duplicate IDs")
        records[instance_id] = database
    return records


def _read_private_file(path: Path) -> bytes:
    metadata = path.stat(follow_symlinks=False)
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_nlink != 1
        or metadata.st_uid != os.getuid()
        or metadata.st_size <= 0
        or metadata.st_size > _MAX_PRIVATE_FILE_BYTES
    ):
        raise BaselineBatchError("attempt artifact is not a private regular file")
    content = path.read_bytes()
    if len(content) != metadata.st_size:
        raise BaselineBatchError("attempt artifact changed during reconciliation")
    return content


def _one_generation_record(content: bytes) -> dict[str, Any]:
    lines = content.decode("utf-8").splitlines()
    if len(lines) != 1:
        raise BaselineBatchError("attempt generation must contain exactly one record")
    value = json.loads(lines[0], parse_constant=_reject_json_constant)
    if not isinstance(value, dict):
        raise BaselineBatchError("attempt generation record must be an object")
    reject_forbidden_keys(value)
    if _SCORED_FIELDS.intersection(value):
        raise BaselineBatchError("public baseline attempt must remain unscored")
    return value


def _reconciled_observation(
    attempt: BaselineAttempt,
    record: Mapping[str, Any],
    manifest: RunManifest,
    generation_sha256: str,
    expected_commit: str,
) -> AttemptObservation:
    expected_identity = {
        "attempt_id": attempt.attempt_id,
        "condition": attempt.condition,
        "instance_id": attempt.instance_id,
        "partition": "train",
        "repetition": attempt.repetition,
        "run_id": attempt.run_id,
    }
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise BaselineBatchError("attempt generation identity does not match schedule")
    if (
        manifest.generation_sha256 != generation_sha256
        or manifest.git_commit != expected_commit
        or manifest.condition != attempt.condition
        or manifest.scope != "train"
        or manifest.repetition != attempt.repetition
    ):
        raise BaselineBatchError(
            "attempt manifest does not bind the scheduled generation"
        )
    outcome = record.get("generation_outcome")
    failure = record.get("terminal_failure_class")
    if outcome not in {"answered", "refused", "errored"}:
        raise BaselineBatchError("attempt generation outcome is invalid")
    if (outcome == "answered") != (failure is None):
        raise BaselineBatchError("attempt outcome and failure class are inconsistent")
    if failure is not None and (not isinstance(failure, str) or not failure):
        raise BaselineBatchError("attempt failure class is invalid")
    return AttemptObservation(
        attempt=attempt,
        cost_usd=_optional_number(record.get("cost_usd"), "cost_usd"),
        database_query_count=_optional_count(
            record.get("database_query_count"), "database_query_count"
        ),
        generation_outcome=outcome,
        latency_ms=_required_number(record.get("latency_ms"), "latency_ms"),
        retry_count=_optional_count(record.get("retry_count"), "retry_count"),
        terminal_failure_class=failure,
        token_count=_token_count(record.get("token_usage")),
        tool_call_count=_optional_count(
            record.get("tool_call_count"), "tool_call_count"
        ),
        validation_attempt_count=_optional_count(
            record.get("validation_attempt_count"), "validation_attempt_count"
        ),
    )


def _reconcile_schedule(
    schedule: BaselineSchedule, repository: ImmutableAttemptRepository
) -> tuple[list[AttemptObservation], tuple[BaselineAttempt, ...]]:
    observations: list[AttemptObservation] = []
    pending: list[BaselineAttempt] = []
    for attempt in schedule.attempts:
        observation = repository.reconcile(
            attempt, expected_commit=schedule.source_commit
        )
        if observation is None:
            pending.append(attempt)
        else:
            if observation.attempt.attempt_id != attempt.attempt_id:
                raise BaselineBatchError("reconciled attempt identity changed")
            observations.append(observation)
    return observations, tuple(pending)


def _database_queues(
    pending: Sequence[BaselineAttempt],
) -> dict[str, deque[BaselineAttempt]]:
    queues: dict[str, deque[BaselineAttempt]] = {}
    for attempt in pending:
        queues.setdefault(attempt.database, deque()).append(attempt)
    return queues


def _next_attempt(
    queues: Mapping[str, deque[BaselineAttempt]], active: set[str]
) -> BaselineAttempt | None:
    for database, queue in queues.items():
        if queue and database not in active:
            return queue[0]
    return None


def _remaining(queues: Mapping[str, deque[BaselineAttempt]]) -> int:
    return sum(len(queue) for queue in queues.values())


def _observed_cost(
    observations: Sequence[AttemptObservation], budget: BatchBudget
) -> float:
    return sum(_hard_budget_cost(observation, budget) for observation in observations)


def _hard_budget_cost(observation: AttemptObservation, budget: BatchBudget) -> float:
    cost = observation.cost_usd
    if cost is None:
        raise BaselineBatchError("hard budget requires observable attempt cost")
    if cost > budget.attempt_cost_ceiling_usd:
        raise BaselineBatchError("attempt cost exceeded the hard budget reservation")
    return cost


def _batch_report(
    schedule: BaselineSchedule,
    *,
    observations: tuple[AttemptObservation, ...],
    reconciled_count: int,
    completed_this_run: int,
    maximum_observed: int,
    remaining: int,
    stopped: bool,
) -> BaselineBatchReport:
    outcomes = Counter(value.generation_outcome for value in observations)
    failures: dict[str, Counter[str]] = {
        condition: Counter() for condition in BASELINE_CONDITIONS
    }
    for value in observations:
        if value.terminal_failure_class is not None:
            failures[value.attempt.condition][value.terminal_failure_class] += 1
    return BaselineBatchReport(
        budget_stop_reason=(
            "next_attempt_reservation_exceeds_ceiling" if stopped else None
        ),
        completed_this_run=completed_this_run,
        failure_classes_by_condition={
            condition: dict(sorted(counter.items()))
            for condition, counter in failures.items()
        },
        maximum_observed_concurrency=maximum_observed,
        outcome_counts=dict(sorted(outcomes.items())),
        reconciled_before_run=reconciled_count,
        remaining_attempts=remaining,
        schedule_attempts=len(schedule.attempts),
        schedule_sha256=schedule.sha256,
        status="budget_stopped" if stopped else "complete",
        telemetry=_aggregate_telemetry(observations),
    )


def _aggregate_telemetry(
    observations: Sequence[AttemptObservation],
) -> BatchTelemetry:
    latencies = [value.latency_ms for value in observations]
    median_latency, iqr_latency = (
        (None, None) if not latencies else median_iqr(latencies)
    )
    costs = [value.cost_usd for value in observations]
    return BatchTelemetry(
        cost_unavailable_count=sum(value is None for value in costs),
        database_query_count=_optional_sum(
            [value.database_query_count for value in observations]
        ),
        iqr_latency_ms=iqr_latency,
        median_latency_ms=median_latency,
        retry_count=_optional_sum([value.retry_count for value in observations]),
        token_count=_optional_sum([value.token_count for value in observations]),
        tool_call_count=_optional_sum(
            [value.tool_call_count for value in observations]
        ),
        total_cost_usd=_optional_sum(costs),
        validation_attempt_count=_optional_sum(
            [value.validation_attempt_count for value in observations]
        ),
    )


def _optional_sum(values: Sequence[int | float | None]) -> int | float | None:
    if any(value is None for value in values):
        return None
    return sum(value for value in values if value is not None)


def _optional_count(value: object, name: str) -> int | None:
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise JsonValueError(f"{name} must be a non-negative integer or null")
    return value


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _required_number(value, name)


def _required_number(value: object, name: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise JsonValueError(f"{name} must be a non-negative finite number")
    return float(value)


def _token_count(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "input_tokens",
        "output_tokens",
        "total_tokens",
    }:
        raise JsonValueError("token_usage is invalid")
    counts = {name: _optional_count(count, name) for name, count in value.items()}
    if any(count is None for count in counts.values()):
        raise JsonValueError("token_usage counts must be observable integers")
    if counts["input_tokens"] + counts["output_tokens"] != counts["total_tokens"]:
        raise JsonValueError("token_usage total is inconsistent")
    return counts["total_tokens"]


def _positive_decimal(value: str, name: str) -> Decimal:
    try:
        parsed = Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise BaselineBatchError(f"{name} must be a positive decimal") from error
    if not parsed.is_finite() or parsed <= 0:
        raise BaselineBatchError(f"{name} must be a positive decimal")
    return parsed


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _reject_json_constant(value: str) -> None:
    raise JsonValueError(f"non-finite JSON constant is forbidden: {value}")


class JsonValueError(ValueError):
    """Internal invalid telemetry value."""
