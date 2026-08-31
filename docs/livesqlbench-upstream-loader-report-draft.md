# Draft upstream report: Large-v1 loader omits case-mismatched tables

> Filed 2026-08-29 as https://github.com/bird-bench/livesqlbench/issues/10.
> The filed body drops the split vocabulary and inlines the per-database audit
> table. Do not open a second issue for this defect.

## Summary

The pinned LiveSQLBench Large-v1 PostgreSQL loader constructs each dump path as
`<declared table>.sql` and tests it with an exact filename match on Linux. In
two databases, the declared table names use mixed or upper case while the
archive filenames are lowercase. The official loader therefore skips 34 of 55
declared tables in `mental_healths_large` and 37 of 57 in
`organ_transplant_large` even though capitalization variants exist in the
archive.

The load loop is in `evaluation/env/init-databases_postgresql_large_v1.sh` at
lines 118-127. For example, the loader requests `Facilities.sql`, while the
archive contains `facilities.sql`.

## Precedent in this repository

The Base loader had the same defect, and it was fixed twice.

- `915a24a3` (2025-08-05), "Fix bug: mismatch between the case of table name and
  real file name, which is incompatible in Linux os", rewrote ten table lists in
  `evaluation/env/init-databases_postgresql.sh` from mixed case to lowercase.
  Before that commit, `mental_template` read `Facilities Clinicians Patients
  AssessmentBasics Encounters AssessmentSymptomsAndRisk
  AssessmentSocialAndDiagnosis TreatmentBasics TreatmentOutcomes`.
- `a9f9e7a4` (2025-08-21), same title, fixed seven lists where the lowercasing
  pass had merged adjacent names, for example `treatmentbasictreatmentoutcomes`
  back to `treatmentbasics treatmentoutcomes`.

`mental_healths_large_template` opens with those same nine names in the
pre-`915a24a3` spelling. The Large-v1 script arrived later, in `db17afaf`
(2026-03-02), and has not been modified since, so the earlier correction never
reached it. At `e15cd221`, current HEAD, `mental_healths_large_template` still
begins `Facilities Clinicians Patients AssessmentBasics` and
`organ_transplant_large_template` still begins `Demographics
Recipients_Demographics Medical_History HLA_Info`.

## Why the shipped checker does not report it

`evaluation/check_db_metadata.py` compares a built database against an expected
table list. `EXPECTED_DATABASES_LITE` and `EXPECTED_DATABASES_FULL` carry real
lists. `EXPECTED_DATABASES_LARGE` maps all 18 Large-v1 database names to the
empty string. In `check_expected_tables`, an empty expectation yields
`expected_count` 0 and `missing_count` 0, and every loaded table is counted as
extra, so `--version large` reports no missing tables for any database no matter
how many the loader skipped.

The same file disagrees with the loader on casing for the related Base-Full
database: `EXPECTED_DATABASES_FULL["organ_transplant"]` lists `demographics
recipients_demographics ... hla_info`, while `organ_transplant_large_template`
lists `Demographics Recipients_Demographics ... HLA_Info`.

## Impact

A task whose reference SQL touches a skipped table cannot be scored against the
database this script builds. We evaluated 18 tasks on these two databases, nine
each. The reference SQL failed to execute for all 18, in every condition we ran.

The public dataset assigns 20 `Query` tasks to `mental_healths_large` and 19 to
`organ_transplant_large`, so the affected population is larger than the 18 we
measured.

We do not load the lowercase files, because that would build a different
database from the official Large-v1 environment. We record the affected tasks as
unscorable instead.

## Attached reproducible audit

The attached `livesqlbench-loader-fidelity-v1.json` resolves the restore order
for all 18 databases against the public dump archive and reports:

- 18 of 18 databases reproduce this script's behavior;
- 973 tables are declared and 901 are loaded;
- 72 are skipped: 71 because only a case-variant filename exists, plus one
  genuinely absent archive file in a separate database.

The command that produced it is stored in the audit and runs against the pinned
public archive. It emits the full per-table case-variant evidence and exits zero
only when every recorded omission matches this script.

## Suggested upstream disposition

For a future benchmark version, either normalize dump lookup and regenerate the
reference databases and gold against that environment, or explicitly exclude
questions whose reference SQL requires omitted tables. Large-v1 itself should
remain immutable so existing published results retain a stable target.

Populating `EXPECTED_DATABASES_LARGE` with the 18 declared table lists would
make this class of build defect visible at check time. It would also give a
report like #2, where a user saw widespread execution errors, a mechanical way
to rule the built schema in or out.
