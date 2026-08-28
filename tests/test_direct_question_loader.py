from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.direct_question_loader import (
    DirectQuestionLoadError,
    load_committed_direct_question,
)


PUBLIC_FIELDS = {
    "category",
    "clean_up_sqls",
    "conditions",
    "high_level",
    "instance_id",
    "normal_query",
    "preprocess_sql",
    "query",
    "selected_database",
    "source_index",
}


def _canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def _record(instance_id: str, *, category: str = "Query") -> dict[str, object]:
    value = {
        "category": category,
        "clean_up_sqls": [],
        "conditions": {"decimal": 2, "distinct": False, "order": True},
        "high_level": False,
        "instance_id": instance_id,
        "normal_query": f"Normal public text for {instance_id}",
        "preprocess_sql": [],
        "query": f"Public question for {instance_id}",
        "selected_database": "archeology_scan_large",
        "source_index": 1,
    }
    assert set(value) == PUBLIC_FIELDS
    return value


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _git(workspace: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(workspace), *args],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()


def _repo(
    tmp_path: Path,
    *,
    records: list[dict[str, object]] | None = None,
    train: str = "dev-a-1\ndev-b-1\ntrain-1\n",
    dev_a: str = "dev-a-1\n",
    dev_b: str = "dev-b-1\n",
) -> tuple[Path, str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    manifest_records = records or [
        _record("dev-a-1"),
        _record("dev-b-1"),
        _record("train-1"),
        _record("test-1"),
    ]
    _write(
        workspace / "data/manifests/eligible_questions.jsonl",
        b"".join(_canonical(record) for record in manifest_records),
    )
    _write(workspace / "data/manifests/train_ids.txt", train.encode())
    _write(workspace / "data/manifests/dev_a_ids.txt", dev_a.encode())
    _write(workspace / "data/manifests/dev_b_ids.txt", dev_b.encode())
    _write(workspace / "data/manifests/test_ids.txt", b"test-1\n")
    config = {
        "dev_a_ids_path": "data/manifests/dev_a_ids.txt",
        "dev_b_ids_path": "data/manifests/dev_b_ids.txt",
        "public_manifest_path": "data/manifests/eligible_questions.jsonl",
        "test_ids_path": "data/manifests/test_ids.txt",
        "train_ids_path": "data/manifests/train_ids.txt",
    }
    _write(workspace / "config/autoresearch.json", _canonical(config))
    _git(workspace, "init", "-q")
    _git(workspace, "config", "user.email", "test@example.test")
    _git(workspace, "config", "user.name", "Test")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "fixture")
    return workspace, _git(workspace, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    ("scope", "instance_id", "scope_path"),
    [
        ("train", "train-1", "data/manifests/train_ids.txt"),
        ("dev-a", "dev-a-1", "data/manifests/dev_a_ids.txt"),
        ("dev-b", "dev-b-1", "data/manifests/dev_b_ids.txt"),
    ],
)
def test_loader_binds_exact_committed_question_and_scope(
    tmp_path: Path, scope: str, instance_id: str, scope_path: str
) -> None:
    workspace, commit = _repo(tmp_path)

    identity = load_committed_direct_question(
        workspace, commit, scope=scope, instance_id=instance_id, environment={}
    )

    manifest = workspace / "data/manifests/eligible_questions.jsonl"
    ids = workspace / scope_path
    selected = _record(instance_id)
    assert identity.scope == scope
    assert identity.instance_id == instance_id
    assert identity.question == selected["query"]
    assert identity.selected_database == "archeology_scan_large"
    assert identity.public_manifest_path == manifest.relative_to(workspace).as_posix()
    assert (
        identity.public_manifest_sha256
        == hashlib.sha256(manifest.read_bytes()).hexdigest()
    )
    assert (
        identity.public_record_sha256
        == hashlib.sha256(_canonical(selected)).hexdigest()
    )
    assert identity.scope_ids_path == scope_path
    assert identity.scope_ids_sha256 == hashlib.sha256(ids.read_bytes()).hexdigest()


def test_loader_rejects_test_scope_and_test_membership(tmp_path: Path) -> None:
    workspace, commit = _repo(tmp_path)

    with pytest.raises(DirectQuestionLoadError, match="development scope"):
        load_committed_direct_question(
            workspace, commit, scope="test", instance_id="test-1", environment={}
        )
    with pytest.raises(DirectQuestionLoadError, match="not a member"):
        load_committed_direct_question(
            workspace, commit, scope="train", instance_id="test-1", environment={}
        )


@pytest.mark.parametrize(
    ("records", "message"),
    [
        ([_record("dev-a-1"), _record("dev-a-1")], "duplicate instance_id"),
        ([_record("dev-a-1", category="Management")], "must be Query"),
        (
            [{**_record("dev-a-1"), "external_knowledge": []}],
            "forbidden field",
        ),
        (
            [{**_record("dev-a-1"), "conditions": {"gold_sql": "SELECT 1"}}],
            "forbidden field",
        ),
        ([{**_record("dev-a-1"), "unexpected": True}], "exact public schema"),
    ],
)
def test_loader_rejects_ineligible_duplicate_or_forbidden_public_records(
    tmp_path: Path, records: list[dict[str, object]], message: str
) -> None:
    workspace, commit = _repo(
        tmp_path,
        records=records,
        train="dev-a-1\n",
        dev_a="dev-a-1\n",
        dev_b="other\n",
    )

    with pytest.raises(DirectQuestionLoadError, match=message):
        load_committed_direct_question(
            workspace, commit, scope="dev-a", instance_id="dev-a-1", environment={}
        )


