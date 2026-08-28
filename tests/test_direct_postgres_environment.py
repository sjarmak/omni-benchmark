from __future__ import annotations

from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

import omni_benchmark.direct_postgres as direct_postgres
from omni_benchmark.direct_postgres import (
    AttestedDirectPostgresTransport,
    DirectPostgresConfigurationError,
)
from tests.test_direct_postgres import (
    PG_ENVIRONMENT,
    AuditConnection,
    SequenceConnector,
    _database_identity,
)


def test_tls_defaults_to_hostname_verification_with_system_roots() -> None:
    events: list[tuple[object, ...]] = []
    connector = SequenceConnector(
        [AuditConnection(("omni_benchmark_reader", False), events)]
    )
    environment = {
        key: value
        for key, value in PG_ENVIRONMENT.items()
        if key not in {"PGSSLMODE", "PGSSLROOTCERT"}
    }

    AttestedDirectPostgresTransport(
        environment,
        expected_identity=_database_identity(environment),
        connector=connector,
    )

    parsed = conninfo_to_dict(connector.calls[0][0])
    assert parsed["sslmode"] == "verify-full"
    assert parsed["sslrootcert"] == "system"


def test_custom_root_certificate_is_rejected_even_when_regular(
    tmp_path: Path,
) -> None:
    root_certificate = tmp_path / "benchmark-root.crt"
    root_certificate.write_text("fixture CA certificate", encoding="utf-8")
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError, match="PGSSLROOTCERT"):
        AttestedDirectPostgresTransport(
            {**PG_ENVIRONMENT, "PGSSLROOTCERT": str(root_certificate)},
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []


def test_canonical_os_root_bundle_is_accepted_for_hostname_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_certificate = "/etc/ssl/certs/ca-certificates.crt"
    stat_calls: list[tuple[object, bool]] = []

    class Metadata:
        st_mode = direct_postgres.stat.S_IFREG | 0o644

    def fake_stat(path: object, *, follow_symlinks: bool) -> Metadata:
        stat_calls.append((path, follow_symlinks))
        return Metadata()

    monkeypatch.setattr(direct_postgres.os, "stat", fake_stat)
    events: list[tuple[object, ...]] = []
    connector = SequenceConnector(
        [AuditConnection(("omni_benchmark_reader", False), events)]
    )
    environment = {
        **PG_ENVIRONMENT,
        "PGSSLROOTCERT": root_certificate,
    }

    AttestedDirectPostgresTransport(
        environment,
        expected_identity=_database_identity(environment),
        connector=connector,
    )

    parsed = conninfo_to_dict(connector.calls[0][0])
    assert parsed["sslmode"] == "verify-full"
    assert parsed["sslrootcert"] == root_certificate
    assert stat_calls == [(root_certificate, False)]


@pytest.mark.parametrize(
    "mode",
    [
        direct_postgres.stat.S_IFREG | 0o666,
        direct_postgres.stat.S_IFDIR | 0o755,
        direct_postgres.stat.S_IFLNK | 0o777,
    ],
)
def test_canonical_os_root_bundle_must_be_safe_and_regular(
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
) -> None:
    class Metadata:
        st_mode = mode

    monkeypatch.setattr(direct_postgres.os, "stat", lambda *_, **__: Metadata())
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError, match="PGSSLROOTCERT"):
        AttestedDirectPostgresTransport(
            {
                **PG_ENVIRONMENT,
                "PGSSLROOTCERT": "/etc/ssl/certs/ca-certificates.crt",
            },
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []


@pytest.mark.parametrize("error", [FileNotFoundError(), PermissionError()])
def test_canonical_os_root_bundle_stat_failure_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    error: OSError,
) -> None:
    def fail_stat(*_: object, **__: object) -> None:
        raise error

    monkeypatch.setattr(direct_postgres.os, "stat", fail_stat)
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError, match="PGSSLROOTCERT"):
        AttestedDirectPostgresTransport(
            {
                **PG_ENVIRONMENT,
                "PGSSLROOTCERT": "/etc/ssl/certs/ca-certificates.crt",
            },
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []


@pytest.mark.parametrize(
    "field",
    [
        "PGHOST",
        "PGHOSTADDR",
        "PGTARGETSESSIONATTRS",
        "PGCHANNELBINDING",
        "PGSSLCERT",
        "PGOPTIONS",
        "PGSERVICE",
    ],
)
def test_ambient_libpq_override_is_rejected_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    monkeypatch.setenv(field, "adversarial-value")
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError, match="ambient"):
        AttestedDirectPostgresTransport(
            PG_ENVIRONMENT,
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []


def test_matching_ambient_connection_fields_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for field, value in PG_ENVIRONMENT.items():
        monkeypatch.setenv(field, value)
    events: list[tuple[object, ...]] = []
    connector = SequenceConnector(
        [AuditConnection(("omni_benchmark_reader", False), events)]
    )

    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT,
        expected_identity=_database_identity(),
        connector=connector,
    )

    assert transport.runtime_identity == _database_identity()
    assert len(connector.calls) == 1


@pytest.mark.parametrize("field", ["SSL_CERT_FILE", "SSL_CERT_DIR"])
@pytest.mark.parametrize("value", ["/tmp/adversarial-trust", ""])
def test_ambient_system_trust_override_is_rejected_before_connecting(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    monkeypatch.setenv(field, value)
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError, match="ambient"):
        AttestedDirectPostgresTransport(
            PG_ENVIRONMENT,
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("PGHOSTADDR", "203.0.113.10"), ("SSL_CERT_FILE", "/tmp/adversarial")],
)
def test_ambient_state_is_rechecked_before_each_connection(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    events: list[tuple[object, ...]] = []
    connector = SequenceConnector(
        [AuditConnection(("omni_benchmark_reader", False), events)]
    )
    transport = AttestedDirectPostgresTransport(
        PG_ENVIRONMENT,
        expected_identity=_database_identity(),
        connector=connector,
    )
    monkeypatch.setenv(field, value)

    with pytest.raises(DirectPostgresConfigurationError, match="ambient"):
        transport.connect()

    assert len(connector.calls) == 1


@pytest.mark.parametrize("root_value", ["", "relative-root.crt", "missing-root.crt"])
def test_invalid_explicit_root_certificate_fails_before_connecting(
    tmp_path: Path,
    root_value: str,
) -> None:
    connector = SequenceConnector([])
    value = root_value
    if root_value == "missing-root.crt":
        value = str(tmp_path / root_value)

    with pytest.raises(DirectPostgresConfigurationError, match="PGSSLROOTCERT"):
        AttestedDirectPostgresTransport(
            {**PG_ENVIRONMENT, "PGSSLROOTCERT": value},
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []


def test_symlink_root_certificate_fails_before_connecting(tmp_path: Path) -> None:
    actual = tmp_path / "actual.crt"
    actual.write_text("fixture CA certificate", encoding="utf-8")
    linked = tmp_path / "linked.crt"
    linked.symlink_to(actual)
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError, match="PGSSLROOTCERT"):
        AttestedDirectPostgresTransport(
            {**PG_ENVIRONMENT, "PGSSLROOTCERT": str(linked)},
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert connector.calls == []
