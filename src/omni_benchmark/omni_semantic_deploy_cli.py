"""Bounded live fan-out for isolated public Omni semantic bundles."""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import subprocess
import tarfile
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from .omni_semantic_deploy_live import (
    DeploymentRecord,
    bundle_preflight_failure_record,
    deployment_record_path,
    deploy_public_plan,
    write_deployment_record,
)
from .omni_semantic_deployment import (
    OmniSemanticDeploymentError,
    OmniSemanticDeploymentPlan,
    build_semantic_deployment_plan,
)

CommandRunner = Callable[
    [tuple[str, ...], Mapping[str, str], str | None, float], tuple[int, str, str]
]
ClientFactory = Callable[[str], "OmniDeploymentCli"]
CommitObserver = Callable[[Path], str]
BundleInventoryLoader = Callable[
    [Path, str],
    tuple[dict[str, OmniSemanticDeploymentPlan], dict[str, str]],
]
_LIVE_CONNECTION_PREFIX = "LiveSQLBench "
_ARCHAEOLOGY_DATABASE = "archeology_scan_large"
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_MAX_REQUEST_INTERVAL_SECONDS = 60.0
_CHILD_ENVIRONMENT_KEYS = frozenset(
    {
        "HOME",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_PROXY",
        "OMNI_CONFIG_PATH",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
        "XDG_CONFIG_HOME",
    }
)


class OmniDeploymentCliError(RuntimeError):
    """Raised when the product deployment boundary returns an invalid response."""


