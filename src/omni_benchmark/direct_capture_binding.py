"""Fail-closed equality checks for direct-capture runtime dependencies."""

from __future__ import annotations

from .direct_capture_contract import (
    DirectDatabaseAttestation,
    DirectDatabaseTransport,
    DirectModelTransport,
    DirectPublicTools,
)
from .direct_runtime_binding import DirectRuntimeBinding, DirectRuntimeIdentityError


class DirectCaptureBindingError(ValueError):
    """Raised when a capture dependency differs from its frozen runtime binding."""


class DirectModelBindingError(DirectCaptureBindingError):
    pass


class DirectDatabaseBindingError(DirectCaptureBindingError):
    pass


class DirectReferenceBindingError(DirectCaptureBindingError):
    pass


def validated_runtime_binding(value: object) -> DirectRuntimeBinding:
    if not isinstance(value, DirectRuntimeBinding):
        raise DirectCaptureBindingError("runtime binding is required")
    try:
        validated = DirectRuntimeBinding.from_dict(value.as_dict())
    except DirectRuntimeIdentityError as error:
        raise DirectCaptureBindingError("runtime binding is invalid") from error
    if validated != value:
        raise DirectCaptureBindingError("runtime binding is not canonical")
    return validated


def validate_model_transport(
    binding: DirectRuntimeBinding, model_transport: DirectModelTransport
) -> DirectModelTransport:
    try:
        require_model_identity(binding, model_transport)
    except DirectModelBindingError as error:
        raise DirectCaptureBindingError(
            "model or budget identity does not match binding"
        ) from error
    if not callable(getattr(model_transport, "next_turn", None)):
        raise DirectCaptureBindingError("model transport must expose next_turn")
    return model_transport


def validate_database_transport(
    binding: DirectRuntimeBinding, database: DirectDatabaseTransport
) -> DirectDatabaseTransport:
    try:
        require_database_identity(binding, database)
    except DirectDatabaseBindingError as error:
        raise DirectCaptureBindingError(
            "database identity or execution attestation does not match binding"
        ) from error
    if not callable(getattr(database, "connect", None)):
        raise DirectCaptureBindingError("database transport must expose connect")
    return database


def validate_public_tools(
    binding: DirectRuntimeBinding, public_tools: DirectPublicTools
) -> DirectPublicTools:
    try:
        require_public_identity(binding, public_tools)
    except DirectReferenceBindingError as error:
        raise DirectCaptureBindingError(
            "context identity does not match binding"
        ) from error
    if not callable(getattr(public_tools, "inspect_schema", None)) or not callable(
        getattr(public_tools, "render_question", None)
    ):
        raise DirectCaptureBindingError("public context tools are incomplete")
    hkb = getattr(public_tools, "search_hkb", None)
    semantic = getattr(public_tools, "search_semantic_model", None)
    if binding.condition == "C1" and (hkb is not None or semantic is not None):
        raise DirectCaptureBindingError("C1 cannot expose HKB or semantic-model search")
    if binding.condition == "C2" and (not callable(hkb) or semantic is not None):
        raise DirectCaptureBindingError(
            "C2 requires HKB search and forbids semantic-model search"
        )
    if binding.condition == "C3" and (not callable(semantic) or hkb is not None):
        raise DirectCaptureBindingError(
            "C3 requires semantic-model search and forbids HKB search"
        )
    return public_tools


def require_runtime_boundaries(
    binding: DirectRuntimeBinding,
    model_transport: DirectModelTransport,
    database: DirectDatabaseTransport,
    public_tools: DirectPublicTools,
) -> None:
    require_model_identity(binding, model_transport)
    require_database_identity(binding, database)
    require_public_identity(binding, public_tools)


def require_model_identity(
    binding: DirectRuntimeBinding, model_transport: DirectModelTransport
) -> None:
    try:
        model = model_transport.runtime_identity
        budget = model_transport.budget_identity
    except Exception as error:
        raise DirectModelBindingError("model identity is unavailable") from error
    if model != binding.model:
        raise DirectModelBindingError("model identity does not match runtime binding")
    if budget != binding.budget:
        raise DirectModelBindingError("budget identity does not match runtime binding")


def require_database_identity(
    binding: DirectRuntimeBinding, database: DirectDatabaseTransport
) -> None:
    try:
        identity = database.runtime_identity
        attestation = database.execution_attestation
    except Exception as error:
        raise DirectDatabaseBindingError("database identity is unavailable") from error
    if identity != binding.database:
        raise DirectDatabaseBindingError(
            "database identity does not match runtime binding"
        )
    required = DirectDatabaseAttestation(True, True)
    if (
        not isinstance(attestation, DirectDatabaseAttestation)
        or attestation != required
    ):
        raise DirectDatabaseBindingError("database execution attestation is incomplete")


def require_public_identity(
    binding: DirectRuntimeBinding, public_tools: DirectPublicTools
) -> None:
    try:
        identity = public_tools.identity
    except Exception as error:
        raise DirectReferenceBindingError("context identity is unavailable") from error
    if identity != binding.context:
        raise DirectReferenceBindingError(
            "context identity does not match runtime binding"
        )
