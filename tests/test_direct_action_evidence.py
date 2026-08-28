from __future__ import annotations

from dataclasses import replace

import pytest

from omni_benchmark.content_policy import ContentPolicy
from omni_benchmark.direct_action_evidence import (
    DirectActionEvidenceError,
    action_evidence_payload,
    public_ids_from_reference,
    retrieval_evidence,
    sql_evidence,
    validate_action_evidence_payload,
)
from omni_benchmark.direct_capture_contract import DirectReferenceResult
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
    forged = replace(records[0], retrieved_public_ids=("x" * 257,))

    with pytest.raises(DirectActionEvidenceError, match="identifier"):
        action_evidence_payload(
            binding=binding,
            trace_sha256=TRACE_SHA256,
            records=(forged, records[1]),
            trace_events=events,
            policy=policy,
        )


def test_schema_retrieval_evidence_is_valid_for_every_direct_condition() -> None:
    policy = ContentPolicy.from_environment({})
    public_id = "labor_certification_applications_large:column:" + "x" * 94
    retrieval = retrieval_evidence(
        trace_seq=1,
        tool_name="inspect_schema",
        query="employer wage",
        retrieved_ids=(public_id,),
        policy=policy,
    )
    event = {
        "event_type": "direct_tool_dispatch",
        "failure_class": None,
        "metadata_sha256": retrieval.sha256(),
        "seq": 1,
        "tool_name": "inspect_schema",
    }

    for condition in ("C1", "C2", "C3"):
        binding = runtime_binding(condition)
        payload = action_evidence_payload(
            binding=binding,
            trace_sha256=TRACE_SHA256,
            records=(retrieval,),
            trace_events=(event,),
            policy=policy,
        )
        assert payload["records"][0]["retrieved_public_ids"] == [public_id]


def test_public_foreign_key_hash_is_a_valid_schema_identifier() -> None:
    public_id = "public:foreign-key:sha256:" + "a" * 64

    evidence = retrieval_evidence(
        trace_seq=1,
        tool_name="inspect_schema",
        query="public relationship",
        retrieved_ids=(public_id,),
        policy=ContentPolicy.from_environment({}),
    )

    assert evidence.retrieved_public_ids == (public_id,)


@pytest.mark.parametrize(
    "public_id",
    [
        "live-secret-value",
        "sk-ant-abcdefghijklmnop",
        "api_key=plainsecret",
        "token:plainsecret",
        "x" * 257,
    ],
)
def test_public_schema_identifier_still_rejects_credentials(public_id: str) -> None:
    policy = ContentPolicy.from_environment({"OMNI_API_TOKEN": "live-secret-value"})

    with pytest.raises(DirectActionEvidenceError, match="identifier"):
        retrieval_evidence(
            trace_seq=1,
            tool_name="inspect_schema",
            query="public relationship",
            retrieved_ids=(public_id,),
            policy=policy,
        )


@pytest.mark.parametrize(
    "public_id",
    [
        "public:foreign-key:sha256:not-a-digest",
        "api_key:foreign-key:sha256:" + "a" * 64,
        "public:foreign-key:sha256:" + "A" * 64,
    ],
)
def test_public_foreign_key_identifier_requires_canonical_form(public_id: str) -> None:
    with pytest.raises(DirectActionEvidenceError, match="identifier"):
        retrieval_evidence(
            trace_seq=1,
            tool_name="inspect_schema",
            query="public relationship",
            retrieved_ids=(public_id,),
            policy=ContentPolicy.from_environment({}),
        )


def test_reference_ids_are_extracted_by_exact_capability() -> None:
    policy = ContentPolicy.from_environment({})
    result = DirectReferenceResult(
        payload={
            "retrieved_schema_stable_ids": ["public:schema:table"],
            "retrieved_hkb_stable_ids": ["public:hkb:must-not-cross"],
        },
        context_sha256="b" * 64,
        capability="inspect_schema",
    )

    assert public_ids_from_reference(result, policy) == ("public:schema:table",)


@pytest.mark.parametrize(
    "payload", [{"tables": []}, {"retrieved_schema_stable_ids": {}}]
)
def test_schema_reference_requires_explicit_identifier_list(
    payload: dict[str, object],
) -> None:
    result = DirectReferenceResult(
        payload=payload,
        context_sha256="b" * 64,
        capability="inspect_schema",
    )

    with pytest.raises(DirectActionEvidenceError, match="identifier list"):
        public_ids_from_reference(result, ContentPolicy.from_environment({}))


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
