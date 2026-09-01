"""Post-receipt production executor for one scheduled R2 attempt at a time."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path

from .omni_cli import (
    COMMON_CHILD_ENVIRONMENT_KEYS,
    PROFILE_CHILD_ENVIRONMENT_KEYS,
    OmniCliError,
    OmniCliSettings,
)
from .omni_probe_preflight import CliVersionObserver
from .r2_attempt_cli import ClientFactory, execute_r2_attempt
from .r2_dispatch import (
    R2DeploymentTarget,
    R2DispatchPolicy,
)
from .r2_execution import R2AttemptArtifacts, R2ExecutionPlan, R2PlannedAttempt
from .r2_runtime_adapter import (
    R2RuntimeAdapterError,
    prepare_r2_attempt_adapter,
)


_CONFIG_PATH = Path("config/autoresearch.json")
_ALLOWED_ENVIRONMENT_KEYS = frozenset(
    {
        *COMMON_CHILD_ENVIRONMENT_KEYS,
        *PROFILE_CHILD_ENVIRONMENT_KEYS,
        "OMNI_API_TOKEN",
        "OMNI_BASE_URL",
        "OMNI_PROFILE",
    }
)

AttemptRunner = Callable[..., tuple[R2AttemptArtifacts, object]]


class R2LiveExecutorError(RuntimeError):
    """Raised before the receipt-gated leaf can target an unverified deployment."""


def prepare_r2_live_environment(environment: Mapping[str, str]) -> dict[str, str]:
    """Validate and minimize the inherited provider environment before consumption."""
    if not isinstance(environment, Mapping):
        raise R2LiveExecutorError("R2 executor environment is invalid")
    selected = {
        key: value
        for key, value in environment.items()
        if key in _ALLOWED_ENVIRONMENT_KEYS and isinstance(value, str) and value
    }
    profile = selected.get("OMNI_PROFILE")
    token = selected.get("OMNI_API_TOKEN")
    if bool(profile) == bool(token):
        raise R2LiveExecutorError(
            "R2 executor requires exactly one operator-owned Omni auth mode"
        )
    if not selected.get("OMNI_BASE_URL"):
        raise R2LiveExecutorError("R2 executor requires the Omni base URL")
    try:
        settings = OmniCliSettings.from_environment(
            {**selected, "OMNI_MODEL_ID": "r2-preflight"}
        )
    except OmniCliError as error:
        raise R2LiveExecutorError(
            "R2 executor provider environment is invalid"
        ) from error
    permitted = {
        *COMMON_CHILD_ENVIRONMENT_KEYS,
        "OMNI_BASE_URL",
        "OMNI_PROFILE"
        if settings.authentication_mode == "profile"
        else "OMNI_API_TOKEN",
    }
    if settings.authentication_mode == "profile":
        permitted.update(PROFILE_CHILD_ENVIRONMENT_KEYS)
    return {key: value for key, value in selected.items() if key in permitted}


class R2LiveExecutor:
    """Create fresh production-agent sessions in the frozen sequential order."""

    def __init__(
        self,
        *,
        workspace: Path,
        plan: R2ExecutionPlan,
        policy: R2DispatchPolicy,
        environment: Mapping[str, str],
        client_factory: ClientFactory | None = None,
        sleep: Callable[[float], None] | None = None,
        cli_version_observer: CliVersionObserver | None = None,
        attempt_runner: AttemptRunner = execute_r2_attempt,
    ) -> None:
        if not isinstance(plan, R2ExecutionPlan):
            raise R2LiveExecutorError("R2 executor requires an execution plan")
        if not isinstance(policy, R2DispatchPolicy):
            raise R2LiveExecutorError("R2 executor policy is invalid")
        if not callable(attempt_runner):
            raise R2LiveExecutorError("R2 attempt runner is invalid")
        self._workspace = Path(workspace)
        self._plan = plan
        self._policy = policy
        self._environment = prepare_r2_live_environment(environment)
        self._client_factory = client_factory
        self._sleep = sleep
        self._cli_version_observer = cli_version_observer
        self._attempt_runner = attempt_runner

    def execute(
        self, attempt: R2PlannedAttempt, target: R2DeploymentTarget
    ) -> R2AttemptArtifacts:
        """Run exactly one plan member against its verified generated product IDs."""
        try:
            selected = self._plan.attempt(attempt.attempt_id)
        except Exception as error:
            raise R2LiveExecutorError("R2 executor attempt is not scheduled") from error
        if selected != attempt:
            raise R2LiveExecutorError("R2 executor attempt was substituted")
        try:
            prepared = prepare_r2_attempt_adapter(
                self._plan,
                attempt_id=attempt.attempt_id,
                deployment_target=target,
            )
        except R2RuntimeAdapterError as error:
            raise R2LiveExecutorError(
                "R2 executor deployment does not match the plan"
            ) from error
        environment = {
            **self._environment,
            "OMNI_BRANCH_ID": prepared.branch_id,
            "OMNI_MODEL_ID": prepared.model_id,
        }
        arguments = argparse.Namespace(
            workspace=self._workspace,
            config=_CONFIG_PATH,
            freeze_a_commit=self._policy.freeze_a_commit,
            system_commit=self._plan.system_commit,
            instance_id=attempt.instance_id,
            output_root=attempt.output_root,
            run_id=attempt.run_id,
            repetition=attempt.repetition,
            harness_config=Path("config/conditions/c4-production-v1.json"),
            prompt_spec=Path("config/prompts/c4-user-prompt-v1.txt"),
            instructions_spec=Path(
                "config/instructions/c4-managed-instructions-v1.json"
            ),
            budget_id=self._policy.budget_id,
            execute_authenticated_smoke=True,
        )
        try:
            result = self._attempt_runner(
                plan=self._plan,
                attempt_id=attempt.attempt_id,
                deployment_target=target,
                probe_arguments=arguments,
                environment=environment,
                client_factory=self._client_factory,
                sleep=self._sleep,
                cli_version_observer=self._cli_version_observer,
            )
        except R2LiveExecutorError:
            raise
        except Exception as error:
            raise R2LiveExecutorError(
                f"R2 attempt leaf failed: {attempt.attempt_id}"
            ) from error
        if (
            not isinstance(result, tuple)
            or len(result) != 2
            or not isinstance(result[0], R2AttemptArtifacts)
        ):
            raise R2LiveExecutorError("R2 attempt leaf returned an invalid result")
        return result[0]