@pytest.mark.parametrize(
    ("train", "dev_a", "message"),
    [
        ("dev-a-1\ndev-a-1\n", "dev-a-1\n", "duplicate ID"),
        ("dev-a-1\n", "dev-a-1\ndev-a-1\n", "duplicate ID"),
        ("other\n", "dev-a-1\n", "subset of train"),
        ("dev-a-1\n", "other\n", "subset of train"),
    ],
)
def test_loader_rejects_invalid_scope_membership(
    tmp_path: Path, train: str, dev_a: str, message: str
) -> None:
    workspace, commit = _repo(
        tmp_path,
        train=train,
        dev_a=dev_a,
        dev_b="other\n",
        records=[_record("dev-a-1"), _record("other")],
    )

    with pytest.raises(DirectQuestionLoadError, match=message):
        load_committed_direct_question(
            workspace, commit, scope="dev-a", instance_id="dev-a-1", environment={}
        )


def test_loader_rejects_manifest_or_scope_drift_after_commit(tmp_path: Path) -> None:
    workspace, commit = _repo(tmp_path)
    manifest = workspace / "data/manifests/eligible_questions.jsonl"
    manifest.write_bytes(manifest.read_bytes() + _canonical(_record("injected")))

    with pytest.raises(DirectQuestionLoadError, match="current bytes"):
        load_committed_direct_question(
            workspace, commit, scope="dev-a", instance_id="dev-a-1", environment={}
        )

    _git(workspace, "checkout", "--", manifest.relative_to(workspace).as_posix())
    ids = workspace / "data/manifests/dev_a_ids.txt"
    ids.write_text("dev-a-1\ninjected\n", encoding="utf-8")
    with pytest.raises(DirectQuestionLoadError, match="current bytes"):
        load_committed_direct_question(
            workspace, commit, scope="dev-a", instance_id="dev-a-1", environment={}
        )


def test_loader_rejects_requested_id_outside_valid_scope(tmp_path: Path) -> None:
    workspace, commit = _repo(
        tmp_path,
        train="dev-a-1\nother\n",
        dev_a="other\n",
        dev_b="dev-a-1\n",
        records=[_record("dev-a-1"), _record("other")],
    )

    with pytest.raises(DirectQuestionLoadError, match="not a member"):
        load_committed_direct_question(
            workspace, commit, scope="dev-a", instance_id="dev-a-1", environment={}
        )


def test_loader_rejects_noncanonical_or_test_path_configuration(tmp_path: Path) -> None:
    workspace, _ = _repo(tmp_path)
    config = workspace / "config/autoresearch.json"
    value = json.loads(config.read_text())
    value["dev_a_ids_path"] = "data/manifests/test_ids.txt"
    config.write_bytes(_canonical(value))
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "malicious path")
    commit = _git(workspace, "rev-parse", "HEAD")

    with pytest.raises(DirectQuestionLoadError, match="canonical dev-a"):
        load_committed_direct_question(
            workspace, commit, scope="dev-a", instance_id="test-1", environment={}
        )


def test_loader_rejects_sensitive_or_nonfinite_public_content(tmp_path: Path) -> None:
    secret_record = _record("dev-a-1")
    secret_record["query"] = "fixture-live-secret"
    workspace, commit = _repo(
        tmp_path,
        records=[secret_record],
        train="dev-a-1\n",
        dev_a="dev-a-1\n",
        dev_b="other\n",
    )
    with pytest.raises(DirectQuestionLoadError, match="sensitive content"):
        load_committed_direct_question(
            workspace,
            commit,
            scope="dev-a",
            instance_id="dev-a-1",
            environment={"BENCHMARK_TOKEN": "fixture-live-secret"},
        )

    workspace, commit = _repo(
        tmp_path / "nonfinite",
        records=[_record("dev-a-1")],
        train="dev-a-1\n",
        dev_a="dev-a-1\n",
        dev_b="other\n",
    )
    nonfinite = _record("dev-a-1")
    nonfinite["source_index"] = float("nan")
    manifest = workspace / "data/manifests/eligible_questions.jsonl"
    manifest.write_text(json.dumps(nonfinite, allow_nan=True) + "\n", encoding="utf-8")
    _git(workspace, "add", ".")
    _git(workspace, "commit", "-qm", "nonfinite fixture")
    commit = _git(workspace, "rev-parse", "HEAD")
    with pytest.raises(DirectQuestionLoadError, match="finite JSON"):
        load_committed_direct_question(
            workspace, commit, scope="dev-a", instance_id="dev-a-1", environment={}
        )
