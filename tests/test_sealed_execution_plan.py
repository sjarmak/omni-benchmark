from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from omni_benchmark.freeze_b import FreezeBManifest, schedule_sha256
from omni_benchmark.freeze_b_schedule import expected_schedule_bytes
from omni_benchmark.scoring import scorer_metadata
from omni_benchmark.sealed_execution_plan import (
    SealedExecutionPlanError,
    load_sealed_execution_plan,
    load_sealed_public_questions,
    plan_main,
)


SHA_A = "a" * 64
SEED = "human-supplied-final-seed"


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _test_ids() -> bytes:
    return "".join(f"q-{index:03d}\n" for index in range(1, 102)).encode()


def _eligible_records() -> list[dict[str, object]]:
    return [
        {
            "category": "synthetic-public",
            "clean_up_sqls": [],
            "conditions": [],
            "high_level": False,
            "instance_id": f"q-{index:03d}",
            "normal_query": "",
            "preprocess_sql": [],
            "query": f"Public synthetic question {index}?",
            "selected_database": f"db-{((index - 1) % 7) + 1}",
            "source_index": index,
        }
        for index in range(1, 102)
    ]


def _jsonl(records: list[dict[str, object]]) -> bytes:
    return b"".join(
        (
            json.dumps(
                record,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode()
        for record in records
    )


def _condition(condition: str) -> dict[str, object]:
    return {
        "budget_id": "sealed-default-v1",
        "condition": condition,
        "harness_config_sha256": SHA_A,
        "instructions_sha256": SHA_A,
        "model": "managed-standard",
        "model_config_id": "frozen-final-v1",
        "prompt_sha256": SHA_A,
        "provider": "aws-bedrock",
        "runtime_policy_sha256": SHA_A,
        "semantic_model_ref": "none" if condition == "C1" else "export:final-v1",
        "semantic_model_sha256": None if condition == "C1" else SHA_A,
    }


def _manifest(
    system_commit: str,
    freeze_a_commit: str,
    *,
    seed: str,
    schedule_content: bytes,
    test_ids_content: bytes,
    eligible_content: bytes,
    frozen_override: dict[str, str] | None = None,
) -> FreezeBManifest:
    registered_schedule = expected_schedule_bytes(test_ids_content, seed)
    attempt_ids = tuple(
        str(json.loads(line)["attempt_id"]) for line in registered_schedule.splitlines()
    )
    frozen = {
        "data/final-schedule.jsonl": hashlib.sha256(schedule_content).hexdigest(),
        "data/manifests/eligible_questions.jsonl": hashlib.sha256(
            eligible_content
        ).hexdigest(),
        "data/manifests/test_ids.txt": hashlib.sha256(test_ids_content).hexdigest(),
    }
    if frozen_override is not None:
        frozen = frozen_override
    return FreezeBManifest.from_dict(
        {
            "conditions": [
                _condition(condition) for condition in ("C1", "C2", "C3", "C4")
            ],
            "database": {
                "libpq_version": "18.6",
                "postgresql_version": "18.6",
                "snapshot_manifest_sha256": SHA_A,
            },
            "expected_test_outputs": 1_212,
            "freeze_a_commit": freeze_a_commit,
            "frozen_files": frozen,
            "kind": "freeze-b-manifest",
            "question_count": 101,
            "recorded_at": "2026-08-29T06:35:00Z",
            "repetitions": 3,
            "schedule": {
                "algorithm": "committed_block_interleaved_v1",
                "seed": seed,
                "sha256": schedule_sha256(attempt_ids),
            },
            "schema_version": 1,
            "scorer": {
                "metadata": scorer_metadata(),
                "source_commit": system_commit,
            },
            "system_commit": system_commit,
        }
    )


def _repository(
    tmp_path: Path,
    *,
    seed: str = SEED,
    test_ids_content: bytes | None = None,
    schedule_content: bytes | None = None,
    eligible_records: list[dict[str, object]] | None = None,
    eligible_raw: bytes | None = None,
    frozen_override: dict[str, str] | None = None,
    plan_source_override: bytes | None = None,
    symlink_input: str | None = None,
) -> tuple[Path, str, str, FreezeBManifest]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Sealed Plan Test")
    _git(repo, "config", "user.email", "plan@example.invalid")
    (repo / "freeze-a.txt").write_text("freeze a\n", encoding="utf-8")
    _git(repo, "add", "freeze-a.txt")
    _git(repo, "commit", "-qm", "freeze a")
    freeze_a_commit = _git(repo, "rev-parse", "HEAD")

    project = Path(__file__).parents[1]
    for relative in (
        "src/omni_benchmark/autoresearch_config.py",
        "src/omni_benchmark/content_policy.py",
        "src/omni_benchmark/freeze_b.py",
        "src/omni_benchmark/freeze_b_control.py",
        "src/omni_benchmark/freeze_b_record.py",
        "src/omni_benchmark/freeze_b_schedule.py",
        "src/omni_benchmark/protected_fields.py",
        "src/omni_benchmark/scoring.py",
        "src/omni_benchmark/sealed_execution_plan.py",
    ):
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = (project / relative).read_bytes()
        if relative.endswith("sealed_execution_plan.py") and plan_source_override:
            content = plan_source_override
        destination.write_bytes(content)

    ids = _test_ids() if test_ids_content is None else test_ids_content
    schedule = (
        expected_schedule_bytes(ids, seed)
        if schedule_content is None
        else schedule_content
    )
    eligible = (
        _jsonl(_eligible_records() if eligible_records is None else eligible_records)
        if eligible_raw is None
        else eligible_raw
    )
    inputs = {
        "data/final-schedule.jsonl": schedule,
        "data/manifests/eligible_questions.jsonl": eligible,
        "data/manifests/test_ids.txt": ids,
    }
    for relative, content in inputs.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    if symlink_input is not None:
        path = repo / symlink_input
        path.unlink()
        path.symlink_to("missing-input")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "frozen system")
    system_commit = _git(repo, "rev-parse", "HEAD")

    manifest = _manifest(
        system_commit,
        freeze_a_commit,
        seed=seed,
        schedule_content=schedule,
        test_ids_content=ids,
        eligible_content=eligible,
        frozen_override=frozen_override,
    )
    manifest_path = repo / "experiments/freeze-b.json"
    manifest_path.parent.mkdir()
    manifest_path.write_bytes(manifest.canonical_bytes())
    _git(repo, "add", "experiments/freeze-b.json")
    _git(repo, "commit", "-qm", "Freeze B control")
    return repo, system_commit, _git(repo, "rev-parse", "HEAD"), manifest


def _load(repo: Path, system: str, control: str):  # type: ignore[no-untyped-def]
    return load_sealed_execution_plan(
        repo,
        control_commit=control,
        system_commit=system,
        freeze_b_path=Path("experiments/freeze-b.json"),
        schedule_path=Path("data/final-schedule.jsonl"),
        public_manifest_path=Path("data/manifests/eligible_questions.jsonl"),
    )


def test_plan_binds_exact_order_cohorts_databases_and_question_digests(
    tmp_path: Path,
) -> None:
    repo, system, control, manifest = _repository(tmp_path)
    (repo / "data/final-schedule.jsonl").write_text("substituted\n")
    (repo / "data/manifests/eligible_questions.jsonl").write_text("substituted\n")

    plan = _load(repo, system, control)

    assert plan.control_commit == control
    assert plan.system_commit == system
    assert plan.freeze_b_sha256 == manifest.sha256()
    assert len(plan.attempts) == 1_212
    assert plan.schedule_sha256 == manifest.schedule_sha256
    assert Counter(attempt.condition for attempt in plan.attempts) == {
        condition: 303 for condition in ("C1", "C2", "C3", "C4")
    }
    assert Counter(attempt.repetition for attempt in plan.attempts) == {
        repetition: 404 for repetition in (1, 2, 3)
    }
    assert Counter(attempt.cohort_id for attempt in plan.attempts) == {
        f"sealed-{condition.lower()}-r{repetition}": 101
        for condition in ("C1", "C2", "C3", "C4")
        for repetition in (1, 2, 3)
    }
    first = plan.attempts[0]
    expected_question = next(
        record["query"]
        for record in _eligible_records()
        if record["instance_id"] == first.instance_id
    )
    assert (
        first.question_sha256
        == hashlib.sha256(str(expected_question).encode()).hexdigest()
    )
    assert {attempt.database for attempt in plan.attempts} == {
        f"db-{index}" for index in range(1, 8)
    }
    assert len(plan.sha256) == 64


def test_public_questions_load_from_frozen_git_and_match_every_plan_row(
    tmp_path: Path,
) -> None:
    repo, system, control, manifest = _repository(tmp_path)
    plan = _load(repo, system, control)
    (repo / "data/manifests/eligible_questions.jsonl").write_text(
        "substituted\n", encoding="utf-8"
    )

    questions = load_sealed_public_questions(
        repo,
        plan=plan,
        freeze_b=manifest,
        public_manifest_path=Path("data/manifests/eligible_questions.jsonl"),
    )

    assert len(questions) == 101
    assert questions["q-001"] == "Public synthetic question 1?"
    assert all(
        hashlib.sha256(questions[item.instance_id].encode()).hexdigest()
        == item.question_sha256
        for item in plan.attempts
    )
    with pytest.raises(SealedExecutionPlanError, match="frozen sealed plan"):
        load_sealed_public_questions(
            repo,
            plan=replace(plan, public_manifest_sha256="0" * 64),
            freeze_b=manifest,
            public_manifest_path=Path("data/manifests/eligible_questions.jsonl"),
        )


@pytest.mark.parametrize("case", ["missing", "mismatch"])
def test_plan_requires_all_frozen_input_digests(tmp_path: Path, case: str) -> None:
    ids = _test_ids()
    schedule = expected_schedule_bytes(ids, SEED)
    eligible = _jsonl(_eligible_records())
    frozen = {
        "data/final-schedule.jsonl": hashlib.sha256(schedule).hexdigest(),
        "data/manifests/eligible_questions.jsonl": hashlib.sha256(eligible).hexdigest(),
        "data/manifests/test_ids.txt": hashlib.sha256(ids).hexdigest(),
    }
    if case == "missing":
        del frozen["data/manifests/eligible_questions.jsonl"]
    else:
        frozen["data/final-schedule.jsonl"] = "f" * 64
    repo, system, control, _ = _repository(
        tmp_path,
        test_ids_content=ids,
        schedule_content=schedule,
        eligible_raw=eligible,
        frozen_override=frozen,
    )

    with pytest.raises(SealedExecutionPlanError, match="frozen file"):
        _load(repo, system, control)


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("protected", "protected"),
        ("duplicate", "duplicate"),
        ("missing", "scheduled identity"),
        ("bad_database", "database"),
        ("bad_question", "question"),
        ("noncanonical", "canonical"),
    ],
)
def test_plan_rejects_invalid_public_manifest(
    tmp_path: Path, case: str, message: str
) -> None:
    records = _eligible_records()
    raw: bytes | None = None
    if case == "protected":
        records[0]["gold_sql"] = "SELECT hidden"
    elif case == "duplicate":
        records[-1]["instance_id"] = records[0]["instance_id"]
    elif case == "missing":
        records.pop()
    elif case == "bad_database":
        records[0]["selected_database"] = "not allowed"
    elif case == "bad_question":
        records[0]["query"] = ""
    else:
        raw = b"".join(
            (json.dumps(record, indent=2) + "\n").encode() for record in records
        )
    repo, system, control, _ = _repository(
        tmp_path, eligible_records=records, eligible_raw=raw
    )

    with pytest.raises(SealedExecutionPlanError, match=message):
        _load(repo, system, control)


