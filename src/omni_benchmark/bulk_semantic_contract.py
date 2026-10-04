"""Executable acceptance oracle for a proposed bulk semantic sync contract."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

_DIGEST = re.compile(r"[0-9a-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,239}")


class BulkSemanticContractError(ValueError):
    """Raised when a bulk request cannot safely enter or resume staging."""


@dataclass(frozen=True, slots=True)
class BulkSemanticFile:
    """One content-addressed semantic file."""

    path: str
    content: bytes
    sha256: str
    size_bytes: int

    @classmethod
    def create(cls, path: str, content: bytes) -> BulkSemanticFile:
        if not isinstance(content, bytes):
            raise BulkSemanticContractError("semantic content must be bytes")
        return cls(
            path=path,
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )


@dataclass(frozen=True, slots=True)
class BulkSyncRequest:
    """Complete desired semantic state and its optimistic-concurrency identity."""

    target: str
    base_revision: str
    manifest_sha256: str
    files: tuple[BulkSemanticFile, ...]
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class BulkSyncResponse:
    """Typed terminal or resumable result from one bulk request."""

    status: str
    manifest_sha256: str
    changed_file_count: int
    accepted_file_count: int
    upload_request_count: int
    resume_token: str | None
    validation_receipt_sha256: str | None
    readback_receipt_sha256: str | None
    error_code: str | None = None
    retryable: bool | None = None


def build_bulk_sync_request(
    *,
    target: str,
    base_revision: str,
    files: Sequence[BulkSemanticFile],
    idempotency_key: str,
) -> BulkSyncRequest:
    """Validate and bind one exact desired-state request before transfer."""
    _identifier(target, "target")
    _identifier(idempotency_key, "idempotency key")
    _digest(base_revision, "base revision")
    checked = tuple(
        sorted((_validated_file(item) for item in files), key=lambda x: x.path)
    )
    paths = [item.path for item in checked]
    if len(paths) != len(set(paths)):
        raise BulkSemanticContractError("semantic file paths must be unique")
    return BulkSyncRequest(
        target=target,
        base_revision=base_revision,
        manifest_sha256=semantic_manifest_sha256(checked),
        files=checked,
        idempotency_key=idempotency_key,
    )


def semantic_manifest_sha256(files: Sequence[BulkSemanticFile]) -> str:
    """Hash the canonical path, content hash, and size manifest."""
    manifest = [
        {
            "path": item.path,
            "sha256": item.sha256,
            "size_bytes": item.size_bytes,
        }
        for item in sorted(files, key=lambda item: item.path)
    ]
    encoded = json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def verify_bulk_readback(
    request: BulkSyncRequest, readback: Mapping[str, bytes]
) -> str:
    """Require exact paths and bytes, then return the canonical desired revision."""
    expected = {item.path: item for item in request.files}
    if set(readback) != set(expected):
        raise BulkSemanticContractError("readback path set does not match manifest")
    for path, item in expected.items():
        content = readback[path]
        if (
            not isinstance(content, bytes)
            or hashlib.sha256(content).hexdigest() != item.sha256
        ):
            raise BulkSemanticContractError(f"readback content differs for {path}")
    return request.manifest_sha256


class ReferenceBulkSemanticService:
    """In-memory oracle for atomicity, idempotency, and bounded resume behavior."""

    def __init__(
        self,
        initial_files: Sequence[BulkSemanticFile],
        *,
        validator: Callable[[Mapping[str, bytes]], Sequence[str]] | None = None,
    ) -> None:
        checked = tuple(_validated_file(item) for item in initial_files)
        if len({item.path for item in checked}) != len(checked):
            raise BulkSemanticContractError("semantic file paths must be unique")
        self._visible = {item.path: item.content for item in checked}
        self.revision = semantic_manifest_sha256(checked)
        self._validator = validator or (lambda _files: ())
        self._bindings: dict[str, tuple[str, str, str]] = {}
        self._staged: dict[str, dict[str, bytes]] = {}
        self._completed: dict[str, BulkSyncResponse] = {}

    def readback(self) -> dict[str, bytes]:
        return dict(self._visible)

    def apply(
        self,
        request: BulkSyncRequest,
        *,
        resume_token: str | None = None,
        fail_after: int | None = None,
    ) -> BulkSyncResponse:
        """Apply, interrupt, or resume one desired state without partial visibility."""
        _validated_request(request)
        if fail_after is not None and (
            isinstance(fail_after, bool)
            or not isinstance(fail_after, int)
            or fail_after < 0
        ):
            raise BulkSemanticContractError("fail_after must be a non-negative integer")
        binding = (request.target, request.base_revision, request.manifest_sha256)
        previous_binding = self._bindings.setdefault(request.idempotency_key, binding)
        if previous_binding != binding:
            raise BulkSemanticContractError(
                "idempotency key is already bound to another request"
            )
        completed = self._completed.get(request.idempotency_key)
        if completed is not None:
            return completed
        expected_token = _resume_token(request)
        staged = self._staged.get(request.idempotency_key)
        if resume_token is not None and (
            staged is None or resume_token != expected_token
        ):
            raise BulkSemanticContractError(
                "resume token does not match staged request"
            )
        if staged is None and resume_token is not None:
            raise BulkSemanticContractError("resume token has no staged request")
        if staged is None and request.manifest_sha256 == self.revision:
            response = BulkSyncResponse(
                status="no_op",
                manifest_sha256=request.manifest_sha256,
                changed_file_count=0,
                accepted_file_count=0,
                upload_request_count=0,
                resume_token=None,
                validation_receipt_sha256=_validation_receipt(request.manifest_sha256),
                readback_receipt_sha256=request.manifest_sha256,
            )
            self._completed[request.idempotency_key] = response
            return response
        if staged is None and request.base_revision != self.revision:
            raise BulkSemanticContractError(
                "base revision conflicts with visible state"
            )

        desired = {item.path: item.content for item in request.files}
        changed_paths = {
            path
            for path in set(self._visible) | set(desired)
            if self._visible.get(path) != desired.get(path)
        }
        staged = self._staged.setdefault(request.idempotency_key, {})
        remaining = [
            path
            for path in sorted(changed_paths)
            if path in desired and path not in staged
        ]
        accepted_now = (
            len(remaining) if fail_after is None else min(fail_after, len(remaining))
        )
        for path in remaining[:accepted_now]:
            staged[path] = desired[path]
        if accepted_now < len(remaining):
            return BulkSyncResponse(
                status="partial_failure",
                manifest_sha256=request.manifest_sha256,
                changed_file_count=len(changed_paths),
                accepted_file_count=len(staged),
                upload_request_count=1,
                resume_token=expected_token,
                validation_receipt_sha256=None,
                readback_receipt_sha256=None,
                error_code="transport_interrupted",
                retryable=True,
            )

        issues = tuple(self._validator(desired))
        if issues:
            return BulkSyncResponse(
                status="validation_failed",
                manifest_sha256=request.manifest_sha256,
                changed_file_count=len(changed_paths),
                accepted_file_count=len(staged),
                upload_request_count=1,
                resume_token=expected_token,
                validation_receipt_sha256=None,
                readback_receipt_sha256=None,
                error_code="semantic_validation_failed",
                retryable=False,
            )
        self._visible = desired
        self.revision = request.manifest_sha256
        response = BulkSyncResponse(
            status="committed",
            manifest_sha256=request.manifest_sha256,
            changed_file_count=len(changed_paths),
            accepted_file_count=len(staged),
            upload_request_count=1,
            resume_token=None,
            validation_receipt_sha256=_validation_receipt(request.manifest_sha256),
            readback_receipt_sha256=verify_bulk_readback(request, self._visible),
        )
        self._completed[request.idempotency_key] = response
        self._staged.pop(request.idempotency_key, None)
        return response


def _validated_request(request: BulkSyncRequest) -> None:
    if not isinstance(request, BulkSyncRequest):
        raise BulkSemanticContractError("bulk sync request is invalid")
    rebuilt = build_bulk_sync_request(
        target=request.target,
        base_revision=request.base_revision,
        files=request.files,
        idempotency_key=request.idempotency_key,
    )
    if rebuilt.manifest_sha256 != request.manifest_sha256:
        raise BulkSemanticContractError("manifest SHA-256 does not match files")


def _validated_file(item: BulkSemanticFile) -> BulkSemanticFile:
    if not isinstance(item, BulkSemanticFile):
        raise BulkSemanticContractError("semantic file entry is invalid")
    _identifier(item.path, "semantic file path")
    if item.path.startswith("/") or ".." in item.path.split("/"):
        raise BulkSemanticContractError("semantic file path is unsafe")
    observed = hashlib.sha256(item.content).hexdigest()
    if observed != item.sha256:
        raise BulkSemanticContractError("content SHA-256 does not match bytes")
    if item.size_bytes != len(item.content):
        raise BulkSemanticContractError("content size does not match bytes")
    return item


def _resume_token(request: BulkSyncRequest) -> str:
    value = f"{request.target}\0{request.idempotency_key}\0{request.manifest_sha256}"
    return hashlib.sha256(value.encode()).hexdigest()


def _validation_receipt(manifest_sha256: str) -> str:
    return hashlib.sha256(f"validated:{manifest_sha256}".encode()).hexdigest()


def _digest(value: str, name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise BulkSemanticContractError(f"{name} must be a SHA-256 digest")
    return value


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise BulkSemanticContractError(f"{name} must be a bounded identifier")
    return value
