from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path

import pytest
import omni_benchmark.custody as custody

from omni_benchmark.custody import (
    CustodyError,
    load_dev_a_records,
    read_id_file,
    release_main,
)


load_train_records = load_dev_a_records
release_train_records = custody._release_selected_records


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


def test_release_emits_only_train_records_with_hashes_and_mode_0600(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    destination = workspace / "data" / "private" / "train.jsonl"
    destination.parent.mkdir(parents=True)
    source = tmp_path / "human-custody" / "attachment.jsonl"
    source.parent.mkdir()
    write_jsonl(
        source,
        [
            private_record("test-1", "TEST-MUST-NOT-BE-RELEASED"),
            private_record("train-2", "TRAIN-TWO"),
            private_record("train-1", "TRAIN-ONE"),
        ],
    )

    report = release_train_records(
        source=source,
        destination=destination,
        train_ids={"train-1", "train-2"},
        workspace=workspace,
    )

    released = [json.loads(line) for line in destination.read_text().splitlines()]
    assert [record["instance_id"] for record in released] == ["train-1", "train-2"]
    assert b"TEST-MUST-NOT-BE-RELEASED" not in destination.read_bytes()
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert report.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report.output_sha256 == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert report.source_count == 3
    assert report.released_count == 2
    assert report.ignored_count == 1


def test_release_projects_exact_private_contract_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = workspace / "data" / "private" / "train.jsonl"
    source = tmp_path / "attachment.jsonl"
    record = private_record("train-1", "TRAIN")
    record.update(
        {
            "query": "unexpected public question",
            "selected_database": "unexpected_database",
            "unexpected_private_payload": "MUST-NOT-BE-COPIED",
        }
    )
    write_jsonl(source, [record])

    release_train_records(
        source=source,
        destination=destination,
        train_ids={"train-1"},
        workspace=workspace,
    )

    released = json.loads(destination.read_text(encoding="utf-8"))
    assert set(released) == {
        "instance_id",
        "sol_sql",
        "test_cases",
        "external_knowledge",
    }
    assert "MUST-NOT-BE-COPIED" not in destination.read_text(encoding="utf-8")


def test_release_membership_checks_foreign_records_before_hidden_shape_validation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    destination = workspace / "data" / "private" / "train.jsonl"
    source = tmp_path / "attachment.jsonl"
    write_jsonl(
        source,
        [
            {
                "instance_id": "test-1",
                "sol_sql": "TEST-HIDDEN-SHAPE-MUST-NOT-BE-INSPECTED",
            },
            private_record("train-1", "TRAIN"),
        ],
    )

    report = release_train_records(
        source=source,
        destination=destination,
        train_ids={"train-1"},
        workspace=workspace,
    )

    assert report.ignored_count == 1
    assert json.loads(destination.read_text(encoding="utf-8"))["instance_id"] == (
        "train-1"
    )


def test_release_rejects_destination_outside_workspace_private_root(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "SECRET")])
    destination = workspace / "train.jsonl"

    with pytest.raises(
        CustodyError, match="destination must resolve inside workspace/data/private"
    ):
        release_train_records(
            source=source,
            destination=destination,
            train_ids={"train-1"},
            workspace=workspace,
        )

    assert not destination.exists()


def test_release_rejects_private_destination_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    private_root = workspace / "data" / "private"
    private_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (private_root / "escape").symlink_to(outside, target_is_directory=True)
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "SECRET")])
    destination = private_root / "escape" / "train.jsonl"

    with pytest.raises(
        CustodyError, match="destination must resolve inside workspace/data/private"
    ):
        release_train_records(
            source=source,
            destination=destination,
            train_ids={"train-1"},
            workspace=workspace,
        )

    assert not (outside / "train.jsonl").exists()


def test_release_rejects_destination_equal_to_a_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    destination = workspace / "data" / "private" / "train.jsonl"
    destination.mkdir(parents=True)
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "SECRET")])

    with pytest.raises(CustodyError, match="destination must be a file path"):
        release_train_records(
            source=source,
            destination=destination,
            train_ids={"train-1"},
            workspace=workspace,
        )


def test_release_rejects_a_source_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "DO-NOT-LEAK")])

    with pytest.raises(
        CustodyError, match="source must resolve outside the workspace"
    ) as error:
        release_train_records(
            source=source,
            destination=workspace / "train.jsonl",
            train_ids={"train-1"},
            workspace=workspace,
        )

    assert "DO-NOT-LEAK" not in str(error.value)


