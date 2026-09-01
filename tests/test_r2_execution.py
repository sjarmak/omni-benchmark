from __future__ import annotations

import copy
import hashlib
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

import omni_benchmark.r2_paired_outcomes as paired_outcomes
import omni_benchmark.r2_semantic_reuse as semantic_reuse
import omni_benchmark.r2_execution as r2_execution
import omni_benchmark.r2_execution_cli as execution_cli
from omni_benchmark.measure_review_catalog import canonical_catalog_bytes
from omni_benchmark.omni_semantic_deployment import BALANCED_AI_SETTINGS
from omni_benchmark.r2_execution import (
    R2ExecutionError,
    build_r2_execution_plan,
    finalize_r2_generations,
    write_r2_attempt_artifacts,
)
from omni_benchmark.r2_paired_schedule import (
    CONTROL_CONDITION,
    TREATMENT_CONDITION,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
COMMIT = "e" * 40
RAW_ROOT = Path("experiments/autoresearch/raw/r2-public-evidence-measures-v1")


def _stable(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()}"


def _schedule() -> dict[str, object]:
    pair_inputs = (
        ("alpha_large", "alpha_1", CONTROL_CONDITION),
        ("beta_large", "beta_1", TREATMENT_CONDITION),
        ("alpha_large", "alpha_2", TREATMENT_CONDITION),
        ("beta_large", "beta_2", CONTROL_CONDITION),
    )
    pairs: list[dict[str, object]] = []
    attempts: list[dict[str, object]] = []
    for pair_position, (database, instance_id, first) in enumerate(
        pair_inputs, start=1
    ):
        second = (
            TREATMENT_CONDITION if first == CONTROL_CONDITION else CONTROL_CONDITION
        )
        pair_id = _stable("r2pair", instance_id)
        pairs.append(
            {
                "database": database,
                "database_round": (pair_position + 1) // 2,
                "first_condition": first,
                "instance_id": instance_id,
                "pair_id": pair_id,
                "pair_position": pair_position,
                "second_condition": second,
            }
        )
        for within_pair_position, condition in enumerate((first, second), start=1):
            attempts.append(
                {
                    "attempt_id": _stable("r2attempt", f"{instance_id}:{condition}"),
                    "attempt_position": len(attempts) + 1,
                    "condition": condition,
                    "database": database,
                    "instance_id": instance_id,
                    "pair_id": pair_id,
                    "pair_position": pair_position,
                    "repetition": 1,
                    "within_pair_position": within_pair_position,
                }
            )
    value: dict[str, object] = {
        "algorithm": {
            "database_order": "sha256",
            "first_arm_balance": "within_database_then_global",
            "name": "r2_database_round_robin_paired_v1",
            "pair_adjacency": True,
            "question_order_within_database": "sha256",
            "seed": "fixture-seed",
        },
        "attempts": attempts,
        "information_boundary": {
            "correctness_used": False,
            "hidden_annotations_used": False,
            "opportunity_map_used": False,
            "question_text_used": False,
            "sealed_test_used": False,
        },
        "kind": "r2-public-evidence-measures-paired-schedule",
        "pairs": pairs,
        "schedule_version": "r2-public-evidence-measures-paired-schedule-v1",
        "schema_version": 1,
        "source": {},
        "summary": {
            "attempt_count": 8,
            "condition_attempt_counts": {
                CONTROL_CONDITION: 4,
                TREATMENT_CONDITION: 4,
            },
            "database_count": 2,
            "dev_a_count": 4,
            "first_condition_counts": {
                CONTROL_CONDITION: 2,
                TREATMENT_CONDITION: 2,
            },
            "first_condition_counts_by_database": {
                "alpha_large": {CONTROL_CONDITION: 1, TREATMENT_CONDITION: 1},
                "beta_large": {CONTROL_CONDITION: 1, TREATMENT_CONDITION: 1},
            },
            "pair_count": 4,
            "pair_count_by_database": {"alpha_large": 2, "beta_large": 2},
        },
        "manifest": {
            "ordered_attempt_ids": [item["attempt_id"] for item in attempts],
            "ordered_pair_ids": [item["pair_id"] for item in pairs],
        },
    }
    unhashed = copy.deepcopy(value)
    value["manifest"]["artifact_sha256"] = hashlib.sha256(  # type: ignore[index]
        canonical_catalog_bytes(unhashed)
    ).hexdigest()
    return value


def _bundle_manifest() -> dict[str, object]:
    value: dict[str, object] = {
        "accepted_catalog": {
            "internal_artifact_sha256": SHA_A,
            "path": "catalog.json",
            "sha256": SHA_B,
        },
        "balanced_ai_settings": copy.deepcopy(BALANCED_AI_SETTINGS),
        "conditions": {
            CONTROL_CONDITION: {"directory": "r2-c5b", "measure_count": 0},
            TREATMENT_CONDITION: {"directory": "r2-m1", "measure_count": 4},
        },
        "databases": [
            {
                "changed_view_files": ["alpha.view"],
                "control_file_count": 2,
                "control_manifest_sha256": SHA_A,
                "database": "alpha_large",
                "measure_count": 2,
                "measure_ids": [
                    _stable("r2m1m", "alpha-1"),
                    _stable("r2m1m", "alpha-2"),
                ],
                "source_c5_manifest_sha256": SHA_C,
                "treatment_file_count": 2,
                "treatment_manifest_sha256": SHA_B,
            },
            {
                "changed_view_files": ["beta.view"],
                "control_file_count": 2,
                "control_manifest_sha256": SHA_C,
                "database": "beta_large",
                "measure_count": 2,
                "measure_ids": [_stable("r2m1m", "beta-1"), _stable("r2m1m", "beta-2")],
                "source_c5_manifest_sha256": SHA_D,
                "treatment_file_count": 2,
                "treatment_manifest_sha256": SHA_D,
            },
        ],
        "generator_version": "fixture-generator",
        "information_boundary": {
            "benchmark_questions_used": False,
            "correctness_used": False,
            "dev_b_used": False,
            "hidden_annotations_used": False,
            "opportunity_map_used": False,
            "public_c5_sources_only": True,
            "sealed_test_used": False,
        },
        "kind": "r2-public-evidence-measure-bundle-set",
        "schema_version": 1,
        "series_id": "r2-public-evidence-measures-v1",
        "summary": {
            "control_measure_count": 0,
            "database_count": 2,
            "treatment_measure_count": 4,
        },
        "target_configuration": {"path": "targets.json", "sha256": SHA_A},
        "manifest": {"files": []},
    }
    unhashed = copy.deepcopy(value)
    value["manifest"]["artifact_sha256"] = hashlib.sha256(  # type: ignore[index]
        canonical_catalog_bytes(unhashed)
    ).hexdigest()
    return value


def _semantic_digests() -> dict[str, dict[str, str]]:
    return {
        CONTROL_CONDITION: {"alpha_large": SHA_A, "beta_large": SHA_B},
        TREATMENT_CONDITION: {"alpha_large": SHA_C, "beta_large": SHA_D},
    }


def _plan(**overrides):  # type: ignore[no-untyped-def]
    arguments = {
        "schedule_bytes": canonical_catalog_bytes(_schedule()),
        "bundle_manifest_bytes": canonical_catalog_bytes(_bundle_manifest()),
        "semantic_model_sha256s": _semantic_digests(),
        "system_commit": COMMIT,
        "output_root": RAW_ROOT,
        "arm_run_ids": {
            CONTROL_CONDITION: "r2-c5b-generation-v1",
            TREATMENT_CONDITION: "r2-m1-generation-v1",
        },
        "deployment_run_ids": {
            CONTROL_CONDITION: "r2-c5b-deployment-v1",
            TREATMENT_CONDITION: "r2-m1-deployment-v1",
        },
        "projected_attempt_cost_usd": {
            CONTROL_CONDITION: 1.25,
            TREATMENT_CONDITION: 1.50,
        },
        "harness_config_sha256": SHA_A,
        "prompt_sha256": SHA_B,
        "instructions_sha256": SHA_C,
        "budget_policy_sha256": SHA_D,
    }
    arguments.update(overrides)
    return build_r2_execution_plan(**arguments)


def _record(attempt) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return {
        "attempt_id": attempt.attempt_id,
        "condition": attempt.condition,
        "cost_unavailable_reason": None,
        "cost_usd": 0.25,
        "database": attempt.database,
        "database_query_count": 1,
        "generated_query": {
            "calculations": [],
            "fields": [],
            "parsed": True,
            "pivots": [],
            "sorts": [],
            "userEditedSQL": "SELECT 1",
        },
        "generation_outcome": "answered",
        "instance_id": attempt.instance_id,
        "latency_ms": 10.0,
        "partition": "dev-a",
        "repetition": 1,
        "run_id": attempt.run_id,
        "terminal_failure_class": None,
        "token_usage": {
            "input_tokens": 3,
            "output_tokens": 2,
            "total_tokens": 5,
        },
        "tool_call_count": 1,
        "validation_attempt_count": None,
    }


def _write_snapshot(snapshot: Path) -> tuple[bytes, bytes]:
    schedule_bytes = canonical_catalog_bytes(_schedule())
    arm_manifests: dict[tuple[str, str], bytes] = {}
    root_files: dict[str, bytes] = {}
    database_records: dict[str, dict[str, object]] = {
        str(item["database"]): copy.deepcopy(item)
        for item in _bundle_manifest()["databases"]  # type: ignore[index]
    }
    for condition, directory in (
        (CONTROL_CONDITION, "r2-c5b"),
        (TREATMENT_CONDITION, "r2-m1"),
    ):
        for database in ("alpha_large", "beta_large"):
            model = canonical_catalog_bytes(
                {
                    "ai_context": f"public fixture {condition} {database}",
                    "ai_settings": copy.deepcopy(BALANCED_AI_SETTINGS),
                }
            )
            model_name = "model"
            arm_manifest = canonical_catalog_bytes(
                {
                    "database": database,
                    "direct_physical_bindings": [],
                    "files": [
                        {
                            "file": model_name,
                            "sha256": hashlib.sha256(model).hexdigest(),
                            "size_bytes": len(model),
                        }
                    ],
                    "kind": "public-omni-semantic-bundle",
                    "schema_version": 1,
                }
            )
            prefix = f"{directory}/{database}"
            root_files[f"{prefix}/{model_name}"] = model
            root_files[f"{prefix}/manifest.json"] = arm_manifest
            arm_manifests[(condition, database)] = arm_manifest
            field = (
                "control_manifest_sha256"
                if condition == CONTROL_CONDITION
                else "treatment_manifest_sha256"
            )
            database_records[database][field] = hashlib.sha256(arm_manifest).hexdigest()

    bundle = _bundle_manifest()
    bundle["databases"] = [database_records[name] for name in sorted(database_records)]
    bundle["manifest"]["files"] = [  # type: ignore[index]
        {
            "path": name,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for name, content in sorted(root_files.items())
    ]
    del bundle["manifest"]["artifact_sha256"]  # type: ignore[index]
    bundle["manifest"]["artifact_sha256"] = hashlib.sha256(  # type: ignore[index]
        canonical_catalog_bytes(bundle)
    ).hexdigest()
    bundle_bytes = canonical_catalog_bytes(bundle)

    files = {
        r2_execution._SCHEDULE_PATH: schedule_bytes,
        r2_execution._BUNDLE_ROOT / "manifest.json": bundle_bytes,
        r2_execution._PUBLIC_MANIFEST_PATH: b"fixture-public\n",
        r2_execution._DEV_A_IDS_PATH: b"fixture-id\n",
        r2_execution._SPLIT_METADATA_PATH: b"{}\n",
        r2_execution._TARGET_CONFIG_PATH: b"{}\n",
        r2_execution._HARNESS_CONFIG_PATH: b"fixture-harness\n",
        r2_execution._PROMPT_PATH: b"fixture-prompt\n",
        r2_execution._INSTRUCTIONS_PATH: b"fixture-instructions\n",
    }
    files.update(
        {
            r2_execution._BUNDLE_ROOT / name: content
            for name, content in root_files.items()
        }
    )
    for relative, content in files.items():
        path = snapshot / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o600)
    return schedule_bytes, bundle_bytes


def test_plan_is_exact_paired_budgeted_and_credential_free() -> None:
    plan = _plan()

    assert len(plan.attempts) == 8
    assert [item.attempt_id for item in plan.attempts] == _schedule()["manifest"][
        "ordered_attempt_ids"
    ]
    assert plan.projected_arm_cost_usd == {
        CONTROL_CONDITION: "5.00",
        TREATMENT_CONDITION: "6.00",
    }
    assert plan.projected_total_cost_usd == "11.00"
    for left, right in zip(plan.attempts[::2], plan.attempts[1::2], strict=True):
        assert left.pair_id == right.pair_id
        assert left.within_pair_position == 1
        assert right.within_pair_position == 2
        assert left.condition != right.condition
    assert {
        item.deployment_identity
        for item in plan.attempts
        if item.database == "alpha_large"
    } == {
        "livesqlbench-alpha_large-r2-c5b-v1",
        "livesqlbench-alpha_large-r2-m1-v1",
    }
    public = canonical_catalog_bytes(plan.public_dict())
    assert b"query" not in public
    assert b"question" not in public
    assert b"gold" not in public
    assert b"token" not in public
    assert (
        plan.sha256
        == hashlib.sha256(
            canonical_catalog_bytes(plan.public_dict(include_plan_sha256=False))
        ).hexdigest()
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("same_run", "arm run IDs must be distinct"),
        ("same_deployment", "deployment run IDs must be distinct"),
        ("cross_action_run", "execution and deployment run IDs must be distinct"),
        ("arm_budget", "per-arm projection exceeds USD 500"),
        ("raw_arm_budget", "per-arm projection exceeds USD 500"),
        ("total_budget", "total projection exceeds USD 1000"),
        ("semantic_coverage", "semantic digest coverage"),
        ("schedule_adjacency", "pair adjacency"),
        ("balanced_settings", "Balanced ai_settings"),
        ("bundle_database", "bundle database coverage"),
    ],
)
def test_plan_rejects_identity_budget_schedule_and_bundle_drift(
    mutation: str, message: str
) -> None:
    overrides: dict[str, object] = {}
    if mutation == "same_run":
        overrides["arm_run_ids"] = {
            CONTROL_CONDITION: "same-v1",
            TREATMENT_CONDITION: "same-v1",
        }
    elif mutation == "same_deployment":
        overrides["deployment_run_ids"] = {
            CONTROL_CONDITION: "same-v1",
            TREATMENT_CONDITION: "same-v1",
        }
    elif mutation == "cross_action_run":
        overrides["deployment_run_ids"] = {
            CONTROL_CONDITION: "r2-c5b-generation-v1",
            TREATMENT_CONDITION: "r2-m1-deployment-v1",
        }
    elif mutation in {"arm_budget", "raw_arm_budget", "total_budget"}:
        overrides["projected_attempt_cost_usd"] = {
            CONTROL_CONDITION: (
                126.0
                if mutation == "arm_budget"
                else 125.001
                if mutation == "raw_arm_budget"
                else 125.01
            ),
            TREATMENT_CONDITION: (
                1.0
                if mutation == "arm_budget"
                else 0.0
                if mutation == "raw_arm_budget"
                else 125.01
            ),
        }
    elif mutation == "semantic_coverage":
        digests = _semantic_digests()
        del digests[CONTROL_CONDITION]["alpha_large"]
        overrides["semantic_model_sha256s"] = digests
    elif mutation == "schedule_adjacency":
        schedule = _schedule()
        schedule["attempts"][1], schedule["attempts"][2] = (  # type: ignore[index]
            schedule["attempts"][2],  # type: ignore[index]
            schedule["attempts"][1],  # type: ignore[index]
        )
        del schedule["manifest"]["artifact_sha256"]  # type: ignore[index]
        schedule["manifest"]["artifact_sha256"] = hashlib.sha256(  # type: ignore[index]
            canonical_catalog_bytes(schedule)
        ).hexdigest()
        overrides["schedule_bytes"] = canonical_catalog_bytes(schedule)
    else:
        bundle = _bundle_manifest()
        if mutation == "balanced_settings":
            bundle["balanced_ai_settings"]["validate_analysis"] = "enabled"  # type: ignore[index]
        else:
            bundle["databases"].pop()  # type: ignore[union-attr]
            del bundle["manifest"]["artifact_sha256"]  # type: ignore[index]
            bundle["manifest"]["artifact_sha256"] = hashlib.sha256(  # type: ignore[index]
                canonical_catalog_bytes(bundle)
            ).hexdigest()
        overrides["bundle_manifest_bytes"] = canonical_catalog_bytes(bundle)

    with pytest.raises(R2ExecutionError, match=message):
        _plan(**overrides)


