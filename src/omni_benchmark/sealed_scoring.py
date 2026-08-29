"""Sealed Query-task lifecycle joining PostgreSQL execution to frozen scorers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import InvalidOperation
from enum import Enum
from typing import Any, Literal, Protocol

from .postgres_execution import (
    PostgreSQLConnection,
    PostgreSQLExecutionError,
    QuerySequenceResult,
    execute_query_sequence,
)
from .scoring import (
    OFFICIAL_SOFT_EX_VERSION,
    SENSITIVITY_SCORER_VERSION,
    ScoringPolicyError,
    official_soft_ex_equal,
    rewrite_sql_official,
    sensitivity_equal,
)
from .sql_admission import query_sql_is_admissible

Outcome = Literal["correct", "wrong_answer", "refused_or_error"]
FailureOrigin = Literal["evaluated_system", "benchmark_infrastructure"]


class ScoringMode(str, Enum):
    """The two preregistered execution/scoring policies."""

    OFFICIAL = "official_soft_ex"
    SENSITIVITY = "sensitivity"


class FailureClass(str, Enum):
    """Closed taxonomy safe to transport into score artifacts."""

    NO_QUERY = "no_query"
    AGENT_REFUSAL = "agent_refusal"
    CANDIDATE_TIMEOUT = "candidate_timeout"
    CANDIDATE_EXECUTION_ERROR = "candidate_execution_error"
    CANDIDATE_DATABASE_UNAVAILABLE = "candidate_database_unavailable"
    CANDIDATE_DATABASE_CONNECT_FAILED = "candidate_database_connect_failed"
    CANDIDATE_DISALLOWED_STATEMENT = "candidate_disallowed_statement"
    CANDIDATE_NO_RESULT = "candidate_no_result"
    CANDIDATE_RESULT_OVERFLOW = "candidate_result_overflow"
    GOLD_QUERY_MISSING = "gold_query_missing"
    GOLD_TIMEOUT = "gold_timeout"
    GOLD_STATEMENT_ERROR = "gold_statement_error"
    GOLD_DATABASE_UNAVAILABLE = "gold_database_unavailable"
    GOLD_DATABASE_CONNECT_FAILED = "gold_database_connect_failed"
    GOLD_NO_RESULT = "gold_no_result"
    GOLD_RESULT_OVERFLOW = "gold_result_overflow"
    DATABASE_ACQUIRE_FAILED = "database_acquire_failed"
    PREPROCESS_CONNECT_FAILED = "preprocess_connect_failed"
    PREPROCESS_TIMEOUT = "preprocess_timeout"
    PREPROCESS_STATEMENT_ERROR = "preprocess_statement_error"
    PREPROCESS_DATABASE_UNAVAILABLE = "preprocess_database_unavailable"
    CLEANUP_CONNECT_FAILED = "cleanup_connect_failed"
    CLEANUP_TIMEOUT = "cleanup_timeout"
    CLEANUP_STATEMENT_ERROR = "cleanup_statement_error"
    CLEANUP_DATABASE_UNAVAILABLE = "cleanup_database_unavailable"
    DATABASE_CLOSE_FAILED = "database_close_failed"
    DATABASE_RESET_FAILED = "database_reset_failed"
    DATABASE_RELEASE_FAILED = "database_release_failed"
    SCORER_POLICY_ERROR = "scorer_policy_error"


_RERUN_ELIGIBLE_FAILURES = frozenset(
    {
        FailureClass.CANDIDATE_DATABASE_UNAVAILABLE,
        FailureClass.CANDIDATE_DATABASE_CONNECT_FAILED,
        FailureClass.GOLD_DATABASE_UNAVAILABLE,
        FailureClass.GOLD_DATABASE_CONNECT_FAILED,
        FailureClass.DATABASE_ACQUIRE_FAILED,
        FailureClass.PREPROCESS_CONNECT_FAILED,
        FailureClass.PREPROCESS_DATABASE_UNAVAILABLE,
        FailureClass.CLEANUP_CONNECT_FAILED,
        FailureClass.CLEANUP_DATABASE_UNAVAILABLE,
        FailureClass.DATABASE_CLOSE_FAILED,
        FailureClass.DATABASE_RESET_FAILED,
        FailureClass.DATABASE_RELEASE_FAILED,
    }
)


class IsolatedPostgreSQLDatabase(Protocol):
    """One disposable database copy leased for a single scorer."""

    def connect_scoring(self) -> PostgreSQLConnection: ...

    def connect_trusted(self) -> PostgreSQLConnection: ...

    def reset(self) -> None: ...

    def release(self) -> None: ...


class PostgreSQLIsolationProvider(Protocol):
    """Provider of per-question disposable database copies."""

    def acquire(self, database: str) -> IsolatedPostgreSQLDatabase: ...


@dataclass(frozen=True)
class SealedQueryCase:
    """One Query task; SQL fields are intentionally absent from repr."""

    database: str
    candidate_sql: str | Sequence[str] = field(repr=False)
    gold_sql: str | Sequence[str] = field(repr=False)
    preprocess_sql: str | Sequence[str] = field(default=(), repr=False)
    cleanup_sql: str | Sequence[str] = field(default=(), repr=False)
    conditions: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class SealedScoringResult:
    """Permitted scoring output; never carries SQL or result rows."""

    scorer_identity: str
    scorer_version: str
    outcome: Outcome | None
    failure_origin: FailureOrigin | None = None
    failure_class: FailureClass | None = None
    rerun_eligible: bool = False
    candidate_row_limit_exceeded: bool = False
    gold_row_limit_exceeded: bool = False

    def __post_init__(self) -> None:
        if self.failure_class is not None and not isinstance(
            self.failure_class, FailureClass
        ):
            raise ValueError("failure_class must be a FailureClass")

    def as_score_record(self, attempt_id: str) -> dict[str, str]:
        """Transport a scored attempt into the immutable score-artifact schema."""
        if self.outcome is None:
            raise ValueError("infrastructure failures cannot become score labels")
        record = {"attempt_id": attempt_id, "outcome": self.outcome}
        if self.outcome == "refused_or_error" and self.failure_class is not None:
            return record | {"failure_category": self.failure_class.value}
        return record


@dataclass(frozen=True)
class _ValidatedCase:
    database: str
    candidate_sql: tuple[str, ...] = field(repr=False)
    gold_sql: tuple[str, ...] = field(repr=False)
    preprocess_sql: tuple[str, ...] = field(repr=False)
    cleanup_sql: tuple[str, ...] = field(repr=False)
    conditions: Mapping[str, Any] = field(repr=False)


def score_query(
    case: SealedQueryCase,
    mode: ScoringMode,
    provider: PostgreSQLIsolationProvider,
) -> SealedScoringResult:
    """Score one case on a fresh isolate and always reset acquired state."""
    if not isinstance(mode, ScoringMode):
        raise ValueError("mode must be a ScoringMode")
    validated = _validate_case(case)
    if not validated.candidate_sql:
        return system_no_answer(mode, failure_class=FailureClass.NO_QUERY)
    if not query_sql_is_admissible(validated.candidate_sql):
        return system_no_answer(
            mode, failure_class=FailureClass.CANDIDATE_DISALLOWED_STATEMENT
        )
    if not validated.gold_sql:
        return _infrastructure(mode, FailureClass.GOLD_QUERY_MISSING)
    try:
        candidate_isolate = provider.acquire(validated.database)
    except Exception:
        return _infrastructure(mode, FailureClass.DATABASE_ACQUIRE_FAILED)
    try:
        gold_isolate = provider.acquire(validated.database)
    except Exception:
        finalization_failure = _reset_and_release(mode, candidate_isolate)
        return finalization_failure or _infrastructure(
            mode, FailureClass.DATABASE_ACQUIRE_FAILED
        )
    try:
        try:
            result = _evaluate_with_isolates(
                validated,
                mode,
                candidate_isolate,
                gold_isolate,
            )
        finally:
            cleanup_failure = _run_cleanup_pair(
                validated,
                mode,
                candidate_isolate,
                gold_isolate,
            )
    finally:
        finalization_failure = _finalize_pair(mode, candidate_isolate, gold_isolate)
    return finalization_failure or cleanup_failure or result


def score_query_both(
    case: SealedQueryCase,
    provider: PostgreSQLIsolationProvider,
) -> tuple[SealedScoringResult, SealedScoringResult]:
    """Run both frozen policies on independent database isolates."""
    return (
        score_query(case, ScoringMode.OFFICIAL, provider),
        score_query(case, ScoringMode.SENSITIVITY, provider),
    )


def system_no_answer(
    mode: ScoringMode, *, failure_class: FailureClass
) -> SealedScoringResult:
    """Create the system-owned terminal label for refusal or exhausted failure."""
    if not isinstance(failure_class, FailureClass):
        raise ValueError("failure_class must be a FailureClass")
    identity, version = _scorer(mode)
    return SealedScoringResult(
        scorer_identity=identity,
        scorer_version=version,
        outcome="refused_or_error",
        failure_origin="evaluated_system",
        failure_class=failure_class,
    )


def _evaluate_with_isolates(
    case: _ValidatedCase,
    mode: ScoringMode,
    candidate_isolate: IsolatedPostgreSQLDatabase,
    gold_isolate: IsolatedPostgreSQLDatabase,
) -> SealedScoringResult:
    for isolate in (candidate_isolate, gold_isolate):
        preprocess = _run_trusted_phase(
            case.preprocess_sql, mode, isolate, "preprocess"
        )
        if preprocess is not None:
            return preprocess
    candidate = _run_candidate(case, mode, candidate_isolate)
    if isinstance(candidate, SealedScoringResult):
        return candidate
    gold = _run_gold(case, mode, gold_isolate)
    if isinstance(gold, SealedScoringResult):
        return gold
    return _compare(mode, candidate, gold, case.conditions)


def _run_candidate(
    case: _ValidatedCase,
    mode: ScoringMode,
    isolate: IsolatedPostgreSQLDatabase,
) -> QuerySequenceResult | SealedScoringResult:
    try:
        connection = isolate.connect_scoring()
    except Exception:
        return _infrastructure(mode, FailureClass.CANDIDATE_DATABASE_CONNECT_FAILED)
    try:
        result = _execute_candidate(case, mode, connection)
    finally:
        close_failure = _close_connection(mode, connection)
    if close_failure is not None:
        return close_failure
    if isinstance(result, SealedScoringResult):
        return result
    if result.rows is None:
        return _system_failure(mode, FailureClass.CANDIDATE_NO_RESULT)
    if result.row_limit_exceeded and mode is ScoringMode.SENSITIVITY:
        return _system_failure(
            mode,
            FailureClass.CANDIDATE_RESULT_OVERFLOW,
            candidate_row_limit_exceeded=True,
        )
    return result


def _execute_candidate(
    case: _ValidatedCase,
    mode: ScoringMode,
    connection: PostgreSQLConnection,
) -> QuerySequenceResult | SealedScoringResult:
    if mode is ScoringMode.OFFICIAL:
        detection = _execute_phase(
            mode, connection, case.candidate_sql, "candidate", read_only=True
        )
        if isinstance(detection, SealedScoringResult):
            return detection
    candidate_sql, _ = _scoring_sql(case, mode)
    return _execute_phase(mode, connection, candidate_sql, "candidate", read_only=True)


def _run_gold(
    case: _ValidatedCase,
    mode: ScoringMode,
    isolate: IsolatedPostgreSQLDatabase,
) -> QuerySequenceResult | SealedScoringResult:
    try:
        connection = isolate.connect_scoring()
    except Exception:
        return _infrastructure(mode, FailureClass.GOLD_DATABASE_CONNECT_FAILED)
    try:
        _, gold_sql = _scoring_sql(case, mode)
        result = _execute_phase(mode, connection, gold_sql, "gold", read_only=True)
    finally:
        close_failure = _close_connection(mode, connection)
    if close_failure is not None:
        return close_failure
    if isinstance(result, SealedScoringResult):
        return result
    if result.rows is None:
        return _infrastructure(mode, FailureClass.GOLD_NO_RESULT)
    if result.row_limit_exceeded and mode is ScoringMode.SENSITIVITY:
        return _infrastructure(
            mode,
            FailureClass.GOLD_RESULT_OVERFLOW,
            gold_row_limit_exceeded=True,
        )
    return result


def _execute_phase(
    mode: ScoringMode,
    connection: PostgreSQLConnection,
    statements: tuple[str, ...],
    phase: Literal["preprocess", "candidate", "gold", "cleanup"],
    *,
    read_only: bool,
) -> QuerySequenceResult | SealedScoringResult:
    try:
        return execute_query_sequence(connection, statements, read_only=read_only)
    except PostgreSQLExecutionError as error:
        if phase == "candidate" and error.kind != "infrastructure":
            failure_class = (
                FailureClass.CANDIDATE_TIMEOUT
                if error.kind == "timeout"
                else FailureClass.CANDIDATE_EXECUTION_ERROR
            )
            return _system_failure(mode, failure_class)
        return _infrastructure(mode, _phase_failure(phase, error.kind))


def _run_trusted_phase(
    statements: tuple[str, ...],
    mode: ScoringMode,
    isolate: IsolatedPostgreSQLDatabase,
    phase: Literal["preprocess", "cleanup"],
) -> SealedScoringResult | None:
    if not statements:
        return None
    try:
        connection = isolate.connect_trusted()
    except Exception:
        failure_class = (
            FailureClass.PREPROCESS_CONNECT_FAILED
            if phase == "preprocess"
            else FailureClass.CLEANUP_CONNECT_FAILED
        )
        return _infrastructure(mode, failure_class)
    try:
        result = _execute_phase(mode, connection, statements, phase, read_only=False)
    finally:
        close_failure = _close_connection(mode, connection)
    if close_failure is not None:
        return close_failure
    return result if isinstance(result, SealedScoringResult) else None


def _run_cleanup_pair(
    case: _ValidatedCase,
    mode: ScoringMode,
    candidate_isolate: IsolatedPostgreSQLDatabase,
    gold_isolate: IsolatedPostgreSQLDatabase,
) -> SealedScoringResult | None:
    first_failure: SealedScoringResult | None = None
    for isolate in (candidate_isolate, gold_isolate):
        failure = _run_trusted_phase(case.cleanup_sql, mode, isolate, "cleanup")
        first_failure = first_failure or failure
    return first_failure


def _finalize_pair(
    mode: ScoringMode,
    candidate_isolate: IsolatedPostgreSQLDatabase,
    gold_isolate: IsolatedPostgreSQLDatabase,
) -> SealedScoringResult | None:
    first_failure: SealedScoringResult | None = None
    for isolate in (candidate_isolate, gold_isolate):
        failure = _reset_and_release(mode, isolate)
        first_failure = first_failure or failure
    return first_failure


def _reset_and_release(
    mode: ScoringMode, isolate: IsolatedPostgreSQLDatabase
) -> SealedScoringResult | None:
    reset_failure: SealedScoringResult | None = None
    try:
        isolate.reset()
    except Exception:
        reset_failure = _infrastructure(mode, FailureClass.DATABASE_RESET_FAILED)
    try:
        isolate.release()
    except Exception:
        return _infrastructure(mode, FailureClass.DATABASE_RELEASE_FAILED)
    return reset_failure


def _close_connection(
    mode: ScoringMode, connection: PostgreSQLConnection
) -> SealedScoringResult | None:
    try:
        connection.close()
    except Exception:
        return _infrastructure(mode, FailureClass.DATABASE_CLOSE_FAILED)
    return None


def _compare(
    mode: ScoringMode,
    candidate: QuerySequenceResult,
    gold: QuerySequenceResult,
    conditions: Mapping[str, Any],
) -> SealedScoringResult:
    if candidate.rows is None:
        return _system_failure(mode, FailureClass.CANDIDATE_NO_RESULT)
    if gold.rows is None:
        return _infrastructure(mode, FailureClass.GOLD_NO_RESULT)
    try:
        equal = (
            official_soft_ex_equal(candidate.rows, gold.rows, conditions=conditions)
            if mode is ScoringMode.OFFICIAL
            else sensitivity_equal(candidate.rows, gold.rows, conditions=conditions)
        )
    except (InvalidOperation, ScoringPolicyError):
        return _infrastructure(mode, FailureClass.SCORER_POLICY_ERROR)
    identity, version = _scorer(mode)
    return SealedScoringResult(
        scorer_identity=identity,
        scorer_version=version,
        outcome="correct" if equal else "wrong_answer",
        candidate_row_limit_exceeded=candidate.row_limit_exceeded,
        gold_row_limit_exceeded=gold.row_limit_exceeded,
    )


def _scoring_sql(
    case: _ValidatedCase, mode: ScoringMode
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if mode is ScoringMode.SENSITIVITY:
        return case.candidate_sql, case.gold_sql
    return (
        tuple(rewrite_sql_official(sql) for sql in case.candidate_sql),
        tuple(rewrite_sql_official(sql) for sql in case.gold_sql),
    )


def _validate_case(case: SealedQueryCase) -> _ValidatedCase:
    if not isinstance(case.database, str) or not case.database:
        raise ValueError("database must be a non-empty string")
    if not isinstance(case.conditions, Mapping):
        raise ValueError("conditions must be a mapping")
    sensitivity_equal((), (), conditions=case.conditions)
    return _ValidatedCase(
        database=case.database,
        candidate_sql=_statements(case.candidate_sql, allow_empty=True),
        gold_sql=_statements(case.gold_sql, allow_empty=True),
        preprocess_sql=_statements(case.preprocess_sql, allow_empty=True),
        cleanup_sql=_statements(case.cleanup_sql, allow_empty=True),
        conditions=dict(case.conditions),
    )


def validate_query_case(case: SealedQueryCase) -> None:
    """Fail closed on all case fields before any database is acquired."""
    _validate_case(case)


def _statements(value: str | Sequence[str], *, allow_empty: bool) -> tuple[str, ...]:
    values: object = (value,) if isinstance(value, str) else value
    if not isinstance(values, Sequence):
        raise ValueError("SQL statements must be a sequence")
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise ValueError("SQL statements must be non-empty strings")
    result = tuple(values)
    if not allow_empty and not result:
        raise ValueError("SQL statements must not be empty")
    return result


def _system_failure(
    mode: ScoringMode,
    failure_class: FailureClass,
    *,
    candidate_row_limit_exceeded: bool = False,
) -> SealedScoringResult:
    identity, version = _scorer(mode)
    return SealedScoringResult(
        scorer_identity=identity,
        scorer_version=version,
        outcome="refused_or_error",
        failure_origin="evaluated_system",
        failure_class=failure_class,
        candidate_row_limit_exceeded=candidate_row_limit_exceeded,
    )


def _infrastructure(
    mode: ScoringMode,
    failure_class: FailureClass,
    *,
    gold_row_limit_exceeded: bool = False,
) -> SealedScoringResult:
    identity, version = _scorer(mode)
    return SealedScoringResult(
        scorer_identity=identity,
        scorer_version=version,
        outcome=None,
        failure_origin="benchmark_infrastructure",
        failure_class=failure_class,
        rerun_eligible=failure_class in _RERUN_ELIGIBLE_FAILURES,
        gold_row_limit_exceeded=gold_row_limit_exceeded,
    )


def _phase_failure(
    phase: Literal["preprocess", "candidate", "gold", "cleanup"],
    kind: Literal["timeout", "statement", "infrastructure"],
) -> FailureClass:
    return {
        ("preprocess", "timeout"): FailureClass.PREPROCESS_TIMEOUT,
        ("preprocess", "statement"): FailureClass.PREPROCESS_STATEMENT_ERROR,
        (
            "preprocess",
            "infrastructure",
        ): FailureClass.PREPROCESS_DATABASE_UNAVAILABLE,
        (
            "candidate",
            "infrastructure",
        ): FailureClass.CANDIDATE_DATABASE_UNAVAILABLE,
        ("gold", "timeout"): FailureClass.GOLD_TIMEOUT,
        ("gold", "statement"): FailureClass.GOLD_STATEMENT_ERROR,
        ("gold", "infrastructure"): FailureClass.GOLD_DATABASE_UNAVAILABLE,
        ("cleanup", "timeout"): FailureClass.CLEANUP_TIMEOUT,
        ("cleanup", "statement"): FailureClass.CLEANUP_STATEMENT_ERROR,
        ("cleanup", "infrastructure"): FailureClass.CLEANUP_DATABASE_UNAVAILABLE,
    }[(phase, kind)]


def _scorer(mode: ScoringMode) -> tuple[str, str]:
    if mode is ScoringMode.OFFICIAL:
        return "official_soft_ex", OFFICIAL_SOFT_EX_VERSION
    if mode is ScoringMode.SENSITIVITY:
        return "sensitivity", SENSITIVITY_SCORER_VERSION
    raise ValueError("unsupported scoring mode")
