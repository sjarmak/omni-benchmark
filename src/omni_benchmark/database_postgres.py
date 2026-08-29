from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from omni_benchmark.dump_coverage import (
    DumpCoverageError,
    describe_dump_coverage,
)


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PSQL_ENVIRONMENT_KEYS = frozenset(
    {
        "LANG",
        "LC_ALL",
        "PATH",
        "PGAPPNAME",
        "PGCHANNELBINDING",
        "PGCLIENTENCODING",
        "PGCONNECT_TIMEOUT",
        "PGDATABASE",
        "PGHOST",
        "PGHOSTADDR",
        "PGOPTIONS",
        "PGPASSFILE",
        "PGPASSWORD",
        "PGPORT",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGSSLCERT",
        "PGSSLCRL",
        "PGSSLCRLDIR",
        "PGSSLKEY",
        "PGSSLMAXPROTOCOLVERSION",
        "PGSSLMINPROTOCOLVERSION",
        "PGSSLMODE",
        "PGSSLNEGOTIATION",
        "PGSSLROOTCERT",
        "PGSSLSNI",
        "PGTARGETSESSIONATTRS",
        "PGUSER",
        "TZ",
    }
)


class DatabaseOperationError(RuntimeError):
    def __init__(self, message: str, *, sqlstate: str | None = None) -> None:
        super().__init__(message)
        self.sqlstate = sqlstate


def validate_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise DatabaseOperationError(f"unsafe PostgreSQL identifier: {value!r}")
    return value


def _quote_identifier(value: str) -> str:
    return f'"{validate_identifier(value)}"'


def _quote_literal(value: str) -> str:
    if "\x00" in value:
        raise DatabaseOperationError("PostgreSQL literal contains a null byte")
    escaped = value.replace("\\", "\\\\").replace("'", "''")
    return "E'" + escaped + "'"


class PostgresClient:
    def run(
        self,
        database: str,
        *,
        sql: str | None = None,
        file: Path | None = None,
        stdin: bytes | None = None,
        environment: dict[str, str] | None = None,
        stop_on_error: bool = True,
    ) -> bytes:
        validate_identifier(database)
        selected = sum(value is not None for value in (sql, file, stdin))
        if selected != 1:
            raise DatabaseOperationError("provide exactly one of sql, file, or stdin")
        command = [
            "psql",
            "--no-psqlrc",
            f"--set=ON_ERROR_STOP={int(stop_on_error)}",
            "--set=VERBOSITY=verbose",
            "--quiet",
            "--tuples-only",
            "--no-align",
            "--dbname",
            database,
        ]
        if sql is not None:
            command.extend(("--command", sql))
        elif file is not None:
            command.extend(("--file", str(file)))
        process_environment = {
            key: value
            for key, value in os.environ.items()
            if key in PSQL_ENVIRONMENT_KEYS or key.startswith("LC_")
        }
        overrides = environment or {}
        unsupported = set(overrides) - PSQL_ENVIRONMENT_KEYS
        if unsupported:
            raise DatabaseOperationError(
                "unsupported psql environment key(s): " + ", ".join(sorted(unsupported))
            )
        process_environment.update(overrides)
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                input=stdin,
                env=process_environment,
            )
        except FileNotFoundError:
            raise DatabaseOperationError("psql is not installed") from None
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            match = re.search(r"(?:ERROR|FATAL|PANIC):\s+([0-9A-Z]{5}):", stderr)
            detail = (
                "details suppressed because SQL was provided over standard input"
                if stdin is not None
                else stderr
            )
            raise DatabaseOperationError(
                f"PostgreSQL operation failed for database {database}: {detail}",
                sqlstate=match.group(1) if match else None,
            ) from None
        return completed.stdout


