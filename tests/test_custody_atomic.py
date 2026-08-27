from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import omni_benchmark.custody as custody

from omni_benchmark.custody import CustodyError


release_selected_records = custody._release_selected_records


def private_record(instance_id: str, marker: str) -> dict[str, object]:
    return {
        "instance_id": instance_id,
        "sol_sql": [f"SELECT '{marker}'"],
        "test_cases": [{"hidden": marker}],
        "external_knowledge": [f"knowledge-{marker}"],
    }


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def test_atomic_publish_failure_leaves_no_destination_or_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "SECRET")])
    destination = workspace / "data" / "private" / "train.jsonl"

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("synthetic publish failure")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(CustodyError, match="could not atomically publish destination"):
        release_selected_records(
            source=source,
            destination=destination,
            train_ids={"train-1"},
            workspace=workspace,
        )

    assert not destination.exists()
    assert list(destination.parent.glob(".*.tmp")) == []


def test_atomic_publish_uses_directory_relative_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "SECRET")])
    destination = workspace / "data" / "private" / "nested" / "train.jsonl"
    original_link = os.link
    calls: list[tuple[object, object, object, object]] = []

    def record_link(
        source_name: object, destination_name: object, **kwargs: object
    ) -> None:
        calls.append(
            (
                source_name,
                destination_name,
                kwargs.get("src_dir_fd"),
                kwargs.get("dst_dir_fd"),
            )
        )
        original_link(source_name, destination_name, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "link", record_link)
    release_selected_records(
        source=source,
        destination=destination,
        train_ids={"train-1"},
        workspace=workspace,
    )

    assert len(calls) == 1
    source_name, destination_name, source_fd, destination_fd = calls[0]
    assert isinstance(source_name, str) and "/" not in source_name
    assert destination_name == "train.jsonl"
    assert isinstance(source_fd, int)
    assert source_fd == destination_fd


def test_atomic_publish_parent_swap_cannot_redirect_private_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "SECRET")])
    private_root = workspace / "data" / "private"
    destination = private_root / "nested" / "train.jsonl"
    outside = tmp_path / "outside"
    outside.mkdir()
    displaced = private_root / "displaced"
    original_link = os.link

    def swap_parent_then_link(
        source_name: object, destination_name: object, **kwargs: object
    ) -> None:
        destination.parent.rename(displaced)
        destination.parent.symlink_to(outside, target_is_directory=True)
        original_link(source_name, destination_name, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "link", swap_parent_then_link)
    with pytest.raises(
        CustodyError, match="destination directory changed during publication"
    ):
        release_selected_records(
            source=source,
            destination=destination,
            train_ids={"train-1"},
            workspace=workspace,
        )

    assert not (outside / "train.jsonl").exists()
    assert not (displaced / "train.jsonl").exists()
    assert list(displaced.glob(".*.tmp")) == []
