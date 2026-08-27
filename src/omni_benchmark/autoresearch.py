"""Public API for the train-only autoresearch control plane."""

from .autoresearch_cli import main
from .autoresearch_config import (
    AutoresearchConfig,
    AutoresearchError,
    create_public_dev_a_view,
    load_config,
)
from .autoresearch_ledger import (
    add_regression_case,
    create_baseline,
    create_checkpoint,
    decide_experiment,
    guard_intervention_text,
    propose_experiment,
    read_pareto_frontier,
    stop_optimization,
)
from .autoresearch_runs import (
    ValidatedRun,
    validate_generation_outputs,
    validate_run,
    validate_scored_generation,
)
from .autoresearch_smoke import validate_telemetry_smoke

__all__ = [
    "AutoresearchConfig",
    "AutoresearchError",
    "ValidatedRun",
    "add_regression_case",
    "create_baseline",
    "create_checkpoint",
    "create_public_dev_a_view",
    "decide_experiment",
    "guard_intervention_text",
    "load_config",
    "main",
    "propose_experiment",
    "read_pareto_frontier",
    "stop_optimization",
    "validate_run",
    "validate_scored_generation",
    "validate_generation_outputs",
    "validate_telemetry_smoke",
]
