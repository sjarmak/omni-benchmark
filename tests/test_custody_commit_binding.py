from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.custody import CustodyError, release_main

from .test_custody import (
    current_git_commit,
    initialise_git_workspace,
    private_record,
    write_jsonl,
)


def test_release_cli_rejects_dev_a_ids_not_bound_by_committed_split_metadata(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    id_file = initialise_git_workspace(workspace, "train-1\n")
    metadata_file = id_file.parent / "development_split_metadata.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    metadata["artifacts"]["dev_a_ids"]["sha256"] = "0" * 64
    metadata_file.write_text(
        json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", str(metadata_file)], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "test: corrupt split binding"],
        cwd=workspace,
        check=True,
    )
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "SECRET")])

    with pytest.raises(CustodyError, match="split metadata does not bind"):
        release_main(
            [
                "--source",
                str(source),
                "--dev-a-ids",
                str(id_file),
                "--destination",
                str(workspace / "data" / "private" / "dev-a.jsonl"),
                "--workspace",
                str(workspace),
                "--freeze-a-commit",
                current_git_commit(workspace),
            ]
        )


def test_release_cli_rejects_post_freeze_partition_reclassification(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    id_file = initialise_git_workspace(workspace, "train-1\n")
    freeze_a_commit = current_git_commit(workspace)
    id_file.write_text("test-1\n", encoding="utf-8")
    metadata_file = id_file.parent / "development_split_metadata.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    metadata["artifacts"]["dev_a_ids"]["sha256"] = hashlib.sha256(
        id_file.read_bytes()
    ).hexdigest()
    metadata_file.write_text(
        json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8"
    )
    subprocess.run(
        ["git", "add", str(id_file), str(metadata_file)], cwd=workspace, check=True
    )
    subprocess.run(
        ["git", "commit", "-qm", "test: attempt reclassification"],
        cwd=workspace,
        check=True,
    )
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("test-1", "MUST-NOT-RELEASE")])
    destination = workspace / "data" / "private" / "dev-a.jsonl"

    with pytest.raises(CustodyError, match="recorded Freeze-A commit"):
        release_main(
            [
                "--source",
                str(source),
                "--dev-a-ids",
                str(id_file),
                "--destination",
                str(destination),
                "--workspace",
                str(workspace),
                "--freeze-a-commit",
                freeze_a_commit,
            ]
        )

    assert not destination.exists()