class OmniDeploymentCli:
    """Credential-safe model deployment operations through the official Omni CLI."""

    def __init__(
        self,
        profile: str,
        *,
        binary: str = "omni",
        timeout_seconds: float = 120.0,
        runner: CommandRunner | None = None,
        environment: Mapping[str, str] | None = None,
        minimum_request_interval_seconds: float = 0.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not profile.strip():
            raise OmniDeploymentCliError("profile must be non-empty")
        if (
            not math.isfinite(minimum_request_interval_seconds)
            or minimum_request_interval_seconds < 0
            or minimum_request_interval_seconds > _MAX_REQUEST_INTERVAL_SECONDS
        ):
            raise OmniDeploymentCliError("request interval is outside safe bounds")
        self._profile = profile.strip()
        self._binary = binary
        self._timeout_seconds = timeout_seconds
        self._runner = _subprocess_runner if runner is None else runner
        source = os.environ if environment is None else environment
        self._environment = {
            key: value
            for key, value in source.items()
            if key in _CHILD_ENVIRONMENT_KEYS and value
        }
        self._minimum_request_interval_seconds = minimum_request_interval_seconds
        self._clock = clock
        self._sleep = sleep
        self._pace_lock = threading.Lock()
        self._last_request_at: float | None = None
        self._lock = threading.Lock()
        self._connections: dict[str, str] | None = None
        self._models: dict[tuple[str, str], tuple[str, dict[str, str]]] | None = None
        self._resource_locks: dict[tuple[str, ...], threading.Lock] = {}

    def connection_ids(self, requested: tuple[str, ...]) -> dict[str, str]:
        """Resolve exact benchmark connection names without retaining coordinates."""
        with self._lock:
            if self._connections is None:
                response = self._run_json_object(("connections", "list"))
                self._connections = _connection_map(response)
            available = dict(self._connections)
        missing = sorted(set(requested) - set(available))
        if missing:
            raise OmniDeploymentCliError(
                f"missing LiveSQLBench connections: {', '.join(missing)}"
            )
        return {database: available[database] for database in requested}

    def ensure_shared_model(self, connection_id: str, name: str) -> tuple[str, bool]:
        """Find the exact isolated shared model or create it once."""
        self._load_models()
        key = (connection_id, name)
        with self._resource_lock(("model", *key)):
            with self._lock:
                assert self._models is not None
                existing = self._models.get(key)
            if existing is not None:
                return existing[0], False
            response = self._run_json_object(
                ("models", "create", "--body", "-"),
                stdin=_compact_json(
                    {
                        "connectionId": connection_id,
                        "modelKind": "SHARED",
                        "modelName": name,
                    }
                ),
            )
            model_id = _response_id(response, "model creation")
            with self._lock:
                assert self._models is not None
                self._models[key] = (model_id, {})
            return model_id, True

    def ensure_branch(self, model_id: str, name: str) -> tuple[str, bool]:
        """Find the exact isolated branch or create it once."""
        self._load_models()
        with self._resource_lock(("branch", model_id, name)):
            with self._lock:
                assert self._models is not None
                model = next(
                    (value for value in self._models.values() if value[0] == model_id),
                    None,
                )
                branch_id = None if model is None else model[1].get(name)
            if branch_id is not None:
                return branch_id, False
            response = self._run_json_object(
                ("models", "create-branch", model_id, "--name", name)
            )
            branch_id = _response_id(response, "branch creation")
            self._remember_branch(model_id, name, branch_id)
            return branch_id, True

    def _remember_branch(self, model_id: str, name: str, branch_id: str) -> None:
        with self._lock:
            assert self._models is not None
            for key, value in tuple(self._models.items()):
                if value[0] == model_id:
                    self._models[key] = (model_id, {**value[1], name: branch_id})
                    break

    def _resource_lock(self, key: tuple[str, ...]) -> threading.Lock:
        with self._lock:
            lock = self._resource_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._resource_locks[key] = lock
            return lock

    def upload_yaml(
        self, model_id: str, branch_id: str, path: str, content: str
    ) -> None:
        """Upload one authenticated extension file to the isolated branch."""
        self._run_json_value(
            ("models", "yaml-create", model_id, "--body", "-"),
            stdin=_compact_json(
                {
                    "branchId": branch_id,
                    "commitMessage": "Deploy public LiveSQLBench semantic baseline",
                    "fileName": path,
                    "mode": "extension",
                    "yaml": content,
                }
            ),
        )

    def validate(self, model_id: str, branch_id: str) -> object:
        """Return the product-native validator response unchanged."""
        return self._run_json_value(
            ("models", "validate", model_id, "--branchid", branch_id)
        )

    def readback(self, model_id: str, branch_id: str) -> Mapping[str, str]:
        """Read the complete extension layer for exact semantic verification."""
        response = self._run_json_object(
            (
                "models",
                "yaml-get",
                model_id,
                "--branchid",
                branch_id,
                "--mode",
                "extension",
            )
        )
        files = response.get("files")
        if not isinstance(files, Mapping) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in files.items()
        ):
            raise OmniDeploymentCliError("model readback files are malformed")
        return dict(files)

    def _load_models(self) -> None:
        with self._lock:
            if self._models is not None:
                return
            response = self._run_json_object(
                (
                    "models",
                    "list",
                    "--modelkind",
                    "SHARED",
                    "--include",
                    "activeBranches",
                )
            )
            self._models = _model_map(response)

    def _run_json_object(
        self, command: tuple[str, ...], *, stdin: str | None = None
    ) -> dict[str, Any]:
        value = self._run_json_value(command, stdin=stdin)
        if not isinstance(value, dict):
            raise OmniDeploymentCliError("Omni CLI response must be an object")
        return value

    def _run_json_value(
        self, command: tuple[str, ...], *, stdin: str | None = None
    ) -> Any:
        arguments = (
            self._binary,
            "--compact",
            "--profile",
            self._profile,
            *command,
        )
        try:
            returncode, stdout, _stderr = self._run_paced(arguments, stdin)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise OmniDeploymentCliError("Omni CLI request did not complete") from error
        if returncode != 0:
            raise OmniDeploymentCliError(
                f"Omni CLI {command[0]} {command[1]} request failed"
            )
        if len(stdout.encode("utf-8")) > _MAX_RESPONSE_BYTES:
            raise OmniDeploymentCliError("Omni CLI response exceeds capture limit")
        try:
            return json.loads(stdout)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise OmniDeploymentCliError(
                "Omni CLI response is not valid JSON"
            ) from error

    def _run_paced(
        self, arguments: tuple[str, ...], stdin: str | None
    ) -> tuple[int, str, str]:
        with self._pace_lock:
            now = self._clock()
            if self._last_request_at is not None:
                delay = self._minimum_request_interval_seconds - (
                    now - self._last_request_at
                )
                if delay > 0:
                    self._sleep(delay)
                    now = self._clock()
            self._last_request_at = now
            return self._runner(
                arguments, self._environment, stdin, self._timeout_seconds
            )


