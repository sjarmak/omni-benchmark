"""Dry-run planning and gated subprocess dispatch for the public baseline."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import secrets
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .baseline_batch import (
    BASELINE_CONDITIONS,
    BaselineAttempt,
    BaselineBatchError,
    BaselineSchedule,
    _money,
    _positive_decimal,
)
from .content_policy import ContentPolicy

_PG_FIELDS = frozenset(
    {"PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD", "PGPORT", "PGSSLMODE"}
)
_IDENTIFIER_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)
_DIRECT_CONCURRENCY_CANARY = (
    ("archeology_scan_3", "archeology_scan_large"),
    ("cross_border_1", "cross_border_large"),
    ("fake_account_1", "fake_account_large"),
    ("solar_panel_1", "solar_panel_large"),
)


@dataclass(frozen=True, slots=True)
class PlannedAttempt:
    attempt_id: str
    command: tuple[str, ...]
    condition: str
    database: str
    entrypoint: str
    output_root: str

    def public_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "command": list(self.command),
            "condition": self.condition,
            "database": self.database,
            "entrypoint": self.entrypoint,
            "output_root": self.output_root,
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    attempts: tuple[PlannedAttempt, ...]
    claude_config_directories: tuple[Path, ...]
    schedule_sha256: str

    @property
    def claude_oauth_slot_sha256(self) -> tuple[str, ...]:
        """Expose non-secret slot identities without publishing profile paths."""
        return tuple(
            hashlib.sha256(str(path).encode()).hexdigest()
            for path in self.claude_config_directories
        )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            _canonical_json(
                {
                    "attempts": [attempt.public_dict() for attempt in self.attempts],
                    "claude_oauth_slot_sha256": self.claude_oauth_slot_sha256,
                    "schedule_sha256": self.schedule_sha256,
                }
            )
        ).hexdigest()

    def public_dict(self) -> dict[str, object]:
        return {
            "attempt_count": len(self.attempts),
            "attempts": [attempt.public_dict() for attempt in self.attempts],
            "claude_oauth_slot_sha256": list(self.claude_oauth_slot_sha256),
            "claude_oauth_slot_count": len(self.claude_config_directories),
            "plan_sha256": self.sha256,
            "schedule_sha256": self.schedule_sha256,
        }


@dataclass(frozen=True, slots=True)
class DeploymentTarget:
    branch_id: str
    model_id: str


@dataclass(frozen=True, slots=True)
class ConditionCostScenario:
    """Condition-specific projection with an explicit range for unobserved rungs."""

    full_cost_high_scenario_usd: str
    full_cost_low_scenario_usd: str
    method: str
    observed_condition_cost_usd: Mapping[str, str]
    observed_condition_subtotal_usd: str
    unobserved_conditions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "full_cost_high_scenario_usd": self.full_cost_high_scenario_usd,
            "full_cost_low_scenario_usd": self.full_cost_low_scenario_usd,
            "method": self.method,
            "observed_condition_cost_usd": dict(self.observed_condition_cost_usd),
            "observed_condition_subtotal_usd": self.observed_condition_subtotal_usd,
            "unobserved_conditions": list(self.unobserved_conditions),
        }


@dataclass(frozen=True, slots=True)
class SubprocessOutcome:
    """Bounded child-process evidence retained long enough for safe diagnosis."""

    returncode: int | None
    stdout: bytes
    stderr: bytes
    failure_kind: str | None = None


SubprocessRunner = Callable[[tuple[str, ...], dict[str, str], float], SubprocessOutcome]


def direct_concurrency_canary_schedule(
    schedule: BaselineSchedule,
) -> BaselineSchedule:
    """Return only the four prespecified public canaries across C1-C3."""
    indexed = {
        (attempt.instance_id, attempt.condition): attempt
        for attempt in schedule.attempts
    }
    if len(indexed) != len(schedule.attempts):
        raise BaselineBatchError("baseline schedule contains duplicate canary keys")
    try:
        attempts = tuple(
            indexed[(instance_id, condition)]
            for instance_id, _ in _DIRECT_CONCURRENCY_CANARY
            for condition in ("C1", "C2", "C3")
        )
    except KeyError as error:
        raise BaselineBatchError(
            "direct concurrency canary is absent from the train schedule"
        ) from error
    expected_databases = {
        instance_id: database for instance_id, database in _DIRECT_CONCURRENCY_CANARY
    }
    if any(
        attempt.database != expected_databases[attempt.instance_id]
        for attempt in attempts
    ):
        raise BaselineBatchError("direct concurrency canary database is invalid")
    return BaselineSchedule(
        attempts=attempts,
        eligible_manifest_sha256=schedule.eligible_manifest_sha256,
        source_commit=schedule.source_commit,
        train_ids_sha256=schedule.train_ids_sha256,
    )


def project_condition_cost_scenario(
    schedule: BaselineSchedule,
    *,
    observed_condition_cost_usd: Mapping[str, str],
) -> ConditionCostScenario:
    """Project successful-canary costs without pretending unobserved C4 is known."""
    if not observed_condition_cost_usd:
        raise BaselineBatchError("condition cost scenario requires observations")
    if set(observed_condition_cost_usd) - set(BASELINE_CONDITIONS):
        raise BaselineBatchError(
            "condition cost scenario contains an unknown condition"
        )
    observed = {
        condition: _positive_decimal(value, f"{condition} observed attempt cost")
        for condition, value in observed_condition_cost_usd.items()
    }
    counts = Counter(attempt.condition for attempt in schedule.attempts)
    subtotal = sum(
        (observed[condition] * counts[condition] for condition in observed),
        start=Decimal(0),
    )
    unobserved = tuple(
        condition
        for condition in BASELINE_CONDITIONS
        if counts[condition] and condition not in observed
    )
    unobserved_attempts = sum(counts[condition] for condition in unobserved)
    low = subtotal + min(observed.values()) * unobserved_attempts
    high = subtotal + max(observed.values()) * unobserved_attempts
    return ConditionCostScenario(
        full_cost_high_scenario_usd=_money(high),
        full_cost_low_scenario_usd=_money(low),
        method="condition_specific_successful_canary_scenario",
        observed_condition_cost_usd={
            condition: _money(value) for condition, value in sorted(observed.items())
        },
        observed_condition_subtotal_usd=_money(subtotal),
        unobserved_conditions=unobserved,
    )


def build_execution_plan(
    schedule: BaselineSchedule,
    *,
    workspace: Path,
    output_root: Path,
    claude_config_directories: tuple[Path, ...],
    freeze_a_commit: str,
) -> ExecutionPlan:
    """Build the exact public command plan without authentication or execution."""
    if not claude_config_directories:
        raise BaselineBatchError("at least one Claude OAuth slot is required")
    resolved_slots = tuple(
        Path(path).expanduser().resolve(strict=False)
        for path in claude_config_directories
    )
    if len(set(resolved_slots)) != len(resolved_slots):
        raise BaselineBatchError("Claude OAuth slots must be distinct")
    attempts = tuple(
        _planned_attempt(
            attempt,
            workspace=workspace,
            output_root=output_root,
            freeze_a_commit=freeze_a_commit,
            system_commit=schedule.source_commit,
        )
        for attempt in schedule.attempts
    )
    return ExecutionPlan(
        attempts=attempts,
        claude_config_directories=resolved_slots,
        schedule_sha256=schedule.sha256,
    )


class DatabaseEnvironmentDirectory:
    """Load one external private PostgreSQL environment without persisting it."""

    def __init__(self, workspace: Path, root: Path) -> None:
        self._workspace = workspace.resolve(strict=True)
        supplied_root = Path(root)
        metadata = supplied_root.stat(follow_symlinks=False)
        self._root = supplied_root.resolve(strict=True)
        if (
            self._root.is_relative_to(self._workspace)
            or supplied_root.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700
            or metadata.st_uid != os.getuid()
        ):
            raise BaselineBatchError(
                "database environment directory must be external and private"
            )

    def __repr__(self) -> str:
        return "DatabaseEnvironmentDirectory(<external-private-directory>)"

    def for_database(self, database: str) -> dict[str, str]:
        _identifier(database, "database")
        path = self._root / f"{database}.json"
        value = _read_private_json(path)
        if not isinstance(value, dict) or set(value) != _PG_FIELDS:
            raise BaselineBatchError("database environment must use the exact schema")
        if any(not isinstance(item, str) or not item for item in value.values()):
            raise BaselineBatchError("database environment values must be non-empty")
        return dict(value)


class LiveBaselineDispatcher:
    """Dispatch planned attempts while leasing isolated Claude OAuth profiles."""

    def __init__(
        self,
        plan: ExecutionPlan,
        *,
        database_environments: DatabaseEnvironmentDirectory | None,
        common_environment: Mapping[str, str],
        runner: SubprocessRunner | None = None,
        timeout_seconds: float,
        deployment_targets: Mapping[str, DeploymentTarget] | None = None,
    ) -> None:
        self._planned = {attempt.attempt_id: attempt for attempt in plan.attempts}
        self._database_environments = database_environments
        self._common_environment = dict(common_environment)
        self._runner = _run_subprocess if runner is None else runner
        self._timeout_seconds = timeout_seconds
        self._deployment_targets = (
            None if deployment_targets is None else dict(deployment_targets)
        )
        self._claude_slots: queue.Queue[Path] = queue.Queue()
        for path in plan.claude_config_directories:
            self._claude_slots.put(path)

    def __call__(self, attempt: BaselineAttempt, root: Path) -> None:
        try:
            planned = self._planned[attempt.attempt_id]
        except KeyError as error:
            raise BaselineBatchError(
                "attempt is absent from the execution plan"
            ) from error
        workspace = Path(planned.command[planned.command.index("--workspace") + 1])
        relative_root = Path(
            planned.command[planned.command.index("--output-root") + 1]
        )
        expected_root = workspace / relative_root
        if root != expected_root:
            raise BaselineBatchError(
                "scheduler output root differs from execution plan"
            )
        if attempt.condition == "C4":
            self._dispatch_c4(attempt, planned, root)
            return
        self._dispatch_direct(attempt, planned, root)

    def _dispatch_direct(
        self, attempt: BaselineAttempt, planned: PlannedAttempt, root: Path
    ) -> None:
        if self._database_environments is None:
            raise BaselineBatchError("direct dispatch requires database environments")
        profile = self._claude_slots.get()
        try:
            environment = {
                **self._common_environment,
                **self._database_environments.for_database(attempt.database),
            }
            command = (*planned.command, "--claude-config-dir", str(profile))
            self._run_staged(attempt, root, command, environment)
        finally:
            self._claude_slots.put(profile)

    def _dispatch_c4(
        self, attempt: BaselineAttempt, planned: PlannedAttempt, root: Path
    ) -> None:
        if self._deployment_targets is None:
            raise BaselineBatchError("C4 dispatch requires a verified deployment gate")
        try:
            target = self._deployment_targets[attempt.database]
        except KeyError as error:
            raise BaselineBatchError(
                "C4 database is absent from the deployment gate"
            ) from error
        environment = {
            **self._common_environment,
            "OMNI_BRANCH_ID": target.branch_id,
            "OMNI_MODEL_ID": target.model_id,
        }
        self._run_staged(attempt, root, planned.command, environment)

    def _run_staged(
        self,
        attempt: BaselineAttempt,
        root: Path,
        command: tuple[str, ...],
        environment: dict[str, str],
    ) -> None:
        workspace = Path(command[command.index("--workspace") + 1])
        _ensure_private_directory(workspace, root.parent)
        stage = root.parent / f".staging-{root.name}-{secrets.token_hex(8)}"
        relative_stage = stage.relative_to(workspace).as_posix()
        output_index = command.index("--output-root") + 1
        staged_command = (
            *command[:output_index],
            relative_stage,
            *command[output_index + 1 :],
        )
        outcome = self._runner(staged_command, environment, self._timeout_seconds)
        if type(outcome) is not SubprocessOutcome:
            raise BaselineBatchError("single-attempt subprocess result is invalid")
        if outcome.returncode != 0 or outcome.failure_kind is not None:
            diagnostic = _preserve_child_failure(
                workspace, stage, attempt, outcome, environment
            )
            raise BaselineBatchError(
                f"single-attempt subprocess failed; diagnostic={diagnostic}"
            )
        _publish_staged_attempt(stage, root)


def verify_deployment_gate(
    root: Path, run_id: str, expected_databases: set[str]
) -> dict[str, DeploymentTarget]:
    """Require a complete immutable 18-database readback gate before execution."""
    _identifier(run_id, "deployment run ID")
    claim = _read_private_json(Path(root) / f"{run_id}.claim")
    if not isinstance(claim, dict):
        raise BaselineBatchError("deployment claim is invalid")
    source_commit = claim.get("source_commit")
    if (
        claim.get("kind") != "public-omni-semantic-deployment-claim"
        or claim.get("schema_version") != 1
        or claim.get("run_id") != run_id
        or set(claim.get("databases", ())) != expected_databases
        or not isinstance(source_commit, str)
    ):
        raise BaselineBatchError(
            "deployment claim does not bind exact database coverage"
        )
    record_paths = tuple(sorted(Path(root).glob(f"{run_id}.*.json")))
    if len(record_paths) != len(expected_databases):
        raise BaselineBatchError(
            "deployment records do not have exact database coverage"
        )
    targets: dict[str, DeploymentTarget] = {}
    for path in record_paths:
        record = _read_private_json(path)
        if not isinstance(record, dict):
            raise BaselineBatchError("deployment record is invalid")
        database = record.get("database")
        branch_id = record.get("branch_id")
        model_id = record.get("model_id")
        if (
            record.get("kind") != "public-omni-semantic-deployment"
            or record.get("schema_version") != 1
            or record.get("run_id") != run_id
            or record.get("source_commit") != source_commit
            or record.get("status") != "verified"
            or record.get("validation_issue_count") != 0
            or record.get("readback_verified") is not True
            or database not in expected_databases
            or database in targets
            or not isinstance(branch_id, str)
            or not isinstance(model_id, str)
        ):
            raise BaselineBatchError("deployment record is not verified")
        targets[database] = DeploymentTarget(branch_id=branch_id, model_id=model_id)
    if set(targets) != expected_databases:
        raise BaselineBatchError(
            "deployment records do not have exact database coverage"
        )
    return targets


def _planned_attempt(
    attempt: BaselineAttempt,
    *,
    workspace: Path,
    output_root: Path,
    freeze_a_commit: str,
    system_commit: str,
) -> PlannedAttempt:
    relative_root = (
        output_root
        / attempt.database
        / attempt.condition.lower()
        / f"{attempt.instance_id}-r{attempt.repetition}"
    )
    if attempt.condition == "C4":
        entrypoint = "scripts/baseline_omni_attempt.py"
        condition_arguments = (
            "--config",
            "config/autoresearch.json",
            "--freeze-a-commit",
            freeze_a_commit,
            "--harness-config",
            "config/conditions/c4-production-v1.json",
            "--prompt-spec",
            "config/prompts/c4-user-prompt-v1.txt",
            "--instructions-spec",
            "config/instructions/c4-managed-instructions-v1.json",
            "--budget-id",
            "omni-production-baseline-v1",
        )
    else:
        entrypoint = "scripts/baseline_direct_attempt.py"
        condition_arguments = ("--condition", attempt.condition)
    command = (
        sys.executable,
        str(workspace / entrypoint),
        "--workspace",
        str(workspace),
        "--system-commit",
        system_commit,
    )
    command = (
        *command,
        "--instance-id",
        attempt.instance_id,
        *condition_arguments,
        "--output-root",
        relative_root.as_posix(),
        "--run-id",
        attempt.run_id,
        "--repetition",
        str(attempt.repetition),
        "--execute-authenticated-smoke",
    )
    return PlannedAttempt(
        attempt_id=attempt.attempt_id,
        command=command,
        condition=attempt.condition,
        database=attempt.database,
        entrypoint=entrypoint,
        output_root=relative_root.as_posix(),
    )


def _read_private_json(path: Path) -> object:
    try:
        metadata = path.stat(follow_symlinks=False)
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise OSError("not private")
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BaselineBatchError("private execution input is unavailable") from error


def _run_subprocess(
    command: tuple[str, ...], environment: dict[str, str], timeout_seconds: float
) -> SubprocessOutcome:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            check=False,
            env=environment,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as error:
        return SubprocessOutcome(
            returncode=None,
            stdout=_as_bytes(error.stdout),
            stderr=_as_bytes(error.stderr),
            failure_kind="timeout",
        )
    except OSError:
        return SubprocessOutcome(
            returncode=None,
            stdout=b"",
            stderr=b"",
            failure_kind="infrastructure",
        )
    return SubprocessOutcome(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _ensure_private_directory(workspace: Path, path: Path) -> None:
    try:
        relative = path.relative_to(workspace)
        current = workspace
        for part in relative.parts:
            current = current / part
            current.mkdir(mode=0o700, exist_ok=True)
            metadata = current.stat(follow_symlinks=False)
            if (
                current.is_symlink()
                or not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
            ):
                raise OSError("unsafe directory")
            os.chmod(current, 0o700)
    except (OSError, ValueError) as error:
        raise BaselineBatchError("attempt staging directory is unavailable") from error


def _preserve_child_failure(
    workspace: Path,
    stage: Path,
    attempt: BaselineAttempt,
    outcome: SubprocessOutcome,
    environment: Mapping[str, str],
) -> str:
    policy = ContentPolicy.from_environment(environment)
    detail = policy.safe_detail(
        "\n".join(
            item.decode("utf-8", errors="replace")
            for item in (outcome.stdout, outcome.stderr)
            if item
        )
    )
    try:
        stage.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError:
        metadata = stage.stat(follow_symlinks=False)
        if stage.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise BaselineBatchError("failed-attempt staging root is invalid") from None
    failure_root = stage.with_name(stage.name.replace(".staging-", ".failed-", 1))
    payload = _canonical_json(
        {
            "attempt_id": attempt.attempt_id,
            "detail": detail,
            "failure_kind": outcome.failure_kind or "child_exit",
            "kind": "public-baseline-child-failure",
            "returncode": outcome.returncode,
            "stderr_sha256": hashlib.sha256(outcome.stderr).hexdigest(),
            "stdout_sha256": hashlib.sha256(outcome.stdout).hexdigest(),
        }
    )
    descriptor = os.open(
        stage / "failure.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    os.rename(stage, failure_root)
    return failure_root.relative_to(workspace).as_posix()


def _publish_staged_attempt(stage: Path, root: Path) -> None:
    try:
        metadata = stage.stat(follow_symlinks=False)
        if (
            stage.is_symlink()
            or not stat.S_ISDIR(metadata.st_mode)
            or os.path.lexists(root)
        ):
            raise OSError("invalid staged attempt")
        os.rename(stage, root)
    except OSError as error:
        raise BaselineBatchError("staged attempt could not be published") from error


def _as_bytes(value: bytes | str | None) -> bytes:
    if value is None:
        return b""
    if isinstance(value, bytes):
        return value
    return value.encode()


def _identifier(value: str, description: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 160
        or any(character not in _IDENTIFIER_CHARS for character in value)
    ):
        raise BaselineBatchError(f"{description} is invalid")
    return value


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
