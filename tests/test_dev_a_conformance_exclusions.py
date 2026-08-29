from __future__ import annotations

import hashlib
import json
from pathlib import Path

from omni_benchmark.dev_a_conformance_exclusions import (
    build_dev_a_conformance_exclusions,
    canonical_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
EXCLUSIONS_PATH = ROOT / "config/conditions/dev-a-scorer-conformance-exclusions-v1.json"
PLAN_PATH = ROOT / "experiments/planned-dev-a-interventions-v1.json"
AUDIT_PATH = ROOT / "experiments/analysis/livesqlbench-loader-fidelity-v1.json"


def _load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def test_committed_exclusions_regenerate_from_public_dev_a_membership() -> None:
    expected = build_dev_a_conformance_exclusions(ROOT)
    content = EXCLUSIONS_PATH.read_bytes()

    assert content == canonical_bytes(expected)
    assert _load_json(EXCLUSIONS_PATH) == expected
    assert expected["counts"] == {
        "answerable_questions": 136,
        "scheduled_questions": 154,
        "unscorable_questions": 18,
    }
    assert expected["databases"] == [
        {
            "database": "mental_healths_large",
            "official_loader_omitted_tables": 34,
            "unscorable_questions": 9,
        },
        {
            "database": "organ_transplant_large",
            "official_loader_omitted_tables": 37,
            "unscorable_questions": 9,
        },
    ]
    assert len(expected["instance_ids"]) == 18
    assert expected["instance_ids"] == sorted(expected["instance_ids"])
    assert expected["human_decision"] == {
        "bead_id": "omni-benchmark-1u8",
        "response": "A",
    }


def test_intervention_plan_schedules_154_and_promotes_on_fixed_136() -> None:
    exclusions = _load_json(EXCLUSIONS_PATH)
    plan = _load_json(PLAN_PATH)
    frame = plan["common_evaluation"]["scorer_conformance_frame"]

    assert PLAN_PATH.read_bytes() == canonical_bytes(plan)
    assert plan["schema_version"] == 2
    assert frame == {
        "answerable_promotion_questions": 136,
        "exclusion_manifest_path": (
            "config/conditions/dev-a-scorer-conformance-exclusions-v1.json"
        ),
        "exclusion_manifest_sha256": hashlib.sha256(
            EXCLUSIONS_PATH.read_bytes()
        ).hexdigest(),
        "scheduled_questions": 154,
        "unscorable_questions": 18,
    }
    assert exclusions["counts"]["answerable_questions"] == 136
    requirement = plan["common_evaluation"]["full_dev_a_requirement"]
    assert "all 154" in requirement
    assert "136 answerable" in requirement
    assert "18" in requirement
    assert "all 154" in plan["stopping_rule"]
    assert "136 answerable" in plan["stopping_rule"]
    for intervention in plan["interventions"]:
        evaluation = intervention["prespecified_dev_a_evaluation"]
        assert "all 154" in evaluation
        assert "136 answerable" in evaluation


def test_public_loader_audit_covers_all_18_databases() -> None:
    audit = _load_json(AUDIT_PATH)

    assert AUDIT_PATH.read_bytes() == canonical_bytes(audit)
    assert audit["counts"] == {
        "databases": 18,
        "loaded_tables": 901,
        "ordered_tables": 973,
        "reproducing_official_loader": 18,
        "skipped_absent_from_archive": 1,
        "skipped_by_official_loader": 72,
        "skipped_over_case_variant": 71,
    }
    assert len(audit["databases"]) == 18
    assert all(item["reproduces_official_loader"] for item in audit["databases"])
