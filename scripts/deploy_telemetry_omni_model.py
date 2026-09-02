#!/usr/bin/env python3
"""Deploy the hand-authored telemetry Omni model through the omni CLI.

Sequence: find or create the shared model on the telemetry connection, create
a branch, upload every file under config/telemetry_db/omni_model, validate the
branch, merge it. ``--dry-run`` (the default) prints the plan; ``--live`` runs
it. The script is plumbing only: every judgement lives in the YAML.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONNECTION_ID = "a511399c-aa51-4f51-b00a-6845d767687b"
MODEL_NAME = "omni-benchmark telemetry"
MODEL_DIR = Path(__file__).resolve().parents[1] / "config/telemetry_db/omni_model"
YAML_MODE = "combined"
COMMIT_MESSAGE = "Deploy hand-authored telemetry semantic model"
REQUEST_INTERVAL_SECONDS = 1.0
RATE_LIMIT_RETRY_DELAYS = (2.0, 5.0, 10.0)


class DeployError(RuntimeError):
    """A deployment step failed; nothing after it ran."""


@dataclass(frozen=True)
class ModelFile:
    name: str
    content: str


@dataclass(frozen=True)
class DeployResult:
    model_id: str
    branch_id: str
    branch_name: str
    uploaded: tuple[str, ...]
    validation: list[Any]
    merged: bool


def model_files(root: Path) -> tuple[ModelFile, ...]:
    """Every file under the model directory, named by its posix relative path."""
    if not root.is_dir():
        raise DeployError(f"model directory missing: {root}")
    paths = sorted(path for path in root.rglob("*") if path.is_file())
    if not paths:
        raise DeployError(f"model directory has no files: {root}")
    return tuple(
        ModelFile(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8"))
        for path in paths
    )


class OmniCli:
    """Thin JSON wrapper over one omni CLI profile.

    Calls are paced by ``interval_seconds`` and an HTTP 429 is retried after
    each delay in ``retry_delays``; every wait is reported on stderr and the
    final failure carries the retry count.
    """

    def __init__(
        self,
        binary: str,
        profile: str,
        *,
        interval_seconds: float = REQUEST_INTERVAL_SECONDS,
        retry_delays: tuple[float, ...] = RATE_LIMIT_RETRY_DELAYS,
        sleep=time.sleep,
    ) -> None:
        self._prefix = (binary, "-p", profile, "-o", "json")
        self._interval = interval_seconds
        self._retry_delays = retry_delays
        self._sleep = sleep
        self._calls = 0

    def run(self, *args: str, stdin: str | None = None) -> Any:
        label = "omni " + " ".join(args[:2])
        for attempt, delay in enumerate((*self._retry_delays, None)):
            if self._calls:
                self._sleep(self._interval)
            self._calls += 1
            completed = self._invoke(args, stdin)
            if completed.returncode == 0:
                return _parse_json(completed.stdout, label)
            detail = completed.stderr.strip() or completed.stdout.strip()
            if "HTTP 429" not in detail or delay is None:
                raise DeployError(
                    f"{label} failed ({completed.returncode}) after {attempt} "
                    f"rate-limit retries: {detail}"
                )
            print(f"{label}: HTTP 429, retrying in {delay:g}s", file=sys.stderr)
            self._sleep(delay)
        raise AssertionError("unreachable: retry loop always returns or raises")

    def _invoke(
        self, args: tuple[str, ...], stdin: str | None
    ) -> subprocess.CompletedProcess[str]:
        command = (*self._prefix, *args)
        try:
            return subprocess.run(
                command,
                input=stdin,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            raise DeployError(
                f"cannot run the omni CLI at {self._prefix[0]!r}: {error}"
            ) from error


def _parse_json(stdout: str, label: str) -> Any:
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        raise DeployError(f"{label} returned non-JSON output") from error


def _record_id(response: Any, what: str) -> str:
    if isinstance(response, dict):
        for key in ("id", "branchId"):
            value = response.get(key)
            if isinstance(value, str) and value:
                return value
        for key in ("model", "branch"):
            nested = response.get(key)
            if isinstance(nested, dict) and isinstance(nested.get("id"), str):
                return nested["id"]
    raise DeployError(f"{what} response carries no id: {json.dumps(response)[:200]}")


def find_shared_model(cli: OmniCli) -> str | None:
    """The one SHARED model named ``MODEL_NAME``, or None.

    ``--name`` bounds the server-side result set so a match cannot sit past the
    first page. An unexhausted page is still refused rather than assumed empty:
    creating a second SHARED model under the same name would split the
    deployment history across two models.
    """
    response = cli.run(
        "models",
        "list",
        "--connectionid",
        CONNECTION_ID,
        "--modelkind",
        "SHARED",
        "--name",
        MODEL_NAME,
    )
    records = response.get("records") if isinstance(response, dict) else None
    if not isinstance(records, list):
        raise DeployError("models list response is malformed")
    page_info = response.get("pageInfo")
    if isinstance(page_info, dict) and page_info.get("hasNextPage"):
        raise DeployError(
            f"models list for {MODEL_NAME!r} has more pages; refusing to decide "
            "from a partial result set"
        )
    matches = [
        record["id"]
        for record in records
        if isinstance(record, dict) and record.get("name") == MODEL_NAME
    ]
    if len(matches) > 1:
        raise DeployError(f"{len(matches)} shared models named {MODEL_NAME!r}")
    return matches[0] if matches else None


def create_shared_model(cli: OmniCli) -> str:
    body = {
        "connectionId": CONNECTION_ID,
        "modelKind": "SHARED",
        "modelName": MODEL_NAME,
    }
    response = cli.run("models", "create", "--body", "-", stdin=json.dumps(body))
    return _record_id(response, "model creation")


def create_branch(cli: OmniCli, model_id: str, name: str) -> str:
    response = cli.run("models", "create-branch", model_id, "--name", name)
    return _record_id(response, "branch creation")


def upload_file(cli: OmniCli, model_id: str, branch_id: str, file: ModelFile) -> None:
    body = {
        "branchId": branch_id,
        "commitMessage": COMMIT_MESSAGE,
        "fileName": file.name,
        "mode": YAML_MODE,
        "yaml": file.content,
    }
    cli.run("models", "yaml-create", model_id, "--body", "-", stdin=json.dumps(body))


def validate_branch(cli: OmniCli, model_id: str, branch_id: str) -> list[Any]:
    response = cli.run("models", "validate", model_id, "--branchid", branch_id)
    if not isinstance(response, list):
        raise DeployError("validate response must be a list of issues")
    return response


def merge_branch(cli: OmniCli, model_id: str, branch_name: str) -> None:
    body = {"commit_message": COMMIT_MESSAGE, "delete_branch": False}
    cli.run(
        "models",
        "merge-branch",
        model_id,
        branch_name,
        "--body",
        "-",
        stdin=json.dumps(body),
    )


def deploy(
    cli: OmniCli, files: tuple[ModelFile, ...], branch_name: str
) -> DeployResult:
    """Run the full sequence; stop before merge when validation reports issues."""
    model_id = find_shared_model(cli) or create_shared_model(cli)
    branch_id = create_branch(cli, model_id, branch_name)
    for file in files:
        upload_file(cli, model_id, branch_id, file)
    validation = validate_branch(cli, model_id, branch_id)
    if validation:
        return DeployResult(
            model_id,
            branch_id,
            branch_name,
            tuple(f.name for f in files),
            validation,
            merged=False,
        )
    merge_branch(cli, model_id, branch_name)
    return DeployResult(
        model_id,
        branch_id,
        branch_name,
        tuple(f.name for f in files),
        validation,
        merged=True,
    )


def plan_lines(files: tuple[ModelFile, ...], branch_name: str) -> list[str]:
    return [
        f"models list --connectionid {CONNECTION_ID} --modelkind SHARED "
        f"--name {MODEL_NAME!r} (reuse it or models create)",
        f"models create-branch <model-id> --name {branch_name}",
        *(
            f"models yaml-create <model-id> fileName={file.name} mode={YAML_MODE} "
            f"({len(file.content)} bytes)"
            for file in files
        ),
        "models validate <model-id> --branchid <branch-id>",
        f"models merge-branch <model-id> {branch_name} (only when validate is clean)",
    ]


def default_branch_name() -> str:
    return "telemetry-model-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the plan (default)")
    mode.add_argument("--live", action="store_true", help="execute against Omni")
    parser.add_argument("--omni", default="omni", help="omni CLI binary")
    parser.add_argument("--profile", default="benchmark-infra", help="omni profile")
    parser.add_argument("--branch-name", default=None)
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    branch_name = arguments.branch_name or default_branch_name()
    files = model_files(arguments.model_dir)
    if not arguments.live:
        print("\n".join(plan_lines(files, branch_name)))
        return 0
    result = deploy(OmniCli(arguments.omni, arguments.profile), files, branch_name)
    print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    if not result.merged:
        print("validation reported issues; branch left unmerged", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DeployError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
