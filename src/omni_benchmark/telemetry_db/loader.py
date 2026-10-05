"""Idempotent load of every public telemetry source into one database.

``collect`` reads all sources into a :class:`LoadPlan` without a connection;
``load_all`` applies the schema and upserts the plan inside one transaction,
recording the load in ``load_run``. Loading the same tree twice leaves every
row as it was, so a reload after a new run or a new label pass is safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .custody import (
    CustodyViolation,
    SplitIds,
    assert_dev_a_instance,
    load_split_ids,
    reject_forbidden_fields,
)
from .generation_rows import optional_instance_of_attempt_id
from .readers import (
    SourceBatch,
    read_arms,
    read_credits,
    read_deployments,
    read_dev_a,
    read_labels,
    read_questions,
    read_sealed,
)
from .rows import Row, upsert_rows
from .schema import apply_schema
from .sealed_readers import SEALED_RUN_ID
from .sources import file_sha256, relative_to

LOADER_VERSION = "telemetry-db-loader-v1"
TABLE_LOAD_ORDER = (
    "question",
    "deployment",
    "run",
    "attempt",
    "score",
    "trace_event",
    "action_evidence",
    "sealed_aggregate",
    "attempt_label",
    "credit_period",
    "arm_cost",
)


class LoaderError(ValueError):
    """Raised when sources cannot be combined into one consistent load."""


@dataclass(frozen=True)
class Sources:
    """Where each public source lives, relative to one repository root."""

    repo_root: Path
    include_dev_a: bool = True
    include_sealed: bool = True
    sealed_name: str = SEALED_RUN_ID

    @property
    def manifests_dir(self) -> Path:
        return self.repo_root / "data" / "manifests"

    @property
    def arms_path(self) -> Path:
        return self.repo_root / "config" / "telemetry_db" / "arms.json"

    @property
    def raw_dir(self) -> Path:
        return self.repo_root / "experiments" / "autoresearch" / "raw"

    @property
    def deployments_dir(self) -> Path:
        return self.repo_root / "experiments" / "deployments"

    @property
    def labels_dir(self) -> Path:
        return self.repo_root / "experiments" / "labels"

    @property
    def analysis_dir(self) -> Path:
        return self.repo_root / "experiments" / "analysis"

    @property
    def credit_scopes_path(self) -> Path:
        return self.repo_root / "config" / "telemetry_db" / "credit_scopes.json"

    @property
    def sealed_dir(self) -> Path:
        return self.repo_root / "runs" / "preserved" / self.sealed_name


@dataclass(frozen=True)
class LoadPlan:
    """Everything a load would write, plus what the readers set aside."""

    rows: Mapping[str, tuple[Row, ...]]
    dropped: Mapping[str, Mapping[str, int]]
    manifests: Mapping[str, str]
    notes: Mapping[str, Mapping[str, Any]]
    custody: Mapping[str, Any]

    @property
    def row_counts(self) -> dict[str, int]:
        return {table: len(self.rows.get(table, ())) for table in TABLE_LOAD_ORDER}


@dataclass(frozen=True)
class LoadResult:
    load_id: str
    row_counts: Mapping[str, int]
    plan: LoadPlan


def collect(sources: Sources) -> LoadPlan:
    """Read every enabled source and merge the rows, without a database."""
    split = load_split_ids(sources.manifests_dir)
    batches = _read_batches(sources, split)
    rows, collapsed = _merge_rows(batches)
    manifests = {
        relative_to(sources.arms_path, sources.repo_root): file_sha256(
            sources.arms_path
        )
    }
    for batch in batches:
        manifests.update(batch.manifests)
    custody = dict(
        _guard_custody(rows, split),
        duplicate_rows_collapsed=collapsed,
        attempts_outside_dev_a_dropped=sum(
            b.dropped.get("attempt_instance_not_dev_a", 0) for b in batches
        ),
    )
    return LoadPlan(
        rows=MappingProxyType(rows),
        dropped=MappingProxyType({b.source: b.dropped for b in batches if b.dropped}),
        manifests=MappingProxyType(dict(sorted(manifests.items()))),
        notes=MappingProxyType({b.source: b.notes for b in batches if b.notes}),
        custody=MappingProxyType(custody),
    )


def _read_batches(sources: Sources, split: SplitIds) -> list[SourceBatch]:
    """Every enabled source in load order; labels last so they can be joined."""
    release = read_questions(sources.manifests_dir, repo_root=sources.repo_root)
    batches = [
        release.batch,
        read_deployments(sources.deployments_dir, repo_root=sources.repo_root),
        read_credits(
            sources.analysis_dir,
            repo_root=sources.repo_root,
            scopes_path=sources.credit_scopes_path,
        ),
    ]
    if sources.include_dev_a:
        batches.append(
            read_dev_a(
                sources.raw_dir,
                repo_root=sources.repo_root,
                arms=read_arms(sources.arms_path),
                split=split,
                questions=release.questions,
            )
        )
    if sources.include_sealed:
        batches.append(
            read_sealed(
                sources.sealed_dir,
                repo_root=sources.repo_root,
                questions=release.questions,
            )
        )
    labels = read_labels(
        sources.labels_dir,
        repo_root=sources.repo_root,
        split=split,
        attempt_keys=_attempt_keys(batches),
    )
    return [*batches, labels]


def _attempt_keys(batches: list[SourceBatch]) -> frozenset[tuple[str, str]]:
    return _attempt_keys_of(
        tuple(row for batch in batches for row in batch.rows.get("attempt", ()))
    )


def _merge_rows(batches: list[SourceBatch]) -> tuple[dict[str, tuple[Row, ...]], int]:
    """Union of all batches keyed by primary key; identical duplicates collapse."""
    merged: dict[str, dict[tuple[Any, ...], Row]] = {
        table: {} for table in TABLE_LOAD_ORDER
    }
    collapsed = 0
    for batch in batches:
        for table, rows in batch.rows.items():
            if table not in merged:
                raise LoaderError(f"{batch.source}: table {table!r} is not loadable")
            for row in rows:
                key = tuple(row.values[column] for column in row.spec.primary_key)
                previous = merged[table].get(key)
                if previous is None:
                    merged[table][key] = row
                elif previous.to_tuple() == row.to_tuple():
                    collapsed += 1
                else:
                    raise LoaderError(
                        f"{batch.source}: {table} row {key} conflicts with an earlier source"
                    )
    return {table: tuple(rows.values()) for table, rows in merged.items()}, collapsed


def _guard_custody(
    rows: Mapping[str, tuple[Row, ...]], split: SplitIds
) -> dict[str, Any]:
    scanned = 0
    for table, table_rows in rows.items():
        for row in table_rows:
            key = tuple(row.values[column] for column in row.spec.primary_key)
            reject_forbidden_fields(dict(row.values), f"{table} row {key}")
            scanned += 1
    attempt_instances = _attempt_instances(rows.get("attempt", ()))
    for table in ("score", "attempt_label"):
        for row in rows.get(table, ()):
            attempt_id = str(row.values["attempt_id"])
            context = f"{table} row {attempt_id}"
            embedded = optional_instance_of_attempt_id(attempt_id, context)
            if embedded is not None:
                assert_dev_a_instance(embedded, split, context)
            key = (row.values["attempt_id"], row.values["generation_record_sha256"])
            instance = attempt_instances.get(key)
            if instance is None:
                raise LoaderError(f"{table} row {key} names no loaded attempt")
            assert_dev_a_instance(instance, split, context)
    for row in rows.get("attempt", ()):
        instance = str(row.values["instance_id"])
        if instance not in split.dev_a and instance not in split.test:
            raise CustodyViolation(
                f"attempt row {row.values['attempt_id']}: instance {instance!r} "
                "is in neither the dev-A nor the sealed test split"
            )
    return {
        "rows_scanned_for_forbidden_fields": scanned,
        "score_rows_checked_against_split": len(rows.get("score", ())),
        "label_rows_checked_against_split": len(rows.get("attempt_label", ())),
        "attempt_rows_checked_against_split": len(rows.get("attempt", ())),
        "dev_a_id_count": len(split.dev_a),
        "test_id_count": len(split.test),
    }


def _attempt_keys_of(rows: tuple[Row, ...]) -> frozenset[tuple[str, str]]:
    return frozenset(_attempt_instances(rows))


def _attempt_instances(rows: tuple[Row, ...]) -> dict[tuple[Any, Any], str]:
    return {
        (row.values["attempt_id"], row.values["generation_record_sha256"]): str(
            row.values["instance_id"]
        )
        for row in rows
    }


def load_all(
    sources: Sources, conn: Any, load_id: str, system_commit: str | None
) -> LoadResult:
    """Apply the schema and upsert every source in one transaction.

    ``system_commit`` is None only when the caller loaded from a tree that did
    not match any commit; ``load_run.row_counts`` records that as unverified.
    """
    if not load_id:
        raise LoaderError("load_id must be a non-empty string")
    plan = collect(sources)
    started_at = datetime.now(timezone.utc)
    try:
        apply_schema(conn)
        counts = {
            table: upsert_rows(conn, table, plan.rows.get(table, ()))
            for table in TABLE_LOAD_ORDER
        }
        upsert_rows(
            conn,
            "load_run",
            (_load_run_row(load_id, started_at, plan, counts, system_commit),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return LoadResult(load_id=load_id, row_counts=MappingProxyType(counts), plan=plan)


def _load_run_row(
    load_id: str,
    started_at: datetime,
    plan: LoadPlan,
    counts: Mapping[str, int],
    system_commit: str | None,
) -> Row:
    return Row(
        "load_run",
        {
            "load_id": load_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
            "source_manifests": dict(plan.manifests),
            "row_counts": {
                "tables": dict(counts),
                "dropped": {
                    source: dict(reasons) for source, reasons in plan.dropped.items()
                },
                "custody": dict(plan.custody),
                "system_commit_verified": system_commit is not None,
            },
            "loader_version": LOADER_VERSION,
            "system_commit": system_commit,
        },
    )