def test_release_refuses_to_overwrite_an_existing_destination(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "DO-NOT-LEAK")])
    destination = workspace / "data" / "private" / "train.jsonl"
    destination.parent.mkdir(parents=True)
    destination.write_text("keep me", encoding="utf-8")

    with pytest.raises(CustodyError, match="destination already exists"):
        release_train_records(
            source=source,
            destination=destination,
            train_ids={"train-1"},
            workspace=workspace,
        )

    assert destination.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize(
    ("records", "train_ids", "message"),
    [
        (
            [private_record("train-1", "SECRET"), private_record("train-1", "SECRET")],
            {"train-1"},
            "duplicate instance_id",
        ),
        ([private_record("other", "SECRET")], {"train-1"}, "missing 1 train records"),
        (
            [{"instance_id": "train-1", "sol_sql": ["SECRET"], "test_cases": []}],
            {"train-1"},
            "missing required fields",
        ),
        (
            [
                {
                    "instance_id": "train-1",
                    "sol_sql": "SECRET",
                    "test_cases": [],
                    "external_knowledge": [],
                }
            ],
            {"train-1"},
            "sol_sql must be an array",
        ),
        (
            [
                {
                    "instance_id": "train-1",
                    "sol_sql": [1],
                    "test_cases": [],
                    "external_knowledge": [],
                }
            ],
            {"train-1"},
            "sol_sql must be an array of strings",
        ),
        (
            [
                {
                    "instance_id": "train-1",
                    "sol_sql": ["SELECT 1"],
                    "test_cases": [],
                    "external_knowledge": [{"hidden": "SECRET"}],
                }
            ],
            {"train-1"},
            "external_knowledge must be an array of strings",
        ),
        (
            [
                {
                    "instance_id": "train-1",
                    "sol_sql": ["SELECT 1"],
                    "test_cases": "SECRET",
                    "external_knowledge": [],
                }
            ],
            {"train-1"},
            "test_cases must be an array",
        ),
        (
            [
                {
                    "instance_id": "train-1",
                    "sol_sql": ["SELECT 1"],
                    "test_cases": [],
                    "external_knowledge": "SECRET",
                }
            ],
            {"train-1"},
            "external_knowledge must be an array",
        ),
    ],
)
def test_release_rejects_invalid_sources_without_leaking_hidden_values(
    tmp_path: Path,
    records: list[dict[str, object]],
    train_ids: set[str],
    message: str,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, records)

    with pytest.raises(CustodyError, match=message) as error:
        release_train_records(
            source=source,
            destination=workspace / "data" / "private" / "train.jsonl",
            train_ids=train_ids,
            workspace=workspace,
        )

    assert "SECRET" not in str(error.value)
    assert not (workspace / "data" / "private" / "train.jsonl").exists()