@pytest.mark.parametrize("case", ["reordered", "missing", "duplicate", "noncanonical"])
def test_plan_rejects_schedule_not_registered_to_seed_and_ids(
    tmp_path: Path, case: str
) -> None:
    ids = _test_ids()
    records = [
        json.loads(line) for line in expected_schedule_bytes(ids, SEED).splitlines()
    ]
    if case == "reordered":
        records[0], records[1] = records[1], records[0]
    elif case == "missing":
        records.pop()
    elif case == "duplicate":
        records[-1] = records[0]
    schedule = _jsonl(records)
    if case == "noncanonical":
        schedule = b"".join(
            (json.dumps(record, indent=2) + "\n").encode() for record in records
        )
    repo, system, control, _ = _repository(
        tmp_path, test_ids_content=ids, schedule_content=schedule
    )

    with pytest.raises(SealedExecutionPlanError, match="registered schedule"):
        _load(repo, system, control)


@pytest.mark.parametrize(
    "path",
    [
        "data/final-schedule.jsonl",
        "data/manifests/test_ids.txt",
        "data/manifests/eligible_questions.jsonl",
    ],
)
def test_plan_rejects_git_symlink_inputs(tmp_path: Path, path: str) -> None:
    repo, system, control, _ = _repository(tmp_path, symlink_input=path)

    with pytest.raises(SealedExecutionPlanError, match="committed regular file"):
        _load(repo, system, control)


