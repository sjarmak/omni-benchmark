"""Psycopg connector for disposable PostgreSQL template clones."""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import psycopg
from psycopg import ClientCursor, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

POSTGRES_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}")
READ_ONLY_CONNECTION_OPTION = "-c default_transaction_read_only=on"
EXECUTION_ROLE_ATTESTATION_SQL = """
SELECT current_user, (
    role.rolsuper OR role.rolcreatedb OR role.rolcreaterole
    OR role.rolreplication OR role.rolbypassrls
    OR current_setting('default_transaction_read_only') <> 'on'
    OR has_database_privilege(current_user, current_database(), 'CREATE')
    OR has_database_privilege(current_user, current_database(), 'TEMPORARY')
    OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_database database
        WHERE database.datname = current_database()
          AND database.datdba = role.oid
    )
    OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_roles granted
        WHERE granted.oid <> role.oid
          AND pg_has_role(current_user, granted.oid, 'MEMBER')
    )
    OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_namespace schema
        WHERE schema.nspname NOT IN ('pg_catalog', 'information_schema')
          AND schema.nspname !~ '^pg_toast'
          AND has_schema_privilege(current_user, schema.oid, 'CREATE')
    )
    OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_attribute attribute
        JOIN pg_catalog.pg_class object ON object.oid = attribute.attrelid
        JOIN pg_catalog.pg_namespace schema ON schema.oid = object.relnamespace
        WHERE schema.nspname NOT IN ('pg_catalog', 'information_schema')
          AND schema.nspname !~ '^pg_toast'
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
          AND (
              has_column_privilege(
                  current_user, object.oid, attribute.attnum, 'INSERT'
              )
              OR has_column_privilege(
                  current_user, object.oid, attribute.attnum, 'UPDATE'
              )
              OR has_column_privilege(
                  current_user, object.oid, attribute.attnum, 'REFERENCES'
              )
          )
    )
    OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_class object
        JOIN pg_catalog.pg_namespace schema ON schema.oid = object.relnamespace
        WHERE schema.nspname NOT IN ('pg_catalog', 'information_schema')
          AND schema.nspname !~ '^pg_toast'
          AND object.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND (
              has_table_privilege(current_user, object.oid, 'INSERT')
              OR has_table_privilege(current_user, object.oid, 'UPDATE')
              OR has_table_privilege(current_user, object.oid, 'DELETE')
              OR has_table_privilege(current_user, object.oid, 'TRUNCATE')
              OR has_table_privilege(current_user, object.oid, 'REFERENCES')
              OR has_table_privilege(current_user, object.oid, 'TRIGGER')
              OR has_table_privilege(current_user, object.oid, 'MAINTAIN')
          )
    )
    OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_class object
        JOIN pg_catalog.pg_namespace schema ON schema.oid = object.relnamespace
        WHERE schema.nspname NOT IN ('pg_catalog', 'information_schema')
          AND schema.nspname !~ '^pg_toast'
          AND object.relkind = 'S'
          AND (
              has_sequence_privilege(current_user, object.oid, 'USAGE')
              OR has_sequence_privilege(current_user, object.oid, 'UPDATE')
          )
    )
    OR EXISTS (
        SELECT 1 FROM pg_catalog.pg_proc object
        JOIN pg_catalog.pg_namespace schema ON schema.oid = object.pronamespace
        WHERE schema.nspname NOT IN ('pg_catalog', 'information_schema')
          AND schema.nspname !~ '^pg_toast'
          AND has_function_privilege(current_user, object.oid, 'EXECUTE')
    )
) AS unsafe
FROM pg_catalog.pg_roles role
WHERE role.rolname = current_user
"""


class PostgreSQLIsolationError(RuntimeError):
    """Sanitized failure to create, connect, or remove an isolated database."""


