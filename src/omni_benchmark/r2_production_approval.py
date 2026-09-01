"""Fail-closed standing approval for one exact paired R2 dispatch."""

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
from pathlib import Path
from types import MappingProxyType
from typing import Any


_DECISION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CONTROL_ENVIRONMENT_KEYS = frozenset(
    {
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PATH",
        "TMPDIR",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_RUNTIME_DIR",
    }
)
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

DecisionLoader = Callable[[Path, str], tuple[Mapping[str, Any], Sequence[str]]]


class R2ProductionApprovalError(ValueError):
    """Raised when an R2 paired dispatch lacks one exact current approval."""


@dataclass(frozen=True, slots=True)
class R2ProductionApproval:
    """Process-local proof that one canonical action receipt authenticated."""

    approved_at: datetime
    binding: Mapping[str, object]
    decision_bead_id: str
    expires_at: datetime
    nonce: str
    receipt_sha256: str


def validate_r2_production_approval(
    workspace: Path,
    receipt_path: Path,
    expected_binding: Mapping[str, object],
    *,
    now: datetime | None = None,
    decision_loader: DecisionLoader | None = None,
) -> R2ProductionApproval:
    """Authenticate a canonical paired-series receipt against one Beads response."""
    root = workspace.resolve(strict=True)
    content = _read_receipt(receipt_path)
    value = _strict_json(content)
    if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
        raise R2ProductionApprovalError("R2 approval receipt schema is invalid")
    decision_id = value.get("decision_bead_id")
    nonce = value.get("nonce")
    binding = value.get("binding")
    if (
        value.get("kind") != "r2-paired-series-standing-approval"
        or value.get("schema_version") != 1
        or not isinstance(decision_id, str)
        or _DECISION_ID.fullmatch(decision_id) is None
        or not isinstance(nonce, str)
        or _SHA256.fullmatch(nonce) is None
        or not isinstance(binding, Mapping)
    ):
        raise R2ProductionApprovalError("R2 approval receipt schema is invalid")
    expected = _canonical_mapping(expected_binding, "expected R2 approval binding")
    observed = _canonical_mapping(binding, "R2 approval binding")
    if observed != expected:
        raise R2ProductionApprovalError("R2 approval binding does not match dispatch")
    observed_at = datetime.now(timezone.utc) if now is None else now
    if observed_at.tzinfo is None:
        raise R2ProductionApprovalError("R2 approval clock must be timezone-aware")
    approved_at = _timestamp(value.get("approved_at"), "approved_at")
    expires_at = _timestamp(value.get("expires_at"), "expires_at")
    if approved_at > observed_at or expires_at <= observed_at:
        raise R2ProductionApprovalError("R2 approval receipt is expired")
    if expires_at <= approved_at or expires_at - approved_at > timedelta(hours=24):
        raise R2ProductionApprovalError("R2 approval validity window is invalid")
    canonical = _canonical_json(value)
    if content != canonical:
        raise R2ProductionApprovalError("R2 approval receipt is not canonical")
    load = _load_beads_decision if decision_loader is None else decision_loader
    issue, comments = load(root, decision_id)
    expected_response = "Response: " + canonical.decode("utf-8").strip()
    labels = issue.get("labels")
    response_comments = tuple(
        comment for comment in comments if comment.startswith("Response: ")
    )
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
        raise R2ProductionApprovalError(
            "human decision does not authenticate R2 receipt"
        )
    return R2ProductionApproval(
        approved_at=approved_at,
        binding=MappingProxyType(observed),
        decision_bead_id=decision_id,
        expires_at=expires_at,
        nonce=nonce,
        receipt_sha256=hashlib.sha256(content).hexdigest(),
    )


def consume_r2_production_approval(
    workspace: Path,
    consumption_root: Path,
    approval: R2ProductionApproval,
    *,
    now: datetime | None = None,
) -> Path:
    """Consume one paired-series approval once before executor construction."""
    root = workspace.resolve(strict=True)
    binding = _validated_approval(approval, now=now)
    if (
        consumption_root.is_absolute()
        or not consumption_root.parts
        or ".." in consumption_root.parts
    ):
        raise R2ProductionApprovalError("R2 approval consumption root is not confined")
    directory = root / consumption_root
    path = directory / f"{approval.receipt_sha256}.consumed.json"
    payload = _canonical_json(
        {
            "binding": binding,
            "decision_bead_id": approval.decision_bead_id,
            "kind": "r2-paired-series-approval-consumption",
            "nonce": approval.nonce,
            "receipt_sha256": approval.receipt_sha256,
            "schema_version": 1,
        }
    )
    directory_descriptor = _open_confined_directory(root, consumption_root)
    try:
        try:
            descriptor = os.open(
                path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=directory_descriptor,
            )
        except FileExistsError as error:
            raise R2ProductionApprovalError(
                "R2 approval was already consumed"
            ) from error
        except OSError as error:
            raise R2ProductionApprovalError("R2 approval consumption failed") from error
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    finally:
        os.close(directory_descriptor)
    return path


