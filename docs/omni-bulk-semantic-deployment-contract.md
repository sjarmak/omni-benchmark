# Bulk semantic deployment: proposed contract and acceptance benchmark

## Decision this contract should support

Can Omni make large semantic-model deployment scale with changed bytes rather
than YAML-file count, while preserving validation, exact readback, atomic
visibility, and safe recovery? This is a product proposal and local acceptance
oracle. It is not evidence that an unimplemented Omni endpoint already meets the
contract.

Omni's current bulk-update guide says the create/update YAML endpoint writes one
file per request and that hundreds or thousands of files can take hours. The
recommended branch workflow avoids a git synchronization after every file and
preserves partial progress, but its documented loop still makes one API call per
file. The proposal below retains branch isolation while changing the transport.

## Observed benchmark baseline

The two successful R2 v1 arm directories each contain 16 terminal records with
1,750 planned files, 1,750 uploads, 1,750 exact-readback files, and zero failed
models. The records predate timing schema v3, so their request and phase timing
fields are **unavailable**, not zero. At the configured global minimum of 1.25
seconds between request starts, 1,750 upload requests alone imply a 2,186.25
second (36.44 minute) lower bound from first to last upload start per arm. That
excludes connection/model/branch setup, 16 validations, 16 or more readbacks,
response time, and retries.

This is exact evidence for one benchmark integration, account, CLI version, and
bundle shape. It is not a fleet-wide Omni latency estimate.

The aggregate, null-preserving evidence artifact is
`experiments/analysis/r2-deployment-throughput-v1.json`. Its exact request total
and phase seconds remain null; it reports 1,782 as a known per-arm lower bound
(1,750 writes plus one validation and one successful readback per model), while
excluding setup and retry calls.

## Proposed wire contract

All digests are lowercase SHA-256. IDs are opaque bounded strings. File paths
are relative, unique, and traversal-free. Unknown fields are rejected in
version 1.

### 1. Prepare

`POST /api/v1/models/{model_id}/branches/{branch_id}/semantic-sync`

```json
{
  "schema_version": 1,
  "idempotency_key": "client-generated stable key",
  "base_revision_sha256": "64 hex",
  "manifest": {
    "sha256": "64 hex",
    "files": [
      {"path": "orders.view", "sha256": "64 hex", "size_bytes": 1234}
    ]
  }
}
```

The server returns one of:

```json
{
  "status": "no_op | staged | conflict",
  "operation_id": "opaque or null",
  "resume_token": "opaque or null",
  "current_revision_sha256": "64 hex",
  "desired_revision_sha256": "64 hex",
  "changed_files": [{"path": "orders.view", "sha256": "64 hex"}],
  "deleted_paths": [],
  "error": null,
  "rate_limit": {"limit": 100, "remaining": 99, "retry_after_ms": null}
}
```

`conflict` is terminal for this base revision. `no_op` has empty changes and no
upload operation. `staged` creates no user-visible model revision.

### 2. Transfer changed content

`PUT /api/v1/semantic-sync/{operation_id}/content` accepts a compressed archive
or chunk containing multiple changed files. Every entry carries path, SHA-256,
size, and bytes. A client may repeat a chunk with the same resume token.

```json
{
  "status": "accepted | partial_failure",
  "operation_id": "opaque",
  "resume_token": "opaque",
  "accepted_sha256": ["64 hex"],
  "missing_sha256": ["64 hex"],
  "errors": [
    {
      "path": "orders.view",
      "code": "digest_mismatch | too_large | invalid_path | transport_interrupted",
      "retryable": true
    }
  ],
  "rate_limit": {"limit": 100, "remaining": 98, "retry_after_ms": 1200}
}
```

Free-form diagnostic text may accompany an error but is never the scored or
programmatic field. A content digest accepted once need not be retransmitted.

### 3. Validate and atomically commit

`POST /api/v1/semantic-sync/{operation_id}/commit`

```json
{
  "schema_version": 1,
  "idempotency_key": "same stable key",
  "resume_token": "latest opaque token",
  "desired_revision_sha256": "64 hex"
}
```

```json
{
  "status": "committed | validation_failed | conflict",
  "revision_sha256": "64 hex or prior revision",
  "changed_file_count": 42,
  "accepted_file_count": 42,
  "validation": {
    "issue_count": 0,
    "receipt_sha256": "64 hex or null",
    "issues": []
  },
  "readback": {
    "file_count": 1750,
    "manifest_sha256": "64 hex or null",
    "receipt_sha256": "64 hex or null"
  },
  "error": null
}
```

## Required invariants

1. The manifest digest binds sorted path, content digest, and byte size.
2. A base-revision mismatch never stages or publishes content.
3. Partial transfer never changes the visible branch revision.
4. A resume token is bound to target, idempotency key, base revision, and desired
   manifest. It cannot resume another operation.
5. Reusing an idempotency key with different inputs is rejected. Repeating the
   same completed request returns the same terminal response.
6. Commit occurs only when every desired digest is present and validation has
   no issues. The visible path set changes atomically, including deletions.
7. The readback receipt covers the complete canonical extension layer, not only
   changed files. A client can independently reproduce its digest.
8. Structured error code, retryability, and rate-limit metadata survive through
   the official CLI as machine-readable output.

The executable local oracle is
`src/omni_benchmark/bulk_semantic_contract.py`. Its tests cover no-op sync,
partial failure with invisible staging, idempotent resume, manifest/content
mismatch, and missing, extra, or changed readback files. It models the
invariants, not Omni's internal implementation.

## Benchmark telemetry schema

Deployment record schema v3 reports:

- counts: planned files, uploaded files, readback files, total CLI requests, and
  setup/upload/validation/readback requests;
- seconds: end-to-end elapsed, each product phase, and local orchestration;
- terminal status: validation issues, exact-readback status, failure stage, and
  safe failure class.

An observed absence is numeric zero. An unavailable observation is JSON `null`.
Legacy v1/v2 records therefore retain their exact file counts while request and
phase timing remain `null`; the benchmark never converts missing instrumentation
to zero. Phase seconds are summed work-seconds across database records and may
exceed arm wall time under parallelism. The arm summary reports wall time
separately.

## Product acceptance thresholds

- An unchanged manifest transfers zero content files and performs zero content
  upload requests.
- A partial transfer leaves the prior revision exactly readable; resume sends
  only missing content and commits once.
- Request count grows with bounded archive chunks, not with YAML-file count.
- Every successful commit returns zero validation issues and an independently
  reproducible complete-readback digest.
- Conflicts, digest mismatches, validation failures, throttling, and transport
  interruptions remain distinct typed outcomes.

The normal benchmark gate is the focused contract, deployment, and
predeployment test set. A full repository suite is reserved for release or a
broad cross-cutting change; this contract adds no new live-action ceremony.

## Sources

- [Omni bulk-update guide](https://docs.omni.co/guides/api/bulk-update-model-yaml)
- [Omni create/update YAML endpoint](https://docs.omni.co/api/models/create-or-update-yaml-files)
- [Omni get-model YAML endpoint](https://docs.omni.co/api/models/get-model-yaml)