def deployment_main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: ClientFactory | None = None,
    commit_observer: CommitObserver | None = None,
    bundle_loader: BundleInventoryLoader | None = None,
) -> int:
    """Deploy selected public bundles in bounded parallel batches."""
    arguments = _parser().parse_args(argv)
    if not arguments.execute_live_deployment:
        raise OmniDeploymentCliError(
            "live deployment requires explicit acknowledgement"
        )
    workspace = arguments.workspace.resolve(strict=True)
    observe = _git_commit if commit_observer is None else commit_observer
    source_commit = observe(workspace)
    load = _committed_bundle_inventory if bundle_loader is None else bundle_loader
    all_plans, all_plan_failures = load(workspace, source_commit)
    available = set(all_plans) | set(all_plan_failures)
    if not available:
        raise OmniDeploymentCliError("no public semantic bundles found")
    requested = tuple(arguments.database or sorted(available))
    if len(requested) != len(set(requested)):
        raise OmniDeploymentCliError("duplicate database selection")
    unknown = sorted(set(requested) - available)
    if unknown:
        raise OmniDeploymentCliError(f"unknown bundle database: {', '.join(unknown)}")
    plans = {
        database: all_plans[database] for database in requested if database in all_plans
    }
    plan_failures = {
        database: all_plan_failures[database]
        for database in requested
        if database in all_plan_failures
    }
    _claim_deployment_run(
        arguments.output_root,
        arguments.run_id,
        requested,
        source_commit,
        arguments.minimum_request_interval_seconds,
    )
    observed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    records: list[DeploymentRecord] = []
    persistence_failures = 0
    for database, detail in plan_failures.items():
        record = bundle_preflight_failure_record(
            database=database,
            run_id=arguments.run_id,
            source_commit=source_commit,
            observed_at=observed_at,
            detail=detail,
        )
        records.append(record)
        try:
            path = write_deployment_record(arguments.output_root, record)
        except OSError:
            persistence_failures += 1
            print(
                _compact_json(
                    {
                        "database": record.database,
                        "record": None,
                        "status": "record_write_failed",
                    }
                )
            )
            continue
        _print_record(record, path)
    if not plans:
        return _print_summary(arguments.run_id, records, persistence_failures)
    client = (
        OmniDeploymentCli(
            arguments.profile,
            minimum_request_interval_seconds=arguments.minimum_request_interval_seconds,
        )
        if client_factory is None
        else client_factory(arguments.profile)
    )
    connections = client.connection_ids(tuple(plans))
    with ThreadPoolExecutor(max_workers=arguments.max_workers) as executor:
        futures = {
            executor.submit(
                deploy_public_plan,
                plan=plan,
                connection_id=connections[database],
                client=client,
                run_id=arguments.run_id,
                source_commit=source_commit,
                observed_at=observed_at,
            ): database
            for database, plan in plans.items()
        }
        for future in as_completed(futures):
            record = future.result()
            records.append(record)
            try:
                path = write_deployment_record(arguments.output_root, record)
            except OSError:
                persistence_failures += 1
                print(
                    _compact_json(
                        {
                            "database": record.database,
                            "record": None,
                            "status": "record_write_failed",
                        }
                    )
                )
                continue
            _print_record(record, path)
    return _print_summary(arguments.run_id, records, persistence_failures)


def _print_summary(
    run_id: str, records: Sequence[DeploymentRecord], persistence_failures: int
) -> int:
    summary = {
        "failed": sum(record.status == "failed" for record in records),
        "run_id": run_id,
        "total": len(records),
        "record_write_failed": persistence_failures,
        "verified": sum(record.status == "verified" for record in records),
    }
    print(_compact_json(summary))
    return 0 if summary["failed"] == 0 and persistence_failures == 0 else 1


