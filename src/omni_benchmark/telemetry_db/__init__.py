"""Benchmark telemetry database: schema, custody gates, and row writes."""

from .arms import ArmMapping, read_arms
from .custody import (
    FORBIDDEN_FIELDS,
    CustodyViolation,
    SplitIds,
    assert_dev_a_instance,
    assert_not_test_instance,
    load_split_ids,
    load_test_ids,
    reject_forbidden_fields,
)
from .generation_rows import ReaderError
from .loader import LoaderError, LoadPlan, LoadResult, Sources, collect, load_all
from .readers import (
    QuestionRelease,
    ReleasedQuestion,
    read_deployments,
    read_dev_a,
    read_labels,
    read_questions,
    read_sealed,
)
from .rows import Row, RowError, adapt_parameters, build_upsert_statement, upsert_rows
from .sources import SourceBatch
from .schema import (
    SCHEMA_NAME,
    SCHEMA_PATH,
    TABLE_COLUMNS,
    TABLE_PRIMARY_KEYS,
    TABLE_SPECS,
    SchemaError,
    TableSpec,
    apply_schema,
    load_schema_sql,
    parse_table_specs,
)

__all__ = [
    "FORBIDDEN_FIELDS",
    "SCHEMA_NAME",
    "SCHEMA_PATH",
    "TABLE_COLUMNS",
    "TABLE_PRIMARY_KEYS",
    "TABLE_SPECS",
    "ArmMapping",
    "CustodyViolation",
    "LoadPlan",
    "LoadResult",
    "LoaderError",
    "QuestionRelease",
    "ReaderError",
    "ReleasedQuestion",
    "Sources",
    "Row",
    "RowError",
    "SchemaError",
    "SourceBatch",
    "SplitIds",
    "TableSpec",
    "adapt_parameters",
    "apply_schema",
    "assert_dev_a_instance",
    "assert_not_test_instance",
    "build_upsert_statement",
    "collect",
    "load_all",
    "load_schema_sql",
    "load_split_ids",
    "load_test_ids",
    "parse_table_specs",
    "read_arms",
    "read_deployments",
    "read_dev_a",
    "read_labels",
    "read_questions",
    "read_sealed",
    "reject_forbidden_fields",
    "upsert_rows",
]
