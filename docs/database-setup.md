# Public LiveSQLBench database setup

This lane provisions only the public LiveSQLBench Large-v1 PostgreSQL dumps. It
must not read or receive gold SQL, hidden annotations, test cases, score
artifacts, sealed evaluator state, credentials, or connection URLs.

The deterministic commands are provider-neutral. They use the normal `PGHOST`,
`PGPORT`, `PGUSER`, `PGPASSWORD`, and `PGSSLMODE` environment variables consumed
by `psql`; those values belong in an untracked environment or secret manager.
The runtime-role password is supplied separately as
`BENCHMARK_RUNTIME_PASSWORD`. Command receipts and committed configuration never
contain either password or a connection URL.

## Pinned public inputs

The inventory is
[`config/databases/livesqlbench-large-v1.json`](../config/databases/livesqlbench-large-v1.json).
It records the public dataset revision, official repository commit, public dump
URL, archive hash, pinned restore-script hash, and a path-independent SHA-256
fingerprint for each of the 18 eligible database directories. Each database
record also contains its secret-free Neon project and branch identifiers, the
verified managed schema/row/content fingerprint, and the gated Omni connection
identifier. Endpoints, usernames other than the fixed runtime role, passwords,
and connection URLs are deliberately absent.

The public archive used for the canary has:

- size: `329482970` bytes;
- SHA-256: `8af9a1459125bda5affe5b5b68211e458724b79a8da02825ec74fd896ff69258`;
- canary directory SHA-256:
  `f539b729b61c31533c61af5b742c56de6723ca878a9ed041f40c3a80246c5053`.

The directory digest hashes a canonical list of every relative `.sql` path,
file size, and file SHA-256. It is independent of the local extraction path and
does not reveal row contents.

Download public assets only into the ignored `data/raw/` tree:

```bash
mkdir -p data/raw/livesqlbench-large-v1
uvx --from gdown gdown \
  'https://drive.google.com/uc?id=1u1L-SvJtOZGfcIST-dINw8DnGEQDMu6C' \
  -O data/raw/livesqlbench-large-v1/public-dumps.zip
sha256sum data/raw/livesqlbench-large-v1/public-dumps.zip
```

Extract one database first. Do not fan out until it passes all canary gates:

```bash
unzip data/raw/livesqlbench-large-v1/public-dumps.zip \
  'postgre_table_dumps_large/archeology_scan_large_template/*' \
  -d data/raw/livesqlbench-large-v1/extracted

uv run python scripts/database_infrastructure.py fingerprint-dump \
  --dump-directory \
  data/raw/livesqlbench-large-v1/extracted/postgre_table_dumps_large/archeology_scan_large_template
```

## Restore and reset

The official import order is committed in
[`config/databases/restore-order-large-v1.json`](../config/databases/restore-order-large-v1.json).
It was mechanically extracted from the pinned official
`evaluation/env/init-databases_postgresql_large_v1.sh`, whose SHA-256 is
`b5c50cd51d235c6667923db44816be56cffa2d6b8a6d1e254a78dfb4403db66c`.
Regeneration refuses to overwrite an existing record:

```bash
uv run python scripts/database_infrastructure.py \
  --inventory config/databases/livesqlbench-large-v1.json \
  prepare-restore-order \
  --source /path/to/pinned/init-databases_postgresql_large_v1.sh \
  --output /new/path/restore-order-large-v1.json
```

Use PostgreSQL 18 and an administrative role named `root`, matching the pinned
official Dockerfile. The plain SQL dumps contain `OWNER TO root`; rewriting
those statements would make the restored input differ from the scorer input.
The canary ran on server version `180006`, image digest
`postgres@sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280`.
Its only installed extension was `plpgsql:1.0`; the strict import completed
without ignored SQL errors.

Restore first requires the directory's file count, size, and SHA-256 to match
the selected inventory record, and requires the restore-order file to match its
pinned SHA-256. It then preflights PostgreSQL major version 18 and the required
dump owner role `root`. Only after every preflight passes does it recreate the
explicitly inventoried database from `template0` and load every table file in
official order with `ON_ERROR_STOP=1`. Table names are identifier-validated and
symlinked dump files are rejected before the drop:

Three upstream mappings contain case-sensitive names whose exact files are
absent from the public archive: one entry for
`labor_certification_applications_large`, 34 for `mental_healths_large`, and 37
for `organ_transplant_large`. The pinned scorer script silently skips those
paths. To reproduce that behavior without weakening restore checks, the public
inventory lists every scorer-omitted table explicitly. Restore accepts only
those listed omissions, requires them to belong to the canonical order, and
fails if an omitted file appears or any unlisted ordered file is absent.
Those omissions cause downstream foreign-key errors in the present mental-
health and organ-transplant dumps. Their inventory records therefore also
enable the pinned scorer's `psql` error-continuation behavior for file imports
only. Connection, process, preflight, reset, role, and fingerprint failures
remain fatal; all other databases retain `ON_ERROR_STOP=1`.

```bash
uv run python scripts/database_infrastructure.py restore \
  --database archeology_scan_large \
  --dump-directory \
  data/raw/livesqlbench-large-v1/extracted/postgre_table_dumps_large/archeology_scan_large_template \
  --restore-order config/databases/restore-order-large-v1.json
```