def restore_database(
    client: PostgresClient,
    *,
    database: str,
    dump_directory: Path,
    restore_order: tuple[str, ...],
    owner_role: str = "root",
    omitted_tables: tuple[str, ...] = (),
    continue_after_sql_error: bool = False,
) -> None:
    database_identifier = _quote_identifier(database)
    owner_identifier = _quote_identifier(owner_role)
    try:
        dump_root = dump_directory.resolve(strict=True)
    except OSError as error:
        raise DatabaseOperationError(
            f"dump directory does not exist: {dump_directory}"
        ) from error
    omitted = set(omitted_tables)
    if len(omitted) != len(omitted_tables) or not omitted.issubset(restore_order):
        raise DatabaseOperationError("invalid explicitly omitted dump tables")
    for table in (*restore_order, *omitted_tables):
        validate_identifier(table)
    try:
        coverage = describe_dump_coverage(
            database=database,
            dump_root=dump_root,
            restore_order=restore_order,
            omitted_tables=omitted_tables,
        )
    except DumpCoverageError as error:
        raise DatabaseOperationError(str(error)) from error
    contradicted = coverage.contradicted_omissions
    if contradicted:
        raise DatabaseOperationError(
            "explicitly omitted dump file exists: "
            + ", ".join(
                f"{entry.table} -> {entry.path.name}"
                for entry in contradicted
                if entry.path is not None
            )
        )
    if coverage.missing:
        raise DatabaseOperationError(
            "missing ordered dump file(s): "
            + ", ".join(f"{table}.sql" for table in coverage.missing)
        )
    dump_files = list(coverage.load_paths)
    symlinked = tuple(path.name for path in dump_files if path.is_symlink())
    if symlinked:
        raise DatabaseOperationError(
            "dump file must not be a symlink: " + ", ".join(symlinked)
        )
    database_literal = _quote_literal(database)
    client.run(
        "postgres",
        sql=(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = {database_literal} AND pid <> pg_backend_pid();"
        ),
    )
    client.run("postgres", sql=f"DROP DATABASE IF EXISTS {database_identifier};")
    client.run(
        "postgres",
        sql=(
            f"CREATE DATABASE {database_identifier} "
            f"WITH OWNER {owner_identifier} ENCODING 'UTF8' TEMPLATE template0;"
        ),
    )
    for dump_file in dump_files:
        client.run(
            database,
            file=dump_file,
            stop_on_error=not continue_after_sql_error,
        )


def preflight_restore(
    client: PostgresClient, *, postgres_major: int, owner_role: str
) -> None:
    validate_identifier(owner_role)
    version_text = (
        client.run("postgres", sql="SHOW server_version_num;").decode().strip()
    )
    if not version_text.isdigit() or int(version_text) // 10_000 != postgres_major:
        raise DatabaseOperationError(
            f"restore requires PostgreSQL {postgres_major}; "
            f"observed {version_text or 'unknown'}"
        )
    owner_exists = (
        client.run(
            "postgres",
            sql=(
                "SELECT 1 FROM pg_catalog.pg_roles "
                f"WHERE rolname = {_quote_literal(owner_role)};"
            ),
        )
        .decode()
        .strip()
    )
    if owner_exists != "1":
        raise DatabaseOperationError(
            f"required dump owner role {owner_role} does not exist"
        )


def _runtime_password() -> str:
    password = os.environ.get("BENCHMARK_RUNTIME_PASSWORD")
    if not password:
        raise DatabaseOperationError("BENCHMARK_RUNTIME_PASSWORD is required")
    return password


def _ownership_audit_sql(role_literal: str) -> str:
    return (
        "DO $ownership$ BEGIN IF EXISTS ("
        "SELECT 1 FROM pg_catalog.pg_shdepend dependency "
        "WHERE dependency.refclassid = 'pg_catalog.pg_authid'::regclass "
        f"AND dependency.refobjid = (SELECT oid FROM pg_roles WHERE rolname = {role_literal}) "
        "AND dependency.deptype = 'o' "
        "AND dependency.dbid IN ("
        "0, (SELECT oid FROM pg_database WHERE datname = current_database()))) THEN "
        "RAISE EXCEPTION USING ERRCODE = '55000', "
        "MESSAGE = 'runtime role owns target objects'; "
        "END IF; END $ownership$;"
    )


def _cluster_role_sql(
    role_identifier: str,
    role_literal: str,
    password_literal: str,
    database_identifier: str,
) -> str:
    return (
        "DO $provision$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_roles "
        f"WHERE rolname = {role_literal} AND ("
        "rolsuper OR rolcreatedb OR rolcreaterole OR "
        "rolreplication OR rolbypassrls)) THEN "
        "RAISE EXCEPTION USING ERRCODE = '55000', "
        "MESSAGE = 'runtime role has privileged attributes'; "
        "END IF; "
        f"IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {role_literal}) "
        f"THEN CREATE ROLE {role_identifier} LOGIN; END IF; END $provision$;\n"
        f"ALTER ROLE {role_identifier} WITH LOGIN PASSWORD {password_literal} "
        "NOINHERIT;\n"
        f"ALTER ROLE {role_identifier} SET default_transaction_read_only = on;\n"
        f"ALTER ROLE {role_identifier} SET statement_timeout = '60s';\n"
        "DO $databases$ DECLARE target record; BEGIN FOR target IN "
        "SELECT datname FROM pg_catalog.pg_database WHERE datallowconn "
        "LOOP EXECUTE format('REVOKE ALL PRIVILEGES ON DATABASE %I FROM %I', "
        f"target.datname, {role_literal}); "
        "EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', target.datname); "
        "END LOOP; END $databases$;\n"
        f"REVOKE TEMPORARY ON DATABASE {database_identifier} FROM PUBLIC;\n"
        f"GRANT CONNECT ON DATABASE {database_identifier} TO {role_identifier};\n"
        "DO $memberships$ DECLARE membership record; BEGIN "
        "FOR membership IN SELECT granted.rolname AS granted_role "
        "FROM pg_catalog.pg_auth_members member "
        "JOIN pg_catalog.pg_roles granted ON granted.oid = member.roleid "
        "JOIN pg_catalog.pg_roles grantee ON grantee.oid = member.member "
        f"WHERE grantee.rolname = {role_literal} LOOP "
        f"EXECUTE format('REVOKE %I FROM %I', membership.granted_role, {role_literal}); "
        "END LOOP; END $memberships$;\n"
    )


