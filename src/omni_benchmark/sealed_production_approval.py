"""Exact human approval for one sealed generation dispatch."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .artifact_store import ALLOWED_RAW_ROOTS

_DECISION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}")
_RECEIPT_FIELDS = frozenset(
    {
        "approved_at",
        "binding",
        "decision_bead_id",
        "expires_at",
        "kind",
        "nonce",
        "schema_version",
    }
)
_BINDING_FIELDS = frozenset(
    {
        "attempt_count",
        "conditions",
        "control_commit",
        "cost_ceiling_usd",
        "freeze_b_sha256",
        "maximum_concurrency",
        "maximum_wall_clock_seconds",
        "output_root",
        "plan_sha256",
        "policy_sha256",
        "run_id",
        "runtime_sources_sha256",
        "schedule_sha256",
        "system_commit",
    }
)

DecisionLoader = Callable[[Path, str], tuple[Mapping[str, Any], Sequence[str]]]


class SealedProductionApprovalError(ValueError):
    """Raised when sealed production lacks one exact current human approval."""


@dataclass(frozen=True, slots=True)
class SealedProductionApproval:
    """Authenticated approval for one immutable sealed production identity."""

    binding: Mapping[str, Any]
    decision_bead_id: str
    nonce: str
    receipt_sha256: str


def validate_sealed_production_approval(
    workspace: Path,
    receipt_path: Path,
    expected_binding: Mapping[str, Any],
    *,
    now: datetime | None = None,
    decision_loader: DecisionLoader | None = None,
) -> SealedProductionApproval:
    """Authenticate a canonical receipt against its answered Beads decision."""
    root = _workspace_root(workspace)
    content = _read_receipt(receipt_path)
    value = _strict_json(content)
    if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
        raise SealedProductionApprovalError(
            "sealed human approval receipt schema is invalid"
        )
    decision_id = value.get("decision_bead_id")
    nonce = value.get("nonce")
    binding = value.get("binding")
    if (
        value.get("kind") != "sealed-production-human-approval"
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or not isinstance(decision_id, str)
        or _DECISION_ID.fullmatch(decision_id) is None
        or not isinstance(nonce, str)
        or _SHA256.fullmatch(nonce) is None
        or not isinstance(binding, Mapping)
    ):
        raise SealedProductionApprovalError(
            "sealed human approval receipt schema is invalid"
        )
    approved_binding = _validated_binding(binding)
    expected = _validated_binding(expected_binding)
    if approved_binding != expected:
        raise SealedProductionApprovalError(
            "sealed human approval binding does not match dispatch"
        )
    observed_at = datetime.now(timezone.utc) if now is None else now
    if observed_at.tzinfo is None:
        raise SealedProductionApprovalError("sealed approval clock must be aware")
    approved_at = _timestamp(value.get("approved_at"), "approved_at")
    expires_at = _timestamp(value.get("expires_at"), "expires_at")
    if approved_at > observed_at or expires_at <= observed_at:
        raise SealedProductionApprovalError("sealed human approval receipt is expired")
    if expires_at <= approved_at or expires_at - approved_at > timedelta(hours=1):
        raise SealedProductionApprovalError(
            "sealed human approval validity window is invalid"
        )
    canonical = _canonical_json(value)
    if content != canonical:
        raise SealedProductionApprovalError(
            "sealed human approval receipt is not canonical"
        )
    load = _load_beads_decision if decision_loader is None else decision_loader
    issue, comments = load(root, decision_id)
    expected_response = "Response: " + canonical.decode().strip()
    response_comments = tuple(
        comment for comment in comments if comment.startswith("Response: ")
    )
    labels = issue.get("labels")
    closed_at = _timestamp_or_none(issue.get("closed_at"))
    if (
        issue.get("id") != decision_id
        or issue.get("issue_type") != "decision"
        or issue.get("status") != "closed"
        or issue.get("close_reason") != "Responded"
        or not isinstance(labels, list)
        or "human" not in labels
        or response_comments != (expected_response,)
        or closed_at is None
        or abs(closed_at - approved_at) > timedelta(minutes=1)
    ):
        raise SealedProductionApprovalError(
            "human decision does not authenticate sealed receipt"
        )
    return SealedProductionApproval(
        binding=approved_binding,
        decision_bead_id=decision_id,
        nonce=nonce,
        receipt_sha256=hashlib.sha256(content).hexdigest(),
    )


def consume_sealed_production_approval(
    workspace: Path,
    consumption_root: Path,
    approval: SealedProductionApproval,
) -> Path:
    """Consume one sealed approval once before constructing live adapters."""
    root = _workspace_root(workspace)
    if type(approval) is not SealedProductionApproval:
        raise SealedProductionApprovalError("sealed production approval is invalid")
    binding = _validated_binding(approval.binding)
    if (
        _DECISION_ID.fullmatch(approval.decision_bead_id) is None
        or _SHA256.fullmatch(approval.nonce) is None
        or _SHA256.fullmatch(approval.receipt_sha256) is None
    ):
        raise SealedProductionApprovalError("sealed production approval is invalid")
    relative = Path(consumption_root)
    if (
        relative.is_absolute()
        or not relative.parts
        or ".." in relative.parts
        or not any(
            relative.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS
        )
    ):
        raise SealedProductionApprovalError(
            "sealed approval consumption root is not confined"
        )
    directory = root / relative
    path = directory / f"{approval.receipt_sha256}.consumed.json"
    payload = _canonical_json(
        {
            "binding": binding,
            "decision_bead_id": approval.decision_bead_id,
            "kind": "sealed-production-approval-consumption",
            "nonce": approval.nonce,
            "receipt_sha256": approval.receipt_sha256,
            "schema_version": 1,
        }
    )
    descriptor = _open_confined_directory(root, relative)
    try:
        try:
            file_descriptor = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=descriptor,
            )
        except FileExistsError as error:
            raise SealedProductionApprovalError(
                "sealed human approval was already consumed"
            ) from error
        except OSError as error:
            raise SealedProductionApprovalError(
                "sealed human approval consumption failed"
            ) from error
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(payload)
    finally:
        os.close(descriptor)
    return path


def _validated_binding(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _BINDING_FIELDS:
        raise SealedProductionApprovalError(
            "sealed human approval receipt schema is invalid"
        )
    binding = dict(value)
    output_root = binding.get("output_root")
    root = Path(output_root) if isinstance(output_root, str) else Path()
    if (
        type(binding.get("attempt_count")) is not int
        or binding["attempt_count"] != 1_212
        or binding.get("conditions") != ["C1", "C2", "C3", "C4"]
        or type(binding.get("maximum_concurrency")) is not int
        or binding["maximum_concurrency"] < 1
        or type(binding.get("maximum_wall_clock_seconds")) is not int
        or binding["maximum_wall_clock_seconds"] < 1
        or not isinstance(binding.get("run_id"), str)
        or _IDENTIFIER.fullmatch(binding["run_id"]) is None
        or _COMMIT.fullmatch(str(binding.get("system_commit", ""))) is None
        or _COMMIT.fullmatch(str(binding.get("control_commit", ""))) is None
        or any(
            _SHA256.fullmatch(str(binding.get(field, ""))) is None
            for field in (
                "freeze_b_sha256",
                "plan_sha256",
                "policy_sha256",
                "runtime_sources_sha256",
                "schedule_sha256",
            )
        )
        or root.is_absolute()
        or not root.parts
        or ".." in root.parts
        or not any(root.is_relative_to(candidate) for candidate in ALLOWED_RAW_ROOTS)
    ):
        raise SealedProductionApprovalError(
            "sealed human approval receipt schema is invalid"
        )
    try:
        cost = Decimal(binding["cost_ceiling_usd"])
        normalized_cost = str(cost.quantize(Decimal("0.000001")))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise SealedProductionApprovalError(
            "sealed human approval receipt schema is invalid"
        ) from error
    if (
        not cost.is_finite()
        or cost <= 0
        or normalized_cost != binding["cost_ceiling_usd"]
    ):
        raise SealedProductionApprovalError(
            "sealed human approval receipt schema is invalid"
        )
    return binding


def _workspace_root(workspace: Path) -> Path:
    absolute = workspace.absolute()
    try:
        resolved = workspace.resolve(strict=True)
    except OSError as error:
        raise SealedProductionApprovalError(
            "sealed approval workspace is unavailable"
        ) from error
    if absolute != resolved or workspace.is_symlink() or not resolved.is_dir():
        raise SealedProductionApprovalError("sealed approval workspace is unsafe")
    return resolved


def _read_receipt(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        content = path.read_bytes()
    except OSError as error:
        raise SealedProductionApprovalError(
            "sealed human approval receipt is unavailable"
        ) from error
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_uid != os.getuid()
        or metadata.st_nlink != 1
        or not content
        or len(content) > 32_768
    ):
        raise SealedProductionApprovalError(
            "sealed human approval receipt must be a private regular file"
        )
    return content


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise SealedProductionApprovalError(f"sealed human approval {name} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise SealedProductionApprovalError(
            f"sealed human approval {name} is invalid"
        ) from error
    if parsed.utcoffset() != timedelta(0):
        raise SealedProductionApprovalError(f"sealed human approval {name} is invalid")
    return parsed


def _timestamp_or_none(value: object) -> datetime | None:
    try:
        return _timestamp(value, "decision close time")
    except SealedProductionApprovalError:
        return None


def _strict_json(content: bytes) -> object:
    try:
        return json.loads(content, object_pairs_hook=_unique_object)
    except SealedProductionApprovalError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SealedProductionApprovalError(
            "sealed human approval receipt is invalid JSON"
        ) from error


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SealedProductionApprovalError(
                "sealed human approval receipt has duplicate keys"
            )
        result[key] = value
    return result


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def _open_confined_directory(root: Path, relative: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as error:
        raise SealedProductionApprovalError(
            "sealed approval consumption root is unsafe"
        ) from error
    try:
        for component in relative.parts:
            try:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            metadata = os.fstat(next_descriptor)
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
                os.close(next_descriptor)
                raise SealedProductionApprovalError(
                    "sealed approval consumption root is unsafe"
                )
            os.fchmod(next_descriptor, 0o700)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except SealedProductionApprovalError:
        os.close(descriptor)
        raise
    except OSError as error:
        os.close(descriptor)
        raise SealedProductionApprovalError(
            "sealed approval consumption root is not confined"
        ) from error


def _load_beads_decision(
    workspace: Path, decision_id: str
) -> tuple[Mapping[str, Any], Sequence[str]]:
    issue = _bd_json(workspace, ("show", decision_id, "--json"))
    comments = _bd_json(workspace, ("comments", decision_id, "--json"))
    if not isinstance(issue, list) or len(issue) != 1 or not isinstance(issue[0], dict):
        raise SealedProductionApprovalError("sealed human decision is unavailable")
    if not isinstance(comments, list) or any(
        not isinstance(comment, Mapping) or not isinstance(comment.get("text"), str)
        for comment in comments
    ):
        raise SealedProductionApprovalError("sealed decision comments are unavailable")
    return issue[0], tuple(comment["text"] for comment in comments)


def _bd_json(workspace: Path, arguments: tuple[str, ...]) -> object:
    try:
        completed = subprocess.run(
            ("bd", "-C", str(workspace), *arguments),
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SealedProductionApprovalError(
            "sealed human decision is unavailable"
        ) from error
    if completed.returncode != 0 or len(completed.stdout) > 1_048_576:
        raise SealedProductionApprovalError("sealed human decision is unavailable")
    try:
        return json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SealedProductionApprovalError(
            "sealed human decision is unavailable"
        ) from error
