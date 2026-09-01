"""Frozen offline execution and arm-finalization contract for R2 measures."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import re
import subprocess
import tarfile
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .artifact_store import ALLOWED_RAW_ROOTS
from .hkb_io import HKBFileSafetyError, read_regular_file
from .measure_catalog_review import (
    MeasureReviewError,
    write_review_artifact,
)
from .measure_review_catalog import canonical_catalog_bytes
from .omni_semantic_deployment import BALANCED_AI_SETTINGS
from .omni_semantic_deployment import (
    OmniSemanticDeploymentError,
    build_semantic_deployment_plan,
    semantic_deployment_sha256,
)
from .protected_fields import ProtectedFieldError, reject_protected_fields
from .r2_paired_schedule import CONTROL_CONDITION, TREATMENT_CONDITION
from .r2_paired_schedule import (
    R2PairedScheduleError,
    validate_r2_paired_schedule,
)


class R2ExecutionError(ValueError):
    """Raised when an R2 run could drift from its frozen paired contract."""


SERIES_ID = "r2-public-evidence-measures-v1"
SCHEDULE_KIND = "r2-public-evidence-measures-paired-schedule"
SCHEDULE_VERSION = "r2-public-evidence-measures-paired-schedule-v1"
BUNDLE_KIND = "r2-public-evidence-measure-bundle-set"
ATTEMPT_MANIFEST_KIND = "r2-public-evidence-measures-attempt-manifest"
FINALIZATION_KIND = "r2-public-evidence-measures-arm-finalization"
MAX_ARM_COST_USD = Decimal("500")
MAX_TOTAL_COST_USD = Decimal("1000")
MAX_GENERATION_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_COMMITTED_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_COMMITTED_MEMBER_BYTES = 16 * 1024 * 1024
EXPECTED_SCHEDULE_SHA256 = (
    "8498c35e062dd893d1f20eda503bb65c95603b94c5fdd5fa2a87a8c7ccc27bda"
)
EXPECTED_BUNDLE_MANIFEST_SHA256 = (
    "bbea478ed6947387607cfcdf043fee2cb1845122c9eabcb4e1487d573901a1a2"
)

_SCHEDULE_PATH = Path(
    "experiments/r2-public-evidence-measures/r2-paired-execution-schedule-v1.json"
)
_BUNDLE_ROOT = Path(
    "experiments/r2-public-evidence-measures/offline-semantic-bundles-v1"
)
_PUBLIC_MANIFEST_PATH = Path("data/manifests/eligible_questions.jsonl")
_DEV_A_IDS_PATH = Path("data/manifests/dev_a_ids.txt")
_SPLIT_METADATA_PATH = Path("data/manifests/development_split_metadata.json")
_TARGET_CONFIG_PATH = Path(
    "config/conditions/r2-public-evidence-measure-databases-v1.json"
)
_HARNESS_CONFIG_PATH = Path("config/conditions/c4-production-v1.json")
_PROMPT_PATH = Path("config/prompts/c4-user-prompt-v1.txt")
_INSTRUCTIONS_PATH = Path("config/instructions/c4-managed-instructions-v1.json")
_COMMITTED_PATHS = (
    _SCHEDULE_PATH,
    _BUNDLE_ROOT,
    _PUBLIC_MANIFEST_PATH,
    _DEV_A_IDS_PATH,
    _SPLIT_METADATA_PATH,
    _TARGET_CONFIG_PATH,
    _HARNESS_CONFIG_PATH,
    _PROMPT_PATH,
    _INSTRUCTIONS_PATH,
)

_CONDITIONS = (CONTROL_CONDITION, TREATMENT_CONDITION)
_CONDITION_DIRECTORIES = {
    CONTROL_CONDITION: "r2-c5b",
    TREATMENT_CONDITION: "r2-m1",
}
_DIGEST = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,119}")
_REVISION = re.compile(r"-(v[0-9]+)\Z")
_SAFE_FAILURE = re.compile(r"[a-z][a-z0-9._-]{0,79}")
_SCORED_FIELDS = frozenset(
    {
        "correctness",
        "official_correct",
        "outcome",
        "score",
        "sensitivity_correct",
    }
)
_ATTEMPT_FIELDS = frozenset(
    {
        "attempt_id",
        "attempt_position",
        "condition",
        "database",
        "instance_id",
        "pair_id",
        "pair_position",
        "repetition",
        "within_pair_position",
    }
)
_PAIR_FIELDS = frozenset(
    {
        "database",
        "database_round",
        "first_condition",
        "instance_id",
        "pair_id",
        "pair_position",
        "second_condition",
    }
)


@dataclass(frozen=True, slots=True)
class R2PlannedAttempt:
    """One exact schedule member with its arm and semantic provenance."""

    attempt_id: str
    attempt_position: int
    condition: str
    database: str
    deployment_identity: str
    deployment_run_id: str
    instance_id: str
    output_root: Path
    pair_id: str
    pair_position: int
    repetition: int
    run_id: str
    semantic_model_sha256: str
    within_pair_position: int

    def public_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "attempt_position": self.attempt_position,
            "condition": self.condition,
            "database": self.database,
            "deployment_identity": self.deployment_identity,
            "deployment_run_id": self.deployment_run_id,
            "instance_id": self.instance_id,
            "output_root": self.output_root.as_posix(),
            "pair_id": self.pair_id,
            "pair_position": self.pair_position,
            "repetition": self.repetition,
            "run_id": self.run_id,
            "semantic_model_sha256": self.semantic_model_sha256,
            "within_pair_position": self.within_pair_position,
        }


@dataclass(frozen=True, slots=True)
class R2ExecutionPlan:
    """Credential-free exact dry plan for the complete paired R2 series."""

    attempts: tuple[R2PlannedAttempt, ...]
    balanced_ai_settings_sha256: str
    budget_policy_sha256: str
    bundle_manifest_sha256: str
    bundle_set_sha256: str
    harness_config_sha256: str
    instructions_sha256: str
    output_root: Path
    projected_arm_cost_usd: Mapping[str, str]
    projected_total_cost_usd: str
    prompt_sha256: str
    schedule_sha256: str
    system_commit: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            canonical_catalog_bytes(self.public_dict(include_plan_sha256=False))
        ).hexdigest()

    def public_dict(self, *, include_plan_sha256: bool = True) -> dict[str, object]:
        value: dict[str, object] = {
            "attempt_count": len(self.attempts),
            "attempts": [attempt.public_dict() for attempt in self.attempts],
            "balanced_ai_settings_sha256": self.balanced_ai_settings_sha256,
            "budget_policy_sha256": self.budget_policy_sha256,
            "bundle_manifest_sha256": self.bundle_manifest_sha256,
            "bundle_set_sha256": self.bundle_set_sha256,
            "conditions": list(_CONDITIONS),
            "harness_config_sha256": self.harness_config_sha256,
            "instructions_sha256": self.instructions_sha256,
            "output_root": self.output_root.as_posix(),
            "projected_arm_cost_usd": dict(self.projected_arm_cost_usd),
            "projected_total_cost_usd": self.projected_total_cost_usd,
            "prompt_sha256": self.prompt_sha256,
            "schedule_sha256": self.schedule_sha256,
            "schema_version": 1,
            "series_id": SERIES_ID,
            "system_commit": self.system_commit,
        }
        if include_plan_sha256:
            value["execution_plan_sha256"] = self.sha256
        return value

    def attempt(self, attempt_id: str) -> R2PlannedAttempt:
        matches = [item for item in self.attempts if item.attempt_id == attempt_id]
        if len(matches) != 1:
            raise R2ExecutionError("attempt is absent from the execution plan")
        return matches[0]


@dataclass(frozen=True, slots=True)
class R2AttemptArtifacts:
    """The immutable one-record generation and its R2 provenance manifest."""

    generation_path: Path
    generation_sha256: str
    manifest_path: Path
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class R2FinalizedGenerations:
    """Canonical complete generation files consumed by both frozen analyzers."""

    control_path: Path
    control_sha256: str
    treatment_path: Path
    treatment_sha256: str
    manifest_path: Path
    manifest_sha256: str


def build_r2_execution_plan(
    *,
    schedule_bytes: bytes,
    bundle_manifest_bytes: bytes,
    semantic_model_sha256s: Mapping[str, Mapping[str, str]],
    system_commit: str,
    output_root: Path,
    arm_run_ids: Mapping[str, str],
    deployment_run_ids: Mapping[str, str],
    projected_attempt_cost_usd: Mapping[str, float | str],
    harness_config_sha256: str,
    prompt_sha256: str,
    instructions_sha256: str,
    budget_policy_sha256: str,
) -> R2ExecutionPlan:
    """Bind the frozen schedule, paired bundles, identities, and budget offline."""
    schedule = _schedule(schedule_bytes)
    databases = tuple(sorted({str(item["database"]) for item in schedule["attempts"]}))
    bundle = _bundle(bundle_manifest_bytes, databases)
    semantic = _semantic_digests(semantic_model_sha256s, databases)
    commit = _commit(system_commit)
    root = _raw_root(output_root)
    run_ids = _arm_identifiers(arm_run_ids, "arm run IDs")
    deployment_ids = _arm_identifiers(deployment_run_ids, "deployment run IDs")
    if len(set(run_ids.values())) != len(_CONDITIONS):
        raise R2ExecutionError("arm run IDs must be distinct")
    if len(set(deployment_ids.values())) != len(_CONDITIONS):
        raise R2ExecutionError("deployment run IDs must be distinct")
    if set(run_ids.values()).intersection(deployment_ids.values()):
        raise R2ExecutionError("execution and deployment run IDs must be distinct")
    revisions = {
        condition: _revision(deployment_ids[condition]) for condition in _CONDITIONS
    }
    counts = Counter(str(item["condition"]) for item in schedule["attempts"])
    raw_projected = {
        condition: _cost(projected_attempt_cost_usd, condition) * counts[condition]
        for condition in _CONDITIONS
    }
    total = sum(raw_projected.values(), Decimal(0))
    if total > MAX_TOTAL_COST_USD:
        raise R2ExecutionError("total projection exceeds USD 1000")
    if any(value > MAX_ARM_COST_USD for value in raw_projected.values()):
        raise R2ExecutionError("per-arm projection exceeds USD 500")
    projected = {
        condition: _money(raw_projected[condition]) for condition in _CONDITIONS
    }
    hashes = {
        "harness_config_sha256": _digest(
            harness_config_sha256, "harness config SHA-256"
        ),
        "prompt_sha256": _digest(prompt_sha256, "prompt SHA-256"),
        "instructions_sha256": _digest(instructions_sha256, "instructions SHA-256"),
        "budget_policy_sha256": _digest(budget_policy_sha256, "budget policy SHA-256"),
    }
    attempts = tuple(
        _planned_attempt(
            item,
            root=root,
            run_id=run_ids[str(item["condition"])],
            deployment_run_id=deployment_ids[str(item["condition"])],
            deployment_revision=revisions[str(item["condition"])],
            semantic_model_sha256=semantic[str(item["condition"])][
                str(item["database"])
            ],
        )
        for item in schedule["attempts"]
    )
    return R2ExecutionPlan(
        attempts=attempts,
        balanced_ai_settings_sha256=hashlib.sha256(
            canonical_catalog_bytes(BALANCED_AI_SETTINGS)
        ).hexdigest(),
        budget_policy_sha256=hashes["budget_policy_sha256"],
        bundle_manifest_sha256=hashlib.sha256(bundle_manifest_bytes).hexdigest(),
        bundle_set_sha256=str(bundle["manifest"]["artifact_sha256"]),
        harness_config_sha256=hashes["harness_config_sha256"],
        instructions_sha256=hashes["instructions_sha256"],
        output_root=root,
        projected_arm_cost_usd=projected,
        projected_total_cost_usd=_money(total),
        prompt_sha256=hashes["prompt_sha256"],
        schedule_sha256=hashlib.sha256(schedule_bytes).hexdigest(),
        system_commit=commit,
    )


def load_committed_r2_execution_plan(
    workspace: Path,
    *,
    system_commit: str,
    output_root: Path,
    arm_run_ids: Mapping[str, str],
    deployment_run_ids: Mapping[str, str],
    projected_attempt_cost_usd: Mapping[str, float | str],
    budget_policy_sha256: str,
    expected_schedule_sha256: str = EXPECTED_SCHEDULE_SHA256,
    expected_bundle_manifest_sha256: str = EXPECTED_BUNDLE_MANIFEST_SHA256,
) -> R2ExecutionPlan:
    """Reproduce the plan only from one exact Git tree, never the worktree."""
    root = _git_root(workspace)
    commit = _canonical_git_commit(root, system_commit)
    schedule_digest = _digest(expected_schedule_sha256, "expected schedule SHA-256")
    bundle_digest = _digest(
        expected_bundle_manifest_sha256,
        "expected bundle manifest SHA-256",
    )
    archive = _committed_archive(root, commit)
    try:
        with tempfile.TemporaryDirectory(prefix="omni-r2-committed-") as directory:
            snapshot = Path(directory) / "snapshot"
            snapshot.mkdir(mode=0o700)
            _extract_committed_archive(archive, snapshot)
            return _snapshot_execution_plan(
                snapshot,
                system_commit=commit,
                output_root=output_root,
                arm_run_ids=arm_run_ids,
                deployment_run_ids=deployment_run_ids,
                projected_attempt_cost_usd=projected_attempt_cost_usd,
                budget_policy_sha256=budget_policy_sha256,
                expected_schedule_sha256=schedule_digest,
                expected_bundle_manifest_sha256=bundle_digest,
            )
    except (OSError, tarfile.TarError) as error:
        raise R2ExecutionError("committed R2 snapshot is invalid") from error


def _snapshot_execution_plan(
    snapshot: Path,
    *,
    system_commit: str,
    output_root: Path,
    arm_run_ids: Mapping[str, str],
    deployment_run_ids: Mapping[str, str],
    projected_attempt_cost_usd: Mapping[str, float | str],
    budget_policy_sha256: str,
    expected_schedule_sha256: str,
    expected_bundle_manifest_sha256: str,
) -> R2ExecutionPlan:
    schedule_bytes = _snapshot_file(snapshot, _SCHEDULE_PATH, MAX_GENERATION_BYTES)
    if hashlib.sha256(schedule_bytes).hexdigest() != expected_schedule_sha256:
        raise R2ExecutionError("committed R2 schedule does not match its freeze")
    bundle_manifest_bytes = _snapshot_file(
        snapshot, _BUNDLE_ROOT / "manifest.json", MAX_GENERATION_BYTES
    )
    if (
        hashlib.sha256(bundle_manifest_bytes).hexdigest()
        != expected_bundle_manifest_sha256
    ):
        raise R2ExecutionError("committed R2 bundle set does not match its freeze")
    public_manifest = _snapshot_file(
        snapshot, _PUBLIC_MANIFEST_PATH, MAX_GENERATION_BYTES
    )
    dev_a_ids = _snapshot_file(snapshot, _DEV_A_IDS_PATH, MAX_MANIFEST_BYTES)
    split_metadata = _snapshot_file(snapshot, _SPLIT_METADATA_PATH, MAX_MANIFEST_BYTES)
    target_config = _snapshot_file(snapshot, _TARGET_CONFIG_PATH, MAX_MANIFEST_BYTES)
    try:
        validate_r2_paired_schedule(
            schedule_bytes,
            public_manifest,
            dev_a_ids,
            split_metadata,
            target_config,
        )
    except R2PairedScheduleError as error:
        raise R2ExecutionError(
            "committed R2 schedule does not reproduce from public inputs"
        ) from error
    schedule = _schedule(schedule_bytes)
    databases = tuple(sorted({str(item["database"]) for item in schedule["attempts"]}))
    bundle = _bundle(bundle_manifest_bytes, databases)
    semantic = _snapshot_semantic_digests(snapshot / _BUNDLE_ROOT, bundle, databases)
    return build_r2_execution_plan(
        schedule_bytes=schedule_bytes,
        bundle_manifest_bytes=bundle_manifest_bytes,
        semantic_model_sha256s=semantic,
        system_commit=system_commit,
        output_root=output_root,
        arm_run_ids=arm_run_ids,
        deployment_run_ids=deployment_run_ids,
        projected_attempt_cost_usd=projected_attempt_cost_usd,
        harness_config_sha256=hashlib.sha256(
            _snapshot_file(snapshot, _HARNESS_CONFIG_PATH, MAX_MANIFEST_BYTES)
        ).hexdigest(),
        prompt_sha256=hashlib.sha256(
            _snapshot_file(snapshot, _PROMPT_PATH, MAX_MANIFEST_BYTES)
        ).hexdigest(),
        instructions_sha256=hashlib.sha256(
            _snapshot_file(snapshot, _INSTRUCTIONS_PATH, MAX_MANIFEST_BYTES)
        ).hexdigest(),
        budget_policy_sha256=budget_policy_sha256,
    )


def _snapshot_semantic_digests(
    bundle_root: Path,
    bundle: Mapping[str, Any],
    databases: Sequence[str],
) -> dict[str, dict[str, str]]:
    manifest = _mapping(bundle.get("manifest"), "bundle-set content manifest")
    records = manifest.get("files")
    if not isinstance(records, list):
        raise R2ExecutionError("bundle-set file inventory is invalid")
    expected: dict[str, tuple[str, int]] = {}
    for raw in records:
        record = _mapping(raw, "bundle-set file record")
        if set(record) != {"path", "sha256", "size_bytes"}:
            raise R2ExecutionError("bundle-set file record is invalid")
        name = _safe_relative(record.get("path"), "bundle-set file")
        digest = _digest(record.get("sha256"), "bundle-set file SHA-256")
        size = record.get("size_bytes")
        if type(size) is not int or size < 0 or name in expected:
            raise R2ExecutionError("bundle-set file record is invalid")
        expected[name] = (digest, size)
    actual_paths = tuple(
        path
        for path in bundle_root.rglob("*")
        if path.is_file() and path != bundle_root / "manifest.json"
    )
    actual_names = {path.relative_to(bundle_root).as_posix() for path in actual_paths}
    if actual_names != set(expected):
        raise R2ExecutionError("bundle-set file inventory does not match snapshot")
    for path in actual_paths:
        name = path.relative_to(bundle_root).as_posix()
        content = read_regular_file(path, maximum_bytes=MAX_COMMITTED_MEMBER_BYTES)
        digest, size = expected[name]
        if len(content) != size or hashlib.sha256(content).hexdigest() != digest:
            raise R2ExecutionError("committed bundle file does not match manifest")

    database_records = {str(item["database"]): item for item in bundle["databases"]}
    result: dict[str, dict[str, str]] = {condition: {} for condition in _CONDITIONS}
    for condition in _CONDITIONS:
        directory = _CONDITION_DIRECTORIES[condition]
        manifest_field = (
            "control_manifest_sha256"
            if condition == CONTROL_CONDITION
            else "treatment_manifest_sha256"
        )
        for database in databases:
            try:
                plan = build_semantic_deployment_plan(
                    bundle_root / directory / database
                )
            except OmniSemanticDeploymentError as error:
                raise R2ExecutionError(
                    "committed R2 semantic bundle is invalid"
                ) from error
            if plan.database != database or plan.manifest_sha256 != database_records[
                database
            ].get(manifest_field):
                raise R2ExecutionError(
                    "committed R2 semantic manifest binding is invalid"
                )
            result[condition][database] = semantic_deployment_sha256(plan)
    return result


def write_r2_attempt_artifacts(
    workspace: Path,
    *,
    plan: R2ExecutionPlan,
    attempt_id: str,
    record: Mapping[str, Any],
) -> R2AttemptArtifacts:
    """Publish one terminal R2 attempt without permitting overwrite or scoring."""
    root = _workspace(workspace)
    if not isinstance(plan, R2ExecutionPlan):
        raise R2ExecutionError("attempt publication requires an execution plan")
    attempt = plan.attempt(attempt_id)
    value = _validated_generation_record(dict(record), attempt)
    generation_bytes = canonical_catalog_bytes(value)
    generation_sha256 = hashlib.sha256(generation_bytes).hexdigest()
    manifest = _attempt_manifest(plan, attempt, generation_sha256)
    manifest_bytes = canonical_catalog_bytes(manifest)
    destination = _inside_workspace(root, attempt.output_root)
    generation_path = destination / "generation.jsonl"
    manifest_path = destination / "run.json"
    try:
        write_review_artifact(generation_path, generation_bytes)
        write_review_artifact(manifest_path, manifest_bytes)
    except MeasureReviewError as error:
        raise R2ExecutionError(str(error)) from error
    return R2AttemptArtifacts(
        generation_path=generation_path,
        generation_sha256=generation_sha256,
        manifest_path=manifest_path,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


def finalize_r2_generations(
    workspace: Path,
    *,
    plan: R2ExecutionPlan,
    destination: Path,
) -> R2FinalizedGenerations:
    """Finalize both complete arms in frozen order after exact reconciliation."""
    root = _workspace(workspace)
    if not isinstance(plan, R2ExecutionPlan):
        raise R2ExecutionError("finalization requires an execution plan")
    selected_destination = _raw_root(destination)
    destination_root = _inside_workspace(root, selected_destination)
    if destination_root.exists() or destination_root.is_symlink():
        raise R2ExecutionError("finalization destination already exists")

    records: dict[str, list[tuple[str, bytes]]] = {
        condition: [] for condition in _CONDITIONS
    }
    for attempt in plan.attempts:
        content = _reconciled_attempt(root, plan, attempt)
        records[attempt.condition].append((attempt.attempt_id, content))
    if any(
        len(records[condition]) * 2 != len(plan.attempts) for condition in _CONDITIONS
    ):
        raise R2ExecutionError("finalized arms do not have exact paired coverage")

    arm_bytes = {
        condition: b"".join(content for _attempt_id, content in records[condition])
        for condition in _CONDITIONS
    }
    file_names = {
        CONTROL_CONDITION: "r2-c5b.generation.jsonl",
        TREATMENT_CONDITION: "r2-m1.generation.jsonl",
    }
    conditions = {
        condition: {
            "generation_file": file_names[condition],
            "generation_sha256": hashlib.sha256(arm_bytes[condition]).hexdigest(),
            "ordered_attempt_ids": [item[0] for item in records[condition]],
            "record_count": len(records[condition]),
            "run_id": next(
                item.run_id for item in plan.attempts if item.condition == condition
            ),
        }
        for condition in _CONDITIONS
    }
    manifest: dict[str, Any] = {
        "bundle_manifest_sha256": plan.bundle_manifest_sha256,
        "bundle_set_sha256": plan.bundle_set_sha256,
        "conditions": conditions,
        "execution_plan_sha256": plan.sha256,
        "information_boundary": {
            "correctness_used": False,
            "hidden_annotations_used": False,
            "result_values_emitted": False,
            "sealed_test_used": False,
        },
        "kind": FINALIZATION_KIND,
        "schedule_sha256": plan.schedule_sha256,
        "schema_version": 1,
        "series_id": SERIES_ID,
        "system_commit": plan.system_commit,
    }
    manifest["manifest_sha256"] = hashlib.sha256(
        canonical_catalog_bytes(manifest)
    ).hexdigest()
    manifest_bytes = canonical_catalog_bytes(manifest)
    try:
        for condition in _CONDITIONS:
            write_review_artifact(
                destination_root / file_names[condition], arm_bytes[condition]
            )
        manifest_path = destination_root / "finalization.json"
        write_review_artifact(manifest_path, manifest_bytes)
    except MeasureReviewError as error:
        raise R2ExecutionError(str(error)) from error
    return R2FinalizedGenerations(
        control_path=destination_root / file_names[CONTROL_CONDITION],
        control_sha256=conditions[CONTROL_CONDITION]["generation_sha256"],
        treatment_path=destination_root / file_names[TREATMENT_CONDITION],
        treatment_sha256=conditions[TREATMENT_CONDITION]["generation_sha256"],
        manifest_path=manifest_path,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
    )


def _schedule(content: bytes) -> dict[str, Any]:
    value = _canonical_object(content, "paired schedule")
    if (
        value.get("kind") != SCHEDULE_KIND
        or value.get("schedule_version") != SCHEDULE_VERSION
        or value.get("schema_version") != 1
    ):
        raise R2ExecutionError("paired schedule identity is invalid")
    attempts = value.get("attempts")
    pairs = value.get("pairs")
    manifest = value.get("manifest")
    if not isinstance(attempts, list) or not attempts or not isinstance(pairs, list):
        raise R2ExecutionError("paired schedule shape is invalid")
    if not isinstance(manifest, Mapping):
        raise R2ExecutionError("paired schedule manifest is invalid")
    _internal_hash(value, manifest, "artifact_sha256", "paired schedule")
    if len(attempts) != len(pairs) * 2:
        raise R2ExecutionError("paired schedule attempt coverage is invalid")
    pair_ids: set[str] = set()
    attempt_ids: set[str] = set()
    for index, raw_pair in enumerate(pairs, start=1):
        pair = _mapping(raw_pair, "schedule pair")
        if set(pair) != _PAIR_FIELDS or pair.get("pair_position") != index:
            raise R2ExecutionError("paired schedule pair shape is invalid")
        pair_id = _text(pair.get("pair_id"), "pair ID")
        if pair_id in pair_ids:
            raise R2ExecutionError("paired schedule contains a duplicate pair")
        pair_ids.add(pair_id)
        selected = attempts[(index - 1) * 2 : index * 2]
        expected_conditions = (
            pair.get("first_condition"),
            pair.get("second_condition"),
        )
        if set(expected_conditions) != set(_CONDITIONS):
            raise R2ExecutionError("paired schedule pair conditions are invalid")
        for within, (raw_attempt, condition) in enumerate(
            zip(selected, expected_conditions, strict=True), start=1
        ):
            attempt = _mapping(raw_attempt, "schedule attempt")
            if set(attempt) != _ATTEMPT_FIELDS:
                raise R2ExecutionError("paired schedule attempt shape is invalid")
            expected_position = (index - 1) * 2 + within
            if (
                attempt.get("attempt_position") != expected_position
                or attempt.get("within_pair_position") != within
                or attempt.get("pair_id") != pair_id
                or attempt.get("pair_position") != index
                or attempt.get("condition") != condition
                or attempt.get("database") != pair.get("database")
                or attempt.get("instance_id") != pair.get("instance_id")
                or attempt.get("repetition") != 1
            ):
                raise R2ExecutionError("paired schedule pair adjacency is invalid")
            attempt_id = _text(attempt.get("attempt_id"), "attempt ID")
            if attempt_id in attempt_ids:
                raise R2ExecutionError("paired schedule contains a duplicate attempt")
            attempt_ids.add(attempt_id)
    if manifest.get("ordered_pair_ids") != [item["pair_id"] for item in pairs] or (
        manifest.get("ordered_attempt_ids") != [item["attempt_id"] for item in attempts]
    ):
        raise R2ExecutionError("paired schedule ordered identity is invalid")
    counts = Counter(str(item["condition"]) for item in attempts)
    if counts[CONTROL_CONDITION] != counts[TREATMENT_CONDITION]:
        raise R2ExecutionError("paired schedule arm counts are not balanced")
    return value


def _bundle(content: bytes, databases: Sequence[str]) -> dict[str, Any]:
    value = _canonical_object(content, "bundle-set manifest")
    try:
        reject_protected_fields(value)
    except ProtectedFieldError as error:
        raise R2ExecutionError(
            "bundle-set manifest contains protected content"
        ) from error
    if (
        value.get("kind") != BUNDLE_KIND
        or value.get("series_id") != SERIES_ID
        or value.get("schema_version") != 1
    ):
        raise R2ExecutionError("bundle-set manifest identity is invalid")
    if value.get("balanced_ai_settings") != BALANCED_AI_SETTINGS:
        raise R2ExecutionError("bundle-set Balanced ai_settings are invalid")
    conditions = value.get("conditions")
    if not isinstance(conditions, Mapping) or set(conditions) != set(_CONDITIONS):
        raise R2ExecutionError("bundle-set condition inventory is invalid")
    if conditions[CONTROL_CONDITION] != {
        "directory": "r2-c5b",
        "measure_count": 0,
    }:
        raise R2ExecutionError("bundle-set control condition is invalid")
    treatment = conditions[TREATMENT_CONDITION]
    if (
        not isinstance(treatment, Mapping)
        or treatment.get("directory") != "r2-m1"
        or type(treatment.get("measure_count")) is not int
        or treatment["measure_count"] < 1
    ):
        raise R2ExecutionError("bundle-set treatment condition is invalid")
    manifest = value.get("manifest")
    if not isinstance(manifest, Mapping):
        raise R2ExecutionError("bundle-set content manifest is invalid")
    _internal_hash(value, manifest, "artifact_sha256", "bundle set")
    records = value.get("databases")
    if not isinstance(records, list):
        raise R2ExecutionError("bundle database inventory is invalid")
    observed: list[str] = []
    for raw in records:
        record = _mapping(raw, "bundle database")
        database = _text(record.get("database"), "bundle database")
        _digest(record.get("control_manifest_sha256"), "control manifest SHA-256")
        _digest(
            record.get("treatment_manifest_sha256"),
            "treatment manifest SHA-256",
        )
        observed.append(database)
    if sorted(observed) != list(databases) or len(observed) != len(set(observed)):
        raise R2ExecutionError("bundle database coverage does not match schedule")
    return value


def _semantic_digests(
    value: Mapping[str, Mapping[str, str]], databases: Sequence[str]
) -> dict[str, dict[str, str]]:
    if not isinstance(value, Mapping) or set(value) != set(_CONDITIONS):
        raise R2ExecutionError("semantic digest coverage is invalid")
    result: dict[str, dict[str, str]] = {}
    for condition in _CONDITIONS:
        selected = value.get(condition)
        if not isinstance(selected, Mapping) or set(selected) != set(databases):
            raise R2ExecutionError("semantic digest coverage is invalid")
        result[condition] = {
            database: _digest(selected[database], "semantic model SHA-256")
            for database in databases
        }
    return result


def _planned_attempt(
    item: Mapping[str, Any],
    *,
    root: Path,
    run_id: str,
    deployment_run_id: str,
    deployment_revision: str,
    semantic_model_sha256: str,
) -> R2PlannedAttempt:
    condition = str(item["condition"])
    database = str(item["database"])
    attempt_id = str(item["attempt_id"])
    position = int(item["attempt_position"])
    identity = (
        f"livesqlbench-{database}-{_CONDITION_DIRECTORIES[condition]}-"
        f"{deployment_revision}"
    )
    if len(identity) > 160:
        raise R2ExecutionError("deployment identity is too long")
    output = (
        root
        / _CONDITION_DIRECTORIES[condition]
        / database
        / f"{position:03d}-{attempt_id}"
    )
    return R2PlannedAttempt(
        attempt_id=attempt_id,
        attempt_position=position,
        condition=condition,
        database=database,
        deployment_identity=identity,
        deployment_run_id=deployment_run_id,
        instance_id=str(item["instance_id"]),
        output_root=output,
        pair_id=str(item["pair_id"]),
        pair_position=int(item["pair_position"]),
        repetition=int(item["repetition"]),
        run_id=run_id,
        semantic_model_sha256=semantic_model_sha256,
        within_pair_position=int(item["within_pair_position"]),
    )


def _attempt_manifest(
    plan: R2ExecutionPlan,
    attempt: R2PlannedAttempt,
    generation_sha256: str,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "attempt_id": attempt.attempt_id,
        "attempt_position": attempt.attempt_position,
        "balanced_ai_settings_sha256": plan.balanced_ai_settings_sha256,
        "budget_policy_sha256": plan.budget_policy_sha256,
        "bundle_manifest_sha256": plan.bundle_manifest_sha256,
        "bundle_set_sha256": plan.bundle_set_sha256,
        "condition": attempt.condition,
        "database": attempt.database,
        "deployment_identity": attempt.deployment_identity,
        "deployment_run_id": attempt.deployment_run_id,
        "execution_plan_sha256": plan.sha256,
        "generation_sha256": generation_sha256,
        "harness_config_sha256": plan.harness_config_sha256,
        "instructions_sha256": plan.instructions_sha256,
        "instance_id": attempt.instance_id,
        "kind": ATTEMPT_MANIFEST_KIND,
        "pair_id": attempt.pair_id,
        "pair_position": attempt.pair_position,
        "prompt_sha256": plan.prompt_sha256,
        "repetition": attempt.repetition,
        "run_id": attempt.run_id,
        "schedule_sha256": plan.schedule_sha256,
        "schema_version": 1,
        "semantic_model_sha256": attempt.semantic_model_sha256,
        "series_id": SERIES_ID,
        "system_commit": plan.system_commit,
        "within_pair_position": attempt.within_pair_position,
    }
    value["manifest_sha256"] = hashlib.sha256(
        canonical_catalog_bytes(value)
    ).hexdigest()
    return value


def _validated_generation_record(
    record: dict[str, Any], attempt: R2PlannedAttempt
) -> dict[str, Any]:
    try:
        reject_protected_fields(record)
    except ProtectedFieldError as error:
        raise R2ExecutionError(
            "generation record contains protected content"
        ) from error
    scored = _find_key(record, _SCORED_FIELDS)
    if scored is not None:
        raise R2ExecutionError(f"generation record contains scored field {scored}")
    expected = {
        "attempt_id": attempt.attempt_id,
        "condition": attempt.condition,
        "database": attempt.database,
        "instance_id": attempt.instance_id,
        "partition": "dev-a",
        "repetition": attempt.repetition,
        "run_id": attempt.run_id,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            description = (
                "attempt identity" if field == "attempt_id" else field.replace("_", " ")
            )
            raise R2ExecutionError(f"generation {description} is invalid")
    outcome = record.get("generation_outcome")
    failure = record.get("terminal_failure_class")
    if outcome not in {"answered", "errored", "refused"}:
        raise R2ExecutionError("generation outcome is invalid")
    if (outcome == "answered") != (failure is None):
        raise R2ExecutionError("generation outcome and failure are inconsistent")
    if failure is not None and (
        not isinstance(failure, str) or _SAFE_FAILURE.fullmatch(failure) is None
    ):
        raise R2ExecutionError("terminal failure class is invalid")
    latency = record.get("latency_ms")
    if (
        not isinstance(latency, (int, float))
        or isinstance(latency, bool)
        or not math.isfinite(latency)
        or latency < 0
    ):
        raise R2ExecutionError("generation latency is invalid")
    cost = record.get("cost_usd")
    unavailable = record.get("cost_unavailable_reason")
    if cost is None:
        if not isinstance(unavailable, str) or not unavailable:
            raise R2ExecutionError("unavailable cost requires a reason")
    elif (
        not isinstance(cost, (int, float))
        or isinstance(cost, bool)
        or not math.isfinite(cost)
        or cost < 0
        or unavailable is not None
    ):
        raise R2ExecutionError("generation cost fields are invalid")
    return record


def _reconciled_attempt(
    workspace: Path,
    plan: R2ExecutionPlan,
    attempt: R2PlannedAttempt,
) -> bytes:
    root = _inside_workspace(workspace, attempt.output_root)
    if not root.exists() or root.is_symlink():
        raise R2ExecutionError(f"scheduled attempt is absent: {attempt.attempt_id}")
    try:
        generation = read_regular_file(
            root / "generation.jsonl", maximum_bytes=MAX_GENERATION_BYTES
        )
        manifest_bytes = read_regular_file(
            root / "run.json", maximum_bytes=MAX_MANIFEST_BYTES
        )
    except HKBFileSafetyError as error:
        raise R2ExecutionError("scheduled attempt artifacts are unsafe") from error
    manifest = _canonical_object(manifest_bytes, "attempt manifest")
    stored_internal = manifest.get("manifest_sha256")
    unhashed = copy.deepcopy(manifest)
    unhashed.pop("manifest_sha256", None)
    if stored_internal != hashlib.sha256(canonical_catalog_bytes(unhashed)).hexdigest():
        raise R2ExecutionError("attempt manifest hash is invalid")
    generation_sha256 = hashlib.sha256(generation).hexdigest()
    expected = _attempt_manifest(plan, attempt, generation_sha256)
    if manifest != expected:
        if manifest.get("semantic_model_sha256") != attempt.semantic_model_sha256:
            raise R2ExecutionError("attempt semantic model is invalid")
        raise R2ExecutionError("attempt manifest does not match execution plan")
    lines = generation.splitlines(keepends=True)
    if len(lines) != 1:
        raise R2ExecutionError("attempt generation must contain exactly one record")
    record = _canonical_object(generation, "attempt generation")
    _validated_generation_record(record, attempt)
    return generation


def _canonical_object(content: bytes, description: str) -> dict[str, Any]:
    if not isinstance(content, bytes) or not content:
        raise R2ExecutionError(f"{description} is empty")
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise R2ExecutionError(f"{description} is not valid JSON") from error
    if not isinstance(value, dict):
        raise R2ExecutionError(f"{description} must be an object")
    if canonical_catalog_bytes(value) != content:
        raise R2ExecutionError(f"{description} is not canonical JSON")
    return value


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise R2ExecutionError(f"JSON contains duplicate key {key}")
        value[key] = item
    return value


def _internal_hash(
    value: Mapping[str, Any],
    manifest: Mapping[str, Any],
    field: str,
    description: str,
) -> None:
    stored = manifest.get(field)
    if not isinstance(stored, str) or _DIGEST.fullmatch(stored) is None:
        raise R2ExecutionError(f"{description} internal hash is invalid")
    unhashed = copy.deepcopy(dict(value))
    del unhashed["manifest"][field]
    if hashlib.sha256(canonical_catalog_bytes(unhashed)).hexdigest() != stored:
        raise R2ExecutionError(f"{description} internal hash is invalid")


def _arm_identifiers(value: Mapping[str, str], description: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != set(_CONDITIONS):
        raise R2ExecutionError(f"{description} must cover both arms")
    return {
        condition: _identifier(value[condition], description)
        for condition in _CONDITIONS
    }


def _cost(value: Mapping[str, float | str], condition: str) -> Decimal:
    if not isinstance(value, Mapping) or set(value) != set(_CONDITIONS):
        raise R2ExecutionError("projected attempt costs must cover both arms")
    raw = value[condition]
    if isinstance(raw, bool):
        raise R2ExecutionError("projected attempt cost is invalid")
    try:
        selected = Decimal(str(raw))
    except (InvalidOperation, ValueError) as error:
        raise R2ExecutionError("projected attempt cost is invalid") from error
    if not selected.is_finite() or selected < 0:
        raise R2ExecutionError("projected attempt cost is invalid")
    return selected


def _raw_root(path: Path) -> Path:
    value = Path(path)
    if (
        value.is_absolute()
        or not value.parts
        or ".." in value.parts
        or not any(value.is_relative_to(root) for root in ALLOWED_RAW_ROOTS)
    ):
        raise R2ExecutionError("R2 output root must be a confined raw-run path")
    return value


def _inside_workspace(workspace: Path, relative: Path) -> Path:
    candidate = workspace / relative
    try:
        if candidate.resolve(strict=False) != candidate:
            raise R2ExecutionError("R2 artifact path must not contain a symlink")
    except OSError as error:
        raise R2ExecutionError("R2 artifact path is unavailable") from error
    return candidate


def _workspace(path: Path) -> Path:
    try:
        root = Path(path).resolve(strict=True)
    except OSError as error:
        raise R2ExecutionError("workspace is unavailable") from error
    if not (root / ".git").exists():
        raise R2ExecutionError("workspace must be a Git repository root")
    return root


def _git_root(path: Path) -> Path:
    try:
        supplied = Path(path).resolve(strict=True)
        completed = subprocess.run(
            ["git", "-C", str(supplied), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        observed = Path(completed.stdout.strip()).resolve(strict=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise R2ExecutionError("workspace must be a Git repository") from error
    if observed != supplied:
        raise R2ExecutionError("workspace must be the Git repository root")
    return supplied


def _canonical_git_commit(workspace: Path, value: str) -> str:
    selected = _commit(value)
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", f"{selected}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise R2ExecutionError("system commit is unavailable") from error
    if completed.stdout.strip() != selected:
        raise R2ExecutionError("system commit is not canonical")
    return selected


def _committed_archive(workspace: Path, commit: str) -> bytes:
    try:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "archive",
                "--format=tar",
                commit,
                "--",
                *(path.as_posix() for path in _COMMITTED_PATHS),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise R2ExecutionError("committed R2 inputs are unavailable") from error
    content = completed.stdout
    if not content or len(content) > MAX_COMMITTED_ARCHIVE_BYTES:
        raise R2ExecutionError("committed R2 input archive is invalid")
    return content


def _extract_committed_archive(content: bytes, destination: Path) -> None:
    if not isinstance(content, bytes) or not content:
        raise R2ExecutionError("committed R2 input archive is empty")
    observed: set[str] = set()
    total = 0
    try:
        archive = tarfile.open(fileobj=io.BytesIO(content), mode="r:")
    except tarfile.TarError as error:
        raise R2ExecutionError("committed R2 input archive is invalid") from error
    with archive:
        for member in archive.getmembers():
            relative = Path(member.name)
            if (
                relative.is_absolute()
                or not relative.parts
                or ".." in relative.parts
                or not (member.isdir() or member.isfile())
                or member.name in observed
            ):
                raise R2ExecutionError("committed R2 input archive is unsafe")
            observed.add(member.name)
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(mode=0o700, parents=True, exist_ok=True)
                continue
            if member.size > MAX_COMMITTED_MEMBER_BYTES:
                raise R2ExecutionError("committed R2 archive member is oversized")
            total += member.size
            if total > MAX_COMMITTED_ARCHIVE_BYTES:
                raise R2ExecutionError("committed R2 input archive is oversized")
            source = archive.extractfile(member)
            if source is None:
                raise R2ExecutionError("committed R2 input archive is malformed")
            content_bytes = source.read(MAX_COMMITTED_MEMBER_BYTES + 1)
            if len(content_bytes) != member.size:
                raise R2ExecutionError("committed R2 archive member is malformed")
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            target.write_bytes(content_bytes)
            target.chmod(0o600)


def _snapshot_file(root: Path, relative: Path, maximum_bytes: int) -> bytes:
    try:
        return read_regular_file(root / relative, maximum_bytes=maximum_bytes)
    except HKBFileSafetyError as error:
        raise R2ExecutionError(
            f"committed R2 input is unavailable: {relative.as_posix()}"
        ) from error


def _safe_relative(value: object, description: str) -> str:
    if not isinstance(value, str):
        raise R2ExecutionError(f"{description} path is invalid")
    path = Path(value)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
    ):
        raise R2ExecutionError(f"{description} path is invalid")
    return path.as_posix()


def _mapping(value: object, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise R2ExecutionError(f"{description} must be an object")
    return value


def _text(value: object, description: str) -> str:
    if not isinstance(value, str) or not value:
        raise R2ExecutionError(f"{description} must be non-empty")
    return value


def _identifier(value: object, description: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise R2ExecutionError(f"{description} contain an invalid identifier")
    return value


def _revision(value: str) -> str:
    match = _REVISION.search(value)
    if match is None:
        raise R2ExecutionError("deployment run IDs must end in a v-number revision")
    return match.group(1)


def _digest(value: object, description: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise R2ExecutionError(f"{description} is invalid")
    return value


def _commit(value: object) -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise R2ExecutionError("system commit must be a full lowercase commit hash")
    return value


def _find_key(value: object, keys: frozenset[str]) -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in keys:
                return key
            nested = _find_key(item, keys)
            if nested is not None:
                return nested
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            nested = _find_key(item, keys)
            if nested is not None:
                return nested
    return None


def _money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")
