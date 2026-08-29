# Draft upstream report: Large-v1 loader omits case-mismatched tables

> Draft for human review only. Do not send or open an upstream issue without
> separate authorization.

## Summary

The pinned LiveSQLBench Large-v1 PostgreSQL loader constructs each dump path as
`<declared table>.sql` and tests it with an exact filename match on Linux. In
two databases, the declared table names use mixed or upper case while the
archive filenames are lowercase. The official loader therefore skips 34 of 55
declared tables in `mental_healths_large` and 37 of 57 in
`organ_transplant_large` even though capitalization variants exist in the
archive.

This is observable in the vendored public loader at
`data/raw/livesqlbench-large-v1/init-databases_postgresql_large_v1.sh`, lines
118–127. For example, the loader requests `Facilities.sql`, while the archive
contains `facilities.sql`.

## Evaluation impact

The committed dev-A split contains nine questions assigned to each affected
database. The benchmark's reference SQL for those 18 questions cannot be
scored against the official database. Our evaluation keeps all 154 dev-A
questions scheduled, preregisters these 18 as scorer-conformance exclusions,
and reports 136 answerable questions separately. We do not load the lowercase
files because doing so would create a different database from the official
Large-v1 environment.

The broader train capture contains 14 and 13 questions for the two databases;
those counts must not be described as dev-A counts.

## Attached reproducible audit

The machine-readable audit is
`experiments/analysis/livesqlbench-loader-fidelity-v1.json`. It records all 18
databases and reports:

- 18 of 18 inventories reproduce the official loader;
- 973 tables are declared and 901 are loaded;
- 72 are skipped: 71 because only a case-variant filename exists, plus one
  genuinely absent archive file in a separate database.

Reproduce it from the pinned public archive with the command stored in the
audit. The command emits the full per-table case-variant evidence and exits
zero only when every committed omission matches the official loader.

## Suggested upstream disposition

For a future benchmark version, either normalize dump lookup and regenerate the
reference databases and gold against that environment, or explicitly exclude
questions whose reference SQL requires omitted tables. Large-v1 itself should
remain immutable so existing published results retain a stable target.
