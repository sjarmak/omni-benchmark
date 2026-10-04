# Total typed result contract for rewritten SQL

## Decision this contract should support

Did a governed query fail in planning or execution, or did it succeed and become
unusable only at the result boundary? Today those cases can collapse into an
unsupported-result-type error. The proposed contract makes the output schema
total, keeps dependency metadata out of the selected columns, and assigns every
failure to a typed owner.

This is a product proposal and offline acceptance oracle. It does not alter or
replay any completed model answer.

## Evidence and limits

In the development baseline, 31 of 34 governed non-answers shared an `UNKNOWN`
selected-field type. In E02, 14 generated semantic queries ended as
`unsupported_semantic_result_type`; those were 14 of 19 capture losses. Preserved
public canaries also showed plan summaries containing helper fields that were not
selected outputs. These observations establish an interface bottleneck. They do
not establish that all 31 unknown types have the same internal cause.

## Version 1 envelope

The top level has exactly five fields:

```json
{
  "schema_version": 1,
  "status": "success | failed",
  "fields": {"selected": [], "dependencies": []},
  "page": null,
  "failure": null
}
```

### Selected fields

Selected fields are the ordered output schema. Their zero-based ordinals must be
unique and contiguous.

```json
{
  "name": "orders.revenue",
  "ordinal": 0,
  "logical_type": "boolean | date | decimal | integer | json | string | timestamp | unknown",
  "source_type": "warehouse or planner type",
  "nullable": true,
  "semantic_role": "dimension | measure | calculation"
}
```

Measures and aggregates use the same scalar logical types; `semantic_role`
describes their modeling role without inventing a second value system. The
listed types cover every shape accepted by the current benchmark adapter:
`BOOLEAN`/`YESNO`, `DATE`, `JSON`, `NUMBER`, `STRING`, and `TIMESTAMP`. `integer`
permits exact integral values without passing through binary floating point.

`unknown` is an explicit extension path, not permission to guess. A non-null
cell must be represented as:

```json
{
  "type": "opaque",
  "source_type": "same value as field.source_type",
  "encoding": "json",
  "value": {}
}
```

Clients that understand the source type can decode it; other clients can retain
or display it without converting it to a number or string. Future native logical
types require a schema-version change.

### Dependency fields

Dependency metadata has the same fields except `ordinal`. Dependencies may
explain joins, filters, calculations, or planner work, but never determine row
width or output order. A dependency with `logical_type: unknown` cannot make a
fully typed selected output fail.

### Values and nullability

- `boolean`, `integer`, and `string` use their JSON primitives; booleans are not
  integers.
- `decimal`, `date`, and `timestamp` use tagged canonical string values.
- `json` accepts finite JSON values.
- `unknown` uses the opaque envelope above.
- JSON `null` is valid only when the selected field declares `nullable: true`.

### Completeness and pagination

A successful result has a page and no failure:

```json
{
  "completeness": "complete | paged",
  "content_sha256": "digest of ordered selected metadata plus exact page rows",
  "returned_row_count": 1000,
  "total_row_count": 4200,
  "next_cursor": "opaque stable cursor or null",
  "rows": []
}
```

`complete` requires `total_row_count == returned_row_count` and forbids a next
cursor. `paged` requires a cursor; total count may be null when the backend does
not know it. A truncated display preview is never labeled complete. Page rows
contain exactly one cell per selected field and are content-addressed.

### Typed failure ownership

A failed result has no page and exactly one closed owner/code pair:

| Owner | Codes |
| --- | --- |
| `planner` | `invalid_semantic_plan`, `output_type_unresolved`, `planning_failed` |
| `semantic_execution` | `database_error`, `query_cancelled`, `query_execution_failed` |
| `transport` | `malformed_provider_response`, `provider_unavailable`, `request_timeout` |
| `adapter` | `result_cardinality_mismatch`, `unsupported_value_encoding` |

The failure also carries required Boolean `retryable`. Free-form details may be
logged separately, but no programmatic decision or metric uses them. In
particular, an `UNKNOWN` selected type becomes
`planner/output_type_unresolved` if the planner cannot emit an opaque value; it
does not masquerade as query-execution failure.

## Acceptance oracle and metrics

`src/omni_benchmark/rewritten_result_contract.py` validates the exact envelope,
canonical page digest, scalar values, nullability, ordinals, pagination, and
owner/code compatibility. A public fixture reproduces the legacy boundary where
the selected field is `UNKNOWN` while a separate summary field is merely a
dependency. No SQL or result value is needed for that classification.

Aggregate output contains only:

- success/failure and complete/paged counts;
- selected logical-type counts;
- failure-owner and failure-code counts;
- selected/dependency field counts.

It emits no question IDs, field names, SQL, row values, correctness, hidden
annotations, dev-B data, or sealed-test data.

Product acceptance requires every terminal job to validate as exactly one
success or typed failure; zero selected `unknown` values may be silently coerced;
dependency-only unknowns must not fail a result; and every page labeled complete
must be independently digestible and complete. The offline oracle currently
passes fixtures for all of these boundaries. No product endpoint has yet been
measured against it.

## Relevant Omni documentation

Omni documents boolean, date/time, number, and string field behavior in its
[point-and-click query guide](https://docs.omni.co/analyze-explore/point-click-queries)
and describes modeled dimensions and type correction in
[Dimensions](https://docs.omni.co/modeling/dimensions). Those modeling surfaces
do not by themselves specify the rewritten-SQL result envelope proposed here.
