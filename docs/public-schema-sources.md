# Public schema and column-meaning sources

The public-only semantic baseline uses the official LiveSQLBench schema and
column metadata alongside the HKB graph. The committed inventory is
[`config/public_schema_sources.json`](../config/public_schema_sources.json). It
pins two objects for each of the 18 benchmark databases at public dataset
revision `a418e108d5cbb4cf9b783a928eff5e924ad2460d`:

- `<database>_schema.txt`;
- `<database>_column_meaning_base.json`.

Each object is bound by canonical dataset path, Git blob OID, byte length, and
SHA-256. The complete inventory contains 36 files and 6,003,364 bytes. Its
SHA-256 is `2b833d1524695ac811bbeac2a78b00815767b793511a74f35ed913b521796c3a`.
The database set and revision must exactly match the independently pinned HKB
inventory and the eligible-question manifest.

Fetch and verify the ignored local copies with:

```bash
uv run python scripts/prepare_schema_sources.py fetch \
  --inventory config/public_schema_sources.json \
  --destination-root data/raw/livesqlbench-large-v1/schema

uv run python scripts/prepare_schema_sources.py inspect \
  --inventory config/public_schema_sources.json \
  --source-root data/raw/livesqlbench-large-v1/schema

uv run python scripts/prepare_schema_sources.py build \
  --inventory config/public_schema_sources.json \
  --source-root data/raw/livesqlbench-large-v1/schema \
  --output-root semantic_models/public_schema_ir \
  --database archeology_scan_large \
  --companion-hkb-ir semantic_models/public_ir/archeology_scan_large.hkb.jsonl
```

The inventory reader walks every absolute path component through held no-follow
directory descriptors, accepts only a regular final file, and caps it at one
MiB. The downloader applies the same component-wise boundary to local sources,
retrieves at most each expected byte length plus one, stages the complete corpus,
and checks size, SHA-256, and Git blob OID before publishing anything.
Destination traversal and symlink protections are shared with the public HKB
acquisition path. Structured description traversal is capped at depth 32; the
pinned corpus's observed maximum is 3.

## Observed public invariants

A deterministic inspection of the verified source bytes found:

| Invariant | Count |
| --- | ---: |
| Databases | 18 |
| DDL `CREATE TABLE` blocks | 971 |
| Top-level column descriptions | 17,749 |
| Structured JSON/JSONB descriptions | 212 |
| Top-level structured-field entries | 1,008 |
| Structured leaf descriptions | 1,925 |
| Maximum structured-description depth | 3 |

Column-meaning keys use `<database>|<table>|<column>`. Most values are strings;
the 212 structured values contain a `column_meaning` plus a `fields_meaning`
tree. Its immediate 1,008 entries expand to 1,925 string leaves across nested
objects and three arrays. The semantic compiler must preserve case, hierarchy,
and sequence for nested JSON fields rather than treating descriptions as a flat
text corpus.

## Information boundary

The official `*_schema.txt` files include public example rows after each DDL
block. Those rows are not needed to describe the modeled schema and will not be
provided to the semantic-model compiler or any evaluated agent. Only the DDL
and the column-meaning JSON are eligible inputs. This narrower boundary reduces
accidental example-value dependence while retaining the public schema,
constraints, types, and business descriptions required by the preregistered
baseline.

No benchmark question text, gold SQL, test case, or hidden
`external_knowledge` annotation is used by this source-acquisition stage.

## Canary schema IR

The committed canary output contains only row-free public semantics:

| Record | Count |
| --- | ---: |
| Tables | 51 |
| Columns | 959 |
| Structured JSON leaves | 92 |
| Primary keys | 51 |
| Foreign keys | 77 |

The generator uses the pinned SQLGlot 30.17 PostgreSQL parser rather than a
custom comma- or line-based DDL grammar. It preserves source order, semantic
identifier case and quote state, declared types, defaults, nullability, key
order, nested JSON paths, and content/intervention provenance. Stable IDs use
percent-encoded exact identifiers. The manifest binds the DDL, column meanings,
companion HKB IR, and emitted JSONL by SHA-256.

This artifact is still pre-semantic. It does not infer joins, aggregation grain,
measures, or HKB-to-field mappings. Those interpretive decisions belong in a
separate mapping artifact so they can carry explicit representability losses
and modeling provenance.