def _database_role_sql(role_literal: str) -> str:
    return (
        "DO $schemas$ DECLARE schema_name text; BEGIN FOR schema_name IN "
        "SELECT nspname FROM pg_catalog.pg_namespace "
        "WHERE nspname NOT IN ('pg_catalog', 'information_schema') "
        "AND nspname !~ '^pg_toast' LOOP "
        "EXECUTE format('REVOKE ALL PRIVILEGES ON SCHEMA %I FROM %I', "
        f"schema_name, {role_literal}); "
        "EXECUTE format('REVOKE CREATE ON SCHEMA %I FROM PUBLIC', schema_name); "
        "EXECUTE format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM %I', "
        f"schema_name, {role_literal}); "
        "EXECUTE format('REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM PUBLIC', "
        "schema_name); "
        "EXECUTE format('REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %I FROM %I', "
        f"schema_name, {role_literal}); "
        "EXECUTE format('REVOKE USAGE, UPDATE ON ALL SEQUENCES IN SCHEMA %I FROM PUBLIC', "
        "schema_name); "
        "EXECUTE format('REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA %I FROM PUBLIC, %I', "
        f"schema_name, {role_literal}); "
        f"EXECUTE format('GRANT USAGE ON SCHEMA %I TO %I', schema_name, {role_literal}); "
        f"EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO %I', schema_name, {role_literal}); "
        f"EXECUTE format('GRANT SELECT ON ALL SEQUENCES IN SCHEMA %I TO %I', schema_name, {role_literal}); "
        "EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON TABLES FROM PUBLIC', schema_name); "
        "EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE ALL ON SEQUENCES FROM PUBLIC', schema_name); "
        "EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC', schema_name); "
        f"EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON TABLES TO %I', schema_name, {role_literal}); "
        f"EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT ON SEQUENCES TO %I', schema_name, {role_literal}); "
        "END LOOP; END $schemas$;\n"
        "DO $columns$ DECLARE column_grant record; BEGIN FOR column_grant IN "
        "SELECT schema.nspname AS schema_name, object.relname AS table_name, "
        "attribute.attname AS column_name, privilege.privilege_type, "
        "privilege.grantee FROM pg_catalog.pg_attribute attribute "
        "JOIN pg_catalog.pg_class object ON object.oid = attribute.attrelid "
        "JOIN pg_catalog.pg_namespace schema ON schema.oid = object.relnamespace "
        "CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) privilege "
        "WHERE attribute.attnum > 0 AND NOT attribute.attisdropped "
        "AND object.relkind IN ('r', 'p', 'v', 'm', 'f') "
        "AND schema.nspname NOT IN ('pg_catalog', 'information_schema') "
        "AND schema.nspname !~ '^pg_toast' "
        f"AND privilege.grantee IN (0, (SELECT oid FROM pg_roles WHERE rolname = {role_literal})) "
        "LOOP IF column_grant.grantee = 0 THEN "
        "EXECUTE format('REVOKE %s (%I) ON TABLE %I.%I FROM PUBLIC', "
        "column_grant.privilege_type, column_grant.column_name, "
        "column_grant.schema_name, column_grant.table_name); ELSE "
        "EXECUTE format('REVOKE %s (%I) ON TABLE %I.%I FROM %I', "
        "column_grant.privilege_type, column_grant.column_name, "
        "column_grant.schema_name, column_grant.table_name, "
        f"{role_literal}); END IF; END LOOP; END $columns$;\n"
    )


