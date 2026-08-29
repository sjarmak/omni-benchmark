"""Build a Freeze-B-bound sealed plan without executing benchmark attempts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .content_policy import ContentPolicy
from .freeze_b import (
    CONDITIONS,
    EXPECTED_TEST_OUTPUTS,
    REPETITIONS,
    FreezeBManifest,
    schedule_sha256,
)
from .freeze_b_control import FreezeBControlError, load_freeze_b_control
from .freeze_b_record import (
    MAX_RUNTIME_SOURCE_BYTES,
    FreezeBRecordError,
    _committed_input,
    _relative_path,
    _runtime_source_bytes,
)
from .freeze_b_schedule import (
    MAX_TEST_IDS_BYTES,
    TEST_IDS_PATH,
    FreezeBScheduleError,
    expected_schedule_bytes,
)
from .protected_fields import ProtectedFieldError, reject_protected_fields

MAX_SCHEDULE_BYTES = 4 * 1024 * 1024
MAX_PUBLIC_MANIFEST_BYTES = 64 * 1024 * 1024
PUBLIC_RECORD_FIELDS = frozenset(
    {
        "category",
        "clean_up_sqls",
        "conditions",
        "high_level",
        "instance_id",
        "normal_query",
        "preprocess_sql",
        "query",
        "selected_database",
        "source_index",
    }
)
PLAN_SOURCE_PATH = "src/omni_benchmark/sealed_execution_plan.py"
PUBLIC_MANIFEST_PATH = "data/manifests/eligible_questions.jsonl"

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")
_SCHEDULE_FIELDS = frozenset({"attempt_id", "condition", "instance_id", "repetition"})


class SealedExecutionPlanError(RuntimeError):
    """Raised when committed public inputs cannot form the exact sealed plan."""


@dataclass(frozen=True)
class SealedPlannedAttempt:
    """Identity-only dispatch metadata for one future sealed attempt."""

    attempt_id: str
    cohort_id: str
    condition: str
    database: str
    instance_id: str
    repetition: int
    question_sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "cohort_id": self.cohort_id,
            "condition": self.condition,
            "database": self.database,
            "instance_id": self.instance_id,
            "question_sha256": self.question_sha256,
            "repetition": self.repetition,
        }


@dataclass(frozen=True)
class SealedExecutionPlan:
    """Immutable in-memory plan derived exclusively from frozen public inputs."""

    attempts: tuple[SealedPlannedAttempt, ...]
    control_commit: str
    system_commit: str
    freeze_b_sha256: str
    schedule_sha256: str
    schedule_file_sha256: str
    test_ids_sha256: str
    public_manifest_sha256: str

    @property
    def sha256(self) -> str:
        value = {
            "attempts": [attempt.as_dict() for attempt in self.attempts],
            "bindings": {
                "control_commit": self.control_commit,
                "freeze_b_sha256": self.freeze_b_sha256,
                "public_manifest_sha256": self.public_manifest_sha256,
                "schedule_file_sha256": self.schedule_file_sha256,
                "schedule_sha256": self.schedule_sha256,
                "system_commit": self.system_commit,
                "test_ids_sha256": self.test_ids_sha256,
            },
            "kind": "sealed-execution-plan",
            "schema_version": 1,
        }
        return hashlib.sha256(_canonical_bytes(value)).hexdigest()

    def public_summary(self) -> dict[str, object]:
        return {
            "attempt_count": len(self.attempts),
            "cohort_counts": dict(
                sorted(Counter(item.cohort_id for item in self.attempts).items())
            ),
            "condition_counts": dict(
                sorted(Counter(item.condition for item in self.attempts).items())
            ),
            "control_commit": self.control_commit,
            "database_count": len({item.database for item in self.attempts}),
            "freeze_b_sha256": self.freeze_b_sha256,
            "plan_sha256": self.sha256,
            "repetition_counts": {
                str(key): value
                for key, value in sorted(
                    Counter(item.repetition for item in self.attempts).items()
                )
            },
            "schedule_sha256": self.schedule_sha256,
            "system_commit": self.system_commit,
        }


def load_sealed_execution_plan(
    workspace: Path,
    *,
    control_commit: str,
    system_commit: str,
    freeze_b_path: Path,
    schedule_path: Path,
    public_manifest_path: Path,
) -> SealedExecutionPlan:
    """Validate and materialize the no-execution plan from frozen Git objects."""
    try:
        control = load_freeze_b_control(
            workspace,
            control_commit=control_commit,
            system_commit=system_commit,
            manifest_path=freeze_b_path,
        )
        schedule_relative = _relative_path(schedule_path, "schedule path")
        public_relative = _relative_path(public_manifest_path, "public manifest path")
        committed_schedule = _committed_input(
            workspace,
            control.system_commit,
            schedule_relative,
            maximum_bytes=MAX_SCHEDULE_BYTES,
        )
        committed_ids = _committed_input(
            workspace,
            control.system_commit,
            TEST_IDS_PATH,
            maximum_bytes=MAX_TEST_IDS_BYTES,
        )
        committed_public = _committed_input(
            workspace,
            control.system_commit,
            public_relative,
            maximum_bytes=MAX_PUBLIC_MANIFEST_BYTES,
        )
        _verify_plan_runtime_source(workspace, control.system_commit)
    except (FreezeBControlError, FreezeBRecordError) as error:
        raise SealedExecutionPlanError(str(error)) from error

    frozen = dict(control.manifest.frozen_files)
    for path, committed in (
        (schedule_relative, committed_schedule),
        (TEST_IDS_PATH, committed_ids),
        (public_relative, committed_public),
    ):
        if frozen.get(path) != committed.sha256:
            raise SealedExecutionPlanError(
                "required committed input does not match its frozen file digest"
            )

    try:
        registered_schedule = expected_schedule_bytes(
            committed_ids.content, control.manifest.schedule_seed
        )
    except FreezeBScheduleError as error:
        raise SealedExecutionPlanError(str(error)) from error
    if committed_schedule.content != registered_schedule:
        raise SealedExecutionPlanError(
            "committed schedule does not match the registered schedule"
        )

    schedule_records = _schedule_records(committed_schedule.content)
    attempt_ids = tuple(record["attempt_id"] for record in schedule_records)
    if schedule_sha256(attempt_ids) != control.manifest.schedule_sha256:
        raise SealedExecutionPlanError(
            "registered schedule does not match the Freeze B schedule digest"
        )
    public_records = _public_records(committed_public.content)
    scheduled_ids = {record["instance_id"] for record in schedule_records}
    missing = scheduled_ids.difference(public_records)
    if missing:
        raise SealedExecutionPlanError(
            "a scheduled identity is absent from the frozen public manifest"
        )

    attempts = tuple(
        _planned_attempt(record, public_records[record["instance_id"]])
        for record in schedule_records
    )
    _validate_plan_shape(attempts, scheduled_ids)
    return SealedExecutionPlan(
        attempts=attempts,
        control_commit=control.control_commit,
        system_commit=control.system_commit,
        freeze_b_sha256=control.freeze_b_sha256,
        schedule_sha256=control.manifest.schedule_sha256,
        schedule_file_sha256=committed_schedule.sha256,
        test_ids_sha256=committed_ids.sha256,
        public_manifest_sha256=committed_public.sha256,
    )


def load_sealed_public_questions(
    workspace: Path,
    *,
    plan: SealedExecutionPlan,
    freeze_b: FreezeBManifest,
    public_manifest_path: Path,
) -> dict[str, str]:
    """Load exact public test questions from S after plan/Freeze-B binding."""
    if type(plan) is not SealedExecutionPlan or type(freeze_b) is not FreezeBManifest:
        raise SealedExecutionPlanError(
            "validated sealed plan and Freeze B are required"
        )
    if (
        plan.freeze_b_sha256 != freeze_b.sha256()
        or plan.system_commit != freeze_b.system_commit
    ):
        raise SealedExecutionPlanError("sealed plan does not match Freeze B")
    try:
        relative = _relative_path(public_manifest_path, "public manifest path")
        committed = _committed_input(
            workspace,
            plan.system_commit,
            relative,
            maximum_bytes=MAX_PUBLIC_MANIFEST_BYTES,
        )
    except FreezeBRecordError as error:
        raise SealedExecutionPlanError(str(error)) from error
    if (
        relative != PUBLIC_MANIFEST_PATH
        or committed.sha256 != plan.public_manifest_sha256
        or dict(freeze_b.frozen_files).get(relative) != committed.sha256
    ):
        raise SealedExecutionPlanError(
            "public questions do not match the frozen sealed plan"
        )
    records = _public_records(committed.content)
    planned = {item.instance_id: item for item in plan.attempts}
    if set(records) != set(planned) or any(
        records[instance_id][:2] != (item.database, item.question_sha256)
        for instance_id, item in planned.items()
    ):
        raise SealedExecutionPlanError(
            "public questions do not match the frozen sealed plan"
        )
    return {instance_id: record[2] for instance_id, record in records.items()}


def _verify_plan_runtime_source(workspace: Path, system_commit: str) -> None:
    committed = _committed_input(
        workspace,
        system_commit,
        PLAN_SOURCE_PATH,
        maximum_bytes=MAX_RUNTIME_SOURCE_BYTES,
    )
    loaded = hashlib.sha256(_runtime_source_bytes(Path(__file__))).hexdigest()
    if loaded != committed.sha256:
        raise SealedExecutionPlanError(
            "sealed plan runtime source does not match the frozen system"
        )


def _schedule_records(content: bytes) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    for raw_line in content.splitlines(keepends=True):
        if not raw_line.endswith(b"\n") or raw_line == b"\n":
            raise SealedExecutionPlanError("committed schedule is not canonical JSONL")
        try:
            value = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SealedExecutionPlanError(
                "committed schedule is not canonical JSONL"
            ) from error
        if not isinstance(value, Mapping) or set(value) != _SCHEDULE_FIELDS:
            raise SealedExecutionPlanError("committed schedule has an invalid schema")
        record = dict(value)
        if _canonical_bytes(record) != raw_line:
            raise SealedExecutionPlanError("committed schedule is not canonical JSONL")
        attempt_id = _safe_identifier(record["attempt_id"], "attempt identity")
        instance_id = _safe_identifier(record["instance_id"], "instance identity")
        condition = record["condition"]
        repetition = record["repetition"]
        if condition not in CONDITIONS or type(repetition) is not int:
            raise SealedExecutionPlanError("committed schedule has invalid coordinates")
        if repetition not in range(1, REPETITIONS + 1):
            raise SealedExecutionPlanError("committed schedule has invalid coordinates")
        expected_attempt = f"sealed:{instance_id}:{condition}:{repetition}"
        if attempt_id != expected_attempt:
            raise SealedExecutionPlanError(
                "committed schedule attempt identity is invalid"
            )
        records.append(
            {
                "attempt_id": attempt_id,
                "condition": condition,
                "instance_id": instance_id,
                "repetition": repetition,
            }
        )
    return tuple(records)


def _public_records(content: bytes) -> dict[str, tuple[str, str, str]]:
    records: dict[str, tuple[str, str, str]] = {}
    for raw_line in content.splitlines(keepends=True):
        if not raw_line.endswith(b"\n") or raw_line == b"\n":
            raise SealedExecutionPlanError(
                "frozen public manifest must use canonical JSONL"
            )
        try:
            value = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SealedExecutionPlanError(
                "frozen public manifest must use canonical JSONL"
            ) from error
        try:
            reject_protected_fields(value)
        except ProtectedFieldError as error:
            raise SealedExecutionPlanError(str(error)) from error
        if not isinstance(value, Mapping) or set(value) != PUBLIC_RECORD_FIELDS:
            raise SealedExecutionPlanError("frozen public manifest schema is invalid")
        record = dict(value)
        if _canonical_bytes(record) != raw_line:
            raise SealedExecutionPlanError(
                "frozen public manifest must use canonical JSONL"
            )
        instance_id = _safe_identifier(record["instance_id"], "instance identity")
        if instance_id in records:
            raise SealedExecutionPlanError(
                "frozen public manifest contains a duplicate identity"
            )
        database = _safe_identifier(record["selected_database"], "database")
        question = record["query"]
        policy = ContentPolicy.from_environment(os.environ)
        if (
            not isinstance(question, str)
            or not question
            or not policy.query_is_safe(question)
        ):
            raise SealedExecutionPlanError("frozen public question is invalid")
        records[instance_id] = (
            database,
            hashlib.sha256(question.encode()).hexdigest(),
            question,
        )
    return records


def _planned_attempt(
    schedule_record: Mapping[str, Any], public_record: tuple[str, str, str]
) -> SealedPlannedAttempt:
    condition = str(schedule_record["condition"])
    repetition = int(schedule_record["repetition"])
    return SealedPlannedAttempt(
        attempt_id=str(schedule_record["attempt_id"]),
        cohort_id=f"sealed-{condition.lower()}-r{repetition}",
        condition=condition,
        database=public_record[0],
        instance_id=str(schedule_record["instance_id"]),
        repetition=repetition,
        question_sha256=public_record[1],
    )


def _validate_plan_shape(
    attempts: tuple[SealedPlannedAttempt, ...], scheduled_ids: set[str]
) -> None:
    if len(attempts) != EXPECTED_TEST_OUTPUTS or len(scheduled_ids) != 101:
        raise SealedExecutionPlanError("sealed execution plan is incomplete")
    coordinates = {
        (attempt.instance_id, attempt.condition, attempt.repetition)
        for attempt in attempts
    }
    if len(coordinates) != EXPECTED_TEST_OUTPUTS:
        raise SealedExecutionPlanError(
            "sealed execution plan has duplicate coordinates"
        )
    expected_cohorts = {
        f"sealed-{condition.lower()}-r{repetition}"
        for condition in CONDITIONS
        for repetition in range(1, REPETITIONS + 1)
    }
    cohort_counts = Counter(attempt.cohort_id for attempt in attempts)
    if set(cohort_counts) != expected_cohorts or set(cohort_counts.values()) != {101}:
        raise SealedExecutionPlanError("sealed execution plan cohorts are incomplete")


def _safe_identifier(value: object, description: str) -> str:
    policy = ContentPolicy.from_environment(os.environ)
    if (
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value) is None
        or not policy.identifier_is_safe(value)
    ):
        raise SealedExecutionPlanError(f"{description} is invalid")
    return value


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate the Freeze-B-bound sealed plan without execution"
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--control-commit", required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--freeze-b", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--public-manifest", type=Path, required=True)
    return parser


def plan_main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    result = load_sealed_execution_plan(
        arguments.workspace,
        control_commit=arguments.control_commit,
        system_commit=arguments.system_commit,
        freeze_b_path=arguments.freeze_b,
        schedule_path=arguments.schedule,
        public_manifest_path=arguments.public_manifest,
    )
    print(json.dumps(result.public_summary(), sort_keys=True))
    return 0
