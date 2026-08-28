"""Canonical runtime identities for one C1-C3 direct-SQL attempt."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from .content_policy import ContentPolicy

DirectDevelopmentScope = Literal["train", "dev-a", "dev-b"]
DirectRuntimeCondition = Literal["C1", "C2", "C3"]

_SCOPES = frozenset({"train", "dev-a", "dev-b"})
_CONDITIONS = frozenset({"C1", "C2", "C3"})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40,64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+/@-]{0,159}")
_DATABASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,127}")
_COMPONENT = re.compile(r"[a-z][a-z0-9_]{0,79}")
_PUBLIC_MANIFEST_PATH = "data/manifests/eligible_questions.jsonl"
_SCOPE_PATHS = {
    "train": "data/manifests/train_ids.txt",
    "dev-a": "data/manifests/dev_a_ids.txt",
    "dev-b": "data/manifests/dev_b_ids.txt",
}
_QUESTION_FIELDS = frozenset(
    {
        "instance_id",
        "public_manifest_path",
        "public_manifest_sha256",
        "public_record_sha256",
        "question",
        "question_sha256",
        "scope",
        "scope_ids_path",
        "scope_ids_sha256",
        "selected_database",
    }
)
_DATABASE_FIELDS = frozenset(
    {
        "backend",
        "connection_target_sha256",
        "content_sha256",
        "database_record_sha256",
        "deployment_identity_sha256",
        "inventory_sha256",
        "physical_database",
        "postgres_server_version_num",
        "runtime_role",
        "schema_sha256",
        "selected_database",
    }
)
_RUNTIME_FIELDS = frozenset(
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
        "system_commit",
    }
)


class DirectRuntimeIdentityError(ValueError):
    """Raised when a direct runtime identity is ambiguous or unsafe."""


def _canonical_bytes(value: object) -> bytes:
    _require_finite_json(value)
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise DirectRuntimeIdentityError("identity must contain strict JSON") from error
    return (encoded + "\n").encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_finite_json(value: object) -> None:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise DirectRuntimeIdentityError("identity must contain strict JSON")
        for nested in value.values():
            _require_finite_json(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _require_finite_json(nested)
    elif isinstance(value, float) and not math.isfinite(value):
        raise DirectRuntimeIdentityError("identity must contain finite JSON")
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise DirectRuntimeIdentityError("identity must contain strict JSON")


def _exact_mapping(
    value: object, fields: frozenset[str], description: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise DirectRuntimeIdentityError(f"{description} must use the exact schema")
    _require_finite_json(value)
    return value


def _safe(value: object, environment: Mapping[str, str]) -> None:
    policy = ContentPolicy.from_environment(environment)
    if policy.sanitize_json(value) != value:
        raise DirectRuntimeIdentityError("identity contains sensitive content")


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DirectRuntimeIdentityError(f"{name} must be a non-empty string")
    return value


def _identifier(value: object, name: str) -> str:
    selected = _text(value, name)
    if _IDENTIFIER.fullmatch(selected) is None:
        raise DirectRuntimeIdentityError(f"{name} is invalid")
    return selected


def _database_name(value: object, name: str) -> str:
    selected = _text(value, name)
    if _DATABASE.fullmatch(selected) is None:
        raise DirectRuntimeIdentityError(f"{name} is invalid")
    return selected


def _sha256(value: object, name: str) -> str:
    selected = _text(value, name)
    if _SHA256.fullmatch(selected) is None:
        raise DirectRuntimeIdentityError(f"{name} must be a lowercase SHA-256")
    return selected


def _relative_path(value: object, name: str) -> str:
    selected = _text(value, name)
    path = PurePosixPath(selected)
    if (
        path.is_absolute()
        or path.as_posix() != selected
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise DirectRuntimeIdentityError(f"{name} must be a canonical relative path")
    return selected


@dataclass(frozen=True)
class DirectQuestionIdentity:
    """One exact public benchmark question bound to a development scope."""

    scope: DirectDevelopmentScope
    instance_id: str
    selected_database: str
    question: str
    question_sha256: str
    public_manifest_path: str
    public_manifest_sha256: str
    public_record_sha256: str
    scope_ids_path: str
    scope_ids_sha256: str

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> DirectQuestionIdentity:
        materialized = _exact_mapping(value, _QUESTION_FIELDS, "question identity")
        _safe(materialized, os.environ if environment is None else environment)
        scope = materialized["scope"]
        if scope not in _SCOPES:
            raise DirectRuntimeIdentityError("scope must be train, dev-a, or dev-b")
        question = _text(materialized["question"], "question")
        question_sha256 = _sha256(materialized["question_sha256"], "question_sha256")
        if hashlib.sha256(question.encode("utf-8")).hexdigest() != question_sha256:
            raise DirectRuntimeIdentityError("question_sha256 does not match question")
        public_path = _relative_path(
            materialized["public_manifest_path"], "public_manifest_path"
        )
        if public_path != _PUBLIC_MANIFEST_PATH:
            raise DirectRuntimeIdentityError("public_manifest_path is not canonical")
        scope_path = _relative_path(materialized["scope_ids_path"], "scope_ids_path")
        if scope_path != _SCOPE_PATHS[scope]:
            raise DirectRuntimeIdentityError("scope_ids_path does not match scope")
        return cls(
            scope=scope,
            instance_id=_identifier(materialized["instance_id"], "instance_id"),
            selected_database=_database_name(
                materialized["selected_database"], "selected_database"
            ),
            question=question,
            question_sha256=question_sha256,
            public_manifest_path=public_path,
            public_manifest_sha256=_sha256(
                materialized["public_manifest_sha256"], "public_manifest_sha256"
            ),
            public_record_sha256=_sha256(
                materialized["public_record_sha256"], "public_record_sha256"
            ),
            scope_ids_path=scope_path,
            scope_ids_sha256=_sha256(
                materialized["scope_ids_sha256"], "scope_ids_sha256"
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "instance_id": self.instance_id,
            "public_manifest_path": self.public_manifest_path,
            "public_manifest_sha256": self.public_manifest_sha256,
            "public_record_sha256": self.public_record_sha256,
            "question": self.question,
            "question_sha256": self.question_sha256,
            "scope": self.scope,
            "scope_ids_path": self.scope_ids_path,
            "scope_ids_sha256": self.scope_ids_sha256,
            "selected_database": self.selected_database,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class DirectContextIdentity:
    """Condition-scoped public context components and their derived digest."""

    condition: DirectRuntimeCondition
    selected_database: str
    component_sha256: tuple[tuple[str, str], ...]
    context_sha256: str

    @classmethod
    def from_components(
        cls,
        *,
        condition: str,
        selected_database: str,
        component_sha256: Mapping[str, str],
        environment: Mapping[str, str] | None = None,
    ) -> DirectContextIdentity:
        if condition not in _CONDITIONS:
            raise DirectRuntimeIdentityError("context condition is invalid")
        database = _database_name(selected_database, "context selected_database")
        components = _component_items(component_sha256)
        core = {
            "component_sha256": dict(components),
            "condition": condition,
            "selected_database": database,
        }
        _safe(core, os.environ if environment is None else environment)
        return cls(condition, database, components, _digest(core))

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> DirectContextIdentity:
        fields = frozenset(
            {"component_sha256", "condition", "context_sha256", "selected_database"}
        )
        materialized = _exact_mapping(value, fields, "context identity")
        expected = _sha256(materialized["context_sha256"], "context_sha256")
        context = cls.from_components(
            condition=materialized["condition"],
            selected_database=materialized["selected_database"],
            component_sha256=materialized["component_sha256"],
            environment=environment,
        )
        if context.context_sha256 != expected:
            raise DirectRuntimeIdentityError("context_sha256 does not match components")
        return context

    def as_dict(self) -> dict[str, object]:
        return {
            "component_sha256": dict(self.component_sha256),
            "condition": self.condition,
            "context_sha256": self.context_sha256,
            "selected_database": self.selected_database,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _component_items(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping) or not value:
        raise DirectRuntimeIdentityError("component_sha256 must be a non-empty object")
    items: list[tuple[str, str]] = []
    for name, digest in value.items():
        if not isinstance(name, str) or _COMPONENT.fullmatch(name) is None:
            raise DirectRuntimeIdentityError("context component name is invalid")
        items.append((name, _sha256(digest, f"component {name} SHA-256")))
    return tuple(sorted(items))


@dataclass(frozen=True)
class DirectDatabaseIdentity:
    """Credential-free identity of the exact attested PostgreSQL deployment."""

    backend: str
    selected_database: str
    physical_database: str
    runtime_role: str
    postgres_server_version_num: int
    inventory_sha256: str
    database_record_sha256: str
    deployment_identity_sha256: str
    connection_target_sha256: str
    schema_sha256: str
    content_sha256: str

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> DirectDatabaseIdentity:
        materialized = _exact_mapping(value, _DATABASE_FIELDS, "database identity")
        _safe(materialized, os.environ if environment is None else environment)
        if materialized["backend"] != "postgresql":
            raise DirectRuntimeIdentityError("backend must equal postgresql")
        server_version = materialized["postgres_server_version_num"]
        if type(server_version) is not int or server_version <= 0:
            raise DirectRuntimeIdentityError("PostgreSQL server version is invalid")
        return cls(
            backend="postgresql",
            selected_database=_database_name(
                materialized["selected_database"], "selected_database"
            ),
            physical_database=_database_name(
                materialized["physical_database"], "physical_database"
            ),
            runtime_role=_identifier(materialized["runtime_role"], "runtime_role"),
            postgres_server_version_num=server_version,
            inventory_sha256=_sha256(
                materialized["inventory_sha256"], "inventory SHA-256"
            ),
            database_record_sha256=_sha256(
                materialized["database_record_sha256"], "database record SHA-256"
            ),
            deployment_identity_sha256=_sha256(
                materialized["deployment_identity_sha256"],
                "deployment identity SHA-256",
            ),
            connection_target_sha256=_sha256(
                materialized["connection_target_sha256"],
                "connection target SHA-256",
            ),
            schema_sha256=_sha256(materialized["schema_sha256"], "schema SHA-256"),
            content_sha256=_sha256(materialized["content_sha256"], "content SHA-256"),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "connection_target_sha256": self.connection_target_sha256,
            "content_sha256": self.content_sha256,
            "database_record_sha256": self.database_record_sha256,
            "deployment_identity_sha256": self.deployment_identity_sha256,
            "inventory_sha256": self.inventory_sha256,
            "physical_database": self.physical_database,
            "postgres_server_version_num": self.postgres_server_version_num,
            "runtime_role": self.runtime_role,
            "schema_sha256": self.schema_sha256,
            "selected_database": self.selected_database,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class DirectModelIdentity:
    """Exact provider, model, adapter, executable, prompt, and transport pins."""

    provider: str
    model: str
    adapter: str
    adapter_version: str
    executable_sha256: str
    executable_version: str
    system_prompt_sha256: str
    transport_config_sha256: str

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> DirectModelIdentity:
        fields = frozenset(
            {
                "adapter",
                "adapter_version",
                "executable_sha256",
                "executable_version",
                "model",
                "provider",
                "system_prompt_sha256",
                "transport_config_sha256",
            }
        )
        materialized = _exact_mapping(value, fields, "model identity")
        _safe(materialized, os.environ if environment is None else environment)
        return cls(
            provider=_identifier(materialized["provider"], "provider"),
            model=_identifier(materialized["model"], "model"),
            adapter=_identifier(materialized["adapter"], "adapter"),
            adapter_version=_identifier(
                materialized["adapter_version"], "adapter_version"
            ),
            executable_sha256=_sha256(
                materialized["executable_sha256"], "executable SHA-256"
            ),
            executable_version=_identifier(
                materialized["executable_version"], "executable_version"
            ),
            system_prompt_sha256=_sha256(
                materialized["system_prompt_sha256"], "system prompt SHA-256"
            ),
            transport_config_sha256=_sha256(
                materialized["transport_config_sha256"],
                "transport config SHA-256",
            ),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "adapter": self.adapter,
            "adapter_version": self.adapter_version,
            "executable_sha256": self.executable_sha256,
            "executable_version": self.executable_version,
            "model": self.model,
            "provider": self.provider,
            "system_prompt_sha256": self.system_prompt_sha256,
            "transport_config_sha256": self.transport_config_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class DirectBudgetIdentity:
    """Pre-run turn, time, and cost ceilings for one model invocation."""

    budget_id: str
    maximum_turns: int
    per_turn_timeout_seconds: float
    per_turn_max_cost_usd: float

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> DirectBudgetIdentity:
        fields = frozenset(
            {
                "budget_id",
                "maximum_turns",
                "per_turn_max_cost_usd",
                "per_turn_timeout_seconds",
            }
        )
        materialized = _exact_mapping(value, fields, "budget identity")
        _safe(materialized, os.environ if environment is None else environment)
        maximum_turns = materialized["maximum_turns"]
        if type(maximum_turns) is not int or maximum_turns <= 0:
            raise DirectRuntimeIdentityError("maximum_turns must be positive")
        timeout = _positive_float(
            materialized["per_turn_timeout_seconds"], "per-turn timeout"
        )
        cost = _positive_float(
            materialized["per_turn_max_cost_usd"], "per-turn maximum cost"
        )
        return cls(
            budget_id=_identifier(materialized["budget_id"], "budget_id"),
            maximum_turns=maximum_turns,
            per_turn_timeout_seconds=timeout,
            per_turn_max_cost_usd=cost,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "budget_id": self.budget_id,
            "maximum_turns": self.maximum_turns,
            "per_turn_max_cost_usd": self.per_turn_max_cost_usd,
            "per_turn_timeout_seconds": self.per_turn_timeout_seconds,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _positive_float(value: object, name: str) -> float:
    if type(value) is not float or not math.isfinite(value) or value <= 0:
        raise DirectRuntimeIdentityError(f"{name} must be a positive finite float")
    return value


def _runtime_scalars(
    value: Mapping[str, Any],
) -> tuple[str, DirectRuntimeCondition, str, int]:
    if value["schema_version"] != 1:
        raise DirectRuntimeIdentityError("schema_version must equal 1")
    condition = value["condition"]
    if condition not in _CONDITIONS:
        raise DirectRuntimeIdentityError("condition must be C1, C2, or C3")
    commit = value["system_commit"]
    if not isinstance(commit, str) or _COMMIT.fullmatch(commit) is None:
        raise DirectRuntimeIdentityError("system_commit is invalid")
    repetition = value["repetition"]
    if type(repetition) is not int or repetition <= 0:
        raise DirectRuntimeIdentityError("repetition must be positive")
    return commit, condition, _identifier(value["run_id"], "run_id"), repetition


def _validate_runtime_relationships(
    value: Mapping[str, Any],
    condition: DirectRuntimeCondition,
    run_id: str,
    repetition: int,
    question: DirectQuestionIdentity,
    context: DirectContextIdentity,
    database: DirectDatabaseIdentity,
) -> str:
    if context.condition != condition:
        raise DirectRuntimeIdentityError("context condition does not match condition")
    if database.selected_database != question.selected_database:
        raise DirectRuntimeIdentityError(
            "database identity does not match question database"
        )
    if context.selected_database != question.selected_database:
        raise DirectRuntimeIdentityError(
            "context database does not match question database"
        )
    attempt = _attempt_id(run_id, question.instance_id, condition, repetition)
    if value["attempt_id"] != attempt:
        raise DirectRuntimeIdentityError("attempt_id does not match runtime identity")
    return attempt


@dataclass(frozen=True)
class DirectRuntimeBinding:
    """Exact immutable inputs that authorize one direct comparator attempt."""

    schema_version: int
    system_commit: str
    run_id: str
    repetition: int
    condition: DirectRuntimeCondition
    attempt_id: str
    question: DirectQuestionIdentity
    context: DirectContextIdentity
    database: DirectDatabaseIdentity
    model: DirectModelIdentity
    budget: DirectBudgetIdentity

    @classmethod
    def from_parts(
        cls,
        *,
        system_commit: str,
        run_id: str,
        repetition: int,
        condition: str,
        question: DirectQuestionIdentity,
        context: DirectContextIdentity,
        database: DirectDatabaseIdentity,
        model: DirectModelIdentity,
        budget: DirectBudgetIdentity,
        environment: Mapping[str, str] | None = None,
    ) -> DirectRuntimeBinding:
        attempt_id = _attempt_id(run_id, question.instance_id, condition, repetition)
        value = {
            "attempt_id": attempt_id,
            "budget": budget.as_dict(),
            "condition": condition,
            "context": context.as_dict(),
            "database": database.as_dict(),
            "model": model.as_dict(),
            "question": question.as_dict(),
            "repetition": repetition,
            "run_id": run_id,
            "schema_version": 1,
            "system_commit": system_commit,
        }
        return cls.from_dict(value, environment=environment)

    @classmethod
    def from_dict(
        cls,
        value: object,
        *,
        environment: Mapping[str, str] | None = None,
    ) -> DirectRuntimeBinding:
        materialized = _exact_mapping(value, _RUNTIME_FIELDS, "runtime binding")
        selected_environment = os.environ if environment is None else environment
        _safe(materialized, selected_environment)
        commit, condition, run_id, repetition = _runtime_scalars(materialized)
        question = DirectQuestionIdentity.from_dict(
            materialized["question"], environment=selected_environment
        )
        context = DirectContextIdentity.from_dict(
            materialized["context"], environment=selected_environment
        )
        database = DirectDatabaseIdentity.from_dict(
            materialized["database"], environment=selected_environment
        )
        model = DirectModelIdentity.from_dict(
            materialized["model"], environment=selected_environment
        )
        budget = DirectBudgetIdentity.from_dict(
            materialized["budget"], environment=selected_environment
        )
        expected_attempt = _validate_runtime_relationships(
            materialized, condition, run_id, repetition, question, context, database
        )
        return cls(
            schema_version=1,
            system_commit=commit,
            run_id=run_id,
            repetition=repetition,
            condition=condition,
            attempt_id=expected_attempt,
            question=question,
            context=context,
            database=database,
            model=model,
            budget=budget,
        )

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
            "system_commit": self.system_commit,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.as_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _attempt_id(
    run_id: object, instance_id: object, condition: object, repetition: object
) -> str:
    selected_run = _identifier(run_id, "run_id")
    selected_instance = _identifier(instance_id, "instance_id")
    if condition not in _CONDITIONS:
        raise DirectRuntimeIdentityError("condition must be C1, C2, or C3")
    if type(repetition) is not int or repetition <= 0:
        raise DirectRuntimeIdentityError("repetition must be positive")
    return f"{selected_run}:{selected_instance}:{condition}:{repetition}"