def _print_record(record: DeploymentRecord, path: Path) -> None:
    print(
        _compact_json(
            {
                "branch_id": record.branch_id,
                "database": record.database,
                "manifest_sha256": record.manifest_sha256,
                "model_id": record.model_id,
                "record": str(path),
                "status": record.status,
            }
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--database", action="append")
    parser.add_argument("--max-workers", type=int, choices=range(1, 9), default=4)
    parser.add_argument(
        "--minimum-request-interval-seconds",
        type=_request_interval,
        default=0.0,
    )
    parser.add_argument("--execute-live-deployment", action="store_true")
    return parser


def _bundle_candidates(workspace: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    canary = workspace / "semantic_models/public_bundle"
    if canary.is_dir():
        result[_ARCHAEOLOGY_DATABASE] = canary
    for root in sorted(
        (workspace / "semantic_models/public_baseline").glob("*/bundle")
    ):
        database = root.parent.name
        if database in result:
            raise OmniDeploymentCliError(f"duplicate bundle for {database}")
        result[database] = root
    if not result:
        raise OmniDeploymentCliError("no public semantic bundles found")
    return result


def _working_bundle_inventory(
    workspace: Path, _source_commit: str
) -> tuple[dict[str, OmniSemanticDeploymentPlan], dict[str, str]]:
    roots = _bundle_candidates(workspace)
    plans: dict[str, OmniSemanticDeploymentPlan] = {}
    failures: dict[str, str] = {}
    for database, root in roots.items():
        try:
            plan = build_semantic_deployment_plan(root)
            if plan.database != database:
                raise OmniSemanticDeploymentError(
                    "manifest database does not match bundle directory"
                )
            plans[database] = plan
        except OmniSemanticDeploymentError as error:
            failures[database] = str(error)
        except RecursionError:
            failures[database] = "bundle parser recursion limit exceeded"
    return plans, failures


def _committed_bundle_inventory(
    workspace: Path, source_commit: str
) -> tuple[dict[str, OmniSemanticDeploymentPlan], dict[str, str]]:
    """Build immutable plans from the exact Git tree recorded in every status."""
    completed = subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            source_commit,
            "--",
            "semantic_models",
        ],
        cwd=workspace,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise OmniDeploymentCliError("could not snapshot committed semantic bundles")
    try:
        with tempfile.TemporaryDirectory(
            prefix="omni-semantic-deployment-"
        ) as directory:
            snapshot = Path(directory)
            _extract_bundle_archive(completed.stdout, snapshot)
            return _working_bundle_inventory(snapshot, source_commit)
    except (OSError, tarfile.TarError) as error:
        raise OmniDeploymentCliError(
            "could not materialize committed semantic bundles"
        ) from error


def committed_bundle_inventory(
    workspace: Path, source_commit: str
) -> tuple[dict[str, OmniSemanticDeploymentPlan], dict[str, str]]:
    """Load authenticated semantic plans from one exact committed Git tree."""
    return _committed_bundle_inventory(workspace, source_commit)


def committed_bundle_plan(
    workspace: Path, source_commit: str, database: str
) -> OmniSemanticDeploymentPlan:
    """Load one authenticated semantic plan from an exact committed Git tree."""
    plans, failures = committed_bundle_inventory(workspace, source_commit)
    if database in failures:
        raise OmniDeploymentCliError(
            f"committed semantic bundle is invalid: {database}: {failures[database]}"
        )
    try:
        return plans[database]
    except KeyError as error:
        raise OmniDeploymentCliError(
            f"committed semantic bundle is unavailable: {database}"
        ) from error


def _extract_bundle_archive(content: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:") as archive:
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if (
                not parts
                or Path(member.name).is_absolute()
                or ".." in parts
                or not (member.isdir() or member.isfile())
            ):
                raise OmniDeploymentCliError("committed bundle archive is unsafe")
            target = destination.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            source = archive.extractfile(member)
            if source is None:
                raise OmniDeploymentCliError("committed bundle archive is malformed")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read())


def _preflight_record_paths(
    root: Path, run_id: str, databases: tuple[str, ...]
) -> None:
    for database in databases:
        path = deployment_record_path(root, run_id, database)
        if path.exists():
            raise OmniDeploymentCliError(
                f"deployment record already exists for {database}"
            )


def _claim_deployment_run(
    root: Path,
    run_id: str,
    databases: tuple[str, ...],
    source_commit: str,
    minimum_request_interval_seconds: float = 0.0,
) -> Path:
    if root.exists() and not root.is_dir():
        raise OmniDeploymentCliError("deployment run could not be claimed")
    try:
        _preflight_record_paths(root, run_id, databases)
        root.mkdir(parents=True, exist_ok=True)
        claim_path = root / f"{run_id}.claim"
        descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            payload = _compact_json(
                {
                    "databases": sorted(databases),
                    "kind": "public-omni-semantic-deployment-claim",
                    "minimum_request_interval_seconds": minimum_request_interval_seconds,
                    "run_id": run_id,
                    "schema_version": 1,
                    "source_commit": source_commit,
                }
            )
            os.write(descriptor, f"{payload}\n".encode("utf-8"))
        finally:
            os.close(descriptor)
        return claim_path
    except FileExistsError as error:
        raise OmniDeploymentCliError("deployment run is already claimed") from error
    except (OSError, ValueError) as error:
        raise OmniDeploymentCliError("deployment run could not be claimed") from error


def _request_interval(value: str) -> float:
    try:
        interval = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("request interval must be numeric") from error
    if (
        not math.isfinite(interval)
        or interval < 0
        or interval > _MAX_REQUEST_INTERVAL_SECONDS
    ):
        raise argparse.ArgumentTypeError("request interval is outside safe bounds")
    return interval


def _connection_map(response: Mapping[str, Any]) -> dict[str, str]:
    records = response.get("connections")
    if not isinstance(records, list):
        raise OmniDeploymentCliError("connection list is malformed")
    result: dict[str, str] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        name, connection_id = record.get("name"), record.get("id")
        if not isinstance(name, str) or not name.startswith(_LIVE_CONNECTION_PREFIX):
            continue
        if not isinstance(connection_id, str) or not connection_id:
            raise OmniDeploymentCliError("benchmark connection ID is malformed")
        database = name.removeprefix(_LIVE_CONNECTION_PREFIX)
        if database in result:
            raise OmniDeploymentCliError(f"duplicate benchmark connection {database}")
        result[database] = connection_id
    return result


def _model_map(
    response: Mapping[str, Any],
) -> dict[tuple[str, str], tuple[str, dict[str, str]]]:
    records = response.get("records")
    if not isinstance(records, list):
        raise OmniDeploymentCliError("model list is malformed")
    result: dict[tuple[str, str], tuple[str, dict[str, str]]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        connection_id, name, model_id = (
            record.get("connectionId"),
            record.get("name"),
            record.get("id"),
        )
        if not all(
            isinstance(value, str) and value
            for value in (connection_id, name, model_id)
        ):
            continue
        branches = _branch_map(record.get("branches"))
        key = (connection_id, name)
        if key in result:
            raise OmniDeploymentCliError("duplicate shared model identity")
        result[key] = (model_id, branches)
    return result


def _branch_map(value: object) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, list):
        raise OmniDeploymentCliError("model branch list is malformed")
    result: dict[str, str] = {}
    for branch in value:
        if not isinstance(branch, Mapping):
            continue
        name, branch_id = branch.get("name"), branch.get("id")
        if isinstance(name, str) and isinstance(branch_id, str):
            if name in result:
                raise OmniDeploymentCliError("duplicate model branch identity")
            result[name] = branch_id
    return result


def _response_id(response: Mapping[str, Any], description: str) -> str:
    value = response.get("id")
    if isinstance(value, str) and value:
        return value
    for key in ("model", "record"):
        nested = response.get(key)
        if isinstance(nested, Mapping):
            value = nested.get("id")
            if isinstance(value, str) and value:
                return value
    raise OmniDeploymentCliError(f"{description} response has no ID")


def _git_commit(workspace: Path) -> str:
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "semantic_models/public_bundle",
            "semantic_models/public_baseline",
        ],
        cwd=workspace,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    if status.returncode != 0 or status.stdout:
        raise OmniDeploymentCliError("public semantic bundle tree is not committed")
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or len(commit) != 40:
        raise OmniDeploymentCliError("could not observe source commit")
    return commit


def _compact_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _subprocess_runner(
    arguments: tuple[str, ...],
    environment: Mapping[str, str],
    stdin: str | None,
    timeout_seconds: float,
) -> tuple[int, str, str]:
    completed = subprocess.run(
        list(arguments),
        input=stdin,
        capture_output=True,
        check=False,
        env=dict(environment),
        text=True,
        timeout=timeout_seconds,
    )
    return completed.returncode, completed.stdout, completed.stderr
