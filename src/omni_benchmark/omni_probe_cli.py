"""Credential-safe CLI for one public dev-A production-agent contract probe."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError, StoredArtifact
from .autoresearch_config import AutoresearchConfig, AutoresearchError, load_config
from .content_policy import ContentPolicy
from .omni_attempt import C4AttemptArtifacts, C4AttemptSpec, write_c4_attempt
from .omni_capture import OmniJobCapture, OmniJobClient, OmniProbeResult
from .omni_cli import OmniCliClient, OmniCliError, OmniCliSettings
from .omni_credit_cost import capture_with_cost
from .omni_probe_preflight import (
    C4ProbeSpecs,
    CliVersionObserver,
    OmniProbePreflightError,
    load_c4_probe_specs,
    observe_omni_cli_version,
    pin_omni_cli_binary,
    render_public_question,
    semantic_model_ref,
    verify_system_commit,
)
from .run_manifest import RunManifest, RunManifestError, SCHEMA_VERSION

OmniProbeCliError = OmniProbePreflightError
ClientFactory = Callable[[OmniCliSettings], OmniJobClient]
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]{0,79}")


@dataclass(frozen=True)
class ProbePlan:
    """All validated local inputs required to cross the authenticated boundary."""

    arguments: argparse.Namespace
    workspace: Path
    environment: dict[str, str]
    settings: OmniCliSettings
    specs: C4ProbeSpecs
    question: str
    semantic_model_ref: str
    software_versions: dict[str, str]
    cli_versions: dict[str, str]
    store: ArtifactStore


@dataclass(frozen=True)
class LocalProbeInputs:
    """Validated public and committed inputs available before authentication."""

    workspace: Path
    settings: OmniCliSettings
    specs: C4ProbeSpecs
    question: str
    semantic_model_ref: str
    software_versions: dict[str, str]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--freeze-a-commit", required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--harness-config", type=Path, required=True)
    parser.add_argument("--prompt-spec", type=Path, required=True)
    parser.add_argument("--instructions-spec", type=Path, required=True)
    parser.add_argument("--budget-id", required=True)
    parser.add_argument("--execute-authenticated-smoke", action="store_true")
    return parser


def probe_main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    sleep: Callable[[float], None] | None = None,
    cli_version_observer: CliVersionObserver | None = None,
) -> int:
    """Run one explicitly acknowledged probe and emit a non-secret receipt."""
    arguments = _parser().parse_args(argv)
    process_environment = dict(os.environ if environment is None else environment)
    plan = _prepare_probe(
        arguments,
        process_environment,
        observe_omni_cli_version
        if cli_version_observer is None
        else cli_version_observer,
    )
    artifacts, result = _execute_probe(
        plan,
        client_factory=client_factory,
        sleep=sleep,
    )
    receipt = _receipt(plan, artifacts, result)
    print(json.dumps(receipt, separators=(",", ":"), sort_keys=True))
    return 0


def _prepare_probe(
    arguments: argparse.Namespace,
    process_environment: dict[str, str],
    version_observer: CliVersionObserver,
) -> ProbePlan:
    if not arguments.execute_authenticated_smoke:
        raise OmniProbeCliError("authenticated smoke requires explicit acknowledgement")
    inputs = _load_local_probe_inputs(arguments, process_environment)
    _prevalidate_local_run(
        arguments,
        process_environment,
        inputs.specs,
        inputs.question,
        inputs.semantic_model_ref,
        inputs.software_versions,
    )
    settings, binary_sha256 = pin_omni_cli_binary(
        inputs.settings,
        process_environment,
        inputs.specs.condition.omni_cli_sha256,
    )
    store = _new_store(inputs.workspace, arguments.output_root, process_environment)
    version = version_observer(settings, process_environment)
    if version != inputs.specs.condition.omni_cli_version:
        raise OmniProbeCliError("Omni CLI version does not match the committed pin")
    cli_versions = {"omni": version, "omni.sha256": binary_sha256}
    _prevalidate_run_metadata(
        arguments=arguments,
        environment=process_environment,
        specs=inputs.specs,
        semantic_model_ref_value=inputs.semantic_model_ref,
        software_versions=inputs.software_versions,
        cli_versions=cli_versions,
    )
    return ProbePlan(
        arguments=arguments,
        workspace=inputs.workspace,
        environment=process_environment,
        settings=settings,
        specs=inputs.specs,
        question=inputs.question,
        semantic_model_ref=inputs.semantic_model_ref,
        software_versions=inputs.software_versions,
        cli_versions=cli_versions,
        store=store,
    )


def _load_local_probe_inputs(
    arguments: argparse.Namespace, environment: Mapping[str, str]
) -> LocalProbeInputs:
    workspace = arguments.workspace.resolve(strict=True)
    if not (workspace / ".git").exists():
        raise OmniProbeCliError("authenticated smoke requires a committed Freeze-A")
    config = _load_protocol_config(arguments, workspace)
    verify_system_commit(workspace, arguments.system_commit)
    specs = load_c4_probe_specs(
        workspace,
        arguments.system_commit,
        condition_path=arguments.harness_config,
        prompt_path=arguments.prompt_spec,
        instructions_path=arguments.instructions_spec,
    )
    public_question = _load_public_dev_a_question(config, arguments.instance_id)
    settings = _load_settings(environment)
    return LocalProbeInputs(
        workspace=workspace,
        settings=settings,
        specs=specs,
        question=render_public_question(specs.prompt, public_question),
        semantic_model_ref=semantic_model_ref(settings),
        software_versions=_software_versions(),
    )


def _prevalidate_local_run(
    arguments: argparse.Namespace,
    environment: Mapping[str, str],
    specs: C4ProbeSpecs,
    question: str,
    model_ref: str,
    software_versions: Mapping[str, str],
) -> None:
    _prevalidate_attempt_identity(arguments, environment)
    if not ContentPolicy.from_environment(environment).query_is_safe(question):
        raise OmniProbeCliError("public question contains credential material")
    _prevalidate_run_metadata(
        arguments=arguments,
        environment=environment,
        specs=specs,
        semantic_model_ref_value=model_ref,
        software_versions=software_versions,
        cli_versions={"omni": "preflight", "omni.sha256": "0" * 64},
    )


def _execute_probe(
    plan: ProbePlan,
    *,
    client_factory: ClientFactory | None,
    sleep: Callable[[float], None] | None,
) -> tuple[C4AttemptArtifacts, OmniProbeResult]:
    factory = client_factory or (
        lambda value: OmniCliClient(value, environment=plan.environment)
    )
    client = factory(plan.settings)
    _verify_authentication(client)
    capture_options: dict[str, Any] = {
        "maximum_status_checks": plan.specs.condition.maximum_status_checks,
        "poll_schedule_seconds": plan.specs.condition.poll_schedule_seconds,
    }
    if sleep is not None:
        capture_options["sleep"] = sleep
    result = capture_with_cost(
        client=client,
        environment=plan.environment,
        capture=lambda: OmniJobCapture(client, plan.store, **capture_options).probe(
            plan.question
        ),
    )
    return _write_attempt(plan, result), result


def _write_attempt(plan: ProbePlan, result: OmniProbeResult) -> C4AttemptArtifacts:
    arguments = plan.arguments
    condition = plan.specs.condition
    return write_c4_attempt(
        workspace=plan.workspace,
        store=plan.store,
        spec=C4AttemptSpec(
            instance_id=arguments.instance_id,
            question=plan.question,
            run_id=arguments.run_id,
            repetition=arguments.repetition,
            provider=condition.provider,
            model=condition.managed_llm_identity,
            model_version=None,
            git_commit=arguments.system_commit,
            harness_config_sha256=plan.specs.condition_sha256,
            prompt_sha256=plan.specs.prompt_sha256,
            instructions_sha256=plan.specs.instructions_sha256,
            semantic_model_ref=plan.semantic_model_ref,
            semantic_model_sha256=None,
            model_config_id=condition.model_config_id,
            budget_id=arguments.budget_id,
            software_versions=plan.software_versions,
            cli_versions=plan.cli_versions,
        ),
        probe=result,
    )


def _receipt(
    plan: ProbePlan,
    artifacts: C4AttemptArtifacts,
    result: OmniProbeResult,
) -> dict[str, object]:
    arguments = plan.arguments
    return {
        "failure_class": result.failure_class,
        "instance_id": arguments.instance_id,
        "job_id_sha256": (
            hashlib.sha256(result.job_id.encode()).hexdigest()
            if result.job_id is not None
            else None
        ),
        "generation": _artifact_receipt(plan.workspace, artifacts.generation),
        "response_shape": _artifact_receipt(plan.workspace, result.response_shape),
        "run_manifest": _artifact_receipt(plan.workspace, artifacts.run_manifest),
        "terminal_state": result.terminal_state,
        "trace": _artifact_receipt(plan.workspace, result.trace),
    }


def _load_protocol_config(
    arguments: argparse.Namespace, workspace: Path
) -> AutoresearchConfig:
    try:
        return load_config(
            arguments.config,
            workspace=workspace,
            freeze_a_commit=arguments.freeze_a_commit,
        )
    except AutoresearchError as error:
        raise OmniProbeCliError(str(error)) from error


def _load_settings(environment: Mapping[str, str]) -> OmniCliSettings:
    try:
        return OmniCliSettings.from_environment(environment)
    except OmniCliError as error:
        raise OmniProbeCliError(str(error)) from error


def _new_store(
    workspace: Path, root: Path, environment: Mapping[str, str]
) -> ArtifactStore:
    try:
        return ArtifactStore(
            workspace,
            root,
            environment=environment,
            require_new_root=True,
        )
    except ArtifactStoreError as error:
        raise OmniProbeCliError(str(error)) from error


def _verify_authentication(client: OmniJobClient) -> None:
    whoami = getattr(client, "whoami", None)
    if not callable(whoami):
        raise OmniProbeCliError(
            "Omni client does not expose authentication verification"
        )
    response = whoami()
    if not isinstance(response, dict) or not response:
        raise OmniProbeCliError("Omni authentication verification returned no identity")


def _load_public_dev_a_question(config: AutoresearchConfig, instance_id: str) -> str:
    if instance_id not in config.dev_a_id_set:
        raise OmniProbeCliError("contract probe instance must belong to dev-A")
    matches: list[str] = []
    for line in config.public_manifest_path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if not isinstance(record, dict) or record.get("instance_id") != instance_id:
            continue
        question = record.get("query")
        if not isinstance(question, str) or not question.strip():
            raise OmniProbeCliError("public manifest question is invalid")
        matches.append(question)
    if len(matches) != 1:
        raise OmniProbeCliError("public dev-A question must resolve exactly once")
    return matches[0]


def _artifact_receipt(workspace: Path, artifact: StoredArtifact) -> dict[str, object]:
    return {
        "path": artifact.path.relative_to(workspace).as_posix(),
        "sha256": artifact.sha256,
        "size_bytes": artifact.size_bytes,
    }


def _software_versions() -> dict[str, str]:
    return {
        "omni-benchmark": importlib.metadata.version("omni-benchmark"),
        "python": platform.python_version(),
    }


def _prevalidate_run_metadata(
    *,
    arguments: argparse.Namespace,
    environment: Mapping[str, str],
    specs: C4ProbeSpecs,
    semantic_model_ref_value: str,
    software_versions: Mapping[str, str],
    cli_versions: Mapping[str, str],
) -> None:
    condition = specs.condition
    value = {
        "budget_id": arguments.budget_id,
        "cli_versions": dict(cli_versions),
        "condition": "C4",
        "controllable_seed": None,
        "finished_at": "2000-01-01T00:00:00Z",
        "generation_sha256": "0" * 64,
        "git_commit": arguments.system_commit,
        "harness_config_sha256": specs.condition_sha256,
        "instructions_sha256": specs.instructions_sha256,
        "model": condition.managed_llm_identity,
        "model_config_id": condition.model_config_id,
        "prompt_sha256": specs.prompt_sha256,
        "provider": condition.provider,
        "repetition": arguments.repetition,
        "schema_version": SCHEMA_VERSION,
        "scope": "dev-a",
        "semantic_model_ref": semantic_model_ref_value,
        "semantic_model_sha256": None,
        "software_versions": dict(software_versions),
        "started_at": "2000-01-01T00:00:00Z",
    }
    try:
        RunManifest.from_dict(value, environment=environment)
    except RunManifestError as error:
        raise OmniProbeCliError(f"invalid run metadata: {error}") from error


def _prevalidate_attempt_identity(
    arguments: argparse.Namespace, environment: Mapping[str, str]
) -> None:
    run_id = arguments.run_id
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise OmniProbeCliError("invalid run identity")
    attempt_id = f"{run_id}:{arguments.instance_id}:C4:{arguments.repetition}"
    value = {"attempt_id": attempt_id, "run_id": run_id}
    if ContentPolicy.from_environment(environment).sanitize_json(value) != value:
        raise OmniProbeCliError("invalid run identity")