def test_attempt_publication_and_finalization_preserve_frozen_arm_order(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    plan = _plan()
    for attempt in plan.attempts:
        artifacts = write_r2_attempt_artifacts(
            tmp_path,
            plan=plan,
            attempt_id=attempt.attempt_id,
            record=_record(attempt),
        )
        assert artifacts.generation_path.stat().st_mode & 0o777 == 0o600
        assert artifacts.manifest_path.stat().st_mode & 0o777 == 0o600

    finalized = finalize_r2_generations(
        tmp_path,
        plan=plan,
        destination=Path("experiments/autoresearch/raw/r2-finalized-v1"),
    )

    schedule = paired_outcomes._schedule(
        canonical_catalog_bytes(_schedule()), expected_pair_count=4
    )
    control = finalized.control_path.read_bytes()
    treatment = finalized.treatment_path.read_bytes()
    assert (
        len(
            paired_outcomes._generation_records(
                control, CONTROL_CONDITION, schedule, expected_pair_count=4
            )
        )
        == 4
    )
    assert (
        len(
            paired_outcomes._generation_records(
                treatment, TREATMENT_CONDITION, schedule, expected_pair_count=4
            )
        )
        == 4
    )
    assert (
        len(
            semantic_reuse._generation_records(
                control,
                CONTROL_CONDITION,
                schedule,
                measures={},
                expected_pair_count=4,
            )
        )
        == 4
    )
    manifest = json.loads(finalized.manifest_path.read_bytes())
    assert manifest["execution_plan_sha256"] == plan.sha256
    assert manifest["conditions"][CONTROL_CONDITION]["record_count"] == 4
    assert manifest["conditions"][TREATMENT_CONDITION]["record_count"] == 4
    assert finalized.manifest_path.stat().st_mode & 0o777 == 0o600

    with pytest.raises(R2ExecutionError, match="already exists"):
        finalize_r2_generations(
            tmp_path,
            plan=plan,
            destination=Path("experiments/autoresearch/raw/r2-finalized-v1"),
        )


def test_attempt_publication_rejects_scored_or_drifted_records(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    plan = _plan()
    attempt = plan.attempts[0]
    wrong = _record(attempt)
    wrong["attempt_id"] = "wrong"
    with pytest.raises(R2ExecutionError, match="attempt identity"):
        write_r2_attempt_artifacts(
            tmp_path, plan=plan, attempt_id=attempt.attempt_id, record=wrong
        )
    scored = _record(attempt)
    scored["correctness"] = True
    with pytest.raises(R2ExecutionError, match="scored field"):
        write_r2_attempt_artifacts(
            tmp_path, plan=plan, attempt_id=attempt.attempt_id, record=scored
        )


def test_finalization_is_all_or_nothing_and_rejects_manifest_drift(
    tmp_path: Path,
) -> None:
    (tmp_path / ".git").mkdir()
    plan = _plan()
    for attempt in plan.attempts[:-1]:
        write_r2_attempt_artifacts(
            tmp_path,
            plan=plan,
            attempt_id=attempt.attempt_id,
            record=_record(attempt),
        )
    destination = Path("experiments/autoresearch/raw/r2-incomplete-v1")
    with pytest.raises(R2ExecutionError, match="scheduled attempt is absent"):
        finalize_r2_generations(tmp_path, plan=plan, destination=destination)
    assert not (tmp_path / destination).exists()

    last = plan.attempts[-1]
    write_r2_attempt_artifacts(
        tmp_path, plan=plan, attempt_id=last.attempt_id, record=_record(last)
    )
    first_manifest = tmp_path / plan.attempts[0].output_root / "run.json"
    value = json.loads(first_manifest.read_bytes())
    value["semantic_model_sha256"] = SHA_D
    first_manifest.write_bytes(canonical_catalog_bytes(value))
    with pytest.raises(R2ExecutionError, match="manifest hash|semantic model"):
        finalize_r2_generations(tmp_path, plan=plan, destination=destination)
    assert not (tmp_path / destination).exists()


def test_snapshot_plan_authenticates_files_semantics_and_committed_configs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schedule_bytes, bundle_bytes = _write_snapshot(tmp_path)
    monkeypatch.setattr(
        r2_execution,
        "validate_r2_paired_schedule",
        lambda *args, **kwargs: _schedule(),
    )

    plan = r2_execution._snapshot_execution_plan(
        tmp_path,
        system_commit=COMMIT,
        output_root=RAW_ROOT,
        arm_run_ids={
            CONTROL_CONDITION: "r2-c5b-generation-v1",
            TREATMENT_CONDITION: "r2-m1-generation-v1",
        },
        deployment_run_ids={
            CONTROL_CONDITION: "r2-c5b-deployment-v1",
            TREATMENT_CONDITION: "r2-m1-deployment-v1",
        },
        projected_attempt_cost_usd={
            CONTROL_CONDITION: "1.00",
            TREATMENT_CONDITION: "1.00",
        },
        budget_policy_sha256=SHA_D,
        expected_schedule_sha256=hashlib.sha256(schedule_bytes).hexdigest(),
        expected_bundle_manifest_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
    )

    assert (
        plan.harness_config_sha256 == hashlib.sha256(b"fixture-harness\n").hexdigest()
    )
    assert plan.prompt_sha256 == hashlib.sha256(b"fixture-prompt\n").hexdigest()
    assert (
        plan.instructions_sha256
        == hashlib.sha256(b"fixture-instructions\n").hexdigest()
    )
    assert len({item.semantic_model_sha256 for item in plan.attempts}) == 4

    unexpected = tmp_path / r2_execution._BUNDLE_ROOT / "unexpected"
    unexpected.write_bytes(b"drift")
    unexpected.chmod(0o600)
    with pytest.raises(R2ExecutionError, match="file inventory"):
        r2_execution._snapshot_execution_plan(
            tmp_path,
            system_commit=COMMIT,
            output_root=RAW_ROOT,
            arm_run_ids={
                CONTROL_CONDITION: "r2-c5b-generation-v1",
                TREATMENT_CONDITION: "r2-m1-generation-v1",
            },
            deployment_run_ids={
                CONTROL_CONDITION: "r2-c5b-deployment-v1",
                TREATMENT_CONDITION: "r2-m1-deployment-v1",
            },
            projected_attempt_cost_usd={
                CONTROL_CONDITION: "1.00",
                TREATMENT_CONDITION: "1.00",
            },
            budget_policy_sha256=SHA_D,
            expected_schedule_sha256=hashlib.sha256(schedule_bytes).hexdigest(),
            expected_bundle_manifest_sha256=hashlib.sha256(bundle_bytes).hexdigest(),
        )


def test_snapshot_plan_rejects_noncanonical_root_inventory_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schedule_bytes, bundle_bytes = _write_snapshot(tmp_path)
    bundle_path = tmp_path / r2_execution._BUNDLE_ROOT / "manifest.json"
    bundle = json.loads(bundle_path.read_bytes())
    bundle["manifest"]["files"][0]["file"] = bundle["manifest"]["files"][0].pop("path")
    del bundle["manifest"]["artifact_sha256"]
    bundle["manifest"]["artifact_sha256"] = hashlib.sha256(
        canonical_catalog_bytes(bundle)
    ).hexdigest()
    drifted = canonical_catalog_bytes(bundle)
    bundle_path.write_bytes(drifted)
    monkeypatch.setattr(
        r2_execution,
        "validate_r2_paired_schedule",
        lambda *args, **kwargs: _schedule(),
    )

    with pytest.raises(R2ExecutionError, match="file record"):
        r2_execution._snapshot_execution_plan(
            tmp_path,
            system_commit=COMMIT,
            output_root=RAW_ROOT,
            arm_run_ids={
                CONTROL_CONDITION: "r2-c5b-generation-v1",
                TREATMENT_CONDITION: "r2-m1-generation-v1",
            },
            deployment_run_ids={
                CONTROL_CONDITION: "r2-c5b-deployment-v1",
                TREATMENT_CONDITION: "r2-m1-deployment-v1",
            },
            projected_attempt_cost_usd={
                CONTROL_CONDITION: "1.00",
                TREATMENT_CONDITION: "1.00",
            },
            budget_policy_sha256=SHA_D,
            expected_schedule_sha256=hashlib.sha256(schedule_bytes).hexdigest(),
            expected_bundle_manifest_sha256=hashlib.sha256(drifted).hexdigest(),
        )


def test_committed_archive_extraction_rejects_non_regular_members(
    tmp_path: Path,
) -> None:
    good = io.BytesIO()
    with tarfile.open(fileobj=good, mode="w") as archive:
        payload = b"public fixture"
        member = tarfile.TarInfo("config/fixture.json")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    destination = tmp_path / "good"
    destination.mkdir()
    r2_execution._extract_committed_archive(good.getvalue(), destination)
    assert (destination / "config/fixture.json").read_bytes() == b"public fixture"

    unsafe = io.BytesIO()
    with tarfile.open(fileobj=unsafe, mode="w") as archive:
        member = tarfile.TarInfo("config/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    with pytest.raises(R2ExecutionError, match="archive is unsafe"):
        r2_execution._extract_committed_archive(unsafe.getvalue(), tmp_path / "unsafe")


def test_snapshot_plan_rejects_frozen_hash_and_regeneration_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schedule_bytes, bundle_bytes = _write_snapshot(tmp_path)
    common = {
        "system_commit": COMMIT,
        "output_root": RAW_ROOT,
        "arm_run_ids": {
            CONTROL_CONDITION: "r2-c5b-generation-v1",
            TREATMENT_CONDITION: "r2-m1-generation-v1",
        },
        "deployment_run_ids": {
            CONTROL_CONDITION: "r2-c5b-deployment-v1",
            TREATMENT_CONDITION: "r2-m1-deployment-v1",
        },
        "projected_attempt_cost_usd": {
            CONTROL_CONDITION: "1.00",
            TREATMENT_CONDITION: "1.00",
        },
        "budget_policy_sha256": SHA_D,
        "expected_schedule_sha256": hashlib.sha256(schedule_bytes).hexdigest(),
        "expected_bundle_manifest_sha256": hashlib.sha256(bundle_bytes).hexdigest(),
    }
    with pytest.raises(R2ExecutionError, match="schedule does not match"):
        r2_execution._snapshot_execution_plan(
            tmp_path, **(common | {"expected_schedule_sha256": SHA_A})
        )
    with pytest.raises(R2ExecutionError, match="bundle set does not match"):
        r2_execution._snapshot_execution_plan(
            tmp_path, **(common | {"expected_bundle_manifest_sha256": SHA_A})
        )
    monkeypatch.setattr(
        r2_execution,
        "validate_r2_paired_schedule",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            r2_execution.R2PairedScheduleError("drift")
        ),
    )
    with pytest.raises(R2ExecutionError, match="does not reproduce"):
        r2_execution._snapshot_execution_plan(tmp_path, **common)


def test_committed_loader_routes_only_the_exact_git_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _plan()
    observed: dict[str, object] = {}
    monkeypatch.setattr(r2_execution, "_git_root", lambda workspace: tmp_path)
    monkeypatch.setattr(
        r2_execution, "_canonical_git_commit", lambda workspace, commit: COMMIT
    )
    monkeypatch.setattr(r2_execution, "_committed_archive", lambda *args: b"archive")

    def extract(content: bytes, destination: Path) -> None:
        observed["archive"] = content
        observed["snapshot"] = destination

    def snapshot(snapshot: Path, **kwargs):  # type: ignore[no-untyped-def]
        observed["snapshot_call"] = snapshot
        observed["system_commit"] = kwargs["system_commit"]
        return expected

    monkeypatch.setattr(r2_execution, "_extract_committed_archive", extract)
    monkeypatch.setattr(r2_execution, "_snapshot_execution_plan", snapshot)

    actual = r2_execution.load_committed_r2_execution_plan(
        tmp_path,
        system_commit=COMMIT,
        output_root=RAW_ROOT,
        arm_run_ids={
            CONTROL_CONDITION: "r2-c5b-generation-v1",
            TREATMENT_CONDITION: "r2-m1-generation-v1",
        },
        deployment_run_ids={
            CONTROL_CONDITION: "r2-c5b-deployment-v1",
            TREATMENT_CONDITION: "r2-m1-deployment-v1",
        },
        projected_attempt_cost_usd={
            CONTROL_CONDITION: "1.00",
            TREATMENT_CONDITION: "1.00",
        },
        budget_policy_sha256=SHA_D,
    )

    assert actual is expected
    assert observed["archive"] == b"archive"
    assert observed["snapshot"] == observed["snapshot_call"]
    assert observed["system_commit"] == COMMIT


def test_git_boundary_requires_repository_root_and_canonical_commit() -> None:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert r2_execution._git_root(REPOSITORY_ROOT) == REPOSITORY_ROOT
    assert r2_execution._canonical_git_commit(REPOSITORY_ROOT, head) == head
    with pytest.raises(R2ExecutionError, match="repository root"):
        r2_execution._git_root(REPOSITORY_ROOT / "src")
    with pytest.raises(R2ExecutionError, match="full lowercase commit"):
        r2_execution._canonical_git_commit(REPOSITORY_ROOT, "short")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"system_commit": "short"}, "full lowercase commit"),
        ({"output_root": Path("outside")}, "confined raw-run path"),
        (
            {
                "deployment_run_ids": {
                    CONTROL_CONDITION: "control",
                    TREATMENT_CONDITION: "treatment",
                }
            },
            "v-number revision",
        ),
        (
            {"projected_attempt_cost_usd": {CONTROL_CONDITION: 1.0}},
            "cover both arms",
        ),
        (
            {
                "projected_attempt_cost_usd": {
                    CONTROL_CONDITION: float("nan"),
                    TREATMENT_CONDITION: 1.0,
                }
            },
            "attempt cost is invalid",
        ),
        ({"prompt_sha256": "bad"}, "prompt SHA-256"),
    ],
)
def test_plan_rejects_malformed_external_boundaries(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(R2ExecutionError, match=message):
        _plan(**overrides)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("outcome", "generation outcome"),
        ("failure", "outcome and failure"),
        ("latency", "latency"),
        ("cost_reason", "requires a reason"),
        ("cost", "cost fields"),
    ],
)
def test_attempt_publication_rejects_invalid_terminal_telemetry(
    tmp_path: Path, mutation: str, message: str
) -> None:
    (tmp_path / ".git").mkdir()
    plan = _plan()
    attempt = plan.attempts[0]
    record = _record(attempt)
    if mutation == "outcome":
        record["generation_outcome"] = "unknown"
    elif mutation == "failure":
        record["terminal_failure_class"] = "response_contract_error"
    elif mutation == "latency":
        record["latency_ms"] = float("nan")
    elif mutation == "cost_reason":
        record["cost_usd"] = None
        record["cost_unavailable_reason"] = None
    else:
        record["cost_usd"] = -1.0
    with pytest.raises(R2ExecutionError, match=message):
        write_r2_attempt_artifacts(
            tmp_path,
            plan=plan,
            attempt_id=attempt.attempt_id,
            record=record,
        )


