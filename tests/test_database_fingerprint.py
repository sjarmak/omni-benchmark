from __future__ import annotations

import hashlib

from omni_benchmark.database_fingerprint import fingerprint_database
from omni_benchmark.database_postgres import PostgresClient


class FingerprintClient(PostgresClient):
    def __init__(self) -> None:
        self.responses = iter(
            (
                b"180006\n",
                b"schema-csv\n",
                b"public\tfirst\npublic\tSecond\n",
                b"2\n",
                b'"{"id": 1}"\n"{"id": 2}"\n',
                b"0\n",
                b"",
            )
        )

    def run(self, database: str, **kwargs) -> bytes:
        return next(self.responses)


def test_database_fingerprint_covers_schema_rows_and_empty_tables() -> None:
    result = fingerprint_database(FingerprintClient(), "fixture_db")

    assert result["postgres_server_version_num"] == "180006"
    assert result["schema_sha256"] == hashlib.sha256(b"schema-csv\n").hexdigest()
    assert result["table_count"] == 2
    assert result["row_count"] == 2
    assert result["tables"] == [
        {
            "schema": "public",
            "table": "first",
            "row_count": 2,
            "content_sha256": hashlib.sha256(b'"{"id": 1}"\n"{"id": 2}"\n').hexdigest(),
        },
        {
            "schema": "public",
            "table": "Second",
            "row_count": 0,
            "content_sha256": hashlib.sha256(b"").hexdigest(),
        },
    ]
