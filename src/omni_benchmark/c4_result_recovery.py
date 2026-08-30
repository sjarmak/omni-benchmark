"""Append-only recovery of C4 result capture failures without rerunning the agent."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .artifact_store import (
    MAX_ARTIFACT_BYTES,
    ArtifactStore,
    ArtifactStoreError,
    StoredArtifact,
)
from .omni_result_adapter import (
    SUPPORTED_OMNI_RESULT_TYPES,
    OmniResultContractError,
    build_replayed_result_artifact,
    planned_query_data_types,
)
from .omni_cli import OmniCliClient, OmniCliError, OmniCliSettings

_SHA256 = re.compile(r"[0-9a-f]{64}")
_RECOVERABLE_FAILURES = frozenset(
    {
        "adapter_transport_error",
        "response_contract_error",
        "unsupported_semantic_result_type",
    }
)


class C4RecoveryError(RuntimeError):
    """Sanitized failure at the C4 recovery boundary."""


class C4RecoveryClient(Protocol):
    """The two provider operations allowed during semantic-query replay."""

    def plan_query(self, query: Mapping[str, Any]) -> dict[str, Any]: ...

    def run_query_json(self, query: Mapping[str, Any]) -> list[dict[str, Any]]: ...


C4RecoveryClientFactory = Callable[[OmniCliSettings], C4RecoveryClient]


class _PacedRecoveryClient:
    """Pace every provider call and retry only the idempotent plan operation."""

    def __init__(
        self,
        client: C4RecoveryClient,
        *,
        minimum_interval_seconds: float,
        sleep: Callable[[float], None],
        clock: Callable[[], float] = time.monotonic,
        plan_retry_schedule_seconds: tuple[float, ...] = (2.0, 5.0, 10.0),
    ) -> None:
        self._client = client
        self._minimum_interval = minimum_interval_seconds
        self._sleep = sleep
        self._clock = clock
        self._plan_retry_schedule = plan_retry_schedule_seconds
        self._last_started: float | None = None

    def plan_query(self, query: Mapping[str, Any]) -> dict[str, Any]:
        for delay in self._plan_retry_schedule:
            self._wait()
            try:
                return self._client.plan_query(query)
            except OmniCliError:
                self._sleep(delay)
        self._wait()
        return self._client.plan_query(query)

    def run_query_json(self, query: Mapping[str, Any]) -> list[dict[str, Any]]:
        self._wait()
        return self._client.run_query_json(query)

    def _wait(self) -> None:
        now = self._clock()
        if self._last_started is not None:
            remaining = self._minimum_interval - (now - self._last_started)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last_started = now


@dataclass(frozen=True, slots=True)
class C4RecoverySource:
    """Hash-bound infrastructure failure eligible for result-only recovery."""

    attempt_id: str
    database: str
    generated_query: str | None
    source_failure_class: str
    source_generation_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.attempt_id, str)
            or not self.attempt_id
            or not isinstance(self.database, str)
            or not self.database
            or self.source_failure_class not in _RECOVERABLE_FAILURES
            or _SHA256.fullmatch(self.source_generation_sha256) is None
            or (
                self.generated_query is not None
                and (
                    not isinstance(self.generated_query, str)
                    or not self.generated_query.strip()
                )
            )
        ):
            raise C4RecoveryError("C4 recovery source is invalid")


@dataclass(frozen=True, slots=True)
class C4RecoveryEntry:
    """One append-only result recovery or pre-correctness system adjudication."""

    attempt_id: str
    disposition: str
    plan_sha256: str | None
    reason: str
    result_artifact_path: Path | None
    result_artifact_sha256: str | None
    source_failure_class: str
    source_generation_sha256: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.attempt_id, str)
            or not self.attempt_id
            or self.disposition not in {"evaluated_system_failure", "recovered_result"}
            or self.source_failure_class not in _RECOVERABLE_FAILURES
            or _SHA256.fullmatch(self.source_generation_sha256) is None
            or (
                self.plan_sha256 is not None
                and _SHA256.fullmatch(self.plan_sha256) is None
            )
        ):
            raise C4RecoveryError("C4 recovery entry is invalid")
        has_result = self.disposition == "recovered_result"
        if has_result != (self.result_artifact_path is not None) or has_result != (
            self.result_artifact_sha256 is not None
        ):
            raise C4RecoveryError("C4 recovery result binding is invalid")
        if self.result_artifact_path is not None and (
            self.result_artifact_path.is_absolute()
            or ".." in self.result_artifact_path.parts
            or not self.result_artifact_path.is_relative_to(
                Path("experiments/autoresearch/raw")
            )
        ):
            raise C4RecoveryError("C4 recovery result path is invalid")
        if self.result_artifact_sha256 is not None and (
            _SHA256.fullmatch(self.result_artifact_sha256) is None
        ):
            raise C4RecoveryError("C4 recovery result SHA-256 is invalid")
        expected_reasons = (
            {"adapter_semantic_query_replay"}
            if has_result
            else {
                "omni_completed_job_contract_invalid",
                "omni_query_plan_rejected",
                "omni_query_plan_contract_invalid",
                "omni_unknown_result_type",
            }
        )
        if self.reason not in expected_reasons:
            raise C4RecoveryError("C4 recovery reason is invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "disposition": self.disposition,
            "plan_sha256": self.plan_sha256,
            "reason": self.reason,
            "result_artifact_path": (
                None
                if self.result_artifact_path is None
                else self.result_artifact_path.as_posix()
            ),
            "result_artifact_sha256": self.result_artifact_sha256,
            "source_failure_class": self.source_failure_class,
            "source_generation_sha256": self.source_generation_sha256,
        }


@dataclass(frozen=True, slots=True)
class C4RecoveryManifest:
    """Canonical overlay over one frozen C4 selection."""

    entries: tuple[C4RecoveryEntry, ...]
    source_commit: str
    source_run_id: str
    source_selection_sha256: str
    kind: str = "c4-result-recovery"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if (
            not self.entries
            or any(not isinstance(entry, C4RecoveryEntry) for entry in self.entries)
            or len({entry.attempt_id for entry in self.entries}) != len(self.entries)
            or re.fullmatch(r"[0-9a-f]{40}", self.source_commit) is None
            or not isinstance(self.source_run_id, str)
            or not self.source_run_id
            or _SHA256.fullmatch(self.source_selection_sha256) is None
            or self.kind != "c4-result-recovery"
            or self.schema_version != 1
        ):
            raise C4RecoveryError("C4 recovery manifest is invalid")

    @property
    def counts(self) -> dict[str, int]:
        return {
            "evaluated_system_failure": sum(
                entry.disposition == "evaluated_system_failure"
                for entry in self.entries
            ),
            "recovered_result": sum(
                entry.disposition == "recovered_result" for entry in self.entries
            ),
            "source_failures": len(self.entries),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "counts": self.counts,
            "entries": [entry.as_dict() for entry in self.entries],
            "kind": self.kind,
            "schema_version": self.schema_version,
            "source_commit": self.source_commit,
            "source_run_id": self.source_run_id,
            "source_selection_sha256": self.source_selection_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical(self.as_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def recover_c4_source(
    source: C4RecoverySource,
    *,
    client: C4RecoveryClient,
    store: ArtifactStore,
) -> C4RecoveryEntry:
    """Replay only an existing semantic query, or record a product contract failure."""
    if not isinstance(source, C4RecoverySource) or not isinstance(store, ArtifactStore):
        raise C4RecoveryError("C4 recovery input is invalid")
    if source.generated_query is None:
        if source.source_failure_class != "response_contract_error":
            raise C4RecoveryError("C4 recovery source lacks a generated query")
        return _system_failure(source, "omni_completed_job_contract_invalid")
    try:
        semantic_query = json.loads(source.generated_query)
    except (TypeError, json.JSONDecodeError) as error:
        raise C4RecoveryError("C4 generated semantic query is invalid") from error
    if not isinstance(semantic_query, dict):
        raise C4RecoveryError("C4 generated semantic query is invalid")
    try:
        plan = client.plan_query(semantic_query)
    except OmniCliError as error:
        detail = str(error)
        if (
            "429" not in detail
            and re.search(r"HTTP 5[0-9]{2}", detail) is None
            and "timed out" not in detail.lower()
            and "could not start" not in detail.lower()
        ):
            return _system_failure(source, "omni_query_plan_rejected")
        raise C4RecoveryError("C4 recovery provider plan failed") from error
    except Exception as error:
        raise C4RecoveryError("C4 recovery provider plan failed") from error
    plan_sha256 = hashlib.sha256(_canonical(plan)).hexdigest()
    try:
        data_types = planned_query_data_types(semantic_query, plan)
    except OmniResultContractError:
        return _system_failure(
            source, "omni_query_plan_contract_invalid", plan_sha256=plan_sha256
        )
    if "UNKNOWN" in data_types:
        return _system_failure(
            source, "omni_unknown_result_type", plan_sha256=plan_sha256
        )
    if any(data_type not in SUPPORTED_OMNI_RESULT_TYPES for data_type in data_types):
        raise C4RecoveryError("C4 recovery plan contains an unsupported result type")
    try:
        rows = client.run_query_json(semantic_query)
        artifact = build_replayed_result_artifact(semantic_query, rows, plan)
        attempt_key = hashlib.sha256(source.attempt_id.encode()).hexdigest()
        stored = store.write_json(
            Path("attempts") / attempt_key / "answer.result.json", artifact
        )
        artifact_path = store.relative_path(stored)
    except (ArtifactStoreError, OmniResultContractError) as error:
        raise C4RecoveryError("C4 semantic-query replay failed") from error
    except Exception as error:
        raise C4RecoveryError("C4 semantic-query replay failed") from error
    return C4RecoveryEntry(
        attempt_id=source.attempt_id,
        disposition="recovered_result",
        plan_sha256=plan_sha256,
        reason="adapter_semantic_query_replay",
        result_artifact_path=artifact_path,
        result_artifact_sha256=stored.sha256,
        source_failure_class=source.source_failure_class,
        source_generation_sha256=source.source_generation_sha256,
    )


def recover_c4_selection(
    workspace: Path,
    *,
    artifact_workspace: Path,
    selection_path: Path,
    expected_selection_sha256: str,
    deployment_workspace: Path,
    deployment_root: Path,
    deployment_run_id: str,
    output_root: Path,
    profile: str,
    expected_source_failures: int,
    client_factory: C4RecoveryClientFactory | None = None,
    minimum_request_interval_seconds: float = 1.25,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Recover every infrastructure failure in one exact frozen C4 selection."""
    if (
        _SHA256.fullmatch(expected_selection_sha256) is None
        or type(expected_source_failures) is not int
        or expected_source_failures < 1
        or not isinstance(profile, str)
        or not profile.strip()
        or not isinstance(deployment_run_id, str)
        or not deployment_run_id
        or isinstance(minimum_request_interval_seconds, bool)
        or not isinstance(minimum_request_interval_seconds, (int, float))
        or minimum_request_interval_seconds < 0
    ):
        raise C4RecoveryError("C4 selection recovery arguments are invalid")
    destination_workspace = _workspace(workspace)
    source_workspace = _workspace(artifact_workspace)
    target_workspace = _workspace(deployment_workspace)
    selected_path = _confined_path(
        selection_path, Path("experiments/autoresearch/state"), "C4 selection"
    )
    selection_bytes = _read_file(source_workspace, selected_path, private=True)
    if hashlib.sha256(selection_bytes).hexdigest() != expected_selection_sha256:
        raise C4RecoveryError("C4 selection SHA-256 does not match")
    try:
        selection = json.loads(selection_bytes)
    except json.JSONDecodeError as error:
        raise C4RecoveryError("C4 selection is invalid") from error
    if (
        not isinstance(selection, dict)
        or selection.get("kind")
        not in {"public-c4-baseline-freeze", "e02-dev-a-c4-freeze"}
        or not isinstance(selection.get("entries"), list)
        or re.fullmatch(r"[0-9a-f]{40}", str(selection.get("source_commit"))) is None
        or not isinstance(selection.get("run_id"), str)
        or not selection["run_id"]
    ):
        raise C4RecoveryError("C4 selection is invalid")
    sources: list[tuple[C4RecoverySource, OmniCliSettings]] = []
    for raw_entry in selection["entries"]:
        source = _selection_source(
            source_workspace,
            selection["run_id"],
            raw_entry,
        )
        if source is None:
            continue
        settings = _deployment_settings(
            target_workspace,
            deployment_root,
            deployment_run_id,
            source.database,
            profile,
        )
        sources.append((source, settings))
    if len(sources) != expected_source_failures:
        raise C4RecoveryError("C4 source failure count does not match authorization")
    try:
        store = ArtifactStore(
            destination_workspace,
            output_root,
            environment={},
            require_new_root=True,
        )
    except ArtifactStoreError as error:
        raise C4RecoveryError("C4 recovery output root is invalid") from error
    factory = client_factory or (
        lambda settings: OmniCliClient(settings, environment=os.environ)
    )
    clients: dict[tuple[str, str], C4RecoveryClient] = {}
    recovered: list[C4RecoveryEntry] = []
    for source, settings in sources:
        identity = (settings.model_id, settings.branch_id or "")
        client = clients.get(identity)
        if client is None:
            client = _PacedRecoveryClient(
                factory(settings),
                minimum_interval_seconds=float(minimum_request_interval_seconds),
                sleep=sleep,
            )
            clients[identity] = client
        recovered.append(recover_c4_source(source, client=client, store=store))
    stored = write_c4_recovery_manifest(
        store,
        source_commit=selection["source_commit"],
        source_run_id=selection["run_id"],
        source_selection_sha256=expected_selection_sha256,
        entries=tuple(recovered),
    )
    manifest = C4RecoveryManifest(
        entries=tuple(recovered),
        source_commit=selection["source_commit"],
        source_run_id=selection["run_id"],
        source_selection_sha256=expected_selection_sha256,
    )
    return {
        "counts": manifest.counts,
        "recovery_manifest_path": store.relative_path(stored).as_posix(),
        "recovery_manifest_sha256": stored.sha256,
        "source_attempts": len(selection["entries"]),
        "source_selection_sha256": expected_selection_sha256,
    }