def test_archive_boundary_rejects_empty_invalid_and_parent_paths(
    tmp_path: Path,
) -> None:
    with pytest.raises(R2ExecutionError, match="archive is empty"):
        r2_execution._extract_committed_archive(b"", tmp_path)
    with pytest.raises(R2ExecutionError, match="archive is invalid"):
        r2_execution._extract_committed_archive(b"not-a-tar", tmp_path)

    parent = io.BytesIO()
    with tarfile.open(fileobj=parent, mode="w") as archive:
        payload = b"bad"
        member = tarfile.TarInfo("../escape")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    with pytest.raises(R2ExecutionError, match="archive is unsafe"):
        r2_execution._extract_committed_archive(parent.getvalue(), tmp_path)


def _cli_arguments(tmp_path: Path) -> list[str]:
    return [
        "--workspace",
        str(tmp_path),
        "--system-commit",
        COMMIT,
        "--output-root",
        RAW_ROOT.as_posix(),
        "--control-run-id",
        "r2-c5b-generation-v1",
        "--treatment-run-id",
        "r2-m1-generation-v1",
        "--control-deployment-run-id",
        "r2-c5b-deployment-v1",
        "--treatment-deployment-run-id",
        "r2-m1-deployment-v1",
        "--control-projected-attempt-cost-usd",
        "1.00",
        "--treatment-projected-attempt-cost-usd",
        "1.00",
        "--budget-policy-sha256",
        SHA_D,
    ]