def test_plan_rejects_runtime_source_drift_and_wrong_control_boundary(
    tmp_path: Path,
) -> None:
    repo, system, control, _ = _repository(
        tmp_path, plan_source_override=b"# substituted sealed plan\n"
    )
    with pytest.raises(SealedExecutionPlanError, match="runtime source"):
        _load(repo, system, control)

    clean = tmp_path / "wrong-control"
    repo, system, control, _ = _repository(clean)
    (repo / "later.txt").write_text("later\n")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-qm", "later")
    with pytest.raises(SealedExecutionPlanError, match="current HEAD"):
        _load(repo, system, control)


def test_plan_sha_changes_with_frozen_public_question_or_database(
    tmp_path: Path,
) -> None:
    repo, system, control, _ = _repository(tmp_path / "first")
    first = _load(repo, system, control)
    changed_question = _eligible_records()
    changed_question[0]["query"] = "Changed public synthetic question?"
    repo, system, control, _ = _repository(
        tmp_path / "question", eligible_records=changed_question
    )
    second = _load(repo, system, control)
    changed_database = _eligible_records()
    changed_database[0]["selected_database"] = "db-8"
    repo, system, control, _ = _repository(
        tmp_path / "database", eligible_records=changed_database
    )
    third = _load(repo, system, control)

    assert len({first.sha256, second.sha256, third.sha256}) == 3


