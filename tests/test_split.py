from __future__ import annotations

import json
from pathlib import Path

import pytest

from omni_benchmark.split import (
    SplitError,
    create_development_split,
    create_split,
    prepare_public_manifest,
)

from .helpers import (
    OFFICIAL_QUERY_COUNTS,
    official_shape_records,
    public_record,
    write_jsonl,
)


def prepare_official_shape(tmp_path: Path) -> Path:
    source = tmp_path / "source.jsonl"
    manifests = tmp_path / "manifests"
    write_jsonl(source, official_shape_records())
    prepare_public_manifest(source, manifests, source_commit="a418e108")
    return manifests


def read_ids(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_split_is_exact_disjoint_exhaustive_and_represents_every_database(
    tmp_path: Path,
) -> None:
    manifests = prepare_official_shape(tmp_path)

    metadata = create_split(manifests, train_size=231, test_size=101, seed="unit-seed")

    train_ids = read_ids(manifests / "train_ids.txt")
    test_ids = read_ids(manifests / "test_ids.txt")
    manifest_ids = {
        json.loads(line)["instance_id"]
        for line in (manifests / "eligible_questions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    }
    assert len(train_ids) == 231
    assert len(test_ids) == 101
    assert set(train_ids).isdisjoint(test_ids)
    assert set(train_ids) | set(test_ids) == manifest_ids
    assert metadata["counts"] == {"test": 101, "train": 231}
    assert set(metadata["distributions"]["by_database"]) == set(OFFICIAL_QUERY_COUNTS)
    for distribution in metadata["distributions"]["by_database"].values():
        assert distribution["train"] > 0
        assert distribution["test"] > 0


def test_database_allocations_are_proportional_with_exact_total(tmp_path: Path) -> None:
    manifests = prepare_official_shape(tmp_path)

    metadata = create_split(manifests, train_size=231, test_size=101, seed="unit-seed")

    distributions = metadata["distributions"]["by_database"]
    for database, eligible_count in OFFICIAL_QUERY_COUNTS.items():
        expected = 101 * eligible_count / 332
        assert abs(distributions[database]["test"] - expected) < 1
        assert distributions[database]["eligible"] == eligible_count
    assert sum(item["test"] for item in distributions.values()) == 101


def test_high_level_balance_is_preserved_within_each_database(tmp_path: Path) -> None:
    manifests = prepare_official_shape(tmp_path)

    metadata = create_split(manifests, train_size=231, test_size=101, seed="unit-seed")

    for distribution in metadata["distributions"]["by_database"].values():
        eligible_high = distribution["high_level"]["eligible"]
        expected_test_high = (
            distribution["test"] * eligible_high / distribution["eligible"]
        )
        assert abs(distribution["high_level"]["test"] - expected_test_high) < 1


def test_split_bytes_are_deterministic_and_seed_controls_membership(
    tmp_path: Path,
) -> None:
    first = prepare_official_shape(tmp_path / "first")
    second = prepare_official_shape(tmp_path / "second")
    third = prepare_official_shape(tmp_path / "third")

    create_split(first, train_size=231, test_size=101, seed="fixed-seed")
    create_split(second, train_size=231, test_size=101, seed="fixed-seed")
    create_split(third, train_size=231, test_size=101, seed="another-seed")

    for filename in ("train_ids.txt", "test_ids.txt", "split_metadata.json"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    assert (first / "test_ids.txt").read_bytes() != (
        third / "test_ids.txt"
    ).read_bytes()


@pytest.mark.parametrize(
    ("train_size", "test_size", "message"),
    [
        (230, 101, "must equal manifest count"),
        (232, 100, "train_size must be 231 and test_size must be 101"),
        (231, 101, "manifest contains duplicate instance_id"),
    ],
)
def test_split_rejects_invalid_sizes_and_duplicate_manifest(
    tmp_path: Path, train_size: int, test_size: int, message: str
) -> None:
    manifests = prepare_official_shape(tmp_path)
    if "duplicate" in message:
        manifest_path = manifests / "eligible_questions.jsonl"
        first_line = manifest_path.read_text(encoding="utf-8").splitlines()[0]
        with manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(first_line + "\n")

    with pytest.raises(SplitError, match=message):
        create_split(
            manifests, train_size=train_size, test_size=test_size, seed="fixed"
        )


def test_split_rejects_empty_seed_and_too_few_databases(tmp_path: Path) -> None:
    source = tmp_path / "source.jsonl"
    manifests = tmp_path / "manifests"
    write_jsonl(source, [public_record(f"only_{index}") for index in range(332)])
    prepare_public_manifest(source, manifests, source_commit="fixed")

    with pytest.raises(SplitError, match="seed must be a non-empty string"):
        create_split(manifests, train_size=231, test_size=101, seed="")

    metadata = create_split(manifests, train_size=231, test_size=101, seed="fixed")
    assert metadata["distributions"]["by_database"]["example_large"] == {
        "eligible": 332,
        "high_level": {"eligible": 0, "test": 0, "train": 0},
        "test": 101,
        "train": 231,
    }


def test_split_rejects_tampered_manifest_metadata(tmp_path: Path) -> None:
    manifests = prepare_official_shape(tmp_path)
    metadata_path = manifests / "manifest_metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["manifest"]["sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(SplitError, match="manifest SHA-256 does not match"):
        create_split(manifests, train_size=231, test_size=101, seed="fixed")


def test_development_split_is_exact_disjoint_exhaustive_and_train_only(
    tmp_path: Path,
) -> None:
    manifests = prepare_official_shape(tmp_path)
    create_split(manifests, train_size=231, test_size=101, seed="outer-seed")

    metadata = create_development_split(
        manifests, dev_a_size=154, dev_b_size=77, seed="inner-seed"
    )

    train_ids = set(read_ids(manifests / "train_ids.txt"))
    test_ids = set(read_ids(manifests / "test_ids.txt"))
    dev_a_ids = set(read_ids(manifests / "dev_a_ids.txt"))
    dev_b_ids = set(read_ids(manifests / "dev_b_ids.txt"))
    assert len(dev_a_ids) == 154
    assert len(dev_b_ids) == 77
    assert dev_a_ids.isdisjoint(dev_b_ids)
    assert dev_a_ids | dev_b_ids == train_ids
    assert (dev_a_ids | dev_b_ids).isdisjoint(test_ids)
    assert metadata["counts"] == {"development": 231, "dev_a": 154, "dev_b": 77}
    assert metadata["source_partition"]["file"] == "train_ids.txt"
    for distribution in metadata["distributions"]["by_database"].values():
        assert distribution["dev_a"] > 0
        assert distribution["dev_b"] > 0


def test_development_database_and_high_level_allocations_are_proportional(
    tmp_path: Path,
) -> None:
    manifests = prepare_official_shape(tmp_path)
    create_split(manifests, train_size=231, test_size=101, seed="outer-seed")

    metadata = create_development_split(
        manifests, dev_a_size=154, dev_b_size=77, seed="inner-seed"
    )

    for distribution in metadata["distributions"]["by_database"].values():
        expected_dev_b = 77 * distribution["development"] / 231
        assert abs(distribution["dev_b"] - expected_dev_b) < 1
        expected_high = (
            distribution["dev_b"]
            * distribution["high_level"]["development"]
            / distribution["development"]
        )
        assert abs(distribution["high_level"]["dev_b"] - expected_high) < 1


def test_development_split_audits_public_condition_marginals(tmp_path: Path) -> None:
    manifests = prepare_official_shape(tmp_path)
    create_split(manifests, train_size=231, test_size=101, seed="outer-seed")

    metadata = create_development_split(
        manifests, dev_a_size=154, dev_b_size=77, seed="inner-seed"
    )

    order_diagnostic = metadata["balance_diagnostics"]["conditions"]["order"]
    for value in ("false", "true"):
        expected = (
            metadata["distributions"]["overall"]["development"]["conditions"]["order"][
                value
            ]
            * 77
            / 231
        )
        actual = metadata["distributions"]["overall"]["dev_b"]["conditions"]["order"][
            value
        ]
        assert order_diagnostic[value] == {
            "actual_dev_b": actual,
            "absolute_deviation": pytest.approx(abs(actual - expected)),
            "expected_dev_b": pytest.approx(expected),
        }
    assert metadata["algorithm"]["primary_strata"] == [
        "selected_database",
        "high_level",
    ]
    assert "difficulty_tier" not in json.dumps(metadata)


def test_development_split_is_byte_deterministic_and_seeded(tmp_path: Path) -> None:
    first = prepare_official_shape(tmp_path / "first")
    second = prepare_official_shape(tmp_path / "second")
    third = prepare_official_shape(tmp_path / "third")
    for manifests in (first, second, third):
        create_split(manifests, train_size=231, test_size=101, seed="outer-seed")

    create_development_split(first, dev_a_size=154, dev_b_size=77, seed="fixed")
    create_development_split(second, dev_a_size=154, dev_b_size=77, seed="fixed")
    create_development_split(third, dev_a_size=154, dev_b_size=77, seed="changed")

    for filename in (
        "dev_a_ids.txt",
        "dev_b_ids.txt",
        "development_split_metadata.json",
    ):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    assert (first / "dev_b_ids.txt").read_bytes() != (
        third / "dev_b_ids.txt"
    ).read_bytes()


@pytest.mark.parametrize(
    ("dev_a_size", "dev_b_size", "message"),
    [
        (153, 77, "must equal the development partition count"),
        (155, 76, "dev_a_size must be 154 and dev_b_size must be 77"),
    ],
)
def test_development_split_rejects_invalid_sizes(
    tmp_path: Path, dev_a_size: int, dev_b_size: int, message: str
) -> None:
    manifests = prepare_official_shape(tmp_path)
    create_split(manifests, train_size=231, test_size=101, seed="outer-seed")

    with pytest.raises(SplitError, match=message):
        create_development_split(
            manifests,
            dev_a_size=dev_a_size,
            dev_b_size=dev_b_size,
            seed="inner-seed",
        )


def test_development_split_rejects_tampered_or_duplicate_train_ids(
    tmp_path: Path,
) -> None:
    manifests = prepare_official_shape(tmp_path)
    create_split(manifests, train_size=231, test_size=101, seed="outer-seed")
    train_path = manifests / "train_ids.txt"
    original = train_path.read_text(encoding="utf-8")
    first_id = original.splitlines()[0]

    train_path.write_text(original + f"{first_id}\n", encoding="utf-8")
    with pytest.raises(SplitError, match="duplicate ID"):
        create_development_split(
            manifests, dev_a_size=154, dev_b_size=77, seed="inner-seed"
        )

    train_path.write_text(original.replace(first_id, "foreign_id", 1), encoding="utf-8")
    with pytest.raises(SplitError, match="train_ids.txt SHA-256 does not match"):
        create_development_split(
            manifests, dev_a_size=154, dev_b_size=77, seed="inner-seed"
        )


def test_development_split_rejects_empty_seed(tmp_path: Path) -> None:
    manifests = prepare_official_shape(tmp_path)
    create_split(manifests, train_size=231, test_size=101, seed="outer-seed")

    with pytest.raises(SplitError, match="seed must be a non-empty string"):
        create_development_split(manifests, dev_a_size=154, dev_b_size=77, seed="")
