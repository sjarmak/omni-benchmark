from __future__ import annotations

import pytest

from omni_benchmark.direct_postgres import (
    AttestedDirectPostgresTransport,
    DirectPostgresConfigurationError,
    DirectPostgresInfrastructureError,
)
from tests.test_direct_postgres import (
    PG_ENVIRONMENT,
    AuditConnection,
    SequenceConnector,
    _database_identity,
)


def test_connection_target_mismatch_fails_before_connecting() -> None:
    connector = SequenceConnector([])

    with pytest.raises(DirectPostgresConfigurationError, match="identity"):
        AttestedDirectPostgresTransport(
            PG_ENVIRONMENT,
            expected_identity=_database_identity(connection_target_sha256="f" * 64),
            connector=connector,
        )

    assert connector.calls == []


@pytest.mark.parametrize(
    "identity_row",
    [
        ("otherdb", "omni_benchmark_reader", 180000),
        ("neondb", "other_reader", 180000),
        ("neondb", "omni_benchmark_reader", 170000),
    ],
)
def test_live_database_identity_mismatch_is_rejected_and_closed(
    identity_row: tuple[object, ...],
) -> None:
    events: list[tuple[object, ...]] = []
    connector = SequenceConnector(
        [
            AuditConnection(
                ("omni_benchmark_reader", False),
                events,
                identity_row=identity_row,
            )
        ]
    )

    with pytest.raises(DirectPostgresInfrastructureError, match="attestation"):
        AttestedDirectPostgresTransport(
            PG_ENVIRONMENT,
            expected_identity=_database_identity(),
            connector=connector,
        )

    assert events[-1] == ("audit_close",)
