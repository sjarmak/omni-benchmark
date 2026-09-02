from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from omni_benchmark.telemetry_db.custody import CustodyViolation, SplitIds
from omni_benchmark.telemetry_db.labels import (
    LabelError,
    LabelRecord,
    append_label,
    build_label_record,
    compute_label_id,
    instance_of_label,
    iter_label_records,
    parse_label_line,
)
from omni_benchmark.telemetry_db.taxonomy import (
    TAXONOMY_V1,
    TAXONOMY_VERSION,
    TaxonomyError,
    taxonomy_for,
    validate_category,
)


REPOSITORY_ROOT = Path(__file__).parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "label_attempt.py"
SHA = "a" * 63 + "b"
ATTEMPT_ID = "run-1:alpha_large_Q1:C1:1"
TEST_INSTANCE = "alpha_large_T1"
SPLIT = SplitIds(
    dev_a=frozenset({"alpha_large_Q1", "alpha_large_Q2", "alpha_large_Q3"}),
    test=frozenset({TEST_INSTANCE}),
)


def _attempt(instance: str, repetition: int = 1) -> str:
    return f"run-1:{instance}:C1:{repetition}"


def _append(labels_dir: Path, pass_id: str, **overrides: object) -> LabelRecord:
    return append_label(labels_dir, pass_id, _fields(**overrides), split=SPLIT)


def _fields(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "attempt_id": ATTEMPT_ID,
        "generation_record_sha256": SHA,
        "taxonomy_version": TAXONOMY_VERSION,
        "category": "relationship_join",
        "labeler": "human:stephanie",
        "rationale": "Joined on the wrong key.",
        "created_at": "2026-09-01T12:00:00Z",
    }
    return {**base, **overrides}


def test_taxonomy_has_thirteen_snake_case_codes_matching_the_doc() -> None:
    doc = (REPOSITORY_ROOT / "docs" / "failure-taxonomy.md").read_text("utf-8")
    assert len(TAXONOMY_V1) == 13
    for code, title in TAXONOMY_V1.items():
        assert code == code.lower() and " " not in code and "/" not in code
        assert f"| {title} |" in doc
    with pytest.raises(TypeError):
        TAXONOMY_V1["new_code"] = "x"  # type: ignore[index]


def test_taxonomy_lookup_rejects_unknown_version_and_category() -> None:
    assert taxonomy_for(TAXONOMY_VERSION) is TAXONOMY_V1
    assert validate_category(TAXONOMY_VERSION, "time_semantics") == "time_semantics"
    with pytest.raises(TaxonomyError, match="unknown taxonomy_version"):
        taxonomy_for("failure-taxonomy-v0")
    with pytest.raises(TaxonomyError, match="unknown category 'join'"):
        validate_category(TAXONOMY_VERSION, "join")


def test_parse_label_line_returns_record_with_derived_id() -> None:
    record = parse_label_line(json.dumps(_fields()), "pass-1")
    assert isinstance(record, LabelRecord)
    assert record.pass_id == "pass-1"
    assert record.category == "relationship_join"
    expected = compute_label_id({**_fields(), "pass_id": "pass-1"})
    assert record.label_id == expected
    assert len(record.label_id) == 64


def test_label_id_is_deterministic_and_sensitive_to_inputs() -> None:
    first = build_label_record(_fields(), "pass-1")
    again = build_label_record(_fields(), "pass-1")
    assert first == again
    assert first.label_id == again.label_id
    other_pass = build_label_record(_fields(), "pass-2")
    other_time = build_label_record(
        _fields(created_at="2026-09-01T12:00:01Z"), "pass-1"
    )
    other_labeler = build_label_record(_fields(labeler="model:claude"), "pass-1")
    assert len({first.label_id, other_pass.label_id, other_time.label_id}) == 3
    assert other_labeler.label_id != first.label_id
    rationale_only = build_label_record(_fields(rationale="different"), "pass-1")
    assert rationale_only.label_id == first.label_id


