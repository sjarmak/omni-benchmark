"""Development-only loader for exact committed public benchmark questions."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .autoresearch_config import MANDATORY_FORBIDDEN_FIELDS
from .content_policy import ContentPolicy
from .direct_runtime_binding import (
    DirectQuestionIdentity,
    DirectRuntimeIdentityError,
)
from .omni_probe_preflight import OmniProbePreflightError, committed_spec

_CONFIG_PATH = Path("config/autoresearch.json")
_PUBLIC_MANIFEST_PATH = Path("data/manifests/eligible_questions.jsonl")
_SCOPE_PATHS = {
    "train": Path("data/manifests/train_ids.txt"),
    "dev-a": Path("data/manifests/dev_a_ids.txt"),
    "dev-b": Path("data/manifests/dev_b_ids.txt"),
}
_CONFIG_PATH_FIELDS = {
    "public_manifest_path": _PUBLIC_MANIFEST_PATH,
    "train_ids_path": _SCOPE_PATHS["train"],
    "dev_a_ids_path": _SCOPE_PATHS["dev-a"],
    "dev_b_ids_path": _SCOPE_PATHS["dev-b"],
    "test_ids_path": Path("data/manifests/test_ids.txt"),
}
_PUBLIC_RECORD_FIELDS = frozenset(
    {
        "category",
        "clean_up_sqls",
        "conditions",
        "high_level",
        "instance_id",
        "normal_query",
        "preprocess_sql",
        "query",
        "selected_database",
        "source_index",
    }
)
_CONDITION_FIELDS = frozenset({"decimal", "distinct", "order"})
_INSTANCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+/@-]{0,159}")
_DATABASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_]{0,127}")


class DirectQuestionLoadError(ValueError):
    """Raised before runtime when a public question is not exactly committed."""


def load_committed_direct_question(
    workspace: Path,
    commit: str,
    *,
    scope: str,
    instance_id: str,
    environment: Mapping[str, str] | None = None,
) -> DirectQuestionIdentity:
    """Load exactly one train/dev-A/dev-B Query record; test is unsupported."""
    if scope not in _SCOPE_PATHS:
        raise DirectQuestionLoadError("scope must be a development scope")
    selected_id = _identifier(instance_id, "instance_id")
    policy = ContentPolicy.from_environment(
        os.environ if environment is None else environment
    )
    config = _committed(workspace, commit, _CONFIG_PATH)
    _validate_config_paths(config.content, policy)
    manifest = _committed(workspace, commit, _PUBLIC_MANIFEST_PATH)
    records = _public_records(manifest.content, policy)
    train = _committed(workspace, commit, _SCOPE_PATHS["train"])
    train_ids = _ids(train.content, "train")
    if not train_ids.issubset(records):
        raise DirectQuestionLoadError("train IDs must exist in the public manifest")
    scope_spec = _scope_spec(workspace, commit, scope, selected_id, train, train_ids)
    record = records[selected_id]
    question = record["query"]
    selected_database = record["selected_database"]
    value = {
        "instance_id": selected_id,
        "public_manifest_path": _PUBLIC_MANIFEST_PATH.as_posix(),
        "public_manifest_sha256": manifest.sha256,
        "public_record_sha256": hashlib.sha256(_canonical(record)).hexdigest(),
        "question": question,
        "question_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
        "scope": scope,
        "scope_ids_path": _SCOPE_PATHS[scope].as_posix(),
        "scope_ids_sha256": scope_spec.sha256,
        "selected_database": selected_database,
    }
    try:
        return DirectQuestionIdentity.from_dict(value, environment=environment)
    except DirectRuntimeIdentityError as error:
        raise DirectQuestionLoadError(str(error)) from error


def _scope_spec(
    workspace: Path,
    commit: str,
    scope: str,
    selected_id: str,
    train: Any,
    train_ids: frozenset[str],
) -> Any:
    selected = train
    scope_ids = train_ids
    if scope != "train":
        selected = _committed(workspace, commit, _SCOPE_PATHS[scope])
        scope_ids = _ids(selected.content, scope)
        if not scope_ids.issubset(train_ids):
            raise DirectQuestionLoadError(f"{scope} IDs must be a subset of train IDs")
    if selected_id not in scope_ids:
        raise DirectQuestionLoadError(
            f"instance_id is not a member of the committed {scope} scope"
        )
    return selected


def _committed(workspace: Path, commit: str, path: Path) -> Any:
    try:
        return committed_spec(workspace, commit, path)
    except OmniProbePreflightError as error:
        raise DirectQuestionLoadError(str(error)) from error


def _validate_config_paths(content: bytes, policy: ContentPolicy) -> None:
    value = _json(content, "autoresearch config")
    if not isinstance(value, Mapping):
        raise DirectQuestionLoadError("autoresearch config must be an object")
    _reject_forbidden_fields(value)
    _require_safe(value, policy)
    for field, expected in _CONFIG_PATH_FIELDS.items():
        if value.get(field) != expected.as_posix():
            label = field.removesuffix("_ids_path").replace("_", "-")
            if field == "public_manifest_path":
                label = "public manifest"
            raise DirectQuestionLoadError(
                f"autoresearch config canonical {label} path is required"
            )


def _public_records(content: bytes, policy: ContentPolicy) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    try:
        text = content.decode("utf-8")
    except UnicodeError as error:
        raise DirectQuestionLoadError("public manifest must be UTF-8") from error
    lines = text.splitlines()
    if not lines:
        raise DirectQuestionLoadError("public manifest is empty")
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise DirectQuestionLoadError(
                f"public manifest line {line_number} is blank"
            )
        value = _json(line.encode(), f"public manifest line {line_number}")
        record = _public_record(value, line_number, policy)
        instance_id = record["instance_id"]
        if instance_id in records:
            raise DirectQuestionLoadError(
                "public manifest contains duplicate instance_id"
            )
        records[instance_id] = record
    return records


def _public_record(
    value: object, line_number: int, policy: ContentPolicy
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DirectQuestionLoadError(
            f"public manifest line {line_number} must be an object"
        )
    _reject_forbidden_fields(value)
    if set(value) != _PUBLIC_RECORD_FIELDS:
        raise DirectQuestionLoadError("public record must use the exact public schema")
    _require_safe(value, policy)
    if value["category"] != "Query":
        raise DirectQuestionLoadError("eligible public records must be Query tasks")
    instance_id = _identifier(value["instance_id"], "instance_id")
    database = _database_name(value["selected_database"])
    query = _nonempty_text(value["query"], "query")
    normal_query = _nonempty_text(value["normal_query"], "normal_query")
    if type(value["high_level"]) is not bool:
        raise DirectQuestionLoadError("high_level must be boolean")
    source_index = value["source_index"]
    if type(source_index) is not int or source_index < 0:
        raise DirectQuestionLoadError("source_index must be a nonnegative integer")
    _string_list(value["preprocess_sql"], "preprocess_sql")
    _string_list(value["clean_up_sqls"], "clean_up_sqls")
    _conditions(value["conditions"])
    return {
        **value,
        "instance_id": instance_id,
        "normal_query": normal_query,
        "query": query,
        "selected_database": database,
    }


def _conditions(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != _CONDITION_FIELDS:
        raise DirectQuestionLoadError("conditions must use the exact public schema")
    decimal = value["decimal"]
    if type(decimal) is not int:
        raise DirectQuestionLoadError("conditions decimal must be an integer")
    if type(value["distinct"]) is not bool or type(value["order"]) is not bool:
        raise DirectQuestionLoadError("conditions flags must be boolean")


def _ids(content: bytes, description: str) -> frozenset[str]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise DirectQuestionLoadError(
            f"{description} ID manifest must be UTF-8"
        ) from error
    if not lines:
        raise DirectQuestionLoadError(f"{description} ID manifest is empty")
    seen: set[str] = set()
    for line_number, value in enumerate(lines, start=1):
        selected = _identifier(value, f"{description} ID at line {line_number}")
        if selected in seen:
            raise DirectQuestionLoadError(
                f"{description} ID manifest contains duplicate ID"
            )
        seen.add(selected)
    return frozenset(seen)


def _json(content: bytes, description: str) -> Any:
    try:
        value = json.loads(
            content.decode("utf-8"),
            parse_constant=lambda constant: _reject_nonfinite(constant),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DirectQuestionLoadError(f"{description} must be valid JSON") from error
    _require_finite(value)
    return value


def _reject_nonfinite(constant: str) -> None:
    raise DirectQuestionLoadError("public content must contain finite JSON")


def _require_finite(value: object) -> None:
    if isinstance(value, Mapping):
        for nested in value.values():
            _require_finite(nested)
    elif isinstance(value, list):
        for nested in value:
            _require_finite(nested)
    elif isinstance(value, float) and not math.isfinite(value):
        raise DirectQuestionLoadError("public content must contain finite JSON")


def _reject_forbidden_fields(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).lower().replace("-", "_") in MANDATORY_FORBIDDEN_FIELDS:
                raise DirectQuestionLoadError(
                    "public content contains a forbidden field"
                )
            _reject_forbidden_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden_fields(nested)


def _require_safe(value: object, policy: ContentPolicy) -> None:
    if policy.sanitize_json(value) != value:
        raise DirectQuestionLoadError("public content contains sensitive content")


def _identifier(value: object, name: str) -> str:
    selected = _nonempty_text(value, name)
    if _INSTANCE_ID.fullmatch(selected) is None:
        raise DirectQuestionLoadError(f"{name} is invalid")
    return selected


def _database_name(value: object) -> str:
    selected = _nonempty_text(value, "selected_database")
    if _DATABASE.fullmatch(selected) is None:
        raise DirectQuestionLoadError("selected_database is invalid")
    return selected


def _nonempty_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DirectQuestionLoadError(f"{name} must be a non-empty string")
    return value


def _string_list(value: object, name: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DirectQuestionLoadError(f"{name} must be an array of strings")


def _canonical(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise DirectQuestionLoadError(
            "public record must contain strict JSON"
        ) from error