def write_c4_recovery_manifest(
    store: ArtifactStore,
    *,
    source_commit: str,
    source_run_id: str,
    source_selection_sha256: str,
    entries: tuple[C4RecoveryEntry, ...],
) -> StoredArtifact:
    """Write one immutable canonical recovery manifest beside its result sidecars."""
    manifest = C4RecoveryManifest(
        entries=entries,
        source_commit=source_commit,
        source_run_id=source_run_id,
        source_selection_sha256=source_selection_sha256,
    )
    try:
        return store.write_json(Path("recovery.manifest.json"), manifest.as_dict())
    except ArtifactStoreError as error:
        raise C4RecoveryError("cannot write C4 recovery manifest") from error


def load_c4_recovery_manifest(
    workspace: Path, path: Path, *, expected_sha256: str
) -> C4RecoveryManifest:
    """Load one exact private recovery manifest by digest."""
    if _SHA256.fullmatch(expected_sha256) is None:
        raise C4RecoveryError("expected C4 recovery SHA-256 is invalid")
    content = _read_private_file(workspace, path)
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise C4RecoveryError("C4 recovery manifest SHA-256 does not match")
    try:
        value = json.loads(content)
        manifest = _manifest_from_dict(value)
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise C4RecoveryError("C4 recovery manifest is invalid") from error
    if content != manifest.canonical_bytes:
        raise C4RecoveryError("C4 recovery manifest is not canonical")
    return manifest


