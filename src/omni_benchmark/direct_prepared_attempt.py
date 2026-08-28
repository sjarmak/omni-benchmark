"""Opaque authority for one fully bound direct-comparator attempt."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .artifact_store import ArtifactStore, ArtifactStoreError
from .claude_direct_contract import ClaudeDirectConfig
from .claude_direct_transport import ClaudeDirectTransport
from .direct_capture_binding import (
    validate_database_transport,
    validate_model_transport,
    validate_public_tools,
    validated_runtime_binding,
)
from .direct_capture_contract import (
    DirectDatabaseTransport,
    DirectModelTransport,
    DirectPublicTools,
)
from .direct_database_loader import (
    DirectDatabaseLoadError,
    load_committed_direct_database_identity,
)
from .direct_postgres import AttestedDirectPostgresTransport
from .direct_public_context import (
    DirectPublicContextError,
    DirectPublicTools as CommittedDirectPublicTools,
    load_direct_public_tools,
)
from .direct_question_loader import (
    DirectQuestionLoadError,
    load_committed_direct_question,
)
from .direct_runtime_binding import (
    DirectDatabaseIdentity,
    DirectQuestionIdentity,
    DirectRuntimeBinding,
    DirectRuntimeIdentityError,
)
from .omni_probe_preflight import OmniProbePreflightError, verify_system_commit

_AUTHORITY_KEY = secrets.token_bytes(32)


class DirectPreparedAttemptError(ValueError):
    """Raised when a prepared attempt was not minted by the trusted preflight."""


@dataclass(frozen=True, init=False)
class DirectPreparedAttempt:
    """Exact dependencies authorized for one immutable direct attempt."""

    binding: DirectRuntimeBinding
    model_transport: DirectModelTransport
    database: DirectDatabaseTransport
    public_tools: DirectPublicTools
    store: ArtifactStore
    _authorization: str

    def __init__(self) -> None:
        raise TypeError("DirectPreparedAttempt is created only by trusted preflight")


def prepare_committed_direct_attempt(
    *,
    workspace: Path,
    commit: str,
    scope: str,
    instance_id: str,
    condition: str,
    run_id: str,
    repetition: int,
    claude_config: ClaudeDirectConfig,
    database_environment: Mapping[str, str],
    store: ArtifactStore,
    environment: Mapping[str, str] | None = None,
) -> DirectPreparedAttempt:
    """Authorize one attempt solely from committed public inputs and exact adapters."""
    if scope != "dev-a":
        raise DirectPreparedAttemptError(
            "ordinary direct attempts are restricted to dev-A"
        )
    _verify_preparation_environment(workspace, commit, store)
    question, public_tools, database_identity = _load_attempt_inputs(
        workspace, commit, scope, instance_id, condition, environment
    )
    _require_database_alignment(question, public_tools, database_identity)
    model_transport, database = _construct_transports(
        claude_config, database_environment, database_identity
    )
    binding = _build_runtime_binding(
        commit,
        run_id,
        repetition,
        condition,
        question,
        public_tools,
        database_identity,
        model_transport,
        environment,
    )
    return _mint_prepared_attempt(
        binding, model_transport, database, public_tools, store
    )


def _verify_preparation_environment(
    workspace: Path, commit: str, store: ArtifactStore
) -> None:
    try:
        verify_system_commit(workspace, commit)
        _verify_runtime_package(workspace)
        if type(store) is not ArtifactStore:
            raise ArtifactStoreError("artifact store has the wrong type")
        store.require_workspace(workspace)
    except (ArtifactStoreError, OmniProbePreflightError) as error:
        raise DirectPreparedAttemptError(str(error)) from error


def _load_attempt_inputs(
    workspace: Path,
    commit: str,
    scope: str,
    instance_id: str,
    condition: str,
    environment: Mapping[str, str] | None,
) -> tuple[DirectQuestionIdentity, CommittedDirectPublicTools, DirectDatabaseIdentity]:
    try:
        question = load_committed_direct_question(
            workspace,
            commit,
            scope=scope,
            instance_id=instance_id,
            environment=environment,
        )
        public_tools = load_direct_public_tools(
            workspace,
            commit,
            question.selected_database,
            condition,
            environment=environment,
        )
        database_identity = load_committed_direct_database_identity(
            workspace,
            commit,
            selected_database=question.selected_database,
            environment=environment,
        )
    except (
        DirectDatabaseLoadError,
        DirectPublicContextError,
        DirectQuestionLoadError,
    ) as error:
        raise DirectPreparedAttemptError(str(error)) from error
    if type(public_tools) is not CommittedDirectPublicTools:
        raise DirectPreparedAttemptError("committed public context loader is required")
    return question, public_tools, database_identity


def _require_database_alignment(
    question: DirectQuestionIdentity,
    public_tools: CommittedDirectPublicTools,
    database_identity: DirectDatabaseIdentity,
) -> None:
    if not (
        question.selected_database
        == public_tools.identity.selected_database
        == database_identity.selected_database
    ):
        raise DirectPreparedAttemptError("committed runtime database identities differ")


def _construct_transports(
    claude_config: ClaudeDirectConfig,
    database_environment: Mapping[str, str],
    database_identity: DirectDatabaseIdentity,
) -> tuple[ClaudeDirectTransport, AttestedDirectPostgresTransport]:
    try:
        model_transport = ClaudeDirectTransport(claude_config)
        database = AttestedDirectPostgresTransport(
            database_environment,
            expected_identity=database_identity,
        )
    except Exception as error:
        raise DirectPreparedAttemptError(
            "direct model or database transport preflight failed"
        ) from error
    return model_transport, database


def _build_runtime_binding(
    commit: str,
    run_id: str,
    repetition: int,
    condition: str,
    question: DirectQuestionIdentity,
    public_tools: CommittedDirectPublicTools,
    database_identity: DirectDatabaseIdentity,
    model_transport: ClaudeDirectTransport,
    environment: Mapping[str, str] | None,
) -> DirectRuntimeBinding:
    try:
        binding = DirectRuntimeBinding.from_parts(
            system_commit=commit,
            run_id=run_id,
            repetition=repetition,
            condition=condition,
            question=question,
            context=public_tools.identity,
            database=database_identity,
            model=model_transport.runtime_identity,
            budget=model_transport.budget_identity,
            environment=environment,
        )
    except DirectRuntimeIdentityError as error:
        raise DirectPreparedAttemptError(
            f"committed runtime binding is invalid: {error}"
        ) from error
    canonical = validated_runtime_binding(binding)
    validate_model_transport(canonical, model_transport)
    return canonical


def _mint_prepared_attempt(
    binding: DirectRuntimeBinding,
    model_transport: DirectModelTransport,
    database: DirectDatabaseTransport,
    public_tools: CommittedDirectPublicTools,
    store: ArtifactStore,
) -> DirectPreparedAttempt:
    validate_database_transport(binding, database)
    validate_public_tools(binding, public_tools)
    if any(
        _transport_execution_authority(transport) == "invalid"
        for transport in (model_transport, database)
    ):
        raise DirectPreparedAttemptError(
            "committed transport execution authority is invalid"
        )
    value = object.__new__(DirectPreparedAttempt)
    object.__setattr__(value, "binding", binding)
    object.__setattr__(value, "model_transport", model_transport)
    object.__setattr__(value, "database", database)
    object.__setattr__(value, "public_tools", public_tools)
    object.__setattr__(value, "store", store)
    object.__setattr__(
        value,
        "_authorization",
        _authorization(binding, model_transport, database, public_tools, store),
    )
    return value


def _verify_runtime_package(workspace: Path) -> None:
    """Require this loaded module to come from the selected workspace source tree."""
    try:
        actual = Path(__file__).resolve(strict=True)
        expected = (
            workspace / "src/omni_benchmark/direct_prepared_attempt.py"
        ).resolve(strict=True)
    except OSError as error:
        raise OmniProbePreflightError(
            "direct comparator runtime package is unavailable"
        ) from error
    if actual != expected:
        raise OmniProbePreflightError(
            "direct comparator runtime package does not belong to the workspace"
        )


def validate_direct_prepared_attempt(value: object) -> DirectPreparedAttempt:
    """Recheck the opaque authority and all live dependency identities."""
    if type(value) is not DirectPreparedAttempt:
        raise DirectPreparedAttemptError("prepared direct attempt is required")
    expected = _authorization(
        value.binding,
        value.model_transport,
        value.database,
        value.public_tools,
        value.store,
    )
    if not hmac.compare_digest(value._authorization, expected):
        raise DirectPreparedAttemptError("prepared direct attempt is not authorized")
    binding = validated_runtime_binding(value.binding)
    validate_model_transport(binding, value.model_transport)
    validate_database_transport(binding, value.database)
    validate_public_tools(binding, value.public_tools)
    if type(value.store) is not ArtifactStore:
        raise DirectPreparedAttemptError("prepared artifact store is invalid")
    return value


def _authorization(
    binding: DirectRuntimeBinding,
    model_transport: DirectModelTransport,
    database: DirectDatabaseTransport,
    public_tools: DirectPublicTools,
    store: ArtifactStore,
) -> str:
    payload = "\0".join(
        (
            binding.sha256(),
            str(id(model_transport)),
            str(id(database)),
            str(id(public_tools)),
            str(id(store)),
            store.root_identity,
            _transport_execution_authority(model_transport),
            _transport_execution_authority(database),
            _callable_identity(getattr(model_transport, "next_turn", None)),
            _callable_identity(getattr(database, "connect", None)),
            *_public_callable_identities(public_tools),
        )
    ).encode()
    return hmac.new(_AUTHORITY_KEY, payload, hashlib.sha256).hexdigest()


def _public_callable_identities(public_tools: DirectPublicTools) -> tuple[str, ...]:
    return tuple(
        _callable_identity(getattr(public_tools, name, None))
        for name in (
            "inspect_schema",
            "render_question",
            "search_hkb",
            "search_semantic_model",
        )
    )


def _callable_identity(value: object) -> str:
    if value is None:
        return "none"
    if not callable(value):
        return "not-callable"
    function = getattr(value, "__func__", value)
    owner = getattr(value, "__self__", None)
    return f"{id(owner)}:{id(function)}"


def _transport_execution_authority(value: object) -> str:
    try:
        authority = getattr(value, "execution_authority", None)
    except Exception:
        return "invalid"
    if not isinstance(authority, str) or not authority:
        return "invalid"
    return authority
