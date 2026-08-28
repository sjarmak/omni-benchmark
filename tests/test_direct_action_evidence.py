from __future__ import annotations

from dataclasses import replace

import pytest

from omni_benchmark.content_policy import ContentPolicy
from omni_benchmark.direct_action_evidence import (
    DirectActionEvidenceError,
    action_evidence_payload,
    retrieval_evidence,
    sql_evidence,
    validate_action_evidence_payload,
)
from tests.direct_capture_fixtures import runtime_binding


TRACE_SHA256 = "a" * 64


def _evidence_fixture() -> tuple[object, list[dict[str, object]], tuple[object, ...]]:
    binding = runtime_binding("C2")
    policy = ContentPolicy.from_environment({})
    retrieval = retrieval_evidence(
        trace_seq=1,
        tool_name="search_hkb",
        query="public metric",
        retrieved_ids=("public:hkb:metric",),
        policy=policy,
    )
    exploratory = sql_evidence(trace_seq=3, sql="SELECT 42", policy=policy)
    events = [
        {
            "event_type": "direct_tool_dispatch",
            "failure_class": None,
            "metadata_sha256": retrieval.sha256(),
            "seq": 1,
            "tool_name": "search_hkb",
        },
        {
            "event_type": "direct_tool_dispatch",
            "failure_class": None,
            "metadata_sha256": exploratory.sha256(),
            "seq": 3,
            "tool_name": "execute_sql",
        },
    ]
    return binding, events, (retrieval, exploratory)


def test_action_evidence_binds_retrieval_and_exploratory_sql_to_trace() -> None:
    binding, events, records = _evidence_fixture()
    policy = ContentPolicy.from_environment({})

    payload = action_evidence_payload(
        binding=binding,
        trace_sha256=TRACE_SHA256,
        records=records,
        trace_events=events,
        policy=policy,
    )

    validate_action_evidence_payload(
        payload,
        binding=binding,
        trace_sha256=TRACE_SHA256,
        trace_events=events,
        policy=policy,
    )
    assert payload["records"][0]["retrieval_query"] == "public metric"
    assert payload["records"][1]["exploratory_sql"] == "SELECT 42"


def test_action_evidence_rejects_omission_and_substitution() -> None:
    binding, events, records = _evidence_fixture()
    policy = ContentPolicy.from_environment({})
    payload = action_evidence_payload(
        binding=binding,
        trace_sha256=TRACE_SHA256,
        records=records,
        trace_events=events,
        policy=policy,
    )

    with pytest.raises(DirectActionEvidenceError, match="complete"):
        validate_action_evidence_payload(
            {**payload, "records": payload["records"][1:]},
            binding=binding,
            trace_sha256=TRACE_SHA256,
            trace_events=events,
            policy=policy,
        )
    changed = {**payload["records"][0], "retrieval_query": "different metric"}
    with pytest.raises(DirectActionEvidenceError, match="digest"):
        validate_action_evidence_payload(
            {**payload, "records": [changed, payload["records"][1]]},
            binding=binding,
            trace_sha256=TRACE_SHA256,
            trace_events=events,
            policy=policy,
        )


def test_action_evidence_rejects_forbidden_or_unbounded_content() -> None:
    policy = ContentPolicy.from_environment({"OMNI_API_TOKEN": "live-secret"})

    with pytest.raises(DirectActionEvidenceError, match="safe"):
        retrieval_evidence(
            trace_seq=1,
            tool_name="search_hkb",
            query="live-secret",
            retrieved_ids=(),
            policy=policy,
        )
    with pytest.raises(DirectActionEvidenceError, match="bounded"):
        sql_evidence(trace_seq=1, sql="SELECT '" + "x" * 65_536 + "'", policy=policy)


def test_action_evidence_rejects_a_forged_identifier() -> None:
    binding, events, records = _evidence_fixture()
    policy = ContentPolicy.from_environment({})
    forged = replace(records[0], retrieved_public_ids=("x" * 129,))

    with pytest.raises(DirectActionEvidenceError, match="identifier"):
        action_evidence_payload(
            binding=binding,
            trace_sha256=TRACE_SHA256,
            records=(forged, records[1]),
            trace_events=events,
            policy=policy,
        )


def test_action_evidence_rejects_malformed_record_and_trace_shapes() -> None:
    binding, events, records = _evidence_fixture()
    policy = ContentPolicy.from_environment({})
    payload = action_evidence_payload(
        binding=binding,
        trace_sha256=TRACE_SHA256,
        records=records,
        trace_events=events,
        policy=policy,
    )
    malformed = {**payload["records"][0], "tool_name": []}

    with pytest.raises(DirectActionEvidenceError, match="tool"):
        validate_action_evidence_payload(
            {**payload, "records": [malformed, payload["records"][1]]},
            binding=binding,
            trace_sha256=TRACE_SHA256,
            trace_events=events,
            policy=policy,
        )
    with pytest.raises(DirectActionEvidenceError, match="trace"):
        validate_action_evidence_payload(
            payload,
            binding=binding,
            trace_sha256=TRACE_SHA256,
            trace_events=[[]],
            policy=policy,
        )