def _system_failure(
    source: C4RecoverySource, reason: str, *, plan_sha256: str | None = None
) -> C4RecoveryEntry:
    return C4RecoveryEntry(
        attempt_id=source.attempt_id,
        disposition="evaluated_system_failure",
        plan_sha256=plan_sha256,
        reason=reason,
        result_artifact_path=None,
        result_artifact_sha256=None,
        source_failure_class=source.source_failure_class,
        source_generation_sha256=source.source_generation_sha256,
    )


def _canonical(value: object) -> bytes:
    try:
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
    except (TypeError, ValueError) as error:
        raise C4RecoveryError("C4 recovery plan is not canonical JSON") from error


def _manifest_from_dict(value: object) -> C4RecoveryManifest:
    if not isinstance(value, dict) or set(value) != {
        "counts",
        "entries",
        "kind",
        "schema_version",
        "source_commit",
        "source_run_id",
        "source_selection_sha256",
    }:
        raise C4RecoveryError("C4 recovery manifest must use the exact schema")
    raw_entries = value["entries"]
    if not isinstance(raw_entries, list):
        raise C4RecoveryError("C4 recovery entries are invalid")
    entries: list[C4RecoveryEntry] = []
    expected_fields = {
        "attempt_id",
        "disposition",
        "plan_sha256",
        "reason",
        "result_artifact_path",
        "result_artifact_sha256",
        "source_failure_class",
        "source_generation_sha256",
    }
    for raw in raw_entries:
        if not isinstance(raw, dict) or set(raw) != expected_fields:
            raise C4RecoveryError("C4 recovery entry must use the exact schema")
        result_path = raw["result_artifact_path"]
        if result_path is not None and not isinstance(result_path, str):
            raise C4RecoveryError("C4 recovery result path is invalid")
        entries.append(
            C4RecoveryEntry(
                attempt_id=raw["attempt_id"],
                disposition=raw["disposition"],
                plan_sha256=raw["plan_sha256"],
                reason=raw["reason"],
                result_artifact_path=(
                    None if result_path is None else Path(result_path)
                ),
                result_artifact_sha256=raw["result_artifact_sha256"],
                source_failure_class=raw["source_failure_class"],
                source_generation_sha256=raw["source_generation_sha256"],
            )
        )
    manifest = C4RecoveryManifest(
        entries=tuple(entries),
        source_commit=value["source_commit"],
        source_run_id=value["source_run_id"],
        source_selection_sha256=value["source_selection_sha256"],
        kind=value["kind"],
        schema_version=value["schema_version"],
    )
    if value["counts"] != manifest.counts:
        raise C4RecoveryError("C4 recovery counts do not match entries")
    return manifest


