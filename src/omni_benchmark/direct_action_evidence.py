"""Bounded private evidence for diagnostic direct-SQL tool actions."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .autoresearch_config import _canonical_bytes
from .content_policy import ContentPolicy
from .direct_action_protocol import DirectToolAction
from .direct_capture_contract import DirectReferenceResult
from .direct_runtime_binding import DirectRuntimeBinding
from .direct_sql_result import DirectResultError, validate_json_value
from .omni_result_adapter import OmniResultContractError, reject_forbidden_keys
from .sql_admission import single_query_sql_is_admissible

_KIND = "direct-action-evidence"
_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_RETRIEVAL_TOOLS = frozenset({"search_hkb", "search_semantic_model"})
_FIELDS = frozenset(
    {"kind", "records", "runtime_binding_sha256", "schema_version", "trace_sha256"}
)
_RECORD_FIELDS = frozenset(
    {
        "exploratory_sql",
        "retrieval_query",
        "retrieved_public_ids",
        "tool_name",
        "trace_seq",
    }
)
_MAX_RECORDS = 1_024
_MAX_RETRIEVAL_QUERY_CHARS = 512
_MAX_EXPLORATORY_SQL_CHARS = 65_536
_MAX_RETRIEVED_IDS = 256
_MAX_PUBLIC_ID_CHARS = 128


class DirectActionEvidenceError(ValueError):
    """Raised when private action evidence is incomplete or unsafe."""


@dataclass(frozen=True)
class DirectActionEvidence:
    """One content-safe model tool action bound to its trace event."""

    trace_seq: int
    tool_name: str
    retrieval_query: str | None
    exploratory_sql: str | None
    retrieved_public_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "exploratory_sql": self.exploratory_sql,
            "retrieval_query": self.retrieval_query,
            "retrieved_public_ids": list(self.retrieved_public_ids),
            "tool_name": self.tool_name,
            "trace_seq": self.trace_seq,
        }

    def sha256(self) -> str:
        return hashlib.sha256(_canonical_bytes(self.as_dict())).hexdigest()


def retrieval_evidence(
    *,
    trace_seq: int,
    tool_name: str,
    query: str,
    retrieved_ids: Sequence[str],
    policy: ContentPolicy,
) -> DirectActionEvidence:
    """Validate and retain one public-reference search action."""
    if tool_name not in _RETRIEVAL_TOOLS:
        raise DirectActionEvidenceError("retrieval tool is invalid")
    if (
        not isinstance(query, str)
        or not query
        or len(query) > _MAX_RETRIEVAL_QUERY_CHARS
    ):
        raise DirectActionEvidenceError("retrieval query must be non-empty and bounded")
    if not policy.query_is_safe(query):
        raise DirectActionEvidenceError("retrieval query is not content-safe")
    identifiers = _canonical_public_ids(retrieved_ids, policy)
    return DirectActionEvidence(trace_seq, tool_name, query, None, identifiers)


def sql_evidence(
    *, trace_seq: int, sql: str, policy: ContentPolicy
) -> DirectActionEvidence:
    """Validate and retain one admitted exploratory SQL action."""
    if not isinstance(sql, str) or not sql or len(sql) > _MAX_EXPLORATORY_SQL_CHARS:
        raise DirectActionEvidenceError("exploratory SQL must be non-empty and bounded")
    if not policy.query_is_safe(sql):
        raise DirectActionEvidenceError("exploratory SQL is not content-safe")
    if not single_query_sql_is_admissible(sql):
        raise DirectActionEvidenceError("exploratory SQL is not admitted")
    return DirectActionEvidence(trace_seq, "execute_sql", None, sql, ())


def validate_action_evidence_input(
    action: DirectToolAction, policy: ContentPolicy
) -> None:
    """Reject unbounded model action content before a tool is dispatched."""
    if action.name in _RETRIEVAL_TOOLS:
        retrieval_evidence(
            trace_seq=0,
            tool_name=action.name,
            query=action.arguments["query"],
            retrieved_ids=(),
            policy=policy,
        )
    elif action.name == "execute_sql" and single_query_sql_is_admissible(
        action.arguments["sql"]
    ):
        sql_evidence(trace_seq=0, sql=action.arguments["sql"], policy=policy)


def tool_action_evidence(
    *,
    action: DirectToolAction,
    trace_seq: int,
    failure_class: str | None,
    retrieved_ids: Sequence[str],
    policy: ContentPolicy,
) -> DirectActionEvidence | None:
    """Create evidence for one dispatched action when the contract requires it."""
    if action.name in _RETRIEVAL_TOOLS:
        return retrieval_evidence(
            trace_seq=trace_seq,
            tool_name=action.name,
            query=action.arguments["query"],
            retrieved_ids=retrieved_ids,
            policy=policy,
        )
    if action.name == "execute_sql" and failure_class != "sql_not_admitted":
        return sql_evidence(
            trace_seq=trace_seq, sql=action.arguments["sql"], policy=policy
        )
    return None


def public_ids_from_reference(
    result: DirectReferenceResult, policy: ContentPolicy
) -> tuple[str, ...]:
    """Extract only explicitly returned public provenance identifiers."""
    identifiers: Sequence[str] = result.semantic_objects
    if not identifiers and isinstance(result.payload, Mapping):
        candidate = result.payload.get("retrieved_hkb_stable_ids", ())
        if isinstance(candidate, list):
            identifiers = candidate
    return _canonical_public_ids(identifiers, policy)


def action_evidence_payload(
    *,
    binding: DirectRuntimeBinding,
    trace_sha256: str,
    records: Sequence[DirectActionEvidence],
    trace_events: Sequence[Mapping[str, Any]],
    policy: ContentPolicy,
) -> dict[str, object]:
    """Build and validate one exact private action-evidence sidecar."""
    payload: dict[str, object] = {
        "kind": _KIND,
        "records": [record.as_dict() for record in records],
        "runtime_binding_sha256": binding.sha256(),
        "schema_version": _SCHEMA_VERSION,
        "trace_sha256": trace_sha256,
    }
    validate_action_evidence_payload(
        payload,
        binding=binding,
        trace_sha256=trace_sha256,
        trace_events=trace_events,
        policy=policy,
    )
    return payload


def validate_action_evidence_payload(
    value: object,
    *,
    binding: DirectRuntimeBinding,
    trace_sha256: str,
    trace_events: Sequence[Mapping[str, Any]],
    policy: ContentPolicy,
) -> None:
    """Reject unsafe content and any omission or trace substitution."""
    payload = _require_payload(value, policy)
    if payload["runtime_binding_sha256"] != binding.sha256():
        raise DirectActionEvidenceError("action evidence binding does not match")
    if payload["trace_sha256"] != trace_sha256 or not _is_sha256(trace_sha256):
        raise DirectActionEvidenceError("action evidence trace digest does not match")
    records = _parse_records(payload["records"], binding, policy)
    _bind_records_to_trace(records, trace_events)


def _require_payload(value: object, policy: ContentPolicy) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        raise DirectActionEvidenceError("action evidence must use the exact schema")
    if value["kind"] != _KIND or value["schema_version"] != _SCHEMA_VERSION:
        raise DirectActionEvidenceError("action evidence schema is invalid")
    if type(value["schema_version"]) is not int:
        raise DirectActionEvidenceError("action evidence schema is invalid")
    try:
        reject_forbidden_keys(value)
        validate_json_value(value)
    except (DirectResultError, OmniResultContractError) as error:
        raise DirectActionEvidenceError(
            "action evidence content is forbidden"
        ) from error
    if policy.sanitize_json(value) != value:
        raise DirectActionEvidenceError("action evidence content is not safe")
    return value


def _parse_records(
    value: object, binding: DirectRuntimeBinding, policy: ContentPolicy
) -> tuple[DirectActionEvidence, ...]:
    if not isinstance(value, list) or len(value) > min(
        _MAX_RECORDS, binding.budget.maximum_turns
    ):
        raise DirectActionEvidenceError("action evidence records are not bounded")
    records = tuple(_parse_record(item, policy) for item in value)
    sequences = [record.trace_seq for record in records]
    if sequences != sorted(set(sequences)):
        raise DirectActionEvidenceError("action evidence sequence is not canonical")
    for record in records:
        _validate_capability(record, binding)
    return records


def _parse_record(value: object, policy: ContentPolicy) -> DirectActionEvidence:
    if not isinstance(value, Mapping) or set(value) != _RECORD_FIELDS:
        raise DirectActionEvidenceError("action evidence record schema is invalid")
    trace_seq = value["trace_seq"]
    if type(trace_seq) is not int or trace_seq < 0:
        raise DirectActionEvidenceError("action evidence trace sequence is invalid")
    tool_name = value["tool_name"]
    if not isinstance(tool_name, str):
        raise DirectActionEvidenceError("action evidence tool is invalid")
    if tool_name in _RETRIEVAL_TOOLS:
        if value["exploratory_sql"] is not None:
            raise DirectActionEvidenceError("retrieval evidence cannot contain SQL")
        return retrieval_evidence(
            trace_seq=trace_seq,
            tool_name=tool_name,
            query=value["retrieval_query"],
            retrieved_ids=value["retrieved_public_ids"],
            policy=policy,
        )
    if tool_name == "execute_sql" and value["retrieval_query"] is None:
        if value["retrieved_public_ids"] != []:
            raise DirectActionEvidenceError("SQL evidence cannot claim public IDs")
        return sql_evidence(
            trace_seq=trace_seq, sql=value["exploratory_sql"], policy=policy
        )
    raise DirectActionEvidenceError("action evidence tool is invalid")


def _validate_capability(
    record: DirectActionEvidence, binding: DirectRuntimeBinding
) -> None:
    expected = {"C1": set(), "C2": {"search_hkb"}, "C3": {"search_semantic_model"}}
    if (
        record.tool_name in _RETRIEVAL_TOOLS
        and record.tool_name not in expected[binding.condition]
    ):
        raise DirectActionEvidenceError("action evidence violates condition capability")


def _bind_records_to_trace(
    records: Sequence[DirectActionEvidence], trace_events: Sequence[Mapping[str, Any]]
) -> None:
    if any(not isinstance(event, Mapping) for event in trace_events):
        raise DirectActionEvidenceError("action evidence trace event is invalid")
    relevant = [event for event in trace_events if _event_requires_evidence(event)]
    required = {event.get("seq"): event for event in relevant}
    if len(required) != len(relevant) or any(
        type(sequence) is not int or sequence < 0 for sequence in required
    ):
        raise DirectActionEvidenceError("action evidence trace sequence is invalid")
    actual = {record.trace_seq: record for record in records}
    if set(actual) != set(required):
        raise DirectActionEvidenceError("action evidence is not complete for the trace")
    for seq, event in required.items():
        record = actual[seq]
        if record.tool_name != event.get("tool_name"):
            raise DirectActionEvidenceError("action evidence tool does not match trace")
        if record.sha256() != event.get("metadata_sha256"):
            raise DirectActionEvidenceError(
                "action evidence digest does not match trace"
            )


def _event_requires_evidence(event: Mapping[str, Any]) -> bool:
    if event.get("event_type") != "direct_tool_dispatch":
        return False
    tool_name = event.get("tool_name")
    return tool_name in _RETRIEVAL_TOOLS or (
        tool_name == "execute_sql" and event.get("failure_class") != "sql_not_admitted"
    )


def _canonical_public_ids(
    values: Sequence[str], policy: ContentPolicy
) -> tuple[str, ...]:
    if (
        not isinstance(values, Sequence)
        or isinstance(values, (str, bytes))
        or len(values) > _MAX_RETRIEVED_IDS
    ):
        raise DirectActionEvidenceError("retrieved public identifiers are not bounded")
    if any(
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_PUBLIC_ID_CHARS
        or not policy.identifier_is_safe(value)
        for value in values
    ):
        raise DirectActionEvidenceError("retrieved public identifier is invalid")
    return tuple(sorted(set(values)))


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None
