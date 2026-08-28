from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


DATABASE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXTERNAL_ID = re.compile(r"^[A-Za-z0-9-]+$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
RESTORE_ORDER = re.compile(
    r'^\s*\["(?P<database>[A-Za-z_][A-Za-z0-9_]*)_template"\]="(?P<tables>[^"]+)"\s*$'
)
TOP_LEVEL_KEYS = frozenset(
    {
        "format_version",
        "benchmark",
        "canary",
        "postgres_major",
        "sources",
        "canary_verification",
        "databases",
    }
)
SOURCE_KEYS = frozenset(
    {
        "dataset_revision",
        "public_dump_archive_sha256",
        "public_dump_archive_size_bytes",
        "public_dump_url",
        "repository_commit",
        "restore_order_sha256",
        "restore_script",
        "restore_script_sha256",
    }
)
CANARY_VERIFICATION_KEYS = frozenset(
    {
        "database",
        "postgres_server_version_num",
        "postgres_image",
        "extensions",
        "table_count",
        "row_count",
        "schema_sha256",
        "content_sha256",
        "repeat_restore_parity",
        "readonly_role_verified",
        "managed_mirror",
        "external_mirror_parity",
    }
)
DATABASE_RECORD_KEYS = frozenset(
    {
        "name",
        "alias",
        "dump_file_count",
        "dump_size_bytes",
        "dump_sha256",
        "scorer_omitted_tables",
        "scorer_continues_after_sql_error",
        "managed_mirror",
        "verification",
        "omni_connection",
    }
)
MANAGED_MIRROR_KEYS = frozenset(
    {
        "provider",
        "organization_id",
        "project_id",
        "branch_id",
        "branch_name",
        "region_id",
        "runtime_role",
    }
)
VERIFICATION_KEYS = frozenset(
    {
        "postgres_server_version_num",
        "table_count",
        "row_count",
        "schema_sha256",
        "content_sha256",
        "readonly_role_verified",
        "external_parity",
    }
)
OMNI_CONNECTION_KEYS = frozenset({"id", "name"})


class InventoryError(ValueError):
    pass


@dataclass(frozen=True)
class ManagedMirror:
    provider: str
    organization_id: str
    project_id: str
    branch_id: str
    branch_name: str
    region_id: str
    runtime_role: str


@dataclass(frozen=True)
class DatabaseVerification:
    postgres_server_version_num: str
    table_count: int
    row_count: int
    schema_sha256: str
    content_sha256: str
    readonly_role_verified: bool
    external_parity: bool


@dataclass(frozen=True)
class OmniConnection:
    id: str
    name: str


@dataclass(frozen=True)
class DatabaseRecord:
    name: str
    alias: str
    dump_file_count: int
    dump_size_bytes: int
    dump_sha256: str
    scorer_omitted_tables: tuple[str, ...]
    scorer_continues_after_sql_error: bool
    managed_mirror: ManagedMirror | None
    verification: DatabaseVerification | None
    omni_connection: OmniConnection | None


@dataclass(frozen=True)
class DatabaseInventory:
    benchmark: str
    canary: str
    postgres_major: int
    databases: tuple[DatabaseRecord, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class DumpFileFingerprint:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class DumpFingerprint:
    sha256: str
    size_bytes: int
    files: tuple[DumpFileFingerprint, ...]


def _reject_connection_urls(value: Any) -> None:
    if isinstance(value, str):
        if re.search(
            r"\b(?:postgres(?:ql)?|neon|mysql)://", value, flags=re.IGNORECASE
        ):
            raise InventoryError("inventory must not contain a connection URL")
        if re.search(r"\b[a-z0-9.-]+\.neon\.tech\b", value, flags=re.IGNORECASE):
            raise InventoryError(
                "inventory must not contain a managed database endpoint"
            )
        if re.search(r"\bep-[a-z0-9-]+\b", value, flags=re.IGNORECASE):
            raise InventoryError(
                "inventory must not contain a managed database endpoint"
            )
        if re.match(r"^https?://", value, flags=re.IGNORECASE):
            try:
                parsed = urlsplit(value)
            except ValueError as error:
                raise InventoryError(
                    "inventory contains an invalid HTTP(S) URL"
                ) from error
            if parsed.username is not None or parsed.password is not None:
                raise InventoryError(
                    "inventory URL must not contain embedded credentials"
                )
    if isinstance(value, dict):
        for item in value.values():
            _reject_connection_urls(item)
    elif isinstance(value, list):
        for item in value:
            _reject_connection_urls(item)


def _required_object(record: dict[str, Any], key: str, database: str) -> dict[str, Any]:
    value = record.get(key)
    if not isinstance(value, dict):
        raise InventoryError(f"invalid {key} for {database}")
    return value


def _reject_unexpected_keys(
    value: dict[str, Any], allowed: frozenset[str], context: str
) -> None:
    unexpected = sorted(set(value) - allowed)
    if unexpected:
        raise InventoryError(f"unexpected {context} keys: {', '.join(unexpected)}")


def _required_string(
    record: dict[str, Any], key: str, database: str, pattern: re.Pattern[str]
) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise InventoryError(f"invalid {key} for {database}")
    return value


def _parse_managed_mirror(record: dict[str, Any], database: str) -> ManagedMirror:
    mirror = _required_object(record, "managed_mirror", database)
    _reject_unexpected_keys(mirror, MANAGED_MIRROR_KEYS, "managed_mirror")
    provider = mirror.get("provider")
    if provider != "neon":
        raise InventoryError(f"invalid managed mirror provider for {database}")
    return ManagedMirror(
        provider=provider,
        organization_id=_required_string(
            mirror, "organization_id", database, EXTERNAL_ID
        ),
        project_id=_required_string(mirror, "project_id", database, EXTERNAL_ID),
        branch_id=_required_string(mirror, "branch_id", database, EXTERNAL_ID),
        branch_name=_required_string(mirror, "branch_name", database, EXTERNAL_ID),
        region_id=_required_string(mirror, "region_id", database, EXTERNAL_ID),
        runtime_role=_required_string(mirror, "runtime_role", database, DATABASE_NAME),
    )


def _parse_verification(record: dict[str, Any], database: str) -> DatabaseVerification:
    verification = _required_object(record, "verification", database)
    _reject_unexpected_keys(verification, VERIFICATION_KEYS, "verification")
    version = verification.get("postgres_server_version_num")
    table_count = verification.get("table_count")
    row_count = verification.get("row_count")
    readonly = verification.get("readonly_role_verified")
    parity = verification.get("external_parity")
    if not isinstance(version, str) or not version.isdigit():
        raise InventoryError(f"invalid PostgreSQL version for {database}")
    if not isinstance(table_count, int) or table_count < 1:
        raise InventoryError(f"invalid verified table count for {database}")
    if not isinstance(row_count, int) or row_count < 0:
        raise InventoryError(f"invalid verified row count for {database}")
    if not isinstance(readonly, bool) or not isinstance(parity, bool):
        raise InventoryError(f"invalid verification gates for {database}")
    return DatabaseVerification(
        postgres_server_version_num=version,
        table_count=table_count,
        row_count=row_count,
        schema_sha256=_required_string(verification, "schema_sha256", database, SHA256),
        content_sha256=_required_string(
            verification, "content_sha256", database, SHA256
        ),
        readonly_role_verified=readonly,
        external_parity=parity,
    )


def _parse_omni_connection(record: dict[str, Any], database: str) -> OmniConnection:
    connection = _required_object(record, "omni_connection", database)
    _reject_unexpected_keys(connection, OMNI_CONNECTION_KEYS, "omni_connection")
    name = connection.get("name")
    if name != f"LiveSQLBench {database}":
        raise InventoryError(f"invalid Omni connection name for {database}")
    return OmniConnection(
        id=_required_string(connection, "id", database, UUID),
        name=name,
    )


def load_database_inventory(path: Path) -> DatabaseInventory:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InventoryError(f"cannot read database inventory: {path}") from error
    if not isinstance(raw, dict):
        raise InventoryError("database inventory must be a JSON object")
    _reject_connection_urls(raw)
    _reject_unexpected_keys(raw, TOP_LEVEL_KEYS, "top-level")
    format_version = raw.get("format_version")
    if format_version not in {1, 2}:
        raise InventoryError("format_version must be 1 or 2")
    sources = raw.get("sources")
    if sources is not None:
        if not isinstance(sources, dict):
            raise InventoryError("invalid sources for inventory")
        _reject_unexpected_keys(sources, SOURCE_KEYS, "sources")
    elif format_version == 2:
        raise InventoryError("format_version 2 requires sources")
    canary_verification = raw.get("canary_verification")
    if canary_verification is not None:
        if not isinstance(canary_verification, dict):
            raise InventoryError("invalid canary_verification for inventory")
        _reject_unexpected_keys(
            canary_verification, CANARY_VERIFICATION_KEYS, "canary_verification"
        )
        canary_mirror = canary_verification.get("managed_mirror")
        if canary_mirror is not None:
            if not isinstance(canary_mirror, dict):
                raise InventoryError("invalid managed_mirror for canary_verification")
            _reject_unexpected_keys(
                canary_mirror, MANAGED_MIRROR_KEYS, "managed_mirror"
            )
    elif format_version == 2:
        raise InventoryError("format_version 2 requires canary_verification")

    records = raw.get("databases")
    if not isinstance(records, list) or not records:
        raise InventoryError("database inventory must contain databases")
    databases: list[DatabaseRecord] = []
    for record in records:
        if not isinstance(record, dict):
            raise InventoryError("each database record must be an object")
        _reject_unexpected_keys(record, DATABASE_RECORD_KEYS, "database record")
        name = record.get("name")
        alias = record.get("alias")
        dump_file_count = record.get("dump_file_count")
        dump_size_bytes = record.get("dump_size_bytes")
        dump_sha256 = record.get("dump_sha256")
        scorer_omitted_tables = record.get("scorer_omitted_tables", [])
        scorer_continues_after_sql_error = record.get(
            "scorer_continues_after_sql_error", False
        )
        if not isinstance(name, str) or not DATABASE_NAME.fullmatch(name):
            raise InventoryError(f"invalid database name: {name!r}")
        if not isinstance(alias, str) or not DATABASE_NAME.fullmatch(alias):
            raise InventoryError(f"invalid database alias for {name}")
        if not isinstance(dump_file_count, int) or dump_file_count < 1:
            raise InventoryError(f"invalid dump file count for {name}")
        if not isinstance(dump_size_bytes, int) or dump_size_bytes < 1:
            raise InventoryError(f"invalid dump size for {name}")
        if not isinstance(dump_sha256, str) or not SHA256.fullmatch(dump_sha256):
            raise InventoryError(f"invalid dump SHA-256 for {name}")
        if (
            not isinstance(scorer_omitted_tables, list)
            or any(
                not isinstance(table, str) or not DATABASE_NAME.fullmatch(table)
                for table in scorer_omitted_tables
            )
            or len(scorer_omitted_tables) != len(set(scorer_omitted_tables))
        ):
            raise InventoryError(f"invalid scorer omissions for {name}")
        if not isinstance(scorer_continues_after_sql_error, bool):
            raise InventoryError(f"invalid scorer SQL error mode for {name}")
        databases.append(
            DatabaseRecord(
                name=name,
                alias=alias,
                dump_file_count=dump_file_count,
                dump_size_bytes=dump_size_bytes,
                dump_sha256=dump_sha256,
                scorer_omitted_tables=tuple(scorer_omitted_tables),
                scorer_continues_after_sql_error=scorer_continues_after_sql_error,
                managed_mirror=(
                    _parse_managed_mirror(record, name)
                    if "managed_mirror" in record
                    else None
                ),
                verification=(
                    _parse_verification(record, name)
                    if "verification" in record
                    else None
                ),
                omni_connection=(
                    _parse_omni_connection(record, name)
                    if "omni_connection" in record
                    else None
                ),
            )
        )

    names = [database.name for database in databases]
    aliases = [database.alias for database in databases]
    if len(names) != len(set(names)) or len(aliases) != len(set(aliases)):
        raise InventoryError("database names and aliases must be unique")
    for database in databases:
        metadata = (
            database.managed_mirror,
            database.verification,
            database.omni_connection,
        )
        if any(item is not None for item in metadata) and any(
            item is None for item in metadata
        ):
            raise InventoryError(
                f"external metadata must be complete for {database.name}"
            )
        if database.omni_connection is not None and (
            not database.verification.external_parity
            or not database.verification.readonly_role_verified
        ):
            raise InventoryError(
                f"Omni connection requires passed verification gates for {database.name}"
            )
    if format_version == 2 and any(
        database.managed_mirror is None for database in databases
    ):
        raise InventoryError("format_version 2 requires complete external metadata")
    external_ids = [
        identifier
        for database in databases
        if database.managed_mirror is not None
        for identifier in (
            database.managed_mirror.project_id,
            database.managed_mirror.branch_id,
            database.omni_connection.id,
        )
    ]
    if len(external_ids) != len(set(external_ids)):
        raise InventoryError("external IDs must be unique")
    canary = raw.get("canary")
    if canary not in names:
        raise InventoryError("canary must name an inventoried database")
    postgres_major = raw.get("postgres_major")
    if not isinstance(postgres_major, int) or postgres_major < 1:
        raise InventoryError("postgres_major must be a positive integer")
    benchmark = raw.get("benchmark")
    if not isinstance(benchmark, str) or not benchmark:
        raise InventoryError("benchmark must be a non-empty string")
    return DatabaseInventory(
        benchmark=benchmark,
        canary=canary,
        postgres_major=postgres_major,
        databases=tuple(databases),
        raw=raw,
    )


def fingerprint_dump_directory(path: Path) -> DumpFingerprint:
    if not path.is_dir():
        raise InventoryError(f"dump directory does not exist: {path}")
    sql_files = sorted(item for item in path.rglob("*.sql") if item.is_file())
    if not sql_files:
        raise InventoryError(f"dump directory contains no SQL files: {path}")

    files: list[DumpFileFingerprint] = []
    for sql_file in sql_files:
        content = sql_file.read_bytes()
        files.append(
            DumpFileFingerprint(
                path=sql_file.relative_to(path).as_posix(),
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    digest_input = json.dumps(
        [file.__dict__ for file in files],
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return DumpFingerprint(
        sha256=hashlib.sha256(digest_input).hexdigest(),
        size_bytes=sum(file.size_bytes for file in files),
        files=tuple(files),
    )


def verify_database_dump(database: DatabaseRecord, path: Path) -> DumpFingerprint:
    fingerprint = fingerprint_dump_directory(path)
    observed = (
        len(fingerprint.files),
        fingerprint.size_bytes,
        fingerprint.sha256,
    )
    expected = (
        database.dump_file_count,
        database.dump_size_bytes,
        database.dump_sha256,
    )
    if observed != expected:
        raise InventoryError(
            f"dump for {database.name} does not match pinned inventory"
        )
    return fingerprint


def verify_restore_order(
    inventory: DatabaseInventory, path: Path
) -> dict[str, tuple[str, ...]]:
    try:
        content = path.read_bytes()
        value = json.loads(content)
    except (OSError, json.JSONDecodeError) as error:
        raise InventoryError(f"cannot read restore order: {path}") from error
    sources = inventory.raw.get("sources")
    expected_sha256 = (
        sources.get("restore_order_sha256") if isinstance(sources, dict) else None
    )
    if not isinstance(expected_sha256, str) or not SHA256.fullmatch(expected_sha256):
        raise InventoryError("inventory has no valid restore-order SHA-256")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise InventoryError("restore-order SHA-256 does not match inventory")
    if not isinstance(value, dict):
        raise InventoryError("restore order must be a JSON object")
    expected_databases = {database.name for database in inventory.databases}
    if set(value) != expected_databases:
        raise InventoryError("restore-order databases do not match inventory")
    result: dict[str, tuple[str, ...]] = {}
    records = {database.name: database for database in inventory.databases}
    for database, tables in value.items():
        if not isinstance(tables, list) or not tables:
            raise InventoryError(f"invalid restore order for {database}")
        if any(
            not isinstance(table, str) or not DATABASE_NAME.fullmatch(table)
            for table in tables
        ):
            raise InventoryError(f"invalid restore table for {database}")
        if len(tables) != len(set(tables)):
            raise InventoryError(f"duplicate restore table for {database}")
        omissions = records[database].scorer_omitted_tables
        if not set(omissions).issubset(tables):
            raise InventoryError(
                f"scorer omissions are not in restore order for {database}"
            )
        result[database] = tuple(tables)
    return result


def parse_restore_order(source: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for line in source.splitlines():
        match = RESTORE_ORDER.fullmatch(line)
        if match is None:
            continue
        database = match.group("database")
        if database in result:
            raise InventoryError(f"duplicate restore order for {database}")
        tables = tuple(match.group("tables").split())
        if not tables or any(not DATABASE_NAME.fullmatch(table) for table in tables):
            raise InventoryError(f"invalid restore order for {database}")
        result[database] = tables
    if not result:
        raise InventoryError("source contains no database restore orders")
    return result