def _read_private_file(workspace: Path, path: Path) -> bytes:
    try:
        root = workspace.resolve(strict=True)
    except OSError as error:
        raise C4RecoveryError("C4 recovery workspace is unavailable") from error
    relative = Path(path)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.is_relative_to(Path("experiments/autoresearch/raw"))
    ):
        raise C4RecoveryError("C4 recovery manifest path is invalid")
    candidate = root / relative
    try:
        metadata = candidate.lstat()
        if (
            candidate.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or metadata.st_size < 1
            or metadata.st_size > MAX_ARTIFACT_BYTES
        ):
            raise C4RecoveryError("C4 recovery manifest file is invalid")
        return candidate.read_bytes()
    except OSError as error:
        raise C4RecoveryError("C4 recovery manifest is unavailable") from error


def _selection_source(
    workspace: Path, run_id: str, raw_entry: object
) -> C4RecoverySource | None:
    required = {
        "attempt_id",
        "condition",
        "database",
        "generation_sha256",
        "instance_id",
        "repetition",
        "run_manifest_sha256",
    }
    if not isinstance(raw_entry, dict) or not required.issubset(raw_entry):
        raise C4RecoveryError("C4 selection entry is invalid")
    database = _component(raw_entry["database"], "C4 database")
    instance_id = _component(raw_entry["instance_id"], "C4 instance")
    expected_attempt = f"{run_id}:{instance_id}:C4:1"
    if (
        raw_entry["attempt_id"] != expected_attempt
        or raw_entry["condition"] != "C4"
        or raw_entry["repetition"] != 1
        or _SHA256.fullmatch(str(raw_entry["generation_sha256"])) is None
    ):
        raise C4RecoveryError("C4 selection entry identity is invalid")
    generation_path = (
        Path("experiments/autoresearch/raw")
        / run_id
        / database
        / "c4"
        / f"{instance_id}-r1"
        / "generation.jsonl"
    )
    generation_bytes = _read_file(workspace, generation_path, private=True)
    if hashlib.sha256(generation_bytes).hexdigest() != raw_entry["generation_sha256"]:
        raise C4RecoveryError("C4 generation SHA-256 does not match selection")
    if len(generation_bytes.splitlines()) != 1 or not generation_bytes.endswith(b"\n"):
        raise C4RecoveryError("C4 generation artifact is invalid")
    try:
        generation = json.loads(generation_bytes)
    except json.JSONDecodeError as error:
        raise C4RecoveryError("C4 generation artifact is invalid") from error
    if (
        not isinstance(generation, dict)
        or generation.get("attempt_id") != expected_attempt
        or generation.get("condition") != "C4"
        or generation.get("instance_id") != instance_id
        or generation.get("repetition") != 1
        or generation.get("run_id") != run_id
    ):
        raise C4RecoveryError("C4 generation identity is invalid")
    if generation.get("failure_origin") != "benchmark_infrastructure":
        return None
    if generation.get("generation_outcome") != "errored":
        raise C4RecoveryError("C4 infrastructure generation outcome is invalid")
    generated_query = generation.get("generated_query")
    if generated_query is not None and not isinstance(generated_query, str):
        raise C4RecoveryError("C4 generated semantic query is invalid")
    return C4RecoverySource(
        attempt_id=expected_attempt,
        database=database,
        generated_query=generated_query,
        source_failure_class=generation.get("terminal_failure_class"),
        source_generation_sha256=raw_entry["generation_sha256"],
    )