def canonical_r2_approval_json(value: object) -> bytes:
    """Expose the exact receipt serialization for the bounded receipt maker."""
    return _canonical_json(value)


def r2_control_subprocess_environment(
    environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the non-secret environment permitted for local control commands."""
    source = os.environ if environment is None else environment
    if not isinstance(source, Mapping):
        raise R2ProductionApprovalError("R2 control environment is invalid")
    return {
        key: value
        for key, value in source.items()
        if key in _CONTROL_ENVIRONMENT_KEYS and isinstance(value, str) and value
    }


def _open_confined_directory(root: Path, relative: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as error:
        raise R2ProductionApprovalError(
            "R2 approval consumption root is unsafe"
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
                raise R2ProductionApprovalError(
                    "R2 approval consumption root is unsafe"
                )
            os.fchmod(next_descriptor, 0o700)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except R2ProductionApprovalError:
        os.close(descriptor)
        raise
    except OSError as error:
        os.close(descriptor)
        raise R2ProductionApprovalError(
            "R2 approval consumption root is not confined"
        ) from error


def _read_receipt(path: Path) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        raise R2ProductionApprovalError("R2 approval receipt is unavailable") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
        ):
            raise R2ProductionApprovalError("R2 approval receipt is unsafe")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            content = stream.read(65_537)
    except OSError as error:
        raise R2ProductionApprovalError("R2 approval receipt is unavailable") from error
    finally:
        os.close(descriptor)
    if not content or len(content) > 65_536:
        raise R2ProductionApprovalError("R2 approval receipt is unsafe")
    return content


def _validated_approval(
    approval: object, *, now: datetime | None = None
) -> dict[str, Any]:
    if not isinstance(approval, R2ProductionApproval):
        raise R2ProductionApprovalError("R2 approval is invalid")
    binding = _canonical_mapping(dict(approval.binding), "R2 approval binding")
    observed_at = datetime.now(timezone.utc) if now is None else now
    if observed_at.tzinfo is None:
        raise R2ProductionApprovalError("R2 approval clock must be timezone-aware")
    if (
        not isinstance(approval.approved_at, datetime)
        or approval.approved_at.tzinfo is None
        or not isinstance(approval.expires_at, datetime)
        or approval.expires_at.tzinfo is None
        or approval.approved_at > observed_at
        or approval.expires_at <= observed_at
        or approval.expires_at <= approval.approved_at
        or approval.expires_at - approval.approved_at > timedelta(hours=24)
        or _DECISION_ID.fullmatch(approval.decision_bead_id) is None
        or _SHA256.fullmatch(approval.nonce) is None
        or _SHA256.fullmatch(approval.receipt_sha256) is None
    ):
        raise R2ProductionApprovalError("R2 approval is expired or invalid")
    return binding


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise R2ProductionApprovalError(f"R2 approval {name} is invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise R2ProductionApprovalError(f"R2 approval {name} is invalid") from error


def _timestamp_or_none(value: object) -> datetime | None:
    try:
        return _timestamp(value, "decision close time")
    except R2ProductionApprovalError:
        return None


def _strict_json(content: bytes) -> object:
    try:
        return json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise R2ProductionApprovalError(
            "R2 approval receipt is invalid JSON"
        ) from error


def _reject_constant(value: str) -> None:
    raise R2ProductionApprovalError(f"R2 approval JSON constant is invalid: {value}")


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise R2ProductionApprovalError("R2 approval receipt has duplicate keys")
        result[key] = value
    return result


def _canonical_mapping(value: Mapping[str, object], description: str) -> dict[str, Any]:
    try:
        encoded = _canonical_json(value)
        decoded = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise R2ProductionApprovalError(f"{description} is invalid") from error
    if not isinstance(decoded, dict):
        raise R2ProductionApprovalError(f"{description} is invalid")
    return decoded


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
    ).encode("utf-8")


def _load_beads_decision(
    workspace: Path, decision_id: str
) -> tuple[Mapping[str, Any], Sequence[str]]:
    issue = _bd_json(workspace, ("show", decision_id, "--json"))
    comments = _bd_json(workspace, ("comments", decision_id, "--json"))
    if not isinstance(issue, list) or len(issue) != 1 or not isinstance(issue[0], dict):
        raise R2ProductionApprovalError("human decision is unavailable")
    if not isinstance(comments, list) or any(
        not isinstance(comment, Mapping) or not isinstance(comment.get("text"), str)
        for comment in comments
    ):
        raise R2ProductionApprovalError("human decision comments are unavailable")
    return issue[0], tuple(comment["text"] for comment in comments)


def _bd_json(workspace: Path, arguments: tuple[str, ...]) -> object:
    try:
        completed = subprocess.run(
            ("bd", "-C", str(workspace), *arguments),
            capture_output=True,
            check=False,
            env=r2_control_subprocess_environment(),
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise R2ProductionApprovalError("human decision is unavailable") from error
    if completed.returncode != 0 or len(completed.stdout) > 1_048_576:
        raise R2ProductionApprovalError("human decision is unavailable")
    try:
        return json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise R2ProductionApprovalError("human decision is unavailable") from error
