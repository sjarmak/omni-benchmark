"""Fail-closed human approval for one exact C4 production dispatch."""

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
from typing import Any

_DECISION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
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
        "condition",
        "deployment_sha256",
        "execution_plan_sha256",
        "output_root",
        "run_id",
        "schedule_sha256",
        "system_commit",
    }
)

DecisionLoader = Callable[[Path, str], tuple[Mapping[str, Any], Sequence[str]]]


class C4ProductionApprovalError(ValueError):
    """Raised when production C4 lacks one exact current human approval."""


@dataclass(frozen=True, slots=True)
class C4ProductionApproval:
    binding: Mapping[str, str]
    decision_bead_id: str
    nonce: str
    receipt_sha256: str


def validate_c4_production_approval(
    workspace: Path,
    receipt_path: Path,
    expected_binding: Mapping[str, str],
    *,
    now: datetime | None = None,
    decision_loader: DecisionLoader | None = None,
) -> C4ProductionApproval:
    """Authenticate a strict receipt against its answered Beads decision."""
    root = workspace.resolve(strict=True)
    content = _read_receipt(receipt_path)
    value = _strict_json(content)
    if not isinstance(value, Mapping) or set(value) != _RECEIPT_FIELDS:
        raise C4ProductionApprovalError("human approval receipt schema is invalid")
    decision_id = value.get("decision_bead_id")
    nonce = value.get("nonce")
    binding = value.get("binding")
    if (
        value.get("kind") != "c4-production-human-approval"
        or value.get("schema_version") != 1
        or not isinstance(decision_id, str)
        or _DECISION_ID.fullmatch(decision_id) is None
        or not isinstance(nonce, str)
        or _SHA256.fullmatch(nonce) is None
        or not isinstance(binding, Mapping)
        or set(binding) != _BINDING_FIELDS
        or any(not isinstance(item, str) or not item for item in binding.values())
        or binding.get("condition") != "C4"
        or _SHA256.fullmatch(binding.get("deployment_sha256", "")) is None
        or _SHA256.fullmatch(binding.get("execution_plan_sha256", "")) is None
        or _SHA256.fullmatch(binding.get("schedule_sha256", "")) is None
        or _COMMIT.fullmatch(binding.get("system_commit", "")) is None
    ):
        raise C4ProductionApprovalError("human approval receipt schema is invalid")
    if dict(binding) != dict(expected_binding):
        raise C4ProductionApprovalError(
            "human approval binding does not match dispatch"
        )
    observed_at = datetime.now(timezone.utc) if now is None else now
    if observed_at.tzinfo is None:
        raise C4ProductionApprovalError("approval clock must be timezone-aware")
    approved_at = _timestamp(value.get("approved_at"), "approved_at")
    expires_at = _timestamp(value.get("expires_at"), "expires_at")
    if approved_at > observed_at or expires_at <= observed_at:
        raise C4ProductionApprovalError("human approval receipt is expired")
    if expires_at <= approved_at or expires_at - approved_at > timedelta(hours=24):
        raise C4ProductionApprovalError("human approval validity window is invalid")
    canonical = _canonical_json(value)
    if content != canonical:
        raise C4ProductionApprovalError("human approval receipt is not canonical")
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
        raise C4ProductionApprovalError("human decision does not authenticate receipt")
    return C4ProductionApproval(
        binding=dict(binding),
        decision_bead_id=decision_id,
        nonce=nonce,
        receipt_sha256=hashlib.sha256(content).hexdigest(),
    )


def consume_c4_production_approval(
    workspace: Path,
    consumption_root: Path,
    approval: C4ProductionApproval,
) -> Path:
    """Consume one approval once before constructing the live dispatcher."""
    root = workspace.resolve(strict=True)
    if consumption_root.is_absolute() or ".." in consumption_root.parts:
        raise C4ProductionApprovalError("approval consumption root is not confined")
    directory = root / consumption_root
    path = directory / f"{approval.receipt_sha256}.consumed.json"
    payload = _canonical_json(
        {
            "binding": dict(approval.binding),
            "decision_bead_id": approval.decision_bead_id,
            "kind": "c4-production-approval-consumption",
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
            raise C4ProductionApprovalError(
                "human approval was already consumed"
            ) from error
        except OSError as error:
            raise C4ProductionApprovalError(
                "human approval consumption failed"
            ) from error
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
    finally:
        os.close(directory_descriptor)
    return path


def _open_confined_directory(root: Path, relative: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as error:
        raise C4ProductionApprovalError(
            "approval consumption root is unsafe"
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
                raise C4ProductionApprovalError("approval consumption root is unsafe")
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except C4ProductionApprovalError:
        os.close(descriptor)
        raise
    except OSError as error:
        os.close(descriptor)
        raise C4ProductionApprovalError(
            "approval consumption root is not confined"
        ) from error


def _read_receipt(path: Path) -> bytes:
    try:
        metadata = path.lstat()
        content = path.read_bytes()
    except OSError as error:
        raise C4ProductionApprovalError(
            "human approval receipt is unavailable"
        ) from error
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or len(content) > 16_384:
        raise C4ProductionApprovalError("human approval receipt is unsafe")
    return content


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise C4ProductionApprovalError(f"human approval {name} is invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise C4ProductionApprovalError(f"human approval {name} is invalid") from error


def _timestamp_or_none(value: object) -> datetime | None:
    try:
        return _timestamp(value, "decision close time")
    except C4ProductionApprovalError:
        return None


def _strict_json(content: bytes) -> object:
    try:
        return json.loads(content, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise C4ProductionApprovalError(
            "human approval receipt is invalid JSON"
        ) from error


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise C4ProductionApprovalError("human approval receipt has duplicate keys")
        result[key] = value
    return result


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _load_beads_decision(
    workspace: Path, decision_id: str
) -> tuple[Mapping[str, Any], Sequence[str]]:
    issue = _bd_json(workspace, ("show", decision_id, "--json"))
    comments = _bd_json(workspace, ("comments", decision_id, "--json"))
    if not isinstance(issue, list) or len(issue) != 1 or not isinstance(issue[0], dict):
        raise C4ProductionApprovalError("human decision is unavailable")
    if not isinstance(comments, list) or any(
        not isinstance(comment, Mapping) or not isinstance(comment.get("text"), str)
        for comment in comments
    ):
        raise C4ProductionApprovalError("human decision comments are unavailable")
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
        raise C4ProductionApprovalError("human decision is unavailable") from error
    if completed.returncode != 0 or len(completed.stdout) > 1_048_576:
        raise C4ProductionApprovalError("human decision is unavailable")
    try:
        return json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise C4ProductionApprovalError("human decision is unavailable") from error
