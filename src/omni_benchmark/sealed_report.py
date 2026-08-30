"""Render validated identity-free sealed aggregates as concise Markdown."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .artifact_store import ArtifactStore, ArtifactStoreError
from .scoring import OFFICIAL_SOFT_EX_VERSION, SENSITIVITY_SCORER_VERSION

CONDITIONS = ("C1", "C2", "C3", "C4")
CONTRASTS = ("C2-C1", "C3-C2", "C4-C1", "C4-C3")
SCHEMA_VERSION = 1
MAX_AGGREGATE_BYTES = 2 * 1024 * 1024
_ENVELOPE_KEYS = {
    "freeze_b_sha256",
    "kind",
    "plan_sha256",
    "release_sha256",
    "report",
    "schema_version",
    "score_artifact_sha256s",
    "test_ids_sha256",
}
_REPORT_KEYS = {
    "bootstrap",
    "conditions",
    "contrasts",
    "mcnemar_repetition_one",
    "primary",
    "question_count",
    "scorer",
}
_CONDITION_KEYS = {
    "content_refusal_rate",
    "correct",
    "correctness_flip_count",
    "correctness_flip_rate",
    "error_rate",
    "generation_outcomes",
    "insufficient_context_rate",
    "mean_accuracy",
    "pass_0_count",
    "pass_1_count",
    "pass_2_count",
    "pass_3_count",
    "pass_3_rate",
    "per_repetition_accuracy",
    "refused_or_error",
    "refused_or_error_rate",
    "refusal_subtype_status",
    "scheduled_attempts",
    "scoreable_attempts",
    "scoreable_questions",
    "terminal_failure_classes",
    "unscorable_attempts",
    "wrong_answer",
    "wrong_rate",
}
_CONTRAST_KEYS = {
    "discordant_gains",
    "discordant_losses",
    "estimate",
    "lower",
    "upper",
}
_MCNEMAR_KEYS = {
    "discordant_gains",
    "discordant_losses",
    "exact_two_sided_p",
    "holm_adjusted_p",
}
_PROTECTED_KEYS = {
    "attempt_id",
    "db_id",
    "expected_result",
    "external_knowledge",
    "gold_result",
    "gold_sql",
    "instance_id",
    "question_id",
    "question_key",
    "sol_sql",
    "task_id",
    "test_cases",
    "test_correctness",
}


class SealedReportError(RuntimeError):
    """Sanitized aggregate-report boundary failure."""


def render_sealed_report(
    official: Mapping[str, Any], sensitivity: Mapping[str, Any]
) -> str:
    """Validate two sealed aggregates and render fixed identity-free fields."""
    official_report = _validate_aggregate(
        official,
        expected_identity="official_soft_ex",
        expected_version=OFFICIAL_SOFT_EX_VERSION,
    )
    sensitivity_report = _validate_aggregate(
        sensitivity,
        expected_identity="sensitivity",
        expected_version=SENSITIVITY_SCORER_VERSION,
    )
    for key in (
        "freeze_b_sha256",
        "plan_sha256",
        "release_sha256",
        "test_ids_sha256",
    ):
        if official[key] != sensitivity[key]:
            raise SealedReportError("sealed aggregates have different custody bindings")
    question_count = official_report["question_count"]
    if question_count != sensitivity_report["question_count"]:
        raise SealedReportError("sealed aggregates have different question counts")
    scheduled_attempts = question_count * len(CONDITIONS) * 3

    lines = [
        "# Sealed held-out results",
        "",
        (
            f"This aggregate-only report covers {question_count} held-out questions "
            f"and {scheduled_attempts} scheduled attempts (four conditions, three "
            "repetitions). It contains "
            "no question identities, SQL, result rows, or per-question correctness."
        ),
        "",
        "## Primary endpoints",
        "",
        "| Scorer | Endpoint | Estimate | 95% interval |",
        "| --- | --- | ---: | ---: |",
    ]
    for label, report in (
        ("Official-compatible Soft EX", official_report),
        ("Corrected multiset sensitivity", sensitivity_report),
    ):
        primary = report["primary"]
        for endpoint, key in (
            ("C4 mean one-shot execution accuracy", "c4_mean_one_shot"),
            ("C4 repetition-one execution accuracy", "c4_repetition_one"),
            ("C4−C1 paired accuracy difference", "c4_minus_c1"),
        ):
            lines.append(
                f"| {label} | {endpoint} | {_percent(primary[key]['estimate'])} "
                f"| {_interval(primary[key])} |"
            )

    lines.extend(
        (
            "",
            "## Four-condition matrix",
            "",
            (
                "| Scorer | Condition | Mean accuracy | Wrong rate | "
                "Refused/error | Error rate | Pass³ | Correctness flips |"
            ),
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        )
    )
    for label, report in (
        ("Official-compatible Soft EX", official_report),
        ("Corrected multiset sensitivity", sensitivity_report),
    ):
        for condition in CONDITIONS:
            row = report["conditions"][condition]
            lines.append(
                f"| {label} | {condition} | {_percent(row['mean_accuracy'])} "
                f"| {_percent(row['wrong_rate'])} "
                f"| {_percent(row['refused_or_error_rate'])} "
                f"| {_percent(row['error_rate'])} "
                f"| {_percent(row['pass_3_rate'])} "
                f"| {row['correctness_flip_count']} |"
            )

    lines.extend(
        (
            "",
            (
                "Content-refusal and insufficient-context rates are **Unavailable "
                "by the frozen generation contract**; the report does not infer "
                "those subtypes after the fact."
            ),
            "",
            "## Exploratory paired contrasts",
            "",
            "| Scorer | Contrast | Difference | 95% interval | Gains | Losses |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        )
    )
    for label, report in (
        ("Official-compatible Soft EX", official_report),
        ("Corrected multiset sensitivity", sensitivity_report),
    ):
        for contrast in CONTRASTS:
            row = report["contrasts"][contrast]
            display = contrast.replace("-", "−")
            lines.append(
                f"| {label} | {display} | {_percent(row['estimate'])} "
                f"| {_interval(row)} | {row['discordant_gains']} "
                f"| {row['discordant_losses']} |"
            )

    lines.extend(
        (
            "",
            (
                "Intervals are deterministic 95% held-out-item-clustered percentile "
                "bootstrap intervals with 10,000 replicates. Both preregistered "
                "scorers are reported without post-result selection."
            ),
            "",
        )
    )
    return "\n".join(lines)


def publish_sealed_report(
    workspace: Path,
    *,
    official_path: Path,
    sensitivity_path: Path,
    expected_official_sha256: str,
    expected_sensitivity_sha256: str,
    destination: Path,
) -> dict[str, str]:
    """Read two private aggregates and exclusively publish owner-only Markdown."""
    root = _workspace(workspace)
    expected_official = _digest(
        expected_official_sha256, "expected official aggregate SHA-256"
    )
    expected_sensitivity = _digest(
        expected_sensitivity_sha256, "expected sensitivity aggregate SHA-256"
    )
    official, official_sha256 = _read_private_json(
        root, official_path, "official aggregate"
    )
    if official_sha256 != expected_official:
        raise SealedReportError("official aggregate hash does not match")
    sensitivity, sensitivity_sha256 = _read_private_json(
        root, sensitivity_path, "sensitivity aggregate"
    )
    if sensitivity_sha256 != expected_sensitivity:
        raise SealedReportError("sensitivity aggregate hash does not match")
    markdown = render_sealed_report(official, sensitivity)
    selected = _relative_path(destination, "report destination")
    if selected.parent == Path("."):
        raise SealedReportError("report destination must use a gitignored raw-run path")
    data = markdown.encode("utf-8")
    try:
        stored = ArtifactStore(root, selected.parent).write_bytes(
            Path(selected.name), data
        )
    except ArtifactStoreError as error:
        raise SealedReportError(str(error)) from error
    return {
        "path": stored.path.relative_to(root).as_posix(),
        "report_sha256": stored.sha256,
    }


def sealed_report_entrypoint() -> int:
    """Sanitized command boundary."""
    try:
        return sealed_report_main()
    except SealedReportError as error:
        print(f"sealed report failed: {error}", file=sys.stderr)
        return 2
    except Exception:
        print("sealed report failed: internal reporting error", file=sys.stderr)
        return 2


def sealed_report_main(argv: Sequence[str] | None = None) -> int:
    """Parse the explicit report-rendering command."""
    arguments = _parser().parse_args(argv)
    if not arguments.render_sealed_report:
        raise SealedReportError(
            "sealed report requires explicit execution acknowledgement"
        )
    result = publish_sealed_report(
        arguments.workspace,
        official_path=arguments.official,
        sensitivity_path=arguments.sensitivity,
        expected_official_sha256=arguments.expected_official_sha256,
        expected_sensitivity_sha256=arguments.expected_sensitivity_sha256,
        destination=arguments.destination,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render two identity-free sealed aggregates as Markdown."
    )
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--sensitivity", type=Path, required=True)
    parser.add_argument("--expected-official-sha256", required=True)
    parser.add_argument("--expected-sensitivity-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--render-sealed-report", action="store_true")
    return parser


def _validate_aggregate(
    value: Mapping[str, Any], *, expected_identity: str, expected_version: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _ENVELOPE_KEYS:
        raise SealedReportError("sealed aggregate envelope schema is invalid")
    if value["schema_version"] != SCHEMA_VERSION:
        raise SealedReportError("sealed aggregate schema version is invalid")
    if value["kind"] != "sealed-aggregate-result":
        raise SealedReportError("sealed aggregate kind is invalid")
    for key in (
        "freeze_b_sha256",
        "plan_sha256",
        "release_sha256",
        "test_ids_sha256",
    ):
        _digest(value[key], key)
    score_hashes = value["score_artifact_sha256s"]
    if (
        isinstance(score_hashes, (str, bytes))
        or not isinstance(score_hashes, Sequence)
        or len(score_hashes) != 12
    ):
        raise SealedReportError("sealed aggregate must bind twelve score artifacts")
    for digest in score_hashes:
        _digest(digest, "score artifact SHA-256")
    if len(set(score_hashes)) != 12:
        raise SealedReportError(
            "sealed aggregate must bind twelve distinct score artifacts"
        )

    report = value["report"]
    if not isinstance(report, Mapping):
        raise SealedReportError("sealed aggregate report schema is invalid")
    _reject_protected(report)
    if set(report) != _REPORT_KEYS:
        raise SealedReportError("sealed aggregate report schema is invalid")
    _reject_nonfinite(report)
    question_count = report["question_count"]
    if isinstance(question_count, bool) or not isinstance(question_count, int):
        raise SealedReportError("sealed aggregate question count is invalid")
    if question_count <= 0:
        raise SealedReportError("sealed aggregate question count is invalid")
    scorer = _mapping(report["scorer"], "scorer")
    if set(scorer) != {"identity", "version"}:
        raise SealedReportError("sealed aggregate scorer schema is invalid")
    if scorer["identity"] != expected_identity:
        raise SealedReportError("sealed aggregate scorer identity is invalid")
    if scorer["version"] != expected_version:
        raise SealedReportError("sealed aggregate scorer version is invalid")
    if report["bootstrap"] != {
        "ci_level": 0.95,
        "interval": "percentile_nearest_rank",
        "replicates": 10_000,
        "sampler": "sha256_modulo_question_count_v1",
        "seed": "omni-livesqlbench-large-v1-analysis-v1",
    }:
        raise SealedReportError("sealed aggregate bootstrap contract is invalid")

    conditions = _mapping(report["conditions"], "conditions")
    if set(conditions) != set(CONDITIONS):
        raise SealedReportError("sealed aggregate condition set is invalid")
    scheduled = 0
    for condition in CONDITIONS:
        row = _mapping(conditions[condition], f"{condition} condition")
        if set(row) != _CONDITION_KEYS:
            raise SealedReportError(f"{condition} condition schema is invalid")
        for field in (
            "mean_accuracy",
            "wrong_rate",
            "refused_or_error_rate",
            "error_rate",
            "pass_3_rate",
            "correctness_flip_rate",
        ):
            _rate(row.get(field), f"{condition} {field}")
        for field in (
            "correct",
            "wrong_answer",
            "refused_or_error",
            "correctness_flip_count",
            "scheduled_attempts",
            "scoreable_attempts",
            "scoreable_questions",
            "unscorable_attempts",
        ):
            _count(row.get(field), f"{condition} {field}")
        if (
            row.get("content_refusal_rate") is not None
            or row.get("insufficient_context_rate") is not None
        ):
            raise SealedReportError("unavailable refusal subtype rate is invalid")
        if row.get("refusal_subtype_status") != (
            "not_observable_from_frozen_generation_contract"
        ):
            raise SealedReportError("refusal subtype status is invalid")
        if row["scheduled_attempts"] != question_count * 3:
            raise SealedReportError(
                "sealed aggregate question count and scheduled count are inconsistent"
            )
        generation = _count_mapping(
            row["generation_outcomes"], f"{condition} generation outcomes"
        )
        terminal = _count_mapping(
            row["terminal_failure_classes"],
            f"{condition} terminal failure classes",
        )
        del terminal
        if sum(generation.values()) != row["scheduled_attempts"]:
            raise SealedReportError(
                f"{condition} generation outcome counts are inconsistent"
            )
        repetitions = _mapping(
            row["per_repetition_accuracy"],
            f"{condition} repetition accuracy",
        )
        if set(repetitions) != {"1", "2", "3"}:
            raise SealedReportError(
                f"{condition} repetition accuracy schema is invalid"
            )
        for repetition, rate in repetitions.items():
            _rate(rate, f"{condition} repetition {repetition} accuracy")
        if (
            row["scoreable_attempts"] + row["unscorable_attempts"]
            != row["scheduled_attempts"]
        ):
            raise SealedReportError(f"{condition} scoreability counts are inconsistent")
        if (
            row["correct"] + row["wrong_answer"] + row["refused_or_error"]
            != row["scoreable_attempts"]
        ):
            raise SealedReportError(f"{condition} outcome counts are inconsistent")
        pass_counts = tuple(row[f"pass_{value}_count"] for value in range(4))
        if sum(pass_counts) != row["scoreable_questions"]:
            raise SealedReportError(f"{condition} reliability counts are inconsistent")
        if row["correctness_flip_count"] != row["pass_1_count"] + row["pass_2_count"]:
            raise SealedReportError(f"{condition} flip counts are inconsistent")
        _require_ratio(
            row["mean_accuracy"],
            row["correct"],
            row["scoreable_attempts"],
            f"{condition} mean accuracy",
        )
        _require_ratio(
            row["wrong_rate"],
            row["wrong_answer"],
            row["scoreable_attempts"],
            f"{condition} wrong rate",
        )
        _require_ratio(
            row["refused_or_error_rate"],
            row["refused_or_error"],
            row["scoreable_attempts"],
            f"{condition} refused/error rate",
        )
        _require_ratio(
            row["pass_3_rate"],
            row["pass_3_count"],
            row["scoreable_questions"],
            f"{condition} pass-three rate",
        )
        _require_ratio(
            row["correctness_flip_rate"],
            row["correctness_flip_count"],
            row["scoreable_questions"],
            f"{condition} flip rate",
        )
        _require_ratio(
            row["error_rate"],
            generation.get("errored", 0),
            row["scheduled_attempts"],
            f"{condition} error rate",
        )
        scheduled += row["scheduled_attempts"]
    if scheduled != question_count * len(CONDITIONS) * 3:
        raise SealedReportError("sealed aggregate attempt count is invalid")

    contrasts = _mapping(report["contrasts"], "contrasts")
    if set(contrasts) != set(CONTRASTS):
        raise SealedReportError("sealed aggregate contrast set is invalid")
    for contrast in CONTRASTS:
        _validate_interval(contrasts[contrast], f"{contrast} contrast", signed=True)
        row = _mapping(contrasts[contrast], f"{contrast} contrast")
        if set(row) != _CONTRAST_KEYS:
            raise SealedReportError(f"{contrast} contrast schema is invalid")
        _count(row.get("discordant_gains"), f"{contrast} gains")
        _count(row.get("discordant_losses"), f"{contrast} losses")

    primary = _mapping(report["primary"], "primary")
    if set(primary) != {
        "c4_mean_one_shot",
        "c4_minus_c1",
        "c4_repetition_one",
    }:
        raise SealedReportError("sealed aggregate primary endpoint set is invalid")
    _validate_interval(primary["c4_mean_one_shot"], "C4 mean", signed=False)
    _validate_interval(primary["c4_repetition_one"], "C4 repetition one", signed=False)
    _validate_interval(primary["c4_minus_c1"], "C4-C1 primary", signed=True)
    if primary["c4_minus_c1"] != contrasts["C4-C1"]:
        raise SealedReportError("C4-C1 primary endpoint is inconsistent")

    mcnemar = _mapping(report["mcnemar_repetition_one"], "McNemar reports")
    if set(mcnemar) != set(CONTRASTS):
        raise SealedReportError("sealed aggregate McNemar set is invalid")
    for contrast in CONTRASTS:
        row = _mapping(mcnemar[contrast], f"{contrast} McNemar report")
        if set(row) != _MCNEMAR_KEYS:
            raise SealedReportError(f"{contrast} McNemar schema is invalid")
        _count(row["discordant_gains"], f"{contrast} McNemar gains")
        _count(row["discordant_losses"], f"{contrast} McNemar losses")
        _rate(row["exact_two_sided_p"], f"{contrast} exact p-value")
        adjusted = row["holm_adjusted_p"]
        if contrast == "C4-C1":
            if adjusted is not None:
                raise SealedReportError("primary McNemar result must be unadjusted")
        else:
            _rate(adjusted, f"{contrast} adjusted p-value")
    return report


def _validate_interval(value: object, description: str, *, signed: bool) -> None:
    row = _mapping(value, description)
    required = {"estimate", "lower", "upper"}
    if not required.issubset(row):
        raise SealedReportError(f"{description} interval is incomplete")
    lower_bound = -1.0 if signed else 0.0
    values = tuple(_number(row[key], f"{description} {key}") for key in required)
    if any(item < lower_bound or item > 1.0 for item in values):
        raise SealedReportError(f"{description} interval is outside its range")
    if row["lower"] > row["estimate"] or row["estimate"] > row["upper"]:
        raise SealedReportError(f"{description} interval ordering is invalid")


def _read_private_json(
    root: Path, selected: Path, description: str
) -> tuple[Mapping[str, Any], str]:
    relative = _relative_path(selected, description)
    directory = os.open(
        root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
    )
    descriptor: int | None = None
    try:
        for part in relative.parts[:-1]:
            try:
                next_directory = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory,
                )
            except OSError as error:
                raise SealedReportError(
                    f"{description} has an invalid private directory path"
                ) from error
            os.close(directory)
            directory = next_directory
        name = relative.name
        metadata = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_uid != os.getuid()
        ):
            raise SealedReportError(f"{description} must be a regular private file")
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            raise SealedReportError(f"{description} must have mode 0600")
        if metadata.st_size < 1 or metadata.st_size > MAX_AGGREGATE_BYTES:
            raise SealedReportError(f"{description} has an invalid size")
        descriptor = os.open(
            name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=directory,
        )
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_mode != metadata.st_mode
            or opened.st_uid != metadata.st_uid
            or opened.st_nlink != metadata.st_nlink
            or opened.st_size != metadata.st_size
        ):
            raise SealedReportError(f"{description} changed while opening")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, 64 * 1024):
            size += len(chunk)
            if size > MAX_AGGREGATE_BYTES:
                raise SealedReportError(f"{description} is too large")
            chunks.append(chunk)
        content = b"".join(chunks)
    except SealedReportError:
        raise
    except OSError as error:
        raise SealedReportError(f"{description} is unavailable") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)
    try:
        value = json.loads(content, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise SealedReportError(f"{description} is not strict JSON") from error
    if not isinstance(value, Mapping):
        raise SealedReportError(f"{description} must be a JSON object")
    return value, hashlib.sha256(content).hexdigest()


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_protected(value: object) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str) or key in _PROTECTED_KEYS:
                raise SealedReportError("sealed aggregate contains a protected field")
            _reject_protected(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _reject_protected(item)


def _reject_nonfinite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise SealedReportError("sealed aggregate numbers must be finite")
    if isinstance(value, Mapping):
        for item in value.values():
            _reject_nonfinite(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            _reject_nonfinite(item)


def _workspace(value: Path) -> Path:
    absolute = Path(value).absolute()
    try:
        resolved = Path(value).resolve(strict=True)
    except OSError as error:
        raise SealedReportError("workspace is unavailable") from error
    if absolute != resolved or not resolved.is_dir() or resolved.is_symlink():
        raise SealedReportError("workspace must be a non-symlink directory")
    return resolved


def _relative_path(selected: Path, description: str) -> Path:
    value = Path(selected)
    if value.is_absolute() or not value.parts or ".." in value.parts:
        raise SealedReportError(f"{description} must be a confined relative path")
    return value


def _mapping(value: object, description: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SealedReportError(f"{description} must be an object")
    return value


def _number(value: object, description: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SealedReportError(f"{description} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise SealedReportError(f"{description} must be finite")
    return numeric


def _rate(value: object, description: str) -> float:
    numeric = _number(value, description)
    if numeric < 0 or numeric > 1:
        raise SealedReportError(f"{description} must be between zero and one")
    return numeric


def _count(value: object, description: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SealedReportError(f"{description} must be a nonnegative integer")
    return value


def _count_mapping(value: object, description: str) -> dict[str, int]:
    selected = _mapping(value, description)
    counts: dict[str, int] = {}
    for key, item in selected.items():
        if not isinstance(key, str) or not key:
            raise SealedReportError(f"{description} keys must be non-empty strings")
        counts[key] = _count(item, f"{description} count")
    return counts


def _require_ratio(
    value: object,
    numerator: int,
    denominator: int,
    description: str,
) -> None:
    if denominator <= 0:
        raise SealedReportError(f"{description} denominator is invalid")
    if not math.isclose(
        _rate(value, description),
        numerator / denominator,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise SealedReportError(f"{description} is inconsistent with counts")


def _digest(value: object, description: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SealedReportError(f"{description} must be a lowercase SHA-256")
    return value


def _percent(value: object) -> str:
    return f"{100 * _number(value, 'report rate'):.1f}%"


def _interval(value: Mapping[str, Any]) -> str:
    return f"{_percent(value['lower'])}–{_percent(value['upper'])}"