def test_cli_dry_plan_prints_only_credential_free_committed_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    plan = _plan()
    observed: dict[str, object] = {}

    def load(workspace: Path, **kwargs):  # type: ignore[no-untyped-def]
        observed["workspace"] = workspace
        observed.update(kwargs)
        return plan

    monkeypatch.setattr(execution_cli, "load_committed_r2_execution_plan", load)

    assert (
        execution_cli.r2_execution_main([*_cli_arguments(tmp_path), "--dry-run-plan"])
        == 0
    )

    value = json.loads(capsys.readouterr().out)
    assert value == plan.public_dict()
    assert observed["system_commit"] == COMMIT
    assert observed["budget_policy_sha256"] == SHA_D
    encoded = json.dumps(value).encode()
    assert b"question" not in encoded
    assert b"gold" not in encoded
    assert b"credential" not in encoded


def test_cli_finalize_requires_complete_attempts_and_prints_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".git").mkdir()
    plan = _plan()
    for attempt in plan.attempts:
        write_r2_attempt_artifacts(
            tmp_path,
            plan=plan,
            attempt_id=attempt.attempt_id,
            record=_record(attempt),
        )
    monkeypatch.setattr(
        execution_cli,
        "load_committed_r2_execution_plan",
        lambda *args, **kwargs: plan,
    )

    assert (
        execution_cli.r2_execution_main(
            [
                *_cli_arguments(tmp_path),
                "--finalize",
                "--finalization-destination",
                "experiments/autoresearch/raw/r2-cli-finalized-v1",
            ]
        )
        == 0
    )

    value = json.loads(capsys.readouterr().out)
    assert value["execution_plan_sha256"] == plan.sha256
    assert value["control"]["record_count"] == 4
    assert value["treatment"]["record_count"] == 4
    assert len(value["control"]["sha256"]) == 64
    assert len(value["treatment"]["sha256"]) == 64
    assert (tmp_path / value["manifest"]["path"]).exists()