def _effective_nonread_privilege_sql() -> str:
    user_schema = (
        "schema.nspname NOT IN ('pg_catalog', 'information_schema') "
        "AND schema.nspname !~ '^pg_toast'"
    )
    return (
        "SELECT 1 FROM pg_catalog.pg_class object "
        "JOIN pg_catalog.pg_namespace schema ON schema.oid = object.relnamespace "
        f"WHERE {user_schema} AND object.relkind IN ('r', 'p', 'v', 'm', 'f') AND ("
        "has_table_privilege(current_user, object.oid, 'INSERT') OR "
        "has_table_privilege(current_user, object.oid, 'UPDATE') OR "
        "has_table_privilege(current_user, object.oid, 'DELETE') OR "
        "has_table_privilege(current_user, object.oid, 'TRUNCATE') OR "
        "has_table_privilege(current_user, object.oid, 'REFERENCES') OR "
        "has_table_privilege(current_user, object.oid, 'TRIGGER') OR "
        "has_table_privilege(current_user, object.oid, 'MAINTAIN')) UNION ALL "
        "SELECT 1 FROM pg_catalog.pg_attribute attribute "
        "JOIN pg_catalog.pg_class object ON object.oid = attribute.attrelid "
        "JOIN pg_catalog.pg_namespace schema ON schema.oid = object.relnamespace "
        f"WHERE {user_schema} AND attribute.attnum > 0 AND NOT attribute.attisdropped AND ("
        "has_column_privilege(current_user, object.oid, attribute.attnum, 'INSERT') OR "
        "has_column_privilege(current_user, object.oid, attribute.attnum, 'UPDATE') OR "
        "has_column_privilege(current_user, object.oid, attribute.attnum, 'REFERENCES')) UNION ALL "
        "SELECT 1 FROM pg_catalog.pg_class object "
        "JOIN pg_catalog.pg_namespace schema ON schema.oid = object.relnamespace "
        f"WHERE {user_schema} AND object.relkind = 'S' AND ("
        "has_sequence_privilege(current_user, object.oid, 'UPDATE') OR "
        "has_sequence_privilege(current_user, object.oid, 'USAGE')) UNION ALL "
        "SELECT 1 FROM pg_catalog.pg_proc object "
        "JOIN pg_catalog.pg_namespace schema ON schema.oid = object.pronamespace "
        f"WHERE {user_schema} AND "
        "has_function_privilege(current_user, object.oid, 'EXECUTE') LIMIT 1;"
    )


def provision_readonly_role(
    client: PostgresClient, *, database: str, role: str
) -> None:
    password = _runtime_password()
    role_identifier = _quote_identifier(role)
    role_literal = _quote_literal(role)
    password_literal = _quote_literal(password)
    database_identifier = _quote_identifier(database)
    client.run(database, sql=_ownership_audit_sql(role_literal))
    client.run(
        "postgres",
        stdin=_cluster_role_sql(
            role_identifier, role_literal, password_literal, database_identifier
        ).encode("utf-8"),
    )
    client.run(database, stdin=_database_role_sql(role_literal).encode("utf-8"))


def verify_readonly_role(client: PostgresClient, *, database: str, role: str) -> None:
    password = _runtime_password()
    validate_identifier(role)
    environment = {"PGPASSWORD": password, "PGUSER": role}
    setting = (
        client.run(
            database,
            sql="SHOW default_transaction_read_only;",
            environment=environment,
        )
        .decode("utf-8", errors="replace")
        .strip()
    )
    if setting != "on":
        raise DatabaseOperationError("runtime role is not transaction-read-only")
    table_line = (
        client.run(
            database,
            sql=(
                "SELECT schemaname || E'\\t' || tablename "
                "FROM pg_catalog.pg_tables "
                "WHERE schemaname NOT IN ('pg_catalog', 'information_schema') "
                "AND schemaname !~ '^pg_toast' "
                'ORDER BY schemaname COLLATE "C", tablename COLLATE "C" LIMIT 1;'
            ),
            environment=environment,
        )
        .decode()
        .strip()
    )
    if "\t" not in table_line:
        raise DatabaseOperationError("runtime role cannot see a public table")
    schema, table = table_line.split("\t", maxsplit=1)
    schema_identifier = _quote_identifier(schema)
    qualified = f"{schema_identifier}.{_quote_identifier(table)}"
    client.run(
        database,
        sql=f"SELECT 1 FROM {qualified} LIMIT 1;",
        environment=environment,
    )
    forbidden_privilege = (
        client.run(
            database,
            sql=_effective_nonread_privilege_sql(),
            environment=environment,
        )
        .decode("utf-8", errors="replace")
        .strip()
    )
    if forbidden_privilege:
        raise DatabaseOperationError("runtime role retains a non-read privilege")
    probes = (
        "BEGIN; SET LOCAL transaction_read_only=off; "
        f"CREATE TABLE {schema_identifier}.__omni_benchmark_write_probe "
        "(id integer); ROLLBACK;",
        "BEGIN; SET LOCAL transaction_read_only=off; "
        "CREATE TEMP TABLE __omni_benchmark_temp_probe (id integer); ROLLBACK;",
        "BEGIN; SET LOCAL transaction_read_only=off; "
        f"TRUNCATE TABLE {qualified}; ROLLBACK;",
    )
    for probe in probes:
        try:
            client.run(database, sql=probe, environment=environment)
        except DatabaseOperationError as error:
            if error.sqlstate in {"25006", "42501"}:
                continue
            raise
        raise DatabaseOperationError("runtime role accepted a write")
