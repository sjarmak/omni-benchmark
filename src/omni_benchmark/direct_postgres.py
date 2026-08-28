"""Fail-closed PostgreSQL transport for direct-SQL benchmark conditions."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import psycopg
from psycopg import ClientCursor
from psycopg.conninfo import make_conninfo

from .direct_capture_contract import DirectDatabaseAttestation
from .direct_runtime_binding import DirectDatabaseIdentity, DirectRuntimeIdentityError
from .postgres_isolation import (
    EXECUTION_ROLE_ATTESTATION_SQL,
    READ_ONLY_CONNECTION_OPTION,
)

_REQUIRED_ENVIRONMENT_FIELDS = ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")
_DEFAULT_PORT = 5432
_REQUIRED_SSL_MODE = "verify-full"
_SYSTEM_ROOT_CERTIFICATE = "system"
_CONNECT_TIMEOUT_SECONDS = 10
_SYSTEM_TRUST_OVERRIDE_FIELDS = frozenset({"SSL_CERT_DIR", "SSL_CERT_FILE"})
RUNTIME_IDENTITY_ATTESTATION_SQL = (
    "SELECT current_database(), current_user, "
    "current_setting('server_version_num')::integer"
)


class DirectPostgresConfigurationError(ValueError):
    """Safe failure raised before a direct PostgreSQL connection is attempted."""


class DirectPostgresInfrastructureError(RuntimeError):
    """Sanitized external PostgreSQL connection or privilege-audit failure."""


class AttestedDirectPostgresTransport:
    """Create query connections only after a live read-only privilege audit."""

    def __init__(
        self,
        environment: Mapping[str, str],
        *,
        expected_identity: DirectDatabaseIdentity,
        connector: Callable[..., Any] = psycopg.connect,
    ) -> None:
        values = _connection_values(environment)
        _assert_ambient_environment_is_safe(values)
        identity = _validated_database_identity(expected_identity, values)
        conninfo = _make_safe_conninfo(values)
        if conninfo is None:
            raise DirectPostgresConfigurationError(
                "direct PostgreSQL connection configuration failed"
            ) from None
        self._conninfo = conninfo
        self._connector = connector
        self._connection_values = values
        self._database_identity = identity
        self._execution_attestation = self._attest()

    @property
    def execution_attestation(self) -> DirectDatabaseAttestation:
        """Return only assertions established by the live database audit."""
        return self._execution_attestation

    @property
    def runtime_identity(self) -> DirectDatabaseIdentity:
        """Return the exact target identity established by config and live audit."""
        return self._database_identity

    @property
    def execution_authority(self) -> str:
        """Fingerprint mutable connector and credential state without exposing it."""
        return _execution_authority(
            connector=self._connector,
            conninfo=self._conninfo,
            connection_values=self._connection_values,
            database_identity=self._database_identity,
            execution_attestation=self._execution_attestation,
        )

    def connect(self) -> Any:
        """Open a fresh read-only connection for one evaluated query attempt."""
        connection = self._try_open_connection()
        if connection is None:
            raise DirectPostgresInfrastructureError(
                "direct PostgreSQL connection failed"
            ) from None
        audit_succeeded = False
        try:
            audit_succeeded = self._connection_is_attested(connection)
        finally:
            if not audit_succeeded:
                _close_connection(connection)
        if audit_succeeded:
            return connection
        raise DirectPostgresInfrastructureError(
            "direct PostgreSQL privilege attestation failed"
        ) from None

    def _try_open_connection(self) -> Any | None:
        _assert_ambient_environment_is_safe(self._connection_values)
        connection: Any | None = None
        try:
            connection = self._connector(
                self._conninfo,
                cursor_factory=ClientCursor,
            )
        except Exception:
            return None
        return connection

    def _connection_is_attested(self, connection: Any) -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute(EXECUTION_ROLE_ATTESTATION_SQL)
                privilege_row = cursor.fetchone()
                cursor.execute(RUNTIME_IDENTITY_ATTESTATION_SQL)
                identity_row = cursor.fetchone()
            return _audit_row_is_safe(
                privilege_row, self._database_identity.runtime_role
            ) and _identity_row_is_safe(identity_row, self._database_identity)
        except Exception:
            return False

    def _attest(self) -> DirectDatabaseAttestation:
        connection = self._try_open_connection()
        if connection is None:
            raise DirectPostgresInfrastructureError(
                "direct PostgreSQL privilege attestation failed"
            ) from None
        audit_succeeded = False
        close_succeeded = False
        try:
            audit_succeeded = self._connection_is_attested(connection)
        finally:
            close_succeeded = _close_connection(connection)
        if not audit_succeeded or not close_succeeded:
            raise DirectPostgresInfrastructureError(
                "direct PostgreSQL privilege attestation failed"
            ) from None
        return DirectDatabaseAttestation(
            role_is_read_only=True,
            no_execute_on_non_system_functions=True,
        )


def _make_safe_conninfo(values: Mapping[str, str]) -> str | None:
    try:
        return make_conninfo(
            host=values["PGHOST"],
            port=values["PGPORT"],
            dbname=values["PGDATABASE"],
            user=values["PGUSER"],
            password=values["PGPASSWORD"],
            sslmode=values["PGSSLMODE"],
            sslrootcert=values["PGSSLROOTCERT"],
            options=READ_ONLY_CONNECTION_OPTION,
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None


def _close_connection(connection: Any) -> bool:
    try:
        connection.close()
    except Exception:
        return False
    return True


def _connection_values(environment: Mapping[str, str]) -> dict[str, str]:
    validation_failed = False
    try:
        values, error = _read_connection_values(environment)
    except Exception:
        values = None
        error = None
        validation_failed = True
    if validation_failed:
        raise DirectPostgresConfigurationError(
            "direct PostgreSQL environment validation failed"
        ) from None
    if error is not None:
        raise DirectPostgresConfigurationError(error) from None
    if values is None:
        raise DirectPostgresConfigurationError(
            "direct PostgreSQL environment validation failed"
        ) from None
    return values


def _assert_ambient_environment_is_safe(
    connection_values: Mapping[str, str],
) -> None:
    try:
        unsafe = any(
            _ambient_entry_is_unsafe(key, value, connection_values)
            for key, value in os.environ.items()
        )
    except Exception:
        unsafe = True
    if unsafe:
        raise DirectPostgresConfigurationError(
            "direct PostgreSQL ambient environment is unsafe"
        ) from None


def _ambient_entry_is_unsafe(
    key: object,
    value: object,
    connection_values: Mapping[str, str],
) -> bool:
    if type(key) is not str or type(value) is not str:
        return True
    if key in _SYSTEM_TRUST_OVERRIDE_FIELDS:
        return True
    if not key.startswith("PG"):
        return False
    expected = connection_values.get(key)
    return expected is None or value != expected


def direct_postgres_connection_target_sha256(
    *,
    host: str,
    port: int,
    physical_database: str,
    runtime_role: str,
) -> str:
    """Hash credential-free PostgreSQL coordinates for an inventory identity."""
    if (
        type(host) is not str
        or not host
        or "\x00" in host
        or type(port) is not int
        or not 1 <= port <= 65535
        or type(physical_database) is not str
        or not physical_database
        or type(runtime_role) is not str
        or not runtime_role
    ):
        raise DirectPostgresConfigurationError(
            "direct PostgreSQL target identity is invalid"
        ) from None
    payload = {
        "host": host,
        "physical_database": physical_database,
        "port": port,
        "runtime_role": runtime_role,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _execution_authority(
    *,
    connector: object,
    conninfo: str,
    connection_values: Mapping[str, str],
    database_identity: DirectDatabaseIdentity,
    execution_attestation: DirectDatabaseAttestation,
) -> str:
    payload = {
        "connection_values_sha256": _strict_json_sha256(connection_values),
        "connector": _callable_identity(connector),
        "conninfo_sha256": hashlib.sha256(conninfo.encode()).hexdigest(),
        "database_identity_sha256": database_identity.sha256(),
        "execution_attestation": {
            "no_execute_on_non_system_functions": (
                execution_attestation.no_execute_on_non_system_functions
            ),
            "role_is_read_only": execution_attestation.role_is_read_only,
        },
    }
    return _strict_json_sha256(payload)


def _strict_json_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _callable_identity(value: object) -> str:
    function = getattr(value, "__func__", value)
    owner = getattr(value, "__self__", None)
    return f"{id(owner)}:{id(function)}"


def _validated_database_identity(
    value: object, connection: Mapping[str, str]
) -> DirectDatabaseIdentity:
    try:
        if type(value) is not DirectDatabaseIdentity:
            raise DirectRuntimeIdentityError("database identity has the wrong type")
        identity = DirectDatabaseIdentity.from_dict(value.as_dict(), environment={})
        target_sha256 = direct_postgres_connection_target_sha256(
            host=connection["PGHOST"],
            port=int(connection["PGPORT"]),
            physical_database=connection["PGDATABASE"],
            runtime_role=connection["PGUSER"],
        )
    except Exception:
        raise DirectPostgresConfigurationError(
            "direct PostgreSQL database identity is invalid"
        ) from None
    if (
        identity.physical_database != connection["PGDATABASE"]
        or identity.runtime_role != connection["PGUSER"]
        or identity.connection_target_sha256 != target_sha256
    ):
        raise DirectPostgresConfigurationError(
            "direct PostgreSQL database identity does not match target"
        ) from None
    return identity


def _read_connection_values(
    environment: Mapping[str, str],
) -> tuple[dict[str, str] | None, str | None]:
    if not isinstance(environment, Mapping):
        return None, "environment must be a mapping"
    values: dict[str, str] = {}
    for field in _REQUIRED_ENVIRONMENT_FIELDS:
        value = environment.get(field)
        if not isinstance(value, str) or not value or "\x00" in value:
            return None, f"{field} must be a safe value"
        values[field] = value

    port_value = environment.get("PGPORT", str(_DEFAULT_PORT))
    if not isinstance(port_value, str) or "\x00" in port_value:
        return None, "PGPORT must be a valid port"
    try:
        port = int(port_value)
    except (TypeError, ValueError):
        return None, "PGPORT must be a valid port"
    if not 1 <= port <= 65535:
        return None, "PGPORT must be a valid port"

    ssl_mode = environment.get("PGSSLMODE", _REQUIRED_SSL_MODE)
    if isinstance(ssl_mode, str) and type(ssl_mode) is not str:
        raise TypeError("hostile PGSSLMODE string subclass")
    if type(ssl_mode) is not str or ssl_mode != _REQUIRED_SSL_MODE:
        return None, "PGSSLMODE must be verify-full"
    root_certificate = environment.get("PGSSLROOTCERT", _SYSTEM_ROOT_CERTIFICATE)
    if isinstance(root_certificate, str) and type(root_certificate) is not str:
        raise TypeError("hostile PGSSLROOTCERT string subclass")
    if not _root_certificate_is_safe(root_certificate):
        return None, "PGSSLROOTCERT must be system"
    values["PGPORT"] = str(port)
    values["PGSSLMODE"] = ssl_mode
    values["PGSSLROOTCERT"] = root_certificate
    return values, None


def _root_certificate_is_safe(value: object) -> bool:
    return type(value) is str and value == _SYSTEM_ROOT_CERTIFICATE


def _audit_row_is_safe(row: object, expected_user: str) -> bool:
    return (
        isinstance(row, Sequence)
        and not isinstance(row, (str, bytes, bytearray))
        and len(row) == 2
        and row[0] == expected_user
        and row[1] is False
    )


def _identity_row_is_safe(row: object, expected: DirectDatabaseIdentity) -> bool:
    return (
        isinstance(row, Sequence)
        and not isinstance(row, (str, bytes, bytearray))
        and len(row) == 3
        and row[0] == expected.physical_database
        and row[1] == expected.runtime_role
        and type(row[2]) is int
        and row[2] == expected.postgres_server_version_num
    )
