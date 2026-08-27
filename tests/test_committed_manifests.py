from __future__ import annotations

import hashlib
import json
from pathlib import Path

from omni_benchmark.split import (
    DEFAULT_DEVELOPMENT_SPLIT_SEED,
    DEFAULT_SPLIT_SEED,
    create_development_split,
    create_split,
)

from .helpers import OFFICIAL_QUERY_COUNTS


MANIFEST_DIR = Path(__file__).parents[1] / "data" / "manifests"
REPOSITORY_ROOT = MANIFEST_DIR.parents[1]


def test_local_mcp_configuration_is_ignored_as_potentially_secret() -> None:
    patterns = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert ".mcp.json" in patterns


def test_scaled_runs_require_hash_bound_run_manifests() -> None:
    config = json.loads(
        (REPOSITORY_ROOT / "config" / "autoresearch.json").read_text(encoding="utf-8")
    )

    assert config["trace_policy"]["scaled_runs_require_run_manifest"] is True


def test_preregistered_statistical_analysis_is_fully_deterministic() -> None:
    preregistration = json.loads(
        (REPOSITORY_ROOT / "config" / "preregistration.json").read_text(
            encoding="utf-8"
        )
    )

    assert preregistration["statistical_analysis"] == {
        "bootstrap": {
            "ci_level": 0.95,
            "cluster_unit": "question",
            "estimator": "mean_attempt_accuracy_or_paired_accuracy_delta",
            "interval": "percentile_nearest_rank",
            "replicates": 10000,
            "resampling": "questions_with_replacement_keep_all_repetitions",
            "sampler": "sha256_modulo_question_count_v1",
            "sampler_digest_input": (
                "utf8(seed)+NUL+ascii_zero_based_replicate+NUL+ascii_zero_based_draw"
            ),
            "sampler_digest_integer": "full_sha256_unsigned_big_endian",
            "sampler_question_order": "instance_id_ascending",
            "seed": "omni-livesqlbench-large-v1-analysis-v1",
            "percentile_rank": "sorted[max(0,ceil(p*replicates)-1)]",
        },
        "mcnemar_sensitivity": {
            "exploratory_family": {
                "contrasts": ["C2-C1", "C3-C2", "C4-C3"],
                "correction": "holm",
            },
            "primary_comparative": {
                "adjustment": "none",
                "contrast": "C4-C1",
            },
            "repetition": 1,
            "test": "exact_two_sided_binomial_on_discordant_pairs",
        },
    }


def test_committed_public_manifest_and_split_are_complete(tmp_path: Path) -> None:
    manifest_path = MANIFEST_DIR / "eligible_questions.jsonl"
    manifest_metadata_path = MANIFEST_DIR / "manifest_metadata.json"
    split_metadata_path = MANIFEST_DIR / "split_metadata.json"

    records = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
    ]
    manifest_metadata = json.loads(manifest_metadata_path.read_text(encoding="utf-8"))
    split_metadata = json.loads(split_metadata_path.read_text(encoding="utf-8"))
    train_ids = set(
        (MANIFEST_DIR / "train_ids.txt").read_text(encoding="utf-8").splitlines()
    )
    test_ids = set(
        (MANIFEST_DIR / "test_ids.txt").read_text(encoding="utf-8").splitlines()
    )
    dev_a_ids = set(
        (MANIFEST_DIR / "dev_a_ids.txt").read_text(encoding="utf-8").splitlines()
    )
    dev_b_ids = set(
        (MANIFEST_DIR / "dev_b_ids.txt").read_text(encoding="utf-8").splitlines()
    )
    development_metadata_path = MANIFEST_DIR / "development_split_metadata.json"
    development_metadata = json.loads(
        development_metadata_path.read_text(encoding="utf-8")
    )

    assert len(records) == 332
    assert len(train_ids) == 231
    assert len(test_ids) == 101
    assert train_ids.isdisjoint(test_ids)
    assert train_ids | test_ids == {record["instance_id"] for record in records}
    assert len(dev_a_ids) == 154
    assert len(dev_b_ids) == 77
    assert dev_a_ids.isdisjoint(dev_b_ids)
    assert dev_a_ids | dev_b_ids == train_ids
    assert development_metadata["counts"] == {
        "development": 231,
        "dev_a": 154,
        "dev_b": 77,
    }
    assert development_metadata["algorithm"]["seed"] == (
        "omni-livesqlbench-large-v1-development-split-v1"
    )
    assert development_metadata["artifacts"]["dev_a_ids"]["sha256"] == (
        hashlib.sha256((MANIFEST_DIR / "dev_a_ids.txt").read_bytes()).hexdigest()
    )
    assert development_metadata["artifacts"]["dev_b_ids"]["sha256"] == (
        hashlib.sha256((MANIFEST_DIR / "dev_b_ids.txt").read_bytes()).hexdigest()
    )
    assert manifest_metadata["databases"] == OFFICIAL_QUERY_COUNTS
    assert split_metadata["source"]["revision"] == (
        "a418e108d5cbb4cf9b783a928eff5e924ad2460d"
    )
    assert split_metadata["algorithm"]["seed"] == (
        "omni-livesqlbench-large-v1-split-v1"
    )
    assert (
        split_metadata["manifest"]["sha256"]
        == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )

    regenerated = tmp_path / "manifests"
    regenerated.mkdir()
    for filename in ("eligible_questions.jsonl", "manifest_metadata.json"):
        (regenerated / filename).write_bytes((MANIFEST_DIR / filename).read_bytes())
    create_split(
        regenerated,
        train_size=231,
        test_size=101,
        seed=DEFAULT_SPLIT_SEED,
    )
    for filename in ("train_ids.txt", "test_ids.txt", "split_metadata.json"):
        assert (regenerated / filename).read_bytes() == (
            MANIFEST_DIR / filename
        ).read_bytes()
    create_development_split(
        regenerated,
        dev_a_size=154,
        dev_b_size=77,
        seed=DEFAULT_DEVELOPMENT_SPLIT_SEED,
    )
    for filename in (
        "dev_a_ids.txt",
        "dev_b_ids.txt",
        "development_split_metadata.json",
    ):
        assert (regenerated / filename).read_bytes() == (
            MANIFEST_DIR / filename
        ).read_bytes()