This is the local reset strategy. A managed mirror needs its own tested reset or
branch-reset operation, but provider operations must not be mixed into the dump
loader. Creating a Neon project or branch is an external action and requires
explicit approval for that action.

## Read-only runtime role

Generate or retrieve the runtime password without printing it, export it only
for the provisioning process, and run:

```bash
uv run python scripts/database_infrastructure.py provision-readonly-role \
  --database archeology_scan_large \
  --role omni_benchmark_reader

uv run python scripts/database_infrastructure.py verify-readonly-role \
  --database archeology_scan_large \
  --role omni_benchmark_reader
```

Use a distinct runtime role for each database. Provisioning revokes that role's
database privileges and PUBLIC CONNECT across every connectable database in the
dedicated cluster, then grants CONNECT only to the selected database. Within the
target it grants only schema usage and SELECT on current and future tables and
sequences in every non-system schema. It removes superuser, database-create,
role-create, inheritance, replication, and row-security bypass capabilities;
revokes existing role memberships and direct object grants; and removes schema-
create, temporary-table, table/column write, `MAINTAIN`, sequence-mutation, and
function-execution paths in this dedicated benchmark database. Provisioning
fails before mutation if a reused role owns target or shared objects, because
ownership privileges cannot be revoked by ACL changes. It also sets
`default_transaction_read_only=on` and a 60-second statement timeout. The
verification command performs a real SELECT, then attempts public DDL, temporary
DDL, and table truncation after explicitly setting transaction read-only off.
Only PostgreSQL read-only or insufficient-privilege SQLSTATEs count as a denied
write; authentication, network, and tool failures propagate. Run provisioning
again after any drop-and-restore reset, because database-scoped grants are
removed with the old database.

## Fingerprint and parity gate

The database fingerprint contains no rows. It hashes canonical schema metadata
and, per table, a deterministic CSV stream of JSONB row representations. It
records table row counts and per-table content hashes, then hashes that table
manifest. Generation and scoring copies must report the same PostgreSQL
`server_version_num`; parity comparison rejects a version mismatch so
PostgreSQL's canonical representations remain comparable.

```bash
uv run python scripts/database_infrastructure.py fingerprint-database \
  --database archeology_scan_large \
  --output /secure/path/scorer-fingerprint.json

uv run python scripts/database_infrastructure.py compare \
  --scorer /secure/path/scorer-fingerprint.json \
  --mirror /secure/path/mirror-fingerprint.json
```

`compare` returns `0` for parity, `1` for a verified mismatch, and `2` when a
fingerprint is missing or invalid. Missing access therefore cannot masquerade
as either a pass or a data mismatch.

The local canary result is recorded in the inventory: 51 tables, 98,640 rows,
schema SHA-256 `f62f8c43e32bdf053e3e58f023820667d98cb713a6cc52edf982e95537ce5bed`,
and content SHA-256
`cd9dcd2a6fc88e00093291d4a40e221bf97e85b4eb87088f331ccd8368e8aaba`.
Two strict restores matched exactly, and the runtime-role denied-write probe
passed after reset. This establishes reproducible local reset parity; it does
not by itself claim managed-mirror parity.

The approved Neon canary project uses PostgreSQL `180006` in `aws-us-east-2`.
Its strict restore and runtime-role verification passed, including actual
SELECT access and denied public DDL, temporary DDL, and table truncation. The
managed fingerprint matched the scorer fingerprint exactly at 51 tables,
98,640 rows, and both schema/content hashes above. The secret-free project and
branch identifiers are recorded in the inventory; no endpoint, connection URL,
or password is recorded. Neon project administrators are not PostgreSQL
superusers, so role hardening verifies that privileged attributes are already
false and alters only provider-permitted attributes before applying ACLs.

## Scale gate

The approved scale-out is complete. All 18 databases use isolated PostgreSQL 18
Neon projects in organization `org-steep-term-23543236`, region
`aws-us-east-2`, and their default `main` branches. The provider-neutral loader
restored the pinned public dumps in scorer order. Every managed copy passed an
exact comparison against its scorer fingerprint and a live
`omni_benchmark_reader` verification before its Omni connection was created.
The inventory records all 18 project IDs, branch IDs, verification summaries,
and Omni connection IDs without recording credentials or endpoints.

Three databases require the explicitly pinned scorer-compatibility behavior
described above: labor certification has one absent ordered file, while mental
health and organ transplant also continue after per-file SQL errors caused by
their exact public omissions. Those behaviors are database-level public-input
compatibility rules; no query-specific or private benchmark input was used.

The largest database, `exchange_traded_funds_large`, completed at 57 tables and
538,932 rows. Its managed fingerprint matched exactly: schema SHA-256
`6bfa42805e091ef8462ee0cdfefb45bb52b41a1e0334d751e5e89249dcb0f3a7`
and content SHA-256
`ffddc88039095c155698a1a5a3cac351d04cca7ced08c9431a35829a76fe5965`.
No project was scaled above its approved 0.25-CU minimum during restore.

The opt-in end-to-end test exercises dump verification, two restores, exact
fingerprint parity, role provisioning, SELECT access, and denied writes:

```bash
OMNI_BENCHMARK_POSTGRES_INTEGRATION=1 \
  uv run pytest tests/test_database_integration.py
```
