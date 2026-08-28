# Public HKB semantic baseline

This document describes the public-information-only input boundary for the
LiveSQLBench HKB-to-Omni transformation. It contains no gold SQL, hidden
knowledge annotations, test cases, or question-selected context.

## Source identity

The source inventory is
[`config/public_hkb_sources.json`](../config/public_hkb_sources.json). It pins
all 18 `*_kb.jsonl` objects from public dataset revision
`a418e108d5cbb4cf9b783a928eff5e924ad2460d` by:

- database and canonical relative path;
- Hugging Face/Git blob OID;
- byte length; and
- SHA-256 of the downloaded bytes.

Source downloads remain ignored under `data/raw/`. Fetching publishes nothing
until every downloaded object has passed its size, SHA-256, and Git blob OID
checks:

```bash
uv run python scripts/prepare_hkb.py fetch \
  --inventory config/public_hkb_sources.json \
  --destination-root data/raw/livesqlbench-large-v1/hkb
```

Network reads are capped at the expected size plus one byte. Local compilation
opens source paths through no-follow directory descriptors and accepts only
regular files, so a canonical filename cannot be replaced by a symlink to data
outside the public source root. Ancestors of the caller-selected source root
remain operating-system-resolved; this is accepted because the caller supplies
that root and every source byte is independently size-, SHA-256-, and Git-OID-
bound before compilation.

## Intermediate representation

Generate the public IR with:

```bash
uv run python scripts/prepare_hkb.py build \
  --inventory config/public_hkb_sources.json \
  --source-root data/raw/livesqlbench-large-v1/hkb \
  --output-root semantic_models/public_ir
```

The committed output contains one deterministic JSONL file per database and a
manifest that binds every output file by SHA-256. Stable object identity is
`<database>:hkb:<id>`. Knowledge names are not identifiers: the public corpus
contains three duplicate names within a database.

Each IR record preserves:

- the public HKB name, description, definition, and source type;
- direct dependency IDs and stable IDs in declared order;
- a prerequisite-first transitive dependency closure;
- dependency depth;
- whether the original no-dependency encoding was `-1` or `[]`;
- exact file, line, file hash, and source-record-span hash;
- content provenance (`public_hkb`);
- intervention provenance (`mechanical_baseline_transformation`); and
- transformation class (`mechanical`).

The record hash covers the exact source byte span for that JSONL record,
including its line terminator when present. The file hash independently binds
all source bytes.

The graph compiler reads the complete database before resolving edges. This is
required because 28 public edges point to a higher numeric ID, IDs can be
nonzero or gapped, and source order is not topological. It rejects duplicate
IDs, duplicate direct edges, dangling references, self-edges, cycles, duplicate
JSON keys, schema drift, and any extra fields—including protected benchmark
fields.

The semantic output directory is dedicated: generation rejects symlink roots,
non-regular files, and any existing name outside the 18 expected IR files plus
`manifest.json`. Files are staged only after every source and graph validates,
then the manifest is replaced last. Publication is not a cross-platform atomic
directory swap; if a process or filesystem fails during replacement, the old
manifest will not validate any mixed output. Rerun generation and the committed
hash-verification test before using or committing that directory.

The generated manifest reproduces the observed public invariants:

| Invariant | Count |
| --- | ---: |
| Databases | 18 |
| HKB definitions | 1,090 |
| Calculation knowledge | 430 |
| Domain knowledge | 462 |
| Value illustrations | 198 |
| `-1` no-dependency encodings | 509 |
| Empty-list no-dependency encodings | 21 |
| Entries with dependencies | 560 |
| Direct dependency edges | 945 |
| Maximum dependency depth | 6 |

## Mechanical versus deferred work

This stage makes no claim that a natural-language HKB rule is expressible as an
Omni measure, dimension, filter, relationship, or AI instruction. Every record
therefore starts with:

```json
{
  "representability": {
    "status": "unassessed",
    "reason": "semantic_mapping_not_attempted"
  }
}
```

The following work is mechanical and complete here:

- source acquisition and content verification;
- strict six-field parsing;
- stable identity;
- dependency normalization, validation, closure, and depth;
- deterministic serialization; and
- source/content/intervention provenance.

The following work remains interpretive and must be performed by the next
semantic-compiler stage with explicit loss records:

- binding natural-language concepts to schema fields;
- choosing measure versus dimension semantics;
- selecting aggregation grain and join ownership;
- translating formulas, filters, and time rules;
- choosing concise discoverability context; and
- determining whether Omni can govern the definition without weakening it.

No benchmark question, question ID, hidden annotation, or gold-derived example
may drive this baseline mapping. Unsupported or ambiguous definitions must be
reported rather than silently converted to generic prompt text.

## Canary representability map

The reviewed public-only canary map is generated independently of Omni syntax:

```bash
uv run python scripts/prepare_semantic_mapping.py \
  --spec config/archeology_scan_public_mapping.json \
  --hkb-ir semantic_models/public_ir/archeology_scan_large.hkb.jsonl \
  --schema-ir semantic_models/public_schema_ir/archeology_scan_large.schema.jsonl \
  --schema-manifest semantic_models/public_schema_ir/manifest.json \
  --output-root semantic_models/public_mapping
```

The mapping classifies all 54 `archeology_scan_large` HKB nodes exactly once:

| Disposition | Count | Meaning |
| --- | ---: | --- |
| `compile` | 14 | Same-table dependencies and inputs have a defensible row grain. |
| `context_only` | 10 | Public value illustrations enrich existing fields without creating executable definitions. |
| `defer_cross_grain` | 20 | A relationship/grain/aggregation contract is missing. |
| `unsupported` | 10 | Required source fields, parsing rules, category mappings, dependencies, or existence semantics are absent. |

Each expanded row preserves source bindings with role and confidence,
dependency-audit exceptions, enumerated loss codes, unresolved relationship
requirements, and separate content/intervention provenance. The mapping output
is SHA-256
`a54234cf768619bd15260a87ff3cd55765d006eaa4bd20bc05fd427ed24eeae6`.
It is the reviewed input to the Omni compiler, not evidence that Omni accepted
or executed the definition.
