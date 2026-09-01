"""Narrow full-development adapter over the committed single-attempt probes."""

from __future__ import annotations

import importlib.metadata
import json
import math
import os
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from . import direct_prepared_attempt as direct_prepared, omni_attempt
from .artifact_store import ArtifactStore
from .claude_direct_transport import (
    PINNED_CLAUDE_BINARY_SHA256,
    PINNED_CLAUDE_VERSION,
)
from .direct_attempt_binding import DirectAttemptSpec
from .direct_prepared_attempt import DirectPreparedAttemptError
from .direct_question_loader import load_committed_direct_question
from .direct_probe_cli import (
    DirectProbeCliError,
    DirectProbePlan,
    _attempt_receipt,
    _semantic_identity,
    direct_probe_main,
)
from .direct_sql_attempt import write_direct_attempt
from .direct_sql_capture import DirectCaptureError, DirectSqlCapture
from .e02_candidate import (
    E02CandidateError,
    load_committed_c5_plan,
    load_committed_e02_candidate,
)
from .omni_attempt import C4AttemptArtifacts, C4AttemptSpec
from .omni_capture import OmniJobCapture, OmniJobClient, OmniProbeResult
from .omni_cli import OmniCliClient
from .omni_credit_cost import COST_UNAVAILABLE_JOB_API, capture_with_cost
from .omni_probe_cli import ProbePlan
from . import omni_probe_cli as omni_probe
from .omni_probe_preflight import (
    CliVersionObserver,
    load_c4_probe_specs,
    observe_omni_cli_version,
    pin_omni_cli_binary,
    render_public_question,
    semantic_model_ref,
    verify_system_commit,
)
from .omni_result_adapter import reject_forbidden_keys
from .omni_semantic_deploy_cli import OmniDeploymentCliError, committed_bundle_plan
from .omni_semantic_deployment import (
    OmniSemanticDeploymentError,
    verified_semantic_deployment_sha256,
)
from .run_manifest import RunManifest

ClientFactory = Callable[[Any], OmniJobClient]


def baseline_direct_probe_main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
) -> int:
    """Use the existing CLI boundary with the precommitted full-train authority."""
    return direct_probe_main(
        argv,
        environment=environment,
        attempt_runner=run_public_baseline_direct_attempt,
    )


def prepare_public_baseline_direct_attempt(plan: DirectProbePlan) -> object:
    """Mint the same opaque direct authority for the public 231-question scope."""
    arguments = plan.arguments
    direct_prepared._verify_preparation_environment(
        plan.workspace, arguments.system_commit, plan.store
    )
    question, public_tools, database_identity = direct_prepared._load_attempt_inputs(
        plan.workspace,
        arguments.system_commit,
        "train",
        arguments.instance_id,
        arguments.condition,
        plan.environment,
    )
    direct_prepared._require_database_alignment(
        question, public_tools, database_identity
    )
    model_transport, database = direct_prepared._construct_transports(
        plan.claude_config, plan.database_environment, database_identity
    )
    binding = direct_prepared._build_runtime_binding(
        arguments.system_commit,
        arguments.run_id,
        arguments.repetition,
        arguments.condition,
        question,
        public_tools,
        database_identity,
        model_transport,
        plan.environment,
    )
    return direct_prepared._mint_prepared_attempt(
        binding, model_transport, database, public_tools, plan.store
    )


def run_public_baseline_direct_attempt(
    plan: DirectProbePlan,
) -> Mapping[str, object]:
    """Capture and publish one public train attempt through existing components."""
    try:
        prepared = prepare_public_baseline_direct_attempt(plan)
        probe = DirectSqlCapture(prepared=prepared).capture()
        semantic_ref, semantic_sha = _semantic_identity(prepared.binding)
        artifacts = write_direct_attempt(
            workspace=plan.workspace,
            store=plan.store,
            spec=DirectAttemptSpec(
                binding=prepared.binding,
                controllable_seed=None,
                semantic_model_ref=semantic_ref,
                semantic_model_sha256=semantic_sha,
                software_versions={
                    "omni-benchmark": importlib.metadata.version("omni-benchmark")
                },
                cli_versions={
                    "claude": PINNED_CLAUDE_VERSION,
                    "claude.sha256": PINNED_CLAUDE_BINARY_SHA256,
                },
            ),
            probe=probe,
        )
    except (DirectPreparedAttemptError, DirectCaptureError, ValueError) as error:
        raise DirectProbeCliError(str(error)) from error
    return _attempt_receipt(
        plan, probe.generation_outcome, probe.failure_class, artifacts
    )


