"""Report-ready Markdown from identity-free sealed aggregates."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from omni_benchmark.scoring import (
    OFFICIAL_SOFT_EX_VERSION,
    SENSITIVITY_SCORER_VERSION,
)
from omni_benchmark.sealed_report import (
    SealedReportError,
    publish_sealed_report,
    render_sealed_report,
    sealed_report_entrypoint,
    sealed_report_main,
)


def _interval(estimate: float) -> dict[str, float]:
    return {
        "estimate": estimate,
        "lower": max(0.0, estimate - 0.1),
        "upper": min(1.0, estimate + 0.1),
    }


def _aggregate(identity: str) -> dict[str, object]:
    version = (
        OFFICIAL_SOFT_EX_VERSION
        if identity == "official_soft_ex"
        else SENSITIVITY_SCORER_VERSION
    )
    conditions = {}
    for index, condition in enumerate(("C1", "C2", "C3", "C4"), start=1):
        accuracy = index / 10
        correct = index * 30
        conditions[condition] = {
            "content_refusal_rate": None,
            "correct": correct,
            "correctness_flip_count": index,
            "correctness_flip_rate": index / 100,
            "error_rate": index / 303,
            "generation_outcomes": {"answered": 303 - index, "errored": index},
            "insufficient_context_rate": None,
            "mean_accuracy": accuracy,
            "pass_0_count": 79 - index,
            "pass_1_count": index,
            "pass_2_count": 0,
            "pass_3_count": 21,
            "pass_3_rate": 21 / 100,
            "per_repetition_accuracy": {
                "1": accuracy,
                "2": accuracy,
                "3": accuracy,
            },
            "refused_or_error": index,
            "refused_or_error_rate": index / 300,
            "refusal_subtype_status": (
                "not_observable_from_frozen_generation_contract"
            ),
            "scheduled_attempts": 303,
            "scoreable_attempts": 300,
            "scoreable_questions": 100,
            "terminal_failure_classes": {},
            "unscorable_attempts": 3,
            "wrong_answer": 300 - correct - index,
            "wrong_rate": 1 - accuracy - index / 300,
        }
    contrasts = {
        label: {
            **_interval(estimate),
            "discordant_gains": 10 + index,
            "discordant_losses": 3 + index,
        }
        for index, (label, estimate) in enumerate(
            (("C2-C1", 0.1), ("C3-C2", 0.1), ("C4-C1", 0.3), ("C4-C3", 0.1))
        )
    }
    report = {
        "bootstrap": {
            "ci_level": 0.95,
            "interval": "percentile_nearest_rank",
            "replicates": 10_000,
            "sampler": "sha256_modulo_question_count_v1",
            "seed": "omni-livesqlbench-large-v1-analysis-v1",
        },
        "conditions": conditions,
        "contrasts": contrasts,
        "mcnemar_repetition_one": {
            label: {
                "discordant_gains": value["discordant_gains"],
                "discordant_losses": value["discordant_losses"],
                "exact_two_sided_p": 0.25,
                "holm_adjusted_p": None if label == "C4-C1" else 0.5,
            }
            for label, value in contrasts.items()
        },
        "primary": {
            "c4_mean_one_shot": _interval(0.4),
            "c4_minus_c1": contrasts["C4-C1"],
            "c4_repetition_one": _interval(0.5),
        },
        "question_count": 101,
        "scorer": {"identity": identity, "version": version},
    }
    return {
        "freeze_b_sha256": "a" * 64,
        "kind": "sealed-aggregate-result",
        "plan_sha256": "b" * 64,
        "release_sha256": "c" * 64,
        "report": report,
        "schema_version": 1,
        "score_artifact_sha256s": [f"{index:064x}" for index in range(12)],
        "test_ids_sha256": "d" * 64,
    }


def _write_private(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_render_sealed_report_contains_both_scorers_and_no_identities() -> None:
    markdown = render_sealed_report(
        _aggregate("official_soft_ex"),
        _aggregate("sensitivity"),
    )

    assert markdown.startswith("# Sealed held-out results\n")
    assert "Official-compatible Soft EX" in markdown
    assert "Corrected multiset sensitivity" in markdown
    assert "C4 mean one-shot execution accuracy | 40.0% | 30.0%–50.0%" in markdown
    assert "C4−C1 | 30.0% | 20.0%–40.0%" in markdown
    assert "Unavailable by the frozen generation contract" in markdown
    assert "1212 scheduled attempts" in markdown
    assert "question-" not in markdown
    assert "sealed:" not in markdown


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        (lambda value: value.__setitem__("schema_version", 2), "schema"),
        (lambda value: value.pop("plan_sha256"), "envelope schema"),
        (lambda value: value.__setitem__("kind", "other"), "kind"),
        (
            lambda value: value.__setitem__("score_artifact_sha256s", []),
            "twelve score artifacts",
        ),
        (
            lambda value: value["report"].__setitem__(  # type: ignore[union-attr]
                "question_count", 100
            ),
            "question count",
        ),
        (
            lambda value: value["report"]["scorer"].__setitem__(  # type: ignore[index]
                "version", "wrong"
            ),
            "scorer version",
        ),
        (
            lambda value: value.__setitem__("release_sha256", "e" * 64),
            "custody bindings",
        ),
        (
            lambda value: value["report"]["scorer"].__setitem__(  # type: ignore[index]
                "identity", "official_soft_ex"
            ),
            "scorer identity",
        ),
        (
            lambda value: value["report"].__setitem__(  # type: ignore[union-attr]
                "question_key", "question-1"
            ),
            "protected field",
        ),
        (
            lambda value: value["report"]["primary"][  # type: ignore[index]
                "c4_mean_one_shot"
            ].__setitem__("estimate", math.nan),
            "finite",
        ),
        (
            lambda value: value["report"]["conditions"]["C1"].pop(  # type: ignore[index]
                "generation_outcomes"
            ),
            "condition schema",
        ),
        (
            lambda value: value["report"]["conditions"]["C1"].__setitem__(  # type: ignore[index]
                "correct", 999
            ),
            "outcome counts",
        ),
        (
            lambda value: value.__setitem__("score_artifact_sha256s", ["e" * 64] * 12),
            "distinct score artifacts",
        ),
    ),
)
def test_render_sealed_report_rejects_invalid_or_mismatched_inputs(
    mutation: object,
    match: str,
) -> None:
    official = _aggregate("official_soft_ex")
    sensitivity = _aggregate("sensitivity")
    mutation(sensitivity)  # type: ignore[operator]

    with pytest.raises(SealedReportError, match=match):
        render_sealed_report(official, sensitivity)


def test_publish_sealed_report_is_confined_private_and_non_overwriting(
    tmp_path: Path,
) -> None:
    workspace = tmp_path.resolve()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    inputs = workspace / "runs" / "sealed-score"
    inputs.mkdir(parents=True)
    official = inputs / "official.json"
    sensitivity = inputs / "sensitivity.json"
    _write_private(official, _aggregate("official_soft_ex"))
    _write_private(sensitivity, _aggregate("sensitivity"))

    result = publish_sealed_report(
        workspace,
        official_path=Path("runs/sealed-score/official.json"),
        sensitivity_path=Path("runs/sealed-score/sensitivity.json"),
        expected_official_sha256=_sha256(official),
        expected_sensitivity_sha256=_sha256(sensitivity),
        destination=Path("runs/sealed-score/held-out-results.md"),
    )

    output = workspace / result["path"]
    assert output.stat().st_mode & 0o777 == 0o600
    assert len(result["report_sha256"]) == 64
    with pytest.raises(SealedReportError, match="exists"):
        publish_sealed_report(
            workspace,
            official_path=Path("runs/sealed-score/official.json"),
            sensitivity_path=Path("runs/sealed-score/sensitivity.json"),
            expected_official_sha256=_sha256(official),
            expected_sensitivity_sha256=_sha256(sensitivity),
            destination=Path("runs/sealed-score/held-out-results.md"),
        )


def test_publish_rejects_nonprivate_source_and_symlink(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    inputs = workspace / "runs"
    inputs.mkdir()
    official = inputs / "official.json"
    sensitivity = inputs / "sensitivity.json"
    _write_private(official, _aggregate("official_soft_ex"))
    _write_private(sensitivity, _aggregate("sensitivity"))
    official.chmod(0o644)

    with pytest.raises(SealedReportError, match="mode 0600"):
        publish_sealed_report(
            workspace,
            official_path=Path("runs/official.json"),
            sensitivity_path=Path("runs/sensitivity.json"),
            expected_official_sha256=_sha256(official),
            expected_sensitivity_sha256=_sha256(sensitivity),
            destination=Path("runs/report.md"),
        )

    official.unlink()
    official.symlink_to(sensitivity)
    with pytest.raises(SealedReportError, match="regular private file"):
        publish_sealed_report(
            workspace,
            official_path=Path("runs/official.json"),
            sensitivity_path=Path("runs/sensitivity.json"),
            expected_official_sha256="a" * 64,
            expected_sensitivity_sha256=_sha256(sensitivity),
            destination=Path("runs/report.md"),
        )


def test_publish_rejects_symlinked_parent_and_nonraw_destination(
    tmp_path: Path,
) -> None:
    workspace = tmp_path.resolve()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    private = workspace / "private"
    private.mkdir()
    _write_private(private / "official.json", _aggregate("official_soft_ex"))
    _write_private(private / "sensitivity.json", _aggregate("sensitivity"))
    (workspace / "runs-link").symlink_to(private, target_is_directory=True)

    with pytest.raises(SealedReportError, match="private directory path"):
        publish_sealed_report(
            workspace,
            official_path=Path("runs-link/official.json"),
            sensitivity_path=Path("runs-link/sensitivity.json"),
            expected_official_sha256=_sha256(private / "official.json"),
            expected_sensitivity_sha256=_sha256(private / "sensitivity.json"),
            destination=Path("runs/report.md"),
        )

    runs = workspace / "runs"
    runs.mkdir()
    _write_private(runs / "official.json", _aggregate("official_soft_ex"))
    _write_private(runs / "sensitivity.json", _aggregate("sensitivity"))
    with pytest.raises(SealedReportError, match="gitignored raw-run path"):
        publish_sealed_report(
            workspace,
            official_path=Path("runs/official.json"),
            sensitivity_path=Path("runs/sensitivity.json"),
            expected_official_sha256=_sha256(runs / "official.json"),
            expected_sensitivity_sha256=_sha256(runs / "sensitivity.json"),
            destination=Path("report.md"),
        )


def test_publish_rejects_aggregate_hash_mismatch_before_output(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    runs = workspace / "runs"
    runs.mkdir()
    official = runs / "official.json"
    sensitivity = runs / "sensitivity.json"
    _write_private(official, _aggregate("official_soft_ex"))
    _write_private(sensitivity, _aggregate("sensitivity"))

    with pytest.raises(SealedReportError, match="hash does not match"):
        publish_sealed_report(
            workspace,
            official_path=Path("runs/official.json"),
            sensitivity_path=Path("runs/sensitivity.json"),
            expected_official_sha256="f" * 64,
            expected_sensitivity_sha256=_sha256(sensitivity),
            destination=Path("runs/report.md"),
        )
    assert not (runs / "report.md").exists()


def test_cli_is_dry_by_default_before_opening_inputs(tmp_path: Path) -> None:
    with pytest.raises(SealedReportError, match="explicit execution acknowledgement"):
        sealed_report_main(
            [
                "--workspace",
                str(tmp_path.resolve()),
                "--official",
                "absent-official.json",
                "--sensitivity",
                "absent-sensitivity.json",
                "--expected-official-sha256",
                "a" * 64,
                "--expected-sensitivity-sha256",
                "b" * 64,
                "--destination",
                "report.md",
            ]
        )


def test_cli_explicitly_renders_and_prints_only_path_and_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path.resolve()
    (workspace / ".gitignore").write_text("runs/\n", encoding="utf-8")
    runs = workspace / "runs"
    runs.mkdir()
    official = runs / "official.json"
    sensitivity = runs / "sensitivity.json"
    _write_private(official, _aggregate("official_soft_ex"))
    _write_private(sensitivity, _aggregate("sensitivity"))

    status = sealed_report_main(
        [
            "--workspace",
            str(workspace),
            "--official",
            "runs/official.json",
            "--sensitivity",
            "runs/sensitivity.json",
            "--expected-official-sha256",
            _sha256(official),
            "--expected-sensitivity-sha256",
            _sha256(sensitivity),
            "--destination",
            "runs/report.md",
            "--render-sealed-report",
        ]
    )

    assert status == 0
    assert json.loads(capsys.readouterr().out) == {
        "path": "runs/report.md",
        "report_sha256": _sha256(runs / "report.md"),
    }


@pytest.mark.parametrize(
    ("failure", "message"),
    (
        (SealedReportError("safe detail"), "sealed report failed: safe detail"),
        (
            RuntimeError("private detail"),
            "sealed report failed: internal reporting error",
        ),
    ),
)
def test_entrypoint_sanitizes_expected_and_unexpected_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: Exception,
    message: str,
) -> None:
    def fail() -> int:
        raise failure

    monkeypatch.setattr(
        "omni_benchmark.sealed_report.sealed_report_main",
        fail,
    )

    assert sealed_report_entrypoint() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == message
    assert "private detail" not in captured.err