def _deployment_settings(
    workspace: Path,
    deployment_root: Path,
    deployment_run_id: str,
    database: str,
    profile: str,
) -> OmniCliSettings:
    root = _confined_path(
        deployment_root, Path("experiments/deployments"), "deployment root"
    )
    path = root / f"{deployment_run_id}.{database}.json"
    content = _read_file(workspace, path, private=False)
    try:
        record = json.loads(content)
    except json.JSONDecodeError as error:
        raise C4RecoveryError("C4 deployment record is invalid") from error
    if (
        not isinstance(record, dict)
        or record.get("database") != database
        or record.get("status") != "verified"
        or not isinstance(record.get("model_id"), str)
        or not record["model_id"]
        or not isinstance(record.get("branch_id"), str)
        or not record["branch_id"]
    ):
        raise C4RecoveryError("C4 deployment record is invalid")
    return OmniCliSettings.from_profile(
        profile=profile,
        model_id=record["model_id"],
        branch_id=record["branch_id"],
    )


def _workspace(path: Path) -> Path:
    try:
        return Path(path).resolve(strict=True)
    except OSError as error:
        raise C4RecoveryError("C4 recovery workspace is unavailable") from error


def _confined_path(path: Path, root: Path, description: str) -> Path:
    selected = Path(path)
    if (
        selected.is_absolute()
        or ".." in selected.parts
        or not selected.is_relative_to(root)
    ):
        raise C4RecoveryError(f"{description} path is invalid")
    return selected


def _component(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", value) is None
    ):
        raise C4RecoveryError(f"{description} is invalid")
    return value


def _read_file(workspace: Path, path: Path, *, private: bool) -> bytes:
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise C4RecoveryError("C4 recovery input path is invalid")
    candidate = workspace / relative
    try:
        metadata = candidate.lstat()
        expected_mode = 0o600 if private else None
        if (
            candidate.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or (
                expected_mode is not None
                and stat.S_IMODE(metadata.st_mode) != expected_mode
            )
            or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1
            or metadata.st_size < 1
            or metadata.st_size > MAX_ARTIFACT_BYTES
        ):
            raise C4RecoveryError("C4 recovery input file is invalid")
        return candidate.read_bytes()
    except OSError as error:
        raise C4RecoveryError("C4 recovery input is unavailable") from error
