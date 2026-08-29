"""Sealed-only C1-C3 identity, capture authority, and record projection."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from .artifact_store import (
    ALLOWED_RAW_ROOTS,
    ArtifactStore,
    ArtifactStoreError,
    StoredArtifact,
)
from .content_policy import ContentPolicy
from .direct_capture_binding import (
    DirectCaptureBindingError,
    validate_database_transport,
    validate_model_transport,
    validate_public_tools,
)
from .direct_capture_contract import (
    DirectDatabaseTransport,
    DirectModelTransport,
    DirectProbeResult,
    DirectPublicTools,
)
from .direct_capture_receipt import capture_summary_from_probe
from .direct_runtime_binding import (
    DirectBudgetIdentity,
    DirectContextIdentity,
    DirectDatabaseIdentity,
    DirectModelIdentity,
    DirectRuntimeIdentityError,
)
from .direct_sql_attempt import (
    _attempt_record,
    _read_stored_artifact,
    _validate_action_evidence_artifact,
    _validate_attempt_measurements,
    _validate_generated_sql,
    _validate_probe_outcome,
    _validate_result_artifact,
    _validate_root_binding,
    _validate_trace_artifact,
)
from .direct_sql_capture import DirectCaptureError, DirectSqlCapture
from .freeze_b import FreezeBCondition
from .protected_fields import ProtectedFieldError, reject_protected_fields
from .sealed_dispatch import SealedAdapterResult, SealedDispatchPolicy
from .sealed_generation_staging import (
    SealedGenerationStagingError,
    SealedPreparedAttempt,
    _validated_prepared,
)

SealedDirectCondition = Literal["C1", "C2", "C3"]
SealedDirectCaptureFactory = Callable[
    [SealedPreparedAttempt, ArtifactStore],
    AbstractContextManager["SealedDirectPreparedCapture"],
]

_AUTHORITY_KEY = secrets.token_bytes(32)
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")
_CONDITIONS = frozenset({"C1", "C2", "C3"})
_QUESTION_FIELDS = frozenset(
    {"instance_id", "question", "question_sha256", "scope", "selected_database"}
)
_AUTHORITY_FIELDS = frozenset(
    {
        "condition_binding_sha256",
        "control_commit",
        "freeze_b_sha256",
        "plan_sha256",
        "schedule_sha256",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "attempt_id",
        "budget",
        "condition",
        "context",
        "database",
        "model",
        "question",
        "repetition",
        "run_id",
        "schema_version",
        "sealed_authority",
        "system_commit",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "action_evidence_path",
        "action_evidence_sha256",
        "artifact_root_identity",
        "attempt_id",
        "capture_summary",
        "generated_sql_sha256",
        "kind",
        "result_path",
        "result_sha256",
        "runtime_binding",
        "runtime_binding_sha256",
        "schema_version",
        "trace_path",
        "trace_sha256",
    }
)


class SealedDirectAdapterError(RuntimeError):
    """Raised when a sealed direct attempt loses an exact authority boundary."""


@dataclass(frozen=True)
class SealedDirectQuestionIdentity:
    """One exact public test question, unavailable to development loaders."""

    instance_id: str
    selected_database: str
    question: str = field(repr=False)
    question_sha256: str
    scope: Literal["test"] = "test"

    @classmethod
    def from_dict(cls, value: object) -> SealedDirectQuestionIdentity:
        if not isinstance(value, Mapping) or set(value) != _QUESTION_FIELDS:
            raise SealedDirectAdapterError("sealed question identity schema is invalid")
        if value["scope"] != "test":
            raise SealedDirectAdapterError("sealed question scope must equal test")
        instance_id = _identifier(value["instance_id"], "instance_id")
        database = _identifier(value["selected_database"], "selected_database")
        question = value["question"]
        digest = _sha256(value["question_sha256"], "question_sha256")
        if (
            not isinstance(question, str)
            or not question
            or hashlib.sha256(question.encode()).hexdigest() != digest
        ):
            raise SealedDirectAdapterError("sealed question identity is invalid")
        _safe(value)
        return cls(instance_id, database, question, digest)

    def as_dict(self) -> dict[str, object]:
        return {
            "instance_id": self.instance_id,
            "question": self.question,
            "question_sha256": self.question_sha256,
            "scope": self.scope,
            "selected_database": self.selected_database,
        }


@dataclass(frozen=True)
class SealedDirectRuntimeBinding:
    """Exact C1-C3 runtime plus the plan and Freeze-B authority that selected it."""

    schema_version: int
    system_commit: str
    run_id: str
    repetition: int
    condition: SealedDirectCondition
    attempt_id: str
    question: SealedDirectQuestionIdentity
    context: DirectContextIdentity
    database: DirectDatabaseIdentity
    model: DirectModelIdentity
    budget: DirectBudgetIdentity
    sealed_authority: Mapping[str, str]

    @classmethod
    def from_prepared(
        cls,
        *,
        prepared: SealedPreparedAttempt,
        context: DirectContextIdentity,
        database: DirectDatabaseIdentity,
        model: DirectModelIdentity,
        budget: DirectBudgetIdentity,
        environment: Mapping[str, str] | None = None,
    ) -> SealedDirectRuntimeBinding:
        value = _validated_sealed_prepared(prepared)
        binding = cls(
            schema_version=1,
            system_commit=value.system_commit,
            run_id=value.cohort_id,
            repetition=value.repetition,
            condition=cast(SealedDirectCondition, value.condition),
            attempt_id=value.attempt_id,
            question=SealedDirectQuestionIdentity.from_dict(
                {
                    "instance_id": value.instance_id,
                    "question": value.question,
                    "question_sha256": value.question_sha256,
                    "scope": "test",
                    "selected_database": value.database,
                }
            ),
            context=_canonical_identity(context, DirectContextIdentity, "context"),
            database=_canonical_identity(database, DirectDatabaseIdentity, "database"),
            model=_canonical_identity(model, DirectModelIdentity, "model"),
            budget=_canonical_identity(budget, DirectBudgetIdentity, "budget"),
            sealed_authority=MappingProxyType(
                {
                    "condition_binding_sha256": _condition_sha256(
                        value.condition_binding
                    ),
                    "control_commit": value.control_commit,
                    "freeze_b_sha256": value.freeze_b_sha256,
                    "plan_sha256": value.plan_sha256,
                    "schedule_sha256": value.schedule_sha256,
                }
            ),
        )
        return _validated_binding(binding, environment=environment)

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> SealedDirectRuntimeBinding:
        if not isinstance(value, Mapping) or set(value) != _BINDING_FIELDS:
            raise SealedDirectAdapterError("sealed direct runtime schema is invalid")
        authority = value["sealed_authority"]
        if not isinstance(authority, Mapping) or set(authority) != _AUTHORITY_FIELDS:
            raise SealedDirectAdapterError("sealed runtime authority schema is invalid")
        condition = value["condition"]
        repetition = value["repetition"]
        if (
            value["schema_version"] != 1
            or condition not in _CONDITIONS
            or type(repetition) is not int
            or repetition not in (1, 2, 3)
        ):
            raise SealedDirectAdapterError("sealed direct runtime scalars are invalid")
        system_commit = value["system_commit"]
        if (
            not isinstance(system_commit, str)
            or _COMMIT.fullmatch(system_commit) is None
        ):
            raise SealedDirectAdapterError("sealed direct system commit is invalid")
        parsed = cls(
            schema_version=1,
            system_commit=system_commit,
            run_id=_identifier(value["run_id"], "run_id"),
            repetition=repetition,
            condition=cast(SealedDirectCondition, condition),
            attempt_id=_identifier(value["attempt_id"], "attempt_id"),
            question=SealedDirectQuestionIdentity.from_dict(value["question"]),
            context=DirectContextIdentity.from_dict(
                value["context"], environment=environment
            ),
            database=DirectDatabaseIdentity.from_dict(
                value["database"], environment=environment
            ),
            model=DirectModelIdentity.from_dict(
                value["model"], environment=environment
            ),
            budget=DirectBudgetIdentity.from_dict(
                value["budget"], environment=environment
            ),
            sealed_authority=MappingProxyType(
                {
                    key: (
                        _commit(item, key)
                        if key == "control_commit"
                        else _sha256(item, key)
                    )
                    for key, item in authority.items()
                }
            ),
        )
        return _validated_binding(parsed, environment=environment, reparse=False)

    def as_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "budget": self.budget.as_dict(),
            "condition": self.condition,
            "context": self.context.as_dict(),
            "database": self.database.as_dict(),
            "model": self.model.as_dict(),
            "question": self.question.as_dict(),
            "repetition": self.repetition,
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "sealed_authority": dict(self.sealed_authority),
            "system_commit": self.system_commit,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True, init=False)
class SealedDirectPreparedCapture:
    """Opaque authority for one sealed direct capture and its live dependencies."""

    sealed_attempt: SealedPreparedAttempt
    binding: SealedDirectRuntimeBinding
    model_transport: DirectModelTransport
    database: DirectDatabaseTransport
    public_tools: DirectPublicTools
    store: ArtifactStore
    _authorization: str

    def __init__(self) -> None:
        raise TypeError("sealed direct capture authority is minted only by preflight")


def prepare_sealed_direct_capture(
    *,
    prepared: SealedPreparedAttempt,
    binding: SealedDirectRuntimeBinding,
    model_transport: DirectModelTransport,
    database: DirectDatabaseTransport,
    public_tools: DirectPublicTools,
    store: ArtifactStore,
) -> SealedDirectPreparedCapture:
    """Mint capture authority only after exact sealed and live identities agree."""
    sealed = _validated_sealed_prepared(prepared)
    canonical = _validated_binding(binding)
    _require_prepared_binding(sealed, canonical)
    _require_freeze_b_identity(sealed.condition_binding, canonical)
    if type(store) is not ArtifactStore:
        raise SealedDirectAdapterError("sealed direct artifact store is invalid")
    try:
        validate_model_transport(cast(Any, canonical), model_transport)
        validate_database_transport(cast(Any, canonical), database)
        validate_public_tools(cast(Any, canonical), public_tools)
    except DirectCaptureBindingError as error:
        raise SealedDirectAdapterError(str(error)) from error
    value = object.__new__(SealedDirectPreparedCapture)
    object.__setattr__(value, "sealed_attempt", sealed)
    object.__setattr__(value, "binding", canonical)
    object.__setattr__(value, "model_transport", model_transport)
    object.__setattr__(value, "database", database)
    object.__setattr__(value, "public_tools", public_tools)
    object.__setattr__(value, "store", store)
    object.__setattr__(value, "_authorization", "")
    object.__setattr__(value, "_authorization", _capture_authorization(value))
    return value


def validate_sealed_direct_capture(
    value: object,
) -> SealedDirectPreparedCapture:
    if type(value) is not SealedDirectPreparedCapture:
        raise SealedDirectAdapterError("sealed direct capture authority is required")
    if not hmac.compare_digest(value._authorization, _capture_authorization(value)):
        raise SealedDirectAdapterError("sealed direct capture is not authorized")
    sealed = _validated_sealed_prepared(value.sealed_attempt)
    binding = _validated_binding(value.binding)
    _require_prepared_binding(sealed, binding)
    _require_freeze_b_identity(sealed.condition_binding, binding)
    try:
        validate_model_transport(cast(Any, binding), value.model_transport)
        validate_database_transport(cast(Any, binding), value.database)
        validate_public_tools(cast(Any, binding), value.public_tools)
    except DirectCaptureBindingError as error:
        raise SealedDirectAdapterError(str(error)) from error
    if type(value.store) is not ArtifactStore:
        raise SealedDirectAdapterError("sealed direct artifact store is invalid")
    return value


class SealedDirectSqlCapture(DirectSqlCapture):
    """Reuse direct capture mechanics under an independently sealed authority."""

    def __init__(self, *, prepared: SealedDirectPreparedCapture) -> None:
        try:
            authority = validate_sealed_direct_capture(prepared)
        except SealedDirectAdapterError as error:
            raise DirectCaptureError(str(error)) from error
        self._initialize_authorized(authority)

    def _revalidate_prepared(self) -> None:
        try:
            validate_sealed_direct_capture(self._prepared)
        except SealedDirectAdapterError as error:
            raise DirectCaptureError(str(error)) from error

    def _write_receipt(
        self,
        sql: str | None,
        trace: StoredArtifact,
        action_evidence: StoredArtifact,
        result: StoredArtifact | None,
        summary: Mapping[str, Any],
    ) -> StoredArtifact:
        payload = {
            "action_evidence_path": self._store.relative_path(
                action_evidence
            ).as_posix(),
            "action_evidence_sha256": action_evidence.sha256,
            "artifact_root_identity": self._store.root_identity,
            "attempt_id": self._binding.attempt_id,
            "capture_summary": dict(summary),
            "generated_sql_sha256": (
                None if sql is None else hashlib.sha256(sql.encode()).hexdigest()
            ),
            "kind": "sealed-direct-capture-receipt",
            "result_path": (
                None if result is None else self._store.relative_path(result).as_posix()
            ),
            "result_sha256": None if result is None else result.sha256,
            "runtime_binding": self._binding.as_dict(),
            "runtime_binding_sha256": self._binding.sha256(),
            "schema_version": 1,
            "trace_path": self._store.relative_path(trace).as_posix(),
            "trace_sha256": trace.sha256,
        }
        reject_protected_fields(payload)
        _safe(payload)
        return self._store.write_json(Path("capture.receipt.json"), payload)


class SealedDirectConditionAdapter:
    """Execute and project one sealed C1-C3 attempt after dispatcher approval."""

    def __init__(
        self,
        *,
        workspace: Path,
        capture_root: Path,
        condition_binding: FreezeBCondition,
        policy: SealedDispatchPolicy,
        capture_factory: SealedDirectCaptureFactory,
    ) -> None:
        if (
            type(condition_binding) is not FreezeBCondition
            or condition_binding.condition not in _CONDITIONS
        ):
            raise SealedDirectAdapterError("sealed direct adapter identity is invalid")
        if type(policy) is not SealedDispatchPolicy or (
            SealedDispatchPolicy.from_dict(policy.as_dict()) != policy
        ):
            raise SealedDirectAdapterError("sealed direct adapter policy is invalid")
        if not callable(capture_factory):
            raise SealedDirectAdapterError("sealed direct capture factory is invalid")
        self._workspace = _workspace_root(workspace)
        self._capture_root = _capture_root(capture_root)
        self._condition_binding = condition_binding
        self._policy = policy
        self._capture_factory = capture_factory

    @property
    def condition_binding(self) -> FreezeBCondition:
        return self._condition_binding

    def execute(self, prepared: SealedPreparedAttempt) -> SealedAdapterResult:
        sealed = _validated_sealed_prepared(prepared)
        if (
            sealed.condition != self.condition_binding.condition
            or sealed.condition_binding != self.condition_binding
        ):
            raise SealedDirectAdapterError(
                "sealed direct adapter requires exact condition identity"
            )
        store = self._new_capture_store(sealed)
        try:
            with self._capture_factory(sealed, store) as authority:
                probe = SealedDirectSqlCapture(prepared=authority).capture()
                record = build_sealed_direct_generation_record(
                    workspace=self._workspace,
                    prepared=sealed,
                    authority=authority,
                    probe=probe,
                )
        except SealedDirectAdapterError:
            raise
        except Exception as error:
            raise SealedDirectAdapterError("sealed direct capture failed") from error
        return SealedAdapterResult(generation_record=record)

    def _new_capture_store(self, prepared: SealedPreparedAttempt) -> ArtifactStore:
        relative = self._capture_root / (
            f"{prepared.database}/{prepared.condition.lower()}/"
            f"{prepared.instance_id}-r{prepared.repetition}/"
            f"capture-{secrets.token_hex(12)}"
        )
        try:
            return ArtifactStore(
                self._workspace,
                relative,
                require_new_root=True,
            )
        except ArtifactStoreError as error:
            raise SealedDirectAdapterError(
                "sealed direct capture root could not be created"
            ) from error


def build_sealed_direct_generation_record(
    *,
    workspace: Path,
    prepared: SealedPreparedAttempt,
    authority: SealedDirectPreparedCapture,
    probe: DirectProbeResult,
) -> dict[str, object]:
    """Project one validated capture into the unscored sealed staging contract."""
    sealed = _validated_sealed_prepared(prepared)
    capture = validate_sealed_direct_capture(authority)
    if not isinstance(probe, DirectProbeResult):
        raise SealedDirectAdapterError("sealed direct probe result is invalid")
    binding = capture.binding
    _require_prepared_binding(sealed, binding)
    expected = {
        "attempt_id": binding.attempt_id,
        "condition": binding.condition,
        "maximum_turns": binding.budget.maximum_turns,
        "model": binding.model.model,
        "provider": binding.model.provider,
        "question_sha256": binding.question.question_sha256,
    }
    if (
        probe.binding != binding
        or probe.binding.sha256() != binding.sha256()
        or any(getattr(probe, key) != item for key, item in expected.items())
    ):
        raise SealedDirectAdapterError("sealed direct probe binding does not match")
    if probe.failure_origin == "benchmark_infrastructure":
        raise SealedDirectAdapterError(
            "sealed direct benchmark infrastructure failure remains unstaged"
        )
    _validate_capture_artifacts(workspace, capture.store, probe)
    record = _attempt_record(
        workspace,
        cast(Any, None),
        cast(Any, binding),
        probe,
    )
    record.update(
        {
            "attempt_id": sealed.attempt_id,
            "condition": sealed.condition,
            "instance_id": sealed.instance_id,
            "partition": "test",
            "question": sealed.question,
            "repetition": sealed.repetition,
            "run_id": sealed.cohort_id,
            "runtime_binding_sha256": binding.sha256(),
        }
    )
    try:
        reject_protected_fields(record)
    except ProtectedFieldError as error:
        raise SealedDirectAdapterError(str(error)) from error
    _safe(record)
    return record


def _validated_binding(
    value: object,
    *,
    environment: Mapping[str, str] | None = None,
    reparse: bool = True,
) -> SealedDirectRuntimeBinding:
    if type(value) is not SealedDirectRuntimeBinding:
        raise SealedDirectAdapterError("sealed direct runtime binding is required")
    if reparse:
        parsed = SealedDirectRuntimeBinding.from_dict(
            value.as_dict(), environment=environment
        )
        if parsed != value or parsed.sha256() != value.sha256():
            raise SealedDirectAdapterError(
                "sealed direct runtime binding is not canonical"
            )
        return parsed
    if (
        value.question.selected_database != value.database.selected_database
        or value.question.selected_database != value.context.selected_database
        or value.condition != value.context.condition
        or value.attempt_id
        != f"sealed:{value.question.instance_id}:{value.condition}:{value.repetition}"
        or value.run_id != f"sealed-{value.condition.lower()}-r{value.repetition}"
    ):
        raise SealedDirectAdapterError("sealed direct runtime relationships differ")
    _safe(value.as_dict(), environment=environment)
    return value


def _validated_sealed_prepared(value: object) -> SealedPreparedAttempt:
    try:
        prepared = _validated_prepared(value)
    except SealedGenerationStagingError as error:
        raise SealedDirectAdapterError("sealed attempt authority is invalid") from error
    if prepared.condition not in _CONDITIONS:
        raise SealedDirectAdapterError("sealed direct condition must be C1, C2, or C3")
    return prepared


def _require_prepared_binding(
    prepared: SealedPreparedAttempt, binding: SealedDirectRuntimeBinding
) -> None:
    expected = {
        "attempt_id": prepared.attempt_id,
        "condition": prepared.condition,
        "repetition": prepared.repetition,
        "run_id": prepared.cohort_id,
        "system_commit": prepared.system_commit,
    }
    if any(getattr(binding, key) != item for key, item in expected.items()) or (
        binding.question.instance_id != prepared.instance_id
        or binding.question.selected_database != prepared.database
        or binding.question.question != prepared.question
        or binding.question.question_sha256 != prepared.question_sha256
    ):
        raise SealedDirectAdapterError("sealed attempt and runtime binding differ")
    authority = dict(binding.sealed_authority)
    expected_authority = {
        "condition_binding_sha256": _condition_sha256(prepared.condition_binding),
        "control_commit": prepared.control_commit,
        "freeze_b_sha256": prepared.freeze_b_sha256,
        "plan_sha256": prepared.plan_sha256,
        "schedule_sha256": prepared.schedule_sha256,
    }
    if authority != expected_authority:
        raise SealedDirectAdapterError("sealed plan or Freeze B binding differs")


def _require_freeze_b_identity(
    condition: FreezeBCondition, binding: SealedDirectRuntimeBinding
) -> None:
    components = dict(binding.context.component_sha256)
    semantic_component = {"C1": None, "C2": "hkb", "C3": "semantic_manifest"}[
        binding.condition
    ]
    semantic_sha = (
        None if semantic_component is None else components.get(semantic_component)
    )
    expected = {
        "budget_id": binding.budget.budget_id,
        "condition": binding.condition,
        "harness_config_sha256": components.get("condition_config"),
        "instructions_sha256": components.get("instructions"),
        "model": binding.model.model,
        "prompt_sha256": components.get("prompt"),
        "provider": binding.model.provider,
        "semantic_model_sha256": semantic_sha,
    }
    if any(getattr(condition, key) != item for key, item in expected.items()):
        raise SealedDirectAdapterError("direct runtime differs from Freeze B")


def _capture_authorization(value: SealedDirectPreparedCapture) -> str:
    payload = "\0".join(
        (
            value.sealed_attempt.plan_sha256,
            value.binding.sha256(),
            str(id(value.model_transport)),
            str(id(value.database)),
            str(id(value.public_tools)),
            str(id(value.store)),
            value.store.root_identity,
            _callable_identity(getattr(value.model_transport, "next_turn", None)),
            _callable_identity(getattr(value.database, "connect", None)),
            _callable_identity(getattr(value.public_tools, "render_question", None)),
        )
    ).encode()
    return hmac.new(_AUTHORITY_KEY, payload, hashlib.sha256).hexdigest()


def _validate_capture_artifacts(
    workspace: Path, store: ArtifactStore, probe: DirectProbeResult
) -> None:
    policy = ContentPolicy.from_environment(os.environ)
    try:
        _validate_root_binding(workspace, store, probe)
        _validate_probe_outcome(probe)
        _validate_generated_sql(probe, policy)
        _validate_trace_artifact(workspace, probe, policy)
        _validate_action_evidence_artifact(workspace, probe, policy)
        _validate_result_artifact(workspace, probe, policy)
        _validate_attempt_measurements(probe)
        content = _read_stored_artifact(workspace, probe.receipt, "capture receipt")
        receipt = json.loads(content)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise SealedDirectAdapterError("sealed direct artifacts are invalid") from error
    expected = {
        "action_evidence_path": store.relative_path(probe.action_evidence).as_posix(),
        "action_evidence_sha256": probe.action_evidence.sha256,
        "artifact_root_identity": store.root_identity,
        "attempt_id": probe.attempt_id,
        "capture_summary": capture_summary_from_probe(probe),
        "generated_sql_sha256": (
            None
            if probe.generated_sql is None
            else hashlib.sha256(probe.generated_sql.encode()).hexdigest()
        ),
        "kind": "sealed-direct-capture-receipt",
        "result_path": (
            None
            if probe.result_artifact is None
            else store.relative_path(probe.result_artifact).as_posix()
        ),
        "result_sha256": (
            None if probe.result_artifact is None else probe.result_artifact.sha256
        ),
        "runtime_binding": probe.binding.as_dict(),
        "runtime_binding_sha256": probe.binding.sha256(),
        "schema_version": 1,
        "trace_path": store.relative_path(probe.trace).as_posix(),
        "trace_sha256": probe.trace.sha256,
    }
    if (
        not isinstance(receipt, Mapping)
        or set(receipt) != _RECEIPT_FIELDS
        or receipt != expected
        or _canonical_bytes(receipt) != content
        or policy.sanitize_json(receipt) != receipt
    ):
        raise SealedDirectAdapterError("sealed direct receipt does not match capture")


def _canonical_identity(value: object, kind: type[Any], description: str) -> Any:
    if type(value) is not kind:
        raise SealedDirectAdapterError(f"sealed direct {description} is invalid")
    try:
        parsed = kind.from_dict(value.as_dict(), environment={})
    except (DirectRuntimeIdentityError, TypeError, ValueError) as error:
        raise SealedDirectAdapterError(
            f"sealed direct {description} is invalid"
        ) from error
    if parsed != value:
        raise SealedDirectAdapterError(f"sealed direct {description} is not canonical")
    return parsed


def _condition_sha256(value: FreezeBCondition) -> str:
    if type(value) is not FreezeBCondition:
        raise SealedDirectAdapterError("sealed direct condition binding is invalid")
    return hashlib.sha256(_canonical_bytes(value.as_dict())).hexdigest()


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
    ).encode()


def _safe(value: object, *, environment: Mapping[str, str] | None = None) -> None:
    policy = ContentPolicy.from_environment(
        os.environ if environment is None else environment
    )
    if policy.sanitize_json(value) != value:
        raise SealedDirectAdapterError("sealed direct content is sensitive")


def _sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SealedDirectAdapterError(f"{name} must be a lowercase SHA-256")
    return value


def _commit(value: object, name: str) -> str:
    if not isinstance(value, str) or _COMMIT.fullmatch(value) is None:
        raise SealedDirectAdapterError(f"{name} must be a full commit")
    return value


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise SealedDirectAdapterError(f"{name} is invalid")
    return value


def _callable_identity(value: object) -> str:
    if not callable(value):
        return "not-callable"
    return f"{id(getattr(value, '__self__', None))}:{id(getattr(value, '__func__', value))}"


def _workspace_root(workspace: Path) -> Path:
    absolute = workspace.absolute()
    try:
        resolved = workspace.resolve(strict=True)
    except OSError as error:
        raise SealedDirectAdapterError(
            "sealed direct workspace is unavailable"
        ) from error
    if absolute != resolved or workspace.is_symlink() or not resolved.is_dir():
        raise SealedDirectAdapterError("sealed direct workspace is unsafe")
    return resolved


def _capture_root(value: Path) -> Path:
    root = Path(value)
    if (
        root.is_absolute()
        or not root.parts
        or ".." in root.parts
        or not any(root.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS)
    ):
        raise SealedDirectAdapterError("sealed direct capture root is invalid")
    return root
