"""Dry-default command boundary for one exact sealed generation dispatch."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .freeze_b_control import load_freeze_b_control
from .sealed_dispatch import (
    AdapterFactory,
    SealedDispatchError,
    SealedDispatchPreflight,
    execute_sealed_dispatch,
    load_sealed_dispatch_policy,
    preflight_sealed_dispatch,
)
from .sealed_execution_plan import (
    load_sealed_execution_plan,
    load_sealed_public_questions,
)
from .sealed_production_factory import (
    SealedProductionAdapterConfig,
    SealedProductionFactoryError,
    build_sealed_production_adapter_factories,
)

AdapterFactoriesBuilder = Callable[
    [SealedDispatchPreflight], Mapping[str, AdapterFactory]
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--control-commit", required=True)
    parser.add_argument("--system-commit", required=True)
    parser.add_argument("--freeze-b", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--public-manifest", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--input-spec", type=Path)
    parser.add_argument("--omni-deployment-gate", type=Path)
    parser.add_argument("--claude-config-dir", type=Path, action="append")
    parser.add_argument("--database-environments", type=Path)
    parser.add_argument("--runtime-parent", type=Path)
    parser.add_argument("--execute-sealed-generation", action="store_true")
    return parser


def dispatch_main(
    argv: Sequence[str] | None = None,
    *,
    adapter_factories_builder: AdapterFactoriesBuilder | None = None,
) -> int:
    """Validate by default; cross the live boundary only with explicit execute."""
    arguments = _parser().parse_args(argv)
    control = load_freeze_b_control(
        arguments.workspace,
        control_commit=arguments.control_commit,
        system_commit=arguments.system_commit,
        manifest_path=arguments.freeze_b,
    )
    freeze_b = control.manifest
    plan = load_sealed_execution_plan(
        arguments.workspace,
        control_commit=arguments.control_commit,
        system_commit=arguments.system_commit,
        freeze_b_path=arguments.freeze_b,
        schedule_path=arguments.schedule,
        public_manifest_path=arguments.public_manifest,
    )
    questions = load_sealed_public_questions(
        arguments.workspace,
        plan=plan,
        freeze_b=freeze_b,
        public_manifest_path=arguments.public_manifest,
    )
    policy = load_sealed_dispatch_policy(
        arguments.workspace,
        system_commit=arguments.system_commit,
        policy_path=arguments.policy,
        freeze_b=freeze_b,
    )
    preflight = preflight_sealed_dispatch(
        workspace=arguments.workspace,
        output_root=arguments.output_root,
        run_id=arguments.run_id,
        plan=plan,
        freeze_b=freeze_b,
        questions=questions,
        policy=policy,
        receipt_path=arguments.receipt,
    )
    if not arguments.execute_sealed_generation:
        print(json.dumps(preflight.public_summary(), sort_keys=True))
        return 0
    if adapter_factories_builder is None:
        try:
            production_config = _production_config(arguments)
        except SealedProductionFactoryError as error:
            raise SealedDispatchError(
                "sealed production adapters are unavailable"
            ) from error

        def adapter_factories_builder(value: SealedDispatchPreflight):
            return build_sealed_production_adapter_factories(production_config, value)

    report = execute_sealed_dispatch(
        preflight,
        adapter_factories_builder=adapter_factories_builder,
    )
    print(json.dumps(report.public_summary(), sort_keys=True))
    return 0


def _production_config(arguments: argparse.Namespace) -> SealedProductionAdapterConfig:
    profiles = arguments.claude_config_dir
    if (
        arguments.input_spec is None
        or arguments.omni_deployment_gate is None
        or profiles is None
        or len(profiles) != 3
        or arguments.database_environments is None
        or arguments.runtime_parent is None
    ):
        raise SealedProductionFactoryError(
            "sealed production resource arguments are incomplete"
        )
    return SealedProductionAdapterConfig.create(
        input_spec_path=arguments.input_spec,
        omni_deployment_gate_path=arguments.omni_deployment_gate,
        claude_config_directories=tuple(profiles),  # type: ignore[arg-type]
        database_environment_root=arguments.database_environments,
        runtime_parent=arguments.runtime_parent,
    )
