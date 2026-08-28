"""Credential-safe read and execution boundary for the Omni CLI."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .content_policy import ContentPolicy


class OmniCliError(RuntimeError):
    """Raised when the Omni CLI boundary cannot produce a valid JSON response."""


CommandRunner = Callable[
    [Sequence[str], Mapping[str, str], str | None, float], tuple[int, str, str]
]

COMMON_CHILD_ENVIRONMENT_KEYS = frozenset(
    {
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "NO_PROXY",
        "PATH",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TMPDIR",
    }
)
PROFILE_CHILD_ENVIRONMENT_KEYS = frozenset(
    {"HOME", "OMNI_CONFIG_PATH", "XDG_CONFIG_HOME"}
)
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/+~-]{0,199}")


@dataclass(frozen=True)
class OmniCliSettings:
    """Non-secret, frozen settings; authentication remains in process environment."""

    base_url: str
    model_id: str
    profile: str | None
    branch_id: str | None
    binary: str = "omni"
    timeout_seconds: float = 60.0

    @property
    def authentication_mode(self) -> str:
        """Derive auth mode from the only retained authentication setting."""
        return "profile" if self.profile is not None else "environment_token"

    @classmethod
    def from_environment(cls, environment: Mapping[str, str]) -> OmniCliSettings:
        """Validate settings without retaining credential values."""
        base_url = _required_environment(environment, "OMNI_BASE_URL")
        model_id = _required_environment(environment, "OMNI_MODEL_ID")
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
        ):
            raise OmniCliError(
                "OMNI_BASE_URL must be an HTTPS origin without credentials"
            )
        profile = _optional_environment(environment, "OMNI_PROFILE")
        token_available = bool(_optional_environment(environment, "OMNI_API_TOKEN"))
        if profile is None and not token_available:
            raise OmniCliError("set exactly one of OMNI_PROFILE or OMNI_API_TOKEN")
        if profile is not None and token_available:
            raise OmniCliError("set exactly one of OMNI_PROFILE or OMNI_API_TOKEN")
        branch_id = _optional_environment(environment, "OMNI_BRANCH_ID")
        return cls(
            base_url=base_url,
            model_id=model_id,
            profile=profile,
            branch_id=branch_id,
        )


class OmniCliClient:
    """Invoke supported Omni operations without shell expansion or token arguments."""

    def __init__(
        self,
        settings: OmniCliSettings,
        *,
        runner: CommandRunner | None = None,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._settings = settings
        self._runner = _subprocess_runner if runner is None else runner
        self._environment = dict(os.environ if environment is None else environment)
        self._content_policy = ContentPolicy.from_environment(self._environment)

    def whoami(self) -> dict[str, Any]:
        """Verify authentication and return the unmodified identity response."""
        return self._run_json(("whoami", "whoami"))

    def list_models(self) -> dict[str, Any]:
        """List shared models available to the authenticated identity."""
        return self._run_json(("models", "list", "--modelkind", "SHARED"))

    def submit_job(self, question: str) -> dict[str, Any]:
        """Submit a fresh production-agent job using JSON stdin."""
        prompt = _required_string(question, "question")
        if not self._content_policy.query_is_safe(prompt):
            raise OmniCliError("question contains credential material")
        body: dict[str, object] = {
            "modelId": self._settings.model_id,
            "progressWebhookEnabled": False,
            "prompt": prompt,
        }
        if self._settings.branch_id is not None:
            body["branchId"] = self._settings.branch_id
        return self._run_json(
            ("ai", "job-submit", "--body", "-"),
            stdin=json.dumps(body, separators=(",", ":"), sort_keys=True),
        )

    def job_status(self, job_id: str) -> dict[str, Any]:
        """Read one asynchronous job's current state."""
        return self._run_json(("ai", "job-status", _required_job_id(job_id)))

    def job_result(self, job_id: str) -> dict[str, Any]:
        """Read all actions and results for one completed job."""
        return self._run_json(("ai", "job-result", _required_job_id(job_id)))

    def run_query_json(self, query: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Rerun one semantic query as raw JSON without formatting or cache reuse."""
        semantic_query = _query_with_model(query, self._settings.model_id)
        body: dict[str, object] = {
            "cache": "SkipCache",
            "formatResults": False,
            "query": semantic_query,
            "resultType": "json",
        }
        if self._settings.branch_id is not None:
            body["branchId"] = self._settings.branch_id
        value = self._run_json_value(
            ("query", "run", "--body", "-"),
            stdin=json.dumps(body, separators=(",", ":"), sort_keys=True),
        )
        if not isinstance(value, list) or any(
            not isinstance(row, dict) for row in value
        ):
            raise OmniCliError("Omni typed result must be an array of row objects")
        return value

    def plan_query(self, query: Mapping[str, Any]) -> dict[str, Any]:
        """Return authoritative field metadata without executing the query."""
        semantic_query = _query_with_model(query, self._settings.model_id)
        body: dict[str, object] = {
            "cache": "SkipRequery",
            "planOnly": True,
            "query": semantic_query,
        }
        if self._settings.branch_id is not None:
            body["branchId"] = self._settings.branch_id
        lines = self._run_ndjson(
            ("query", "run", "--body", "-"),
            stdin=json.dumps(body, separators=(",", ":"), sort_keys=True),
        )
        return _one_planned_job(lines)

    def _run_json(
        self, command: Sequence[str], *, stdin: str | None = None
    ) -> dict[str, Any]:
        value = self._run_json_value(command, stdin=stdin)
        if not isinstance(value, dict):
            raise OmniCliError("Omni CLI JSON response must be an object")
        return value

    def _run_json_value(
        self, command: Sequence[str], *, stdin: str | None = None
    ) -> Any:
        stdout = self._run_output(command, stdin=stdin)
        try:
            value = json.loads(stdout)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise OmniCliError("Omni CLI did not return valid JSON") from error
        return value

    def _run_ndjson(
        self, command: Sequence[str], *, stdin: str | None = None
    ) -> tuple[dict[str, Any], ...]:
        stdout = self._run_output(command, stdin=stdin)
        values: list[dict[str, Any]] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except (UnicodeError, json.JSONDecodeError) as error:
                raise OmniCliError("Omni CLI did not return valid NDJSON") from error
            if not isinstance(value, dict):
                raise OmniCliError("Omni CLI NDJSON lines must be objects")
            values.append(value)
        if not values:
            raise OmniCliError("Omni CLI returned an empty NDJSON stream")
        return tuple(values)

    def _run_output(self, command: Sequence[str], *, stdin: str | None = None) -> str:
        arguments = (*self._base_arguments(), *command)
        environment = self._child_environment()
        try:
            returncode, stdout, stderr = self._runner(
                arguments,
                environment,
                stdin,
                self._settings.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise OmniCliError("Omni CLI request timed out") from error
        except OSError as error:
            raise OmniCliError("Omni CLI request could not start") from error
        if returncode != 0:
            detail = self._content_policy.safe_detail(stderr.strip() or stdout.strip())
            raise OmniCliError(f"Omni CLI request failed: {detail}")
        if len(stdout.encode()) > MAX_RESPONSE_BYTES:
            raise OmniCliError("Omni CLI response exceeds the capture limit")
        return stdout

    def _base_arguments(self) -> tuple[str, ...]:
        arguments = (
            self._settings.binary,
            "--compact",
            "--base-url",
            self._settings.base_url,
        )
        if self._settings.profile is not None:
            return (*arguments, "--profile", self._settings.profile)
        return arguments

    def _child_environment(self) -> dict[str, str]:
        permitted = set(COMMON_CHILD_ENVIRONMENT_KEYS)
        if self._settings.authentication_mode == "profile":
            permitted.update(PROFILE_CHILD_ENVIRONMENT_KEYS)
        else:
            permitted.add("OMNI_API_TOKEN")
        return {
            key: value
            for key, value in self._environment.items()
            if key in permitted and value
        }


def _subprocess_runner(
    arguments: Sequence[str],
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


def _required_environment(environment: Mapping[str, str], name: str) -> str:
    value = _optional_environment(environment, name)
    if value is None:
        raise OmniCliError(f"{name} must be set")
    return value


def _optional_environment(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OmniCliError(f"{name} must be a non-empty string")
    return value


def _required_job_id(value: object) -> str:
    if not isinstance(value, str) or JOB_ID_PATTERN.fullmatch(value) is None:
        raise OmniCliError("job_id must be a bounded identifier")
    return value


def _query_with_model(query: Mapping[str, Any], model_id: str) -> dict[str, Any]:
    if not isinstance(query, Mapping) or not query:
        raise OmniCliError("query must be a non-empty object")
    supplied_model = query.get("modelId")
    if supplied_model is not None and supplied_model != model_id:
        raise OmniCliError("query modelId does not match the configured model")
    return {**query, "modelId": model_id}


def _one_planned_job(lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    jobs = [line for line in lines if "job_id" in line]
    footers = [line for line in lines if "remaining_job_ids" in line]
    if len(jobs) != 1 or len(footers) != 1:
        raise OmniCliError("Omni query plan stream has an invalid shape")
    footer = footers[0]
    if footer.get("remaining_job_ids") != [] or footer.get("timed_out") != "false":
        raise OmniCliError("Omni query plan did not finish synchronously")
    job = jobs[0]
    if job.get("status") != "PLANNED":
        raise OmniCliError("Omni query plan did not reach PLANNED")
    return dict(job)