class PsycopgTemplateIsolationProvider:
    """Create single-use databases from trusted pristine PostgreSQL templates."""

    def __init__(
        self,
        admin_conninfo: str,
        execution_conninfo: str,
        templates: Mapping[str, str],
        *,
        connector: Callable[..., Any] = psycopg.connect,
    ) -> None:
        if not isinstance(admin_conninfo, str) or not admin_conninfo:
            raise ValueError("admin_conninfo must be a non-empty string")
        if not isinstance(execution_conninfo, str) or not execution_conninfo:
            raise ValueError("execution_conninfo must be a non-empty string")
        if not isinstance(templates, Mapping) or not templates:
            raise ValueError("templates must be a non-empty mapping")
        _, execution_role = _validate_distinct_roles(admin_conninfo, execution_conninfo)
        self._admin_conninfo = admin_conninfo
        self._execution_conninfo = execution_conninfo
        self._execution_role = execution_role
        self._templates = dict(templates)
        self._connector = connector

    def acquire(self, database: str) -> _PsycopgTemplateIsolate:
        _validate_identifier(database)
        template = self._templates.get(database)
        if template is None:
            raise ValueError("database has no configured pristine template")
        _validate_identifier(template)
        clone = _clone_name(database)
        self._create_clone(clone, template)
        return _PsycopgTemplateIsolate(self, clone)

    def _create_clone(self, clone: str, template: str) -> None:
        statement = sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
            sql.Identifier(clone), sql.Identifier(template)
        )
        creation_attempted = False
        try:
            with self._admin_connection() as connection:
                with connection.cursor() as cursor:
                    creation_attempted = True
                    cursor.execute(statement)
                    cursor.execute(
                        sql.SQL(
                            "REVOKE ALL PRIVILEGES ON DATABASE {} FROM PUBLIC"
                        ).format(sql.Identifier(clone))
                    )
                    cursor.execute(
                        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                            sql.Identifier(clone),
                            sql.Identifier(self._execution_role),
                        )
                    )
        except Exception:
            if creation_attempted:
                try:
                    self._drop_clone(clone)
                except PostgreSQLIsolationError:
                    raise PostgreSQLIsolationError(
                        "cannot create or remove isolated PostgreSQL database"
                    ) from None
            raise PostgreSQLIsolationError(
                "cannot create isolated PostgreSQL database"
            ) from None

    def _connect_scoring(self, clone: str) -> Any:
        connection: Any | None = None
        try:
            parsed = conninfo_to_dict(self._execution_conninfo)
            existing_options = parsed.get("options", "")
            read_only_options = (
                f"{existing_options} {READ_ONLY_CONNECTION_OPTION}".strip()
            )
            conninfo = make_conninfo(
                self._execution_conninfo,
                dbname=clone,
                options=read_only_options,
            )
            connection = self._connector(conninfo, cursor_factory=ClientCursor)
            self._attest_execution_role(connection)
            return connection
        except Exception:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    raise PostgreSQLIsolationError(
                        "cannot close rejected PostgreSQL scoring connection"
                    ) from None
            raise PostgreSQLIsolationError(
                "cannot establish restricted PostgreSQL scoring connection"
            ) from None

    def _attest_execution_role(self, connection: Any) -> None:
        with connection.cursor() as cursor:
            cursor.execute(EXECUTION_ROLE_ATTESTATION_SQL)
            row = cursor.fetchone()
        if (
            not isinstance(row, Sequence)
            or len(row) != 2
            or row[0] != self._execution_role
            or row[1] is not False
        ):
            raise PostgreSQLIsolationError(
                "PostgreSQL execution role failed read-only privilege attestation"
            )

    def _connect_trusted(self, clone: str) -> Any:
        try:
            conninfo = make_conninfo(self._admin_conninfo, dbname=clone)
            return self._connector(conninfo, cursor_factory=ClientCursor)
        except Exception:
            raise PostgreSQLIsolationError(
                "cannot connect trusted setup to isolated PostgreSQL database"
            ) from None

    def _drop_clone(self, clone: str) -> None:
        terminate = (
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = %s AND pid <> pg_backend_pid()"
        )
        drop = sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(clone))
        try:
            with self._admin_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(terminate, (clone,))
                    cursor.execute(drop)
        except Exception:
            raise PostgreSQLIsolationError(
                "cannot remove isolated PostgreSQL database"
            ) from None

    def _admin_connection(self) -> Any:
        return self._connector(
            self._admin_conninfo,
            autocommit=True,
            cursor_factory=ClientCursor,
        )


class _PsycopgTemplateIsolate:
    """One clone whose reset operation destroys all question-local state."""

    def __init__(self, provider: PsycopgTemplateIsolationProvider, clone: str) -> None:
        self._provider = provider
        self._clone = clone
        self._dropped = False

    def connect_scoring(self) -> Any:
        if self._dropped:
            raise PostgreSQLIsolationError("isolated PostgreSQL database was released")
        return self._provider._connect_scoring(self._clone)

    def connect_trusted(self) -> Any:
        if self._dropped:
            raise PostgreSQLIsolationError("isolated PostgreSQL database was released")
        return self._provider._connect_trusted(self._clone)

    def reset(self) -> None:
        if not self._dropped:
            self._provider._drop_clone(self._clone)
            self._dropped = True

    def release(self) -> None:
        self.reset()


def _clone_name(database: str) -> str:
    suffix = f"_score_{secrets.token_hex(6)}"
    stem = database[: 63 - len(suffix)]
    return f"{stem}{suffix}"


def _validate_identifier(identifier: str) -> None:
    if (
        not isinstance(identifier, str)
        or POSTGRES_IDENTIFIER.fullmatch(identifier) is None
    ):
        raise ValueError("PostgreSQL database identifier is invalid")


def _validate_distinct_roles(
    admin_conninfo: str, execution_conninfo: str
) -> tuple[str, str]:
    try:
        admin_role = conninfo_to_dict(admin_conninfo).get("user")
        execution_role = conninfo_to_dict(execution_conninfo).get("user")
    except Exception:
        raise ValueError("PostgreSQL connection strings are invalid") from None
    if (
        not isinstance(admin_role, str)
        or not admin_role
        or not isinstance(execution_role, str)
        or not execution_role
        or admin_role == execution_role
    ):
        raise ValueError("admin and execution conninfo need distinct explicit roles")
    return admin_role, execution_role
