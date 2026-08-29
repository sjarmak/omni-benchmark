"""Synthetic end-to-end tests for the sealed Query scoring lifecycle."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

import pytest

from omni_benchmark.scoring import (
    OFFICIAL_SOFT_EX_VERSION,
    SENSITIVITY_SCORER_VERSION,
)
from omni_benchmark.sealed_scoring import (
    FailureClass,
    SealedQueryCase,
    ScoringMode,
    system_no_answer,
    score_query,
    score_query_both,
)
from tests.execution_fixtures import (
    SyntheticConnection,
    SyntheticDatabaseError,
    SyntheticIsolate,
    SyntheticIsolationProvider,
)


def _case(**changes: object) -> SealedQueryCase:
    values: dict[str, object] = {
        "database": "public_fixture",
        "candidate_sql": "SELECT DISTINCT x FROM values_table",
        "gold_sql": "SELECT x FROM values_table",
        "preprocess_sql": ("CREATE TEMP VIEW ready AS SELECT 1",),
        "cleanup_sql": ("DROP VIEW ready",),
        "conditions": {"decimal": -1, "order": False},
    }
    values.update(changes)
    return SealedQueryCase(**values)  # type: ignore[arg-type]


def _responses() -> dict[str, object]:
    return {
        "CREATE TEMP VIEW ready AS SELECT 1": None,
        "DROP VIEW ready": None,
        "SELECT DISTINCT x FROM values_table": [(1,)],
        "SELECT x FROM values_table": [(1,), (1,)],
    }


def test_official_lifecycle_runs_detection_comparison_cleanup_reset_and_release() -> (
    None
):
    provider = SyntheticIsolationProvider(_responses())

    result = score_query(_case(), ScoringMode.OFFICIAL, provider)

    assert result.outcome == "correct"
    assert result.scorer_version == OFFICIAL_SOFT_EX_VERSION
    executed = [event[1] for event in provider.events if event[0] == "execute"]
    lifecycle_sql = [
        sql
        for sql in executed
        if not sql.startswith("SET statement_timeout")
        and sql != "SET TRANSACTION READ ONLY;"
    ]
    assert lifecycle_sql == [
        "CREATE TEMP VIEW ready AS SELECT 1",
        "CREATE TEMP VIEW ready AS SELECT 1",
        "SELECT DISTINCT x FROM values_table",
        "SELECT x FROM values_table",
        "SELECT x FROM values_table",
        "DROP VIEW ready",
        "DROP VIEW ready",
    ]
    assert executed.count("SELECT DISTINCT x FROM values_table") == 1
    assert executed.count("SELECT x FROM values_table") == 2
    assert provider.events[-4:] == [
        ("reset",),
        ("release",),
        ("reset",),
        ("release",),
    ]


def test_both_scorers_use_fresh_isolates_and_preserve_distinct_for_sensitivity() -> (
    None
):
    provider = SyntheticIsolationProvider(_responses())

    official, sensitivity = score_query_both(_case(), provider)

    assert official.outcome == "correct"
    assert sensitivity.outcome == "wrong_answer"
    assert sensitivity.scorer_version == SENSITIVITY_SCORER_VERSION
    assert provider.events.count(("acquire", "public_fixture")) == 4
    assert provider.events.count(("reset",)) == 4
    assert provider.events.count(("release",)) == 4


def test_empty_results_reproduce_official_failure_and_sensitivity_correction() -> None:
    responses = {
        "SELECT nothing": [],
        "CREATE TEMP VIEW ready AS SELECT 1": None,
        "DROP VIEW ready": None,
    }
    case = _case(candidate_sql="SELECT nothing", gold_sql="SELECT nothing")
    provider = SyntheticIsolationProvider(responses)

    official, sensitivity = score_query_both(case, provider)

    assert official.outcome == "wrong_answer"
    assert sensitivity.outcome == "correct"


def test_no_result_is_distinct_from_a_valid_empty_result() -> None:
    responses = {
        "SET application_name = 'x'": None,
        "SELECT no_result": None,
        "SELECT nothing": [],
        "CREATE TEMP VIEW ready AS SELECT 1": None,
        "DROP VIEW ready": None,
    }
    candidate_no_result = _case(
        candidate_sql="SELECT no_result", gold_sql="SELECT nothing"
    )
    gold_no_result = _case(
        candidate_sql="SELECT nothing", gold_sql="SET application_name = 'x'"
    )

    candidate = score_query(
        candidate_no_result,
        ScoringMode.SENSITIVITY,
        SyntheticIsolationProvider(responses),
    )
    gold = score_query(
        gold_no_result,
        ScoringMode.SENSITIVITY,
        SyntheticIsolationProvider(responses),
    )

    assert candidate.outcome == "refused_or_error"
    assert candidate.failure_class is FailureClass.CANDIDATE_NO_RESULT
    assert gold.outcome is None
    assert gold.failure_origin == "benchmark_infrastructure"
    assert gold.failure_class is FailureClass.GOLD_NO_RESULT


def test_row_limit_overflow_cannot_compare_equal_on_a_shared_prefix() -> None:
    candidate_rows = [(index,) for index in range(10_001)]
    gold_rows = [(index,) for index in range(10_002)]
    responses = _responses() | {
        "SELECT candidate": candidate_rows,
        "SELECT gold": gold_rows,
    }
    case = _case(candidate_sql="SELECT candidate", gold_sql="SELECT gold")

    result = score_query(
        case, ScoringMode.SENSITIVITY, SyntheticIsolationProvider(responses)
    )

    assert result.outcome == "refused_or_error"
    assert result.failure_class is FailureClass.CANDIDATE_RESULT_OVERFLOW


def test_official_overflow_preserves_upstream_prefix_result_but_discloses_it() -> None:
    responses = _responses() | {
        "SELECT candidate": [(index,) for index in range(10_001)],
        "SELECT gold": [(index,) for index in range(10_002)],
    }
    case = _case(candidate_sql="SELECT candidate", gold_sql="SELECT gold")

    result = score_query(
        case, ScoringMode.OFFICIAL, SyntheticIsolationProvider(responses)
    )

    assert result.outcome == "correct"
    assert result.candidate_row_limit_exceeded
    assert result.gold_row_limit_exceeded


def test_gold_row_limit_overflow_is_non_rerunnable_infrastructure() -> None:
    responses = _responses() | {
        "SELECT candidate": [(index,) for index in range(10_000)],
        "SELECT gold": [(index,) for index in range(10_001)],
    }
    case = _case(candidate_sql="SELECT candidate", gold_sql="SELECT gold")

    result = score_query(
        case, ScoringMode.SENSITIVITY, SyntheticIsolationProvider(responses)
    )

    assert result.outcome is None
    assert result.failure_origin == "benchmark_infrastructure"
    assert result.failure_class is FailureClass.GOLD_RESULT_OVERFLOW
    assert not result.rerun_eligible


def test_official_decimal_normalization_failure_is_scorer_policy_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_decimal(*args: object, **kwargs: object) -> bool:
        raise InvalidOperation

    monkeypatch.setattr(
        "omni_benchmark.sealed_scoring.official_soft_ex_equal", invalid_decimal
    )
    responses = _responses() | {
        "SELECT candidate": [(Decimal("1"),)],
        "SELECT gold": [(Decimal("1"),)],
    }
    case = _case(candidate_sql="SELECT candidate", gold_sql="SELECT gold")

    result = score_query(
        case, ScoringMode.OFFICIAL, SyntheticIsolationProvider(responses)
    )

    assert result.outcome is None
    assert result.failure_origin == "benchmark_infrastructure"
    assert result.failure_class is FailureClass.SCORER_POLICY_ERROR


class MutableConnection(SyntheticConnection):
    def __init__(self, state: dict[str, int], events: list[tuple[Any, ...]]) -> None:
        super().__init__({}, events)
        self._state = state

    def cursor(self):  # type: ignore[no-untyped-def]
        connection = self

        class MutableCursor:
            description: object | None = None
            rows: tuple[tuple[int, ...], ...] = ()

            def execute(self, sql: str) -> None:
                connection.events.append(("execute", sql))
                if sql == "UPDATE fixture SET value = 2":
                    connection._state["value"] = 2
                    self.description = None
                elif sql == "SELECT value FROM fixture":
                    self.rows = ((connection._state["value"],),)
                    self.description = object()
                else:
                    self.description = None

            def fetchmany(self, size: int):  # type: ignore[no-untyped-def]
                connection.events.append(("fetchmany", size))
                return self.rows[:size]

            def nextset(self) -> bool:
                return False

            def close(self) -> None:
                connection.events.append(("cursor_close",))

        self.events.append(("cursor",))
        return MutableCursor()


class MutableIsolate(SyntheticIsolate):
    def __init__(
        self,
        responses: Mapping[str, object],
        events: list[tuple[Any, ...]],
    ) -> None:
        super().__init__(responses, events)  # type: ignore[arg-type]
        self._state = {"value": 1}

    def connect_scoring(self) -> MutableConnection:
        self._events.append(("connect_scoring",))
        return MutableConnection(self._state, self._events)


def test_candidate_mutation_is_rejected_before_isolate_acquisition() -> None:
    provider = SyntheticIsolationProvider({}, isolate_factory=MutableIsolate)
    case = _case(
        candidate_sql=(
            "UPDATE fixture SET value = 2",
            "SELECT value FROM fixture",
        ),
        gold_sql="SELECT value FROM fixture",
        preprocess_sql=(),
        cleanup_sql=(),
    )

    result = score_query(case, ScoringMode.SENSITIVITY, provider)

    assert result.outcome == "refused_or_error"
    assert result.failure_class is FailureClass.CANDIDATE_DISALLOWED_STATEMENT
    assert provider.events == []


def test_candidate_timeout_is_system_owned_and_still_resets_isolate() -> None:
    responses = _responses() | {
        "SELECT DISTINCT x FROM values_table": SyntheticDatabaseError("57014")
    }
    provider = SyntheticIsolationProvider(responses)

    result = score_query(_case(), ScoringMode.OFFICIAL, provider)

    assert result.outcome == "refused_or_error"
    assert result.failure_origin == "evaluated_system"
    assert result.failure_class is FailureClass.CANDIDATE_TIMEOUT
    assert not result.rerun_eligible
    assert provider.events[-2:] == [("reset",), ("release",)]


def test_gold_timeout_is_infrastructure_owned_and_not_materializable() -> None:
    responses = _responses() | {
        "SELECT x FROM values_table": SyntheticDatabaseError("57014")
    }
    provider = SyntheticIsolationProvider(responses)

    result = score_query(_case(), ScoringMode.SENSITIVITY, provider)

    assert result.outcome is None
    assert result.failure_origin == "benchmark_infrastructure"
    assert result.failure_class is FailureClass.GOLD_TIMEOUT
    assert not result.rerun_eligible
    with pytest.raises(ValueError, match="infrastructure"):
        result.as_score_record("run-1:q-1:C1:1")


class CleanupFailingIsolate(SyntheticIsolate):
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self._trusted_connections = 0

    def connect_trusted(self):  # type: ignore[no-untyped-def]
        connection = super().connect_trusted()
        self._trusted_connections += 1
        if self._trusted_connections == 2:
            connection._responses = connection._responses | {
                "DROP VIEW ready": SyntheticDatabaseError("42601")
            }
        return connection


def test_cleanup_failure_overrides_score_as_rerunnable_infrastructure() -> None:
    provider = SyntheticIsolationProvider(
        _responses(), isolate_factory=CleanupFailingIsolate
    )

    result = score_query(_case(), ScoringMode.OFFICIAL, provider)

    assert result.outcome is None
    assert result.failure_origin == "benchmark_infrastructure"
    assert result.failure_class is FailureClass.CLEANUP_STATEMENT_ERROR
    assert not result.rerun_eligible
    assert provider.events[-2:] == [("reset",), ("release",)]


class AcquisitionFailingProvider:
    def acquire(self, database: str) -> SyntheticIsolate:
        raise ConnectionError("synthetic database outage")


def test_database_acquisition_outage_is_the_rerunnable_infrastructure_class() -> None:
    result = score_query(_case(), ScoringMode.OFFICIAL, AcquisitionFailingProvider())

    assert result.outcome is None
    assert result.failure_class is FailureClass.DATABASE_ACQUIRE_FAILED
    assert result.rerun_eligible


def test_score_record_transport_has_only_three_state_label_and_failure_category() -> (
    None
):
    provider = SyntheticIsolationProvider(_responses())
    result = score_query(_case(), ScoringMode.SENSITIVITY, provider)

    assert result.as_score_record("run-1:q-1:C2:1") == {
        "attempt_id": "run-1:q-1:C2:1",
        "outcome": "wrong_answer",
    }

    no_answer = system_no_answer(
        ScoringMode.OFFICIAL, failure_class=FailureClass.AGENT_REFUSAL
    )
    assert no_answer.as_score_record("run-1:q-2:C4:1") == {
        "attempt_id": "run-1:q-2:C4:1",
        "failure_category": "agent_refusal",
        "outcome": "refused_or_error",
    }


def test_private_sql_is_excluded_from_case_repr_and_returned_score() -> None:
    case = _case(gold_sql="SELECT 'never-log-this' AS secret")
    provider = SyntheticIsolationProvider(
        _responses() | {"SELECT 'never-log-this' AS secret": [(1,)]}
    )

    result = score_query(case, ScoringMode.SENSITIVITY, provider)

    assert "never-log-this" not in repr(case)
    assert "never-log-this" not in repr(result)
    assert not hasattr(result, "gold_sql")
    assert not hasattr(result, "gold_rows")


class EvaluationBugIsolate(SyntheticIsolate):
    def connect_scoring(self):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt("synthetic evaluator interruption")


def test_isolate_is_reset_and_released_even_for_unexpected_base_exception() -> None:
    provider = SyntheticIsolationProvider(
        _responses(), isolate_factory=EvaluationBugIsolate
    )

    with pytest.raises(KeyboardInterrupt):
        score_query(_case(), ScoringMode.OFFICIAL, provider)

    assert provider.events[-2:] == [("reset",), ("release",)]


def test_failure_categories_reject_untrusted_free_form_values() -> None:
    with pytest.raises(ValueError, match="FailureClass"):
        system_no_answer(
            ScoringMode.OFFICIAL,
            failure_class="password=synthetic-secret",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "candidate_sql",
    [
        "ALTER ROLE scorer PASSWORD 'changed'; SELECT 1",
        "NOTIFY outside_listener, 'payload'",
        "SELECT 1 INTO side_effect_table",
        "SELECT lo_create(987654)",
        "SELECT set_config('default_transaction_read_only', 'off', false), "
        "lo_create(987655)",
        "SELECT pg_notify('outside_listener', 'payload')",
        "SELECT pg_logical_emit_message(false, 'channel', 'payload')",
        "SELECT pg_try_advisory_lock(42)",
        "SELECT pg_try_advisory_xact_lock(42)",
        'SELECT U&"pg\\005flogical\\005femit\\005fmessage"('
        "false, 'channel', 'payload')",
        "SELECT setseed(0.25)",
    ],
)
def test_candidate_sql_rejects_global_side_effect_surfaces(
    candidate_sql: str,
) -> None:
    provider = SyntheticIsolationProvider(_responses())

    result = score_query(
        _case(candidate_sql=candidate_sql), ScoringMode.SENSITIVITY, provider
    )

    assert result.outcome == "refused_or_error"
    assert result.failure_class is FailureClass.CANDIDATE_DISALLOWED_STATEMENT
    assert all(
        event[1] != candidate_sql for event in provider.events if event[0] == "execute"
    )


def test_rejected_sql_is_not_emitted_to_logs_or_stderr(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    marker = "SYNTHETIC_SECRET_MARKER"
    provider = SyntheticIsolationProvider(_responses())
    results = tuple(
        score_query(
            _case(candidate_sql=candidate_sql),
            ScoringMode.SENSITIVITY,
            provider,
        )
        for candidate_sql in (
            f"ALTER ROLE scorer PASSWORD '{marker}'; SELECT 1",
            f"SELECT E'{marker}\\",
        )
    )

    captured = capsys.readouterr()
    assert all(
        result.failure_class is FailureClass.CANDIDATE_DISALLOWED_STATEMENT
        for result in results
    )
    assert all(event[0] != "acquire" for event in provider.events)
    assert marker not in captured.out
    assert marker not in captured.err
    assert marker not in caplog.text


def test_multiple_select_statements_remain_admissible_for_official_behavior() -> None:
    sql = "SELECT 1; SELECT 2"
    responses = _responses() | {sql: [(2,)], "SELECT 2": [(2,)]}

    result = score_query(
        _case(candidate_sql=sql, gold_sql="SELECT 2"),
        ScoringMode.OFFICIAL,
        SyntheticIsolationProvider(responses),
    )

    assert result.outcome == "correct"