def test_declared_label_id_and_pass_id_are_verified() -> None:
    record = build_label_record(_fields(), "pass-1")
    line = record.to_line()
    assert line.endswith("\n")
    assert parse_label_line(line, "pass-1") == record
    with pytest.raises(LabelError, match="pass_id 'pass-1' does not match 'pass-2'"):
        parse_label_line(line, "pass-2")
    with pytest.raises(LabelError, match="label_id 'deadbeef' does not match"):
        build_label_record(_fields(label_id="deadbeef"), "pass-1")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"category": "join"}, "unknown category 'join'"),
        ({"taxonomy_version": "failure-taxonomy-v9"}, "unknown taxonomy_version"),
        ({"labeler": "stephanie"}, "must be 'human:<name>' or 'model:<name>'"),
        ({"labeler": "human:"}, "must be 'human:<name>' or 'model:<name>'"),
        ({"labeler": "robot:x"}, "must be 'human:<name>' or 'model:<name>'"),
        ({"generation_record_sha256": "abc"}, "64 lowercase hex"),
        ({"generation_record_sha256": SHA.upper()}, "64 lowercase hex"),
        ({"rationale": "   "}, "rationale must be a non-empty string"),
        ({"attempt_id": 7}, "attempt_id must be a non-empty string"),
        (
            {"attempt_id": "attempt-001"},
            "attempt_id: attempt_id 'attempt-001' is malformed",
        ),
        ({"created_at": "2026-09-01T12:00:00"}, "explicit UTC offset"),
        ({"created_at": "2026-09-01T12:00:00+02:00"}, "explicit UTC offset"),
        ({"created_at": "yesterday"}, "not ISO-8601"),
        ({"extra": 1}, "unknown label keys: extra"),
        ({"sol_sql": "select 1"}, "unknown label keys: sol_sql"),
    ],
)
def test_parse_label_line_rejects_invalid_fields(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(LabelError, match=message):
        parse_label_line(json.dumps(_fields(**overrides)), "pass-1")


def test_parse_label_line_rejects_missing_keys_bad_json_and_non_objects() -> None:
    fields = _fields()
    del fields["rationale"]
    del fields["created_at"]
    with pytest.raises(LabelError, match="missing label keys: created_at, rationale"):
        parse_label_line(json.dumps(fields), "pass-1")
    with pytest.raises(LabelError, match="not valid JSON"):
        parse_label_line("{not json", "pass-1")
    with pytest.raises(LabelError, match="must be a JSON object"):
        parse_label_line("[1, 2]", "pass-1")
    with pytest.raises(LabelError, match="pass_id '../x' must be a file stem"):
        parse_label_line(json.dumps(_fields()), "../x")


def test_created_at_accepts_plus_zero_offset() -> None:
    record = build_label_record(
        _fields(created_at="2026-09-01T12:00:00.250+00:00"), "pass-1"
    )
    assert record.created_at == "2026-09-01T12:00:00.250+00:00"


def test_append_label_appends_newline_terminated_lines(tmp_path: Path) -> None:
    first = _append(tmp_path, "pass-1")
    second = _append(tmp_path, "pass-1", attempt_id=_attempt("alpha_large_Q2"))
    path = tmp_path / "pass-1.jsonl"
    text = path.read_text("utf-8")
    assert text.count("\n") == 2 and text.endswith("\n")
    lines = text.splitlines()
    assert json.loads(lines[0])["label_id"] == first.label_id
    assert json.loads(lines[1])["attempt_id"] == _attempt("alpha_large_Q2")
    assert json.loads(lines[1])["pass_id"] == "pass-1"
    assert second.label_id != first.label_id
    assert list(iter_label_records(tmp_path)) == [first, second]
    assert instance_of_label(second) == "alpha_large_Q2"


def test_append_label_requires_existing_directory_and_valid_record(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "absent"
    with pytest.raises(LabelError, match="does not exist"):
        _append(missing, "pass-1")
    with pytest.raises(LabelError, match="unknown category"):
        _append(tmp_path, "pass-1", category="nope")
    assert not (tmp_path / "pass-1.jsonl").exists()
    with pytest.raises(LabelError, match="does not exist"):
        list(iter_label_records(missing))


@pytest.mark.parametrize(
    ("instance", "match"),
    [
        (TEST_INSTANCE, "is in the sealed test split"),
        ("beta_large_Q7", "is not in the dev-A split"),
    ],
)
def test_append_label_refuses_attempts_outside_dev_a(
    tmp_path: Path, instance: str, match: str
) -> None:
    with pytest.raises(CustodyViolation, match=match):
        _append(tmp_path, "pass-1", attempt_id=_attempt(instance))
    assert not (tmp_path / "pass-1.jsonl").exists()


def test_iter_label_records_orders_by_file_then_line(tmp_path: Path) -> None:
    b1, a1, a2 = (_attempt("alpha_large_Q1", r) for r in (3, 1, 2))
    b_second = _append(tmp_path, "b-pass", attempt_id=b1)
    a_first = _append(tmp_path, "a-pass", attempt_id=a1)
    a_second = _append(tmp_path, "a-pass", attempt_id=a2)
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    records = list(iter_label_records(tmp_path))
    assert [record.attempt_id for record in records] == [a1, a2, b1]
    assert records == [a_first, a_second, b_second]


def test_iter_label_records_reports_file_and_line_on_error(tmp_path: Path) -> None:
    _append(tmp_path, "pass-1")
    bad = tmp_path / "pass-1.jsonl"
    with bad.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_fields(category="bogus")) + "\n")
    with pytest.raises(LabelError, match=r"pass-1\.jsonl:2: unknown category"):
        list(iter_label_records(tmp_path))
    blank = tmp_path / "pass-2.jsonl"
    blank.write_text("\n" + json.dumps(_fields()) + "\n", encoding="utf-8")
    bad.unlink()
    with pytest.raises(LabelError, match=r"pass-2\.jsonl:1: blank line"):
        list(iter_label_records(tmp_path))