def baseline_omni_probe_main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    sleep: Callable[[float], None] | None = None,
    cli_version_observer: CliVersionObserver | None = None,
) -> int:
    """Run one full-development C4 attempt through the production probe path."""
    arguments = omni_probe._parser().parse_args(argv)
    if not arguments.execute_authenticated_smoke:
        raise omni_probe.OmniProbeCliError(
            "authenticated smoke requires explicit acknowledgement"
        )
    process_environment = dict(os.environ if environment is None else environment)
    plan = _prepare_public_baseline_omni_plan(
        arguments,
        process_environment,
        observe_omni_cli_version
        if cli_version_observer is None
        else cli_version_observer,
    )
    result = _capture_public_baseline_omni(
        plan, client_factory=client_factory, sleep=sleep
    )
    spec = _c4_attempt_spec(plan)
    artifacts = write_public_baseline_c4_attempt(
        workspace=plan.workspace,
        store=plan.store,
        spec=spec,
        probe=result,
    )
    print(
        json.dumps(
            omni_probe._receipt(plan, artifacts, result),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


def load_public_baseline_question(
    workspace: Path | str,
    commit: str,
    instance_id: str,
    environment: Mapping[str, str],
) -> str:
    """Load public text from the exact committed 231-question development scope."""
    identity = load_committed_direct_question(
        Path(workspace),
        commit,
        scope="train",
        instance_id=instance_id,
        environment=environment,
    )
    return identity.question


def write_public_baseline_c4_attempt(
    *,
    workspace: Path | str,
    store: ArtifactStore | Any,
    spec: C4AttemptSpec | Any,
    probe: OmniProbeResult | Any,
) -> C4AttemptArtifacts:
    """Publish existing C4 telemetry with the preregistered train scope."""
    record = {
        **omni_attempt._attempt_record(
            workspace=Path(workspace), spec=spec, probe=probe
        ),
        "partition": "train",
    }
    reject_forbidden_keys(record)
    generation = store.write_jsonl(Path("generation.jsonl"), [record])
    manifest_value = {
        **omni_attempt._run_manifest(spec, probe, generation.sha256).as_dict(),
        "generation_sha256": generation.sha256,
        "scope": "train",
    }
    manifest = RunManifest.from_dict(manifest_value)
    run_manifest = store.write_json(Path("run.json"), manifest.as_dict())
    return C4AttemptArtifacts(generation=generation, run_manifest=run_manifest)


def _prepare_public_baseline_omni_plan(
    arguments: Any,
    environment: dict[str, str],
    version_observer: CliVersionObserver,
) -> ProbePlan:
    workspace = arguments.workspace.resolve(strict=True)
    omni_probe._load_protocol_config(arguments, workspace)
    verify_system_commit(workspace, arguments.system_commit)
    specs = load_c4_probe_specs(
        workspace,
        arguments.system_commit,
        condition_path=arguments.harness_config,
        prompt_path=arguments.prompt_spec,
        instructions_path=arguments.instructions_spec,
    )
    question = render_public_question(
        specs.prompt,
        load_public_baseline_question(
            workspace,
            arguments.system_commit,
            arguments.instance_id,
            environment,
        ),
    )
    settings = omni_probe._load_settings(environment)
    software_versions = omni_probe._software_versions()
    model_ref = semantic_model_ref(settings)
    omni_probe._prevalidate_attempt_identity(arguments, environment)
    settings, binary_sha256 = pin_omni_cli_binary(
        settings, environment, specs.condition.omni_cli_sha256
    )
    store = omni_probe._new_store(workspace, arguments.output_root, environment)
    version = version_observer(settings, environment)
    if version != specs.condition.omni_cli_version:
        raise omni_probe.OmniProbeCliError(
            "Omni CLI version does not match the committed pin"
        )
    plan = ProbePlan(
        arguments=arguments,
        workspace=workspace,
        environment=environment,
        settings=settings,
        specs=specs,
        question=question,
        semantic_model_ref=model_ref,
        software_versions=software_versions,
        cli_versions={"omni": version, "omni.sha256": binary_sha256},
        store=store,
    )
    _prevalidate_train_manifest(_c4_attempt_spec(plan), environment)
    return plan


def _capture_public_baseline_omni(
    plan: ProbePlan,
    *,
    client_factory: ClientFactory | None,
    sleep: Callable[[float], None] | None,
) -> OmniProbeResult:
    factory = client_factory or (
        lambda settings: OmniCliClient(settings, environment=plan.environment)
    )
    client = factory(plan.settings)
    omni_probe._verify_authentication(client)
    expected_semantic_sha256 = _required_sha256_environment(
        plan.environment, "OMNI_SEMANTIC_MODEL_SHA256"
    )
    database = _required_environment(plan.environment, "OMNI_SEMANTIC_DATABASE")
    candidate_kind = plan.environment.get("OMNI_SEMANTIC_CANDIDATE_KIND", "baseline")
    try:
        semantic_plan = _committed_semantic_plan(
            plan.workspace,
            plan.arguments.system_commit,
            database,
            candidate_kind,
        )
        observed_semantic_sha256 = verified_semantic_deployment_sha256(
            semantic_plan,
            _semantic_readback_documents(client.read_semantic_model(), candidate_kind),
        )
    except (
        E02CandidateError,
        KeyError,
        OmniDeploymentCliError,
        OmniSemanticDeploymentError,
        ValueError,
    ) as error:
        raise omni_probe.OmniProbeCliError(
            "C4 semantic model drifted after verified deployment"
        ) from error
    if observed_semantic_sha256 != expected_semantic_sha256:
        raise omni_probe.OmniProbeCliError(
            "C4 semantic model drifted after verified deployment"
        )
    options: dict[str, Any] = {
        "maximum_status_checks": plan.specs.condition.maximum_status_checks,
        "poll_schedule_seconds": plan.specs.condition.poll_schedule_seconds,
    }
    if sleep is not None:
        options["sleep"] = sleep
    return capture_with_cost(
        client=client,
        environment=plan.environment,
        capture=lambda: OmniJobCapture(client, plan.store, **options).probe(
            plan.question
        ),
    )


def _committed_semantic_plan(
    workspace: Path,
    system_commit: str,
    database: str,
    candidate_kind: object,
) -> object:
    if candidate_kind == "baseline":
        return committed_bundle_plan(workspace, system_commit, database)
    if candidate_kind == "e02":
        return load_committed_e02_candidate(workspace, system_commit).plans[database]
    if candidate_kind == "c5":
        return load_committed_c5_plan(workspace, system_commit, database)
    raise ValueError("semantic candidate kind is invalid")


def _semantic_readback_documents(
    readback: Mapping[str, str | bytes], candidate_kind: object
) -> dict[str, str | bytes]:
    if candidate_kind not in {"baseline", "e02", "c5"}:
        raise ValueError("semantic candidate kind is invalid")
    # C5 deploys its own model-level ai_context, so that document is part of the
    # attested plan rather than an artifact Omni added on its own.
    excluded = set() if candidate_kind == "c5" else {"model"}
    if candidate_kind == "baseline":
        excluded.add("relationships")
    return {path: content for path, content in readback.items() if path not in excluded}


def _c4_attempt_spec(plan: ProbePlan) -> C4AttemptSpec:
    arguments = plan.arguments
    condition = plan.specs.condition
    return C4AttemptSpec(
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
        semantic_model_sha256=_required_sha256_environment(
            plan.environment, "OMNI_SEMANTIC_MODEL_SHA256"
        ),
        model_config_id=condition.model_config_id,
        budget_id=arguments.budget_id,
        software_versions=plan.software_versions,
        cli_versions=plan.cli_versions,
        cost_reservation_usd=_required_nonnegative_environment_number(
            plan.environment, "OMNI_COST_RESERVATION_USD"
        ),
        budget_policy_sha256=_required_sha256_environment(
            plan.environment, "OMNI_BUDGET_POLICY_SHA256"
        ),
        cost_unavailable_reason=COST_UNAVAILABLE_JOB_API,
    )


def _required_sha256_environment(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise omni_probe.OmniProbeCliError(f"{name} must be a lowercase SHA-256")
    return value


def _required_environment(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name)
    if not isinstance(value, str) or not value:
        raise omni_probe.OmniProbeCliError(f"{name} is required")
    return value


def _required_nonnegative_environment_number(
    environment: Mapping[str, str], name: str
) -> float:
    value = environment.get(name)
    try:
        number = float(value) if isinstance(value, str) else math.nan
    except ValueError as error:
        raise omni_probe.OmniProbeCliError(
            f"{name} must be a non-negative finite number"
        ) from error
    if not math.isfinite(number) or number < 0:
        raise omni_probe.OmniProbeCliError(
            f"{name} must be a non-negative finite number"
        )
    return number


def _prevalidate_train_manifest(
    spec: C4AttemptSpec, environment: Mapping[str, str]
) -> None:
    RunManifest.from_dict(
        {
            **omni_attempt._run_manifest(
                spec,
                SimpleProbeTimes(),
                "0" * 64,
            ).as_dict(),
            "scope": "train",
        },
        environment=environment,
    )


class SimpleProbeTimes:
    """Minimal structural value used only for preflight manifest validation."""

    started_at = "2000-01-01T00:00:00Z"
    finished_at = "2000-01-01T00:00:01Z"
    model_name = None
    model_provider = None