def test_cli_rejects_inapplicable_finalization_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        execution_cli,
        "load_committed_r2_execution_plan",
        lambda *args, **kwargs: _plan(),
    )
    with pytest.raises(R2ExecutionError, match="only valid with finalize"):
        execution_cli.r2_execution_main(
            [
                *_cli_arguments(tmp_path),
                "--dry-run-plan",
                "--finalization-destination",
                "experiments/autoresearch/raw/not-used",
            ]
        )
    with pytest.raises(R2ExecutionError, match="requires a destination"):
        execution_cli.r2_execution_main([*_cli_arguments(tmp_path), "--finalize"])


def test_cli_entrypoint_sanitizes_expected_and_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        execution_cli,
        "r2_execution_main",
        lambda: (_ for _ in ()).throw(R2ExecutionError("safe detail")),
    )
    assert execution_cli.r2_execution_entrypoint() == 1
    assert "safe detail" in capsys.readouterr().err

    monkeypatch.setattr(
        execution_cli,
        "r2_execution_main",
        lambda: (_ for _ in ()).throw(RuntimeError("secret detail")),
    )
    assert execution_cli.r2_execution_entrypoint() == 1
    error = capsys.readouterr().err
    assert "internal error" in error
    assert "secret detail" not in error


def test_script_exposes_only_offline_execution_entrypoint() -> None:
    content = Path("scripts/r2_execution.py").read_text(encoding="utf-8")
    assert "r2_execution_entrypoint" in content
    assert "execute_live" not in content