def _load_cli():
    spec = importlib.util.spec_from_file_location("label_attempt", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifests_dir(tmp_path: Path) -> Path:
    manifests = tmp_path / "manifests"
    manifests.mkdir(exist_ok=True)
    (manifests / "dev_a_ids.txt").write_text(
        "".join(f"{i}\n" for i in sorted(SPLIT.dev_a)), encoding="utf-8"
    )
    (manifests / "test_ids.txt").write_text(f"{TEST_INSTANCE}\n", encoding="utf-8")
    return manifests


def _cli_args(tmp_path: Path, **overrides: str) -> list[str]:
    values = {
        "labels-dir": str(tmp_path),
        "manifests-dir": str(_manifests_dir(tmp_path)),
        "pass-id": "cli-pass",
        "attempt-id": _attempt("alpha_large_Q3"),
        "generation-record-sha256": SHA,
        "category": "validation_retry",
        "labeler": "human:stephanie",
        "rationale": "Result contract exposed an UNKNOWN type.",
        **overrides,
    }
    return [f"--{key}={value}" for key, value in values.items()]


def test_cli_main_appends_and_prints_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _load_cli()
    exit_code = cli.main(_cli_args(tmp_path, **{"created-at": "2026-09-01T12:00:00Z"}))
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["created_at"] == "2026-09-01T12:00:00Z"
    assert printed["pass_id"] == "cli-pass"
    stored = list(iter_label_records(tmp_path))
    assert len(stored) == 1 and stored[0].to_dict() == printed


def test_cli_main_defaults_created_at_to_utc_now(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _load_cli()
    assert cli.main(_cli_args(tmp_path)) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["created_at"].endswith("Z")
    assert printed["created_at"].startswith("20")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"category": "nope"}, "unknown category 'nope'"),
        ({"attempt-id": _attempt(TEST_INSTANCE)}, "is in the sealed test split"),
        ({"attempt-id": _attempt("beta_large_Q7")}, "is not in the dev-A split"),
    ],
)
def test_cli_main_reports_rejection_with_non_zero_exit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    overrides: dict[str, str],
    message: str,
) -> None:
    cli = _load_cli()
    assert cli.main(_cli_args(tmp_path, **overrides)) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "label rejected: " in captured.err and message in captured.err
    assert not (tmp_path / "cli-pass.jsonl").exists()


def test_cli_reads_split_ids_from_the_committed_manifests_by_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli = _load_cli()
    assert cli._parser().get_default("manifests_dir") == Path("data/manifests")
    args = [a for a in _cli_args(tmp_path) if not a.startswith("--manifests-dir=")]
    assert cli.main([f"--manifests-dir={tmp_path / 'nowhere'}", *args]) == 2
    assert "label rejected: cannot load dev-A IDs" in capsys.readouterr().err
    assert not (tmp_path / "cli-pass.jsonl").exists()


def test_cli_subprocess_round_trip(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            *_cli_args(tmp_path, **{"created-at": "2026-09-01T00:00:00Z"}),
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stderr
    printed = json.loads(result.stdout)
    assert printed["label_id"] == list(iter_label_records(tmp_path))[0].label_id
    failure = subprocess.run(
        [sys.executable, str(SCRIPT), *_cli_args(tmp_path, labeler="nobody")],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"},
    )
    assert failure.returncode == 2
    assert "label rejected" in failure.stderr
