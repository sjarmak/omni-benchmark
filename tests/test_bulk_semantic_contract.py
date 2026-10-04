from __future__ import annotations

import pytest

from omni_benchmark.bulk_semantic_contract import (
    BulkSemanticContractError,
    BulkSemanticFile,
    ReferenceBulkSemanticService,
    build_bulk_sync_request,
    semantic_manifest_sha256,
    verify_bulk_readback,
)


def _files(**contents: str) -> tuple[BulkSemanticFile, ...]:
    return tuple(
        BulkSemanticFile.create(path, content.encode())
        for path, content in contents.items()
    )


def test_no_op_sync_observes_zero_changed_files_and_zero_upload_requests() -> None:
    initial = _files(**{"orders.view": "label: Orders\n"})
    service = ReferenceBulkSemanticService(initial)
    request = build_bulk_sync_request(
        target="model/branch",
        base_revision=service.revision,
        files=initial,
        idempotency_key="sync-001",
    )

    response = service.apply(request)

    assert response.status == "no_op"
    assert response.changed_file_count == 0
    assert response.accepted_file_count == 0
    assert response.upload_request_count == 0
    assert response.resume_token is None
    assert service.revision == request.manifest_sha256


def test_partial_failure_is_invisible_and_resume_commits_atomically() -> None:
    initial = _files(**{"orders.view": "label: Old\n"})
    desired = _files(
        **{
            "orders.view": "label: Orders\n",
            "orders.topic": "base_view: orders\n",
        }
    )
    service = ReferenceBulkSemanticService(initial)
    original_revision = service.revision
    request = build_bulk_sync_request(
        target="model/branch",
        base_revision=original_revision,
        files=desired,
        idempotency_key="sync-002",
    )

    partial = service.apply(request, fail_after=1)

    assert partial.status == "partial_failure"
    assert partial.accepted_file_count == 1
    assert partial.error_code == "transport_interrupted"
    assert partial.retryable is True
    assert partial.resume_token is not None
    assert service.revision == original_revision
    assert service.readback() == {"orders.view": b"label: Old\n"}

    completed = service.apply(request, resume_token=partial.resume_token)

    assert completed.status == "committed"
    assert completed.accepted_file_count == 2
    assert completed.changed_file_count == 2
    assert completed.upload_request_count == 1
    assert completed.validation_receipt_sha256 is not None
    assert completed.readback_receipt_sha256 == request.manifest_sha256
    assert service.revision == request.manifest_sha256
    assert verify_bulk_readback(request, service.readback()) == request.manifest_sha256


def test_resume_token_and_idempotency_key_are_bound_to_exact_manifest() -> None:
    service = ReferenceBulkSemanticService(())
    first = build_bulk_sync_request(
        target="model/branch",
        base_revision=service.revision,
        files=_files(**{"orders.view": "label: Orders\n"}),
        idempotency_key="sync-003",
    )
    partial = service.apply(first, fail_after=0)
    changed = build_bulk_sync_request(
        target="model/branch",
        base_revision=service.revision,
        files=_files(**{"orders.view": "label: Changed\n"}),
        idempotency_key="sync-003",
    )

    with pytest.raises(BulkSemanticContractError, match="idempotency"):
        service.apply(changed, resume_token=partial.resume_token)


def test_content_mismatch_is_rejected_before_staging() -> None:
    valid = BulkSemanticFile.create("orders.view", b"label: Orders\n")
    corrupted = BulkSemanticFile(
        path=valid.path,
        content=b"label: Corrupted\n",
        sha256=valid.sha256,
        size_bytes=valid.size_bytes,
    )

    with pytest.raises(BulkSemanticContractError, match="content SHA-256"):
        build_bulk_sync_request(
            target="model/branch",
            base_revision=semantic_manifest_sha256(()),
            files=(corrupted,),
            idempotency_key="sync-004",
        )


def test_exact_readback_rejects_missing_extra_or_changed_files() -> None:
    desired = _files(**{"orders.view": "label: Orders\n"})
    request = build_bulk_sync_request(
        target="model/branch",
        base_revision=semantic_manifest_sha256(()),
        files=desired,
        idempotency_key="sync-005",
    )

    with pytest.raises(BulkSemanticContractError, match="path set"):
        verify_bulk_readback(request, {})
    with pytest.raises(BulkSemanticContractError, match="path set"):
        verify_bulk_readback(
            request,
            {"orders.view": b"label: Orders\n", "extra.view": b"extra"},
        )
    with pytest.raises(BulkSemanticContractError, match="content differs"):
        verify_bulk_readback(request, {"orders.view": b"label: Wrong\n"})