def test_release_rejects_malformed_json_without_echoing_the_line(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    source.write_text('{"sol_sql":"DO-NOT-LEAK"\n', encoding="utf-8")

    with pytest.raises(CustodyError, match="line 1 is not valid JSON") as error:
        release_train_records(
            source=source,
            destination=workspace / "data" / "private" / "train.jsonl",
            train_ids={"train-1"},
            workspace=workspace,
        )

    assert "DO-NOT-LEAK" not in str(error.value)


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([], "private source contains no records"),
        ([[]], "record must be a JSON object"),
        ([{"instance_id": ""}], "instance_id must be a non-empty string"),
    ],
)
def test_release_rejects_sources_without_usable_membership_keys(
    tmp_path: Path, records: list[object], message: str
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    source.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    with pytest.raises(CustodyError, match=message):
        release_train_records(
            source=source,
            destination=workspace / "data" / "private" / "train.jsonl",
            train_ids={"train-1"},
            workspace=workspace,
        )


def test_loader_requires_exact_train_partition_and_returns_deeply_immutable_data(
    tmp_path: Path,
) -> None:
    source = tmp_path / "train.jsonl"
    write_jsonl(
        source,
        [
            private_record("train-2", "TWO"),
            private_record("train-1", "ONE"),
        ],
    )

    records = load_train_records(source, {"train-1", "train-2"})

    assert tuple(records) == ("train-1", "train-2")
    assert records["train-1"]["sol_sql"] == ("SELECT 'ONE'",)
    with pytest.raises(TypeError):
        records["train-1"]["instance_id"] = "changed"  # type: ignore[index]
    with pytest.raises(AttributeError):
        records["train-1"]["test_cases"].append({})  # type: ignore[union-attr]
    with pytest.raises(TypeError):
        records["train-1"]["test_cases"][0]["hidden"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("records", "train_ids", "message"),
    [
        (
            [private_record("train-1", "ONE"), private_record("test-1", "TEST")],
            {"train-1"},
            "record outside the committed train partition",
        ),
        (
            [private_record("train-1", "ONE"), private_record("train-1", "TWO")],
            {"train-1"},
            "duplicate instance_id",
        ),
        (
            [private_record("train-1", "ONE")],
            {"train-1", "train-2"},
            "missing 1 train records",
        ),
    ],
)
def test_loader_rejects_foreign_duplicate_and_missing_records(
    tmp_path: Path,
    records: list[dict[str, object]],
    train_ids: set[str],
    message: str,
) -> None:
    source = tmp_path / "train.jsonl"
    write_jsonl(source, records)

    with pytest.raises(CustodyError, match=message):
        load_train_records(source, train_ids)


def test_loader_rejects_foreign_membership_before_hidden_shape_validation(
    tmp_path: Path,
) -> None:
    source = tmp_path / "train.jsonl"
    write_jsonl(
        source,
        [
            private_record("train-1", "ONE"),
            {
                "instance_id": "test-1",
                "sol_sql": "TEST-HIDDEN-SHAPE-MUST-NOT-BE-INSPECTED",
            },
        ],
    )

    with pytest.raises(
        CustodyError, match="record outside the committed train partition"
    ):
        load_train_records(source, {"train-1"})


def test_read_id_file_rejects_blank_and_duplicate_ids(tmp_path: Path) -> None:
    blank = tmp_path / "blank.txt"
    blank.write_text("train-1\n\ntrain-2\n", encoding="utf-8")
    duplicate = tmp_path / "duplicate.txt"
    duplicate.write_text("train-1\ntrain-1\n", encoding="utf-8")

    with pytest.raises(CustodyError, match="blank ID at line 2"):
        read_id_file(blank)
    with pytest.raises(CustodyError, match="duplicate ID at line 2"):
        read_id_file(duplicate)


def test_read_id_file_rejects_missing_and_empty_files(tmp_path: Path) -> None:
    with pytest.raises(CustodyError, match="cannot read train ID file"):
        read_id_file(tmp_path / "missing.txt")

    empty = tmp_path / "empty.txt"
    empty.touch()
    with pytest.raises(CustodyError, match="train ID file is empty"):
        read_id_file(empty)


@pytest.mark.parametrize("train_ids", [[], ["train-1", "train-1"], [1]])
def test_release_rejects_ambiguous_train_id_inputs(
    tmp_path: Path, train_ids: list[object]
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "SECRET")])

    with pytest.raises(CustodyError):
        release_train_records(
            source=source,
            destination=workspace / "data" / "private" / "train.jsonl",
            train_ids=train_ids,  # type: ignore[arg-type]
            workspace=workspace,
        )


def initialise_git_workspace(
    workspace: Path, dev_a_ids: str, *, guardian_pin: str = "a" * 64
) -> Path:
    workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=workspace, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace, check=True)
    id_file = workspace / "data" / "manifests" / "dev_a_ids.txt"
    id_file.parent.mkdir(parents=True)
    id_file.write_text(dev_a_ids, encoding="utf-8")
    development_split_metadata = {
        "artifacts": {
            "dev_a_ids": {
                "file": "dev_a_ids.txt",
                "sha256": hashlib.sha256(id_file.read_bytes()).hexdigest(),
            }
        }
    }
    (id_file.parent / "development_split_metadata.json").write_text(
        json.dumps(development_split_metadata, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    config = workspace / "config" / "autoresearch.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps({"guardian_public_key_sha256": guardian_pin}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "add",
            "config/autoresearch.json",
            "data/manifests/dev_a_ids.txt",
            "data/manifests/development_split_metadata.json",
        ],
        cwd=workspace,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "test: freeze split"], cwd=workspace, check=True
    )
    return id_file