def test_plan_cli_prints_only_hashes_and_counts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, system, control, _ = _repository(tmp_path)

    status = plan_main(
        [
            "--workspace",
            str(repo),
            "--control-commit",
            control,
            "--system-commit",
            system,
            "--freeze-b",
            "experiments/freeze-b.json",
            "--schedule",
            "data/final-schedule.jsonl",
            "--public-manifest",
            "data/manifests/eligible_questions.jsonl",
        ]
    )

    output_text = capsys.readouterr().out
    output = json.loads(output_text)
    assert status == 0
    assert set(output) == {
        "attempt_count",
        "cohort_counts",
        "condition_counts",
        "control_commit",
        "database_count",
        "freeze_b_sha256",
        "plan_sha256",
        "repetition_counts",
        "schedule_sha256",
        "system_commit",
    }
    assert "q-001" not in output_text
    assert "Public synthetic" not in output_text
    assert SEED not in output_text


def test_plan_script_entrypoint_prints_the_same_public_summary(tmp_path: Path) -> None:
    repo, system, control, _ = _repository(tmp_path)
    project = Path(__file__).parents[1]
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(project / "sealed_tools/plan_sealed_generation.py"),
            "--workspace",
            str(repo),
            "--control-commit",
            control,
            "--system-commit",
            system,
            "--freeze-b",
            "experiments/freeze-b.json",
            "--schedule",
            "data/final-schedule.jsonl",
            "--public-manifest",
            "data/manifests/eligible_questions.jsonl",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    output = json.loads(completed.stdout)
    assert output["attempt_count"] == 1_212
    assert output["control_commit"] == control
    assert output["system_commit"] == system
    assert completed.stderr == ""