def current_git_commit(workspace: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_documented_release_exposes_only_dev_a_labels() -> None:
    repository = Path(__file__).resolve().parents[1]
    readme = (repository / "README.md").read_text(encoding="utf-8")
    protocol = (repository / "EVALUATION_PROTOCOL.md").read_text(encoding="utf-8")

    assert "--dev-a-ids data/manifests/dev_a_ids.txt" in readme
    assert "--train-ids" not in readme
    assert "data/private/dev-a/labels.jsonl" in readme
    assert "only the 154 dev-A records" in protocol
    assert "only the 231 train records" not in protocol


def test_release_cli_rejects_a_committed_non_dev_a_id_manifest(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    initialise_git_workspace(workspace, "train-1\n")
    train_ids = workspace / "data" / "manifests" / "train_ids.txt"
    train_ids.write_text("train-1\ndev-b-1\n", encoding="utf-8")
    subprocess.run(["git", "add", str(train_ids)], cwd=workspace, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "test: add full development IDs"],
        cwd=workspace,
        check=True,
    )
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("dev-b-1", "MUST-NOT-RELEASE")])
    destination = workspace / "data" / "private" / "dev-a.jsonl"

    with pytest.raises(CustodyError, match="canonical dev-A ID manifest"):
        release_main(
            [
                "--source",
                str(source),
                "--dev-a-ids",
                str(train_ids),
                "--destination",
                str(destination),
                "--workspace",
                str(workspace),
                "--freeze-a-commit",
                current_git_commit(workspace),
            ]
        )

    assert not destination.exists()


def test_release_cli_accepts_only_committed_ids_and_prints_counts_and_hashes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "workspace"
    id_file = initialise_git_workspace(workspace, "train-1\n")
    source = tmp_path / "attachment.jsonl"
    write_jsonl(
        source,
        [
            private_record("train-1", "DEV-A-SECRET"),
            {
                "instance_id": "dev-b-1",
                "sol_sql": "DEV-B-HIDDEN-SHAPE-MUST-NOT-BE-INSPECTED",
            },
            private_record("test-1", "TEST-SECRET"),
        ],
    )
    destination = workspace / "data" / "private" / "dev-a" / "records.jsonl"
    destination.parent.mkdir(parents=True)

    assert (
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
                current_git_commit(workspace),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    summary = json.loads(output)
    assert set(summary) == {"counts", "output_sha256", "source_sha256"}
    assert summary["counts"] == {"ignored": 2, "released": 1, "source": 3}
    assert "DEV-A-SECRET" not in output
    assert "DEV-B-HIDDEN-SHAPE-MUST-NOT-BE-INSPECTED" not in output
    assert "TEST-SECRET" not in output
    released = destination.read_text(encoding="utf-8")
    assert "DEV-A-SECRET" in released
    assert "DEV-B-HIDDEN-SHAPE-MUST-NOT-BE-INSPECTED" not in released
    assert "TEST-SECRET" not in released


def test_release_cli_uses_committed_id_snapshot_after_worktree_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    id_file = initialise_git_workspace(workspace, "dev-a-1\n")
    source = tmp_path / "attachment.jsonl"
    write_jsonl(
        source,
        [
            private_record("dev-a-1", "DEV-A-SECRET"),
            private_record("dev-b-1", "DEV-B-MUST-NOT-BE-RELEASED"),
        ],
    )
    destination = workspace / "data" / "private" / "dev-a" / "records.jsonl"
    original_verify = custody._verify_committed_dev_a_ids

    def swap_after_verification(*args, **kwargs):
        verified = original_verify(*args, **kwargs)
        id_file.write_text("dev-b-1\n", encoding="utf-8")
        return verified

    monkeypatch.setattr(custody, "_verify_committed_dev_a_ids", swap_after_verification)

    assert (
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
                current_git_commit(workspace),
            ]
        )
        == 0
    )

    released = destination.read_text(encoding="utf-8")
    assert "DEV-A-SECRET" in released
    assert "DEV-B-MUST-NOT-BE-RELEASED" not in released


def test_release_cli_rejects_unprovisioned_guardian_before_private_source_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    id_file = initialise_git_workspace(
        workspace,
        "train-1\n",
        guardian_pin="UNPROVISIONED",
    )
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-1", "MUST-NOT-BE-READ")])
    source_read = False

    def reject_private_read(*args, **kwargs):
        nonlocal source_read
        source_read = True
        raise AssertionError("private source was opened before Freeze A validation")

    monkeypatch.setattr(custody, "_read_private_jsonl", reject_private_read)

    with pytest.raises(CustodyError, match="guardian key.*provisioned"):
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

    assert source_read is False


def test_release_cli_rejects_dev_a_ids_changed_since_commit(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    id_file = initialise_git_workspace(workspace, "train-1\n")
    id_file.write_text("train-2\n", encoding="utf-8")
    source = tmp_path / "attachment.jsonl"
    write_jsonl(source, [private_record("train-2", "SECRET")])

    with pytest.raises(CustodyError, match="recorded Freeze-A commit"):
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
