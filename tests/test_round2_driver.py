import ast
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, strategies as st

from omni_benchmark.round2_driver import (
    DriverError,
    _write_exclusive,
    parse_manifest,
    run_stages,
)


def manifest(root, mode="dry"):
    return {
        "schema_version": 1,
        "series_id": "fake-series",
        "mode": mode,
        "stages": [
            {"name": name, "argv": [name], "outputs": [str(root / name)]}
            for name in ("prepare", "generate", "finalize")
        ],
    }


def records(root):
    return [
        json.loads(line)
        for line in (root / "stage-ledger.jsonl").read_text().splitlines()
    ]


def runner(calls, failed=""):
    def invoke(argv):
        calls.append(argv[0])
        return subprocess.CompletedProcess(argv, 7 if argv[0] == failed else 0)

    return invoke


def test_dry_manifest_runs_stages_in_order(tmp_path):
    calls = []
    data = manifest(tmp_path)
    assert (
        run_stages(parse_manifest(json.dumps(data)), tmp_path / "state", runner(calls))
        == 0
    )
    assert calls == ["prepare", "generate", "finalize"]
    ledger = records(tmp_path / "state")
    assert [row["event"] for row in ledger] == ["start", "end"] * 3
    assert [row["exit_code"] for row in ledger] == [None, 0] * 3
    assert ledger[0]["outputs"] == data["stages"][0]["outputs"]
    assert stat.S_IMODE((tmp_path / "state/stage-ledger.jsonl").stat().st_mode) == 0o600


@pytest.mark.parametrize("name", ["prepare", "generate", "finalize"])
def test_resume_from_each_stage(tmp_path, name):
    calls = []
    run_stages(
        parse_manifest(json.dumps(manifest(tmp_path))),
        tmp_path / "state",
        runner(calls),
        name,
    )
    names = ["prepare", "generate", "finalize"]
    assert calls == names[names.index(name) :]


def test_failed_stage_stops_and_records_exit_code(tmp_path):
    calls = []
    parsed = parse_manifest(json.dumps(manifest(tmp_path)))
    state = tmp_path / "state"
    assert run_stages(parsed, state, runner(calls, "generate")) == 7
    assert calls == ["prepare", "generate"]
    assert records(state)[-1]["exit_code"] == 7
    before = (state / "stage-ledger.jsonl").read_bytes()
    (tmp_path / "prepare").touch()
    calls = []
    assert run_stages(parsed, state, runner(calls)) == 0
    assert calls == ["generate", "finalize"]
    assert (state / "stage-ledger.jsonl").read_bytes().startswith(before)


def test_resume_requires_outputs_and_latest_success(tmp_path):
    parsed = parse_manifest(json.dumps(manifest(tmp_path)))
    state = tmp_path / "state"
    run_stages(parsed, state, runner([]))
    calls = []
    run_stages(parsed, state, runner(calls))
    assert calls == ["prepare", "generate", "finalize"]
    for name in calls:
        (tmp_path / name).touch()
    before = (state / "stage-ledger.jsonl").read_bytes()
    calls = []
    run_stages(parsed, state, runner(calls))
    assert calls == []
    assert (state / "stage-ledger.jsonl").read_bytes() == before


def test_ledger_refuses_overwrite(tmp_path):
    path = tmp_path / "ledger"
    _write_exclusive(path, b"original")
    with pytest.raises(DriverError, match="refusing overwrite"):
        _write_exclusive(path, b"replacement")
    assert path.read_bytes() == b"original"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: {**d, "extra": 1},
        lambda d: {**d, "stages": [d["stages"][0]] * 2},
        lambda d: {**d, "stages": [{**d["stages"][0], "extra": 1}]},
        lambda d: {**d, "stages": [{**d["stages"][0], "argv": []}]},
        lambda d: {**d, "schema_version": True},
        lambda d: {**d, "schema_version": 2},
        lambda d: {**d, "series_id": ""},
        lambda d: {**d, "mode": "other"},
        lambda d: {**d, "stages": {}},
        lambda d: {**d, "stages": []},
        lambda d: {**d, "stages": [None]},
        lambda d: {**d, "stages": [{**d["stages"][0], "outputs": [1]}]},
        lambda d: {**d, "stages": [{**d["stages"][0], "argv": ["x\x00"]}]},
    ],
)
def test_manifest_rejects_unknown_keys_and_duplicates(tmp_path, change):
    with pytest.raises(DriverError):
        parse_manifest(json.dumps(change(manifest(tmp_path))))


@pytest.mark.parametrize("raw", ["{", "null", '{"mode":"dry","mode":"live"}'])
def test_invalid_json(raw):
    with pytest.raises(DriverError):
        parse_manifest(raw)


@given(
    st.lists(
        st.text(alphabet="abcdef", min_size=1, max_size=12),
        unique=True,
        min_size=1,
        max_size=8,
    )
)
def test_manifest_json_roundtrip_preserves_stage_order(names):
    data = {
        "schema_version": 1,
        "series_id": "property",
        "mode": "dry",
        "stages": [
            {"name": name, "argv": ["fake", name], "outputs": []} for name in names
        ],
    }
    parsed = parse_manifest(json.dumps(data))
    assert [stage.name for stage in parsed.stages] == names
    assert parsed == parse_manifest(json.dumps(data, indent=2))


def test_driver_imports_no_policy_module():
    path = Path(__file__).parents[1] / "src/omni_benchmark/round2_driver.py"
    tree = ast.parse(path.read_text())
    names = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    ]
    names += [
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    ]
    assert not any(
        part.startswith(
            ("r2_dispatch", "r2_execution", "sealed_", "custody", "scoring", "freeze_b")
        )
        for name in names
        for part in name.split(".")
    )


def test_manifest_binding_and_invalid_resume_fail_before_runner(tmp_path):
    state = tmp_path / "state"
    original = manifest(tmp_path)
    run_stages(parse_manifest(json.dumps(original)), state, runner([]))
    before = (state / "stage-ledger.jsonl").read_bytes()
    calls = []
    with pytest.raises(DriverError, match="manifest"):
        run_stages(
            parse_manifest(json.dumps({**original, "mode": "live"})),
            state,
            runner(calls),
        )
    with pytest.raises(DriverError, match="unknown stage"):
        run_stages(parse_manifest(json.dumps(original)), state, runner(calls), "absent")
    assert calls == []
    assert (state / "stage-ledger.jsonl").read_bytes() == before


def test_runner_exception_records_terminal_error_and_propagates(tmp_path):
    def fail(argv):
        raise OSError("fake subprocess failure")

    state = tmp_path / "state"
    with pytest.raises(OSError, match="fake subprocess"):
        run_stages(parse_manifest(json.dumps(manifest(tmp_path))), state, fail)
    assert records(state)[-1]["event"] == "end"
    assert records(state)[-1]["error_type"] == "OSError"
    assert records(state)[-1]["exit_code"] is None


@pytest.mark.parametrize("content", [b"", b"broken\n", b"{}\n", b"{}"])
def test_corrupt_ledger_is_not_repaired(tmp_path, content):
    state = tmp_path / "state"
    state.mkdir()
    path = state / "stage-ledger.jsonl"
    path.write_bytes(content)
    calls = []
    with pytest.raises(DriverError):
        run_stages(parse_manifest(json.dumps(manifest(tmp_path))), state, runner(calls))
    assert calls == []
    assert path.read_bytes() == content


@pytest.mark.parametrize(
    "field,value",
    [
        ("stage", []),
        ("stage", "absent"),
        ("event", {}),
        ("exit_code", True),
        ("error_type", 123),
        ("outputs", []),
    ],
)
def test_ledger_rejects_malformed_record_fields(tmp_path, field, value):
    state = tmp_path / "state"
    parsed = parse_manifest(json.dumps(manifest(tmp_path)))
    run_stages(parsed, state, runner([]))
    rows = records(state)
    rows[0] = {**rows[0], field: value}
    path = state / "stage-ledger.jsonl"
    content = "".join(json.dumps(row) + "\n" for row in rows)
    path.write_text(content)
    with pytest.raises(DriverError):
        run_stages(parsed, state, runner([]))
    assert path.read_text() == content


@pytest.mark.parametrize(
    "changes",
    [
        {"exit_code": 0},
        {"event": "end", "exit_code": 0},
        {"event": "end"},
    ],
)
def test_invalid_ledger_event_sequence(tmp_path, changes):
    state = tmp_path / "state"
    parsed = parse_manifest(json.dumps(manifest(tmp_path)))
    run_stages(parsed, state, runner([]))
    row = {**records(state)[0], **changes}
    path = state / "stage-ledger.jsonl"
    path.write_text(json.dumps(row) + "\n")
    with pytest.raises(DriverError):
        run_stages(parsed, state, runner([]))


def test_noninteger_runner_status_is_recorded(tmp_path):
    state = tmp_path / "state"
    parsed = parse_manifest(json.dumps(manifest(tmp_path)))
    with pytest.raises(DriverError, match="noninteger"):
        run_stages(parsed, state, lambda argv: subprocess.CompletedProcess(argv, True))
    assert records(state)[-1]["error_type"] == "DriverError"
    assert run_stages(parsed, state, runner([])) == 0


def test_exclusive_write_io_failure_is_contextual(tmp_path):
    parent = tmp_path / "file"
    parent.touch()
    with pytest.raises(DriverError, match="materialization failed"):
        _write_exclusive(parent / "nested" / "ledger", b"content")


def test_latest_failure_prevents_skipping_even_with_outputs(tmp_path):
    parsed = parse_manifest(json.dumps(manifest(tmp_path)))
    state = tmp_path / "state"
    run_stages(parsed, state, runner([]))
    assert run_stages(parsed, state, runner([], "prepare")) == 7
    for stage in parsed.stages:
        Path(stage.outputs[0]).touch()
    calls = []
    run_stages(parsed, state, runner(calls))
    assert calls == ["prepare"]


def test_concurrent_invocation_is_rejected(tmp_path):
    parsed = parse_manifest(json.dumps(manifest(tmp_path)))
    state = tmp_path / "state"

    def nested(argv):
        with pytest.raises(DriverError, match="in use"):
            run_stages(parsed, state, runner([]))
        return subprocess.CompletedProcess(argv, 0)

    assert run_stages(parsed, state, nested) == 0


def test_cli_real_subprocess_resume_and_required_state_root(tmp_path):
    data = manifest(tmp_path)
    data = {
        **data,
        "stages": [
            {
                **stage,
                "argv": [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                    stage["outputs"][0],
                ],
            }
            for stage in data["stages"]
        ],
    }
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(data))
    script = Path(__file__).parents[1] / "scripts/round2_driver.py"
    env = {**os.environ, "PYTHONPATH": str(script.parent.parent / "src")}
    command = [sys.executable, str(script), "--manifest", str(source)]
    assert subprocess.run(command, env=env, capture_output=True).returncode == 2
    command += ["--state-root", str(tmp_path / "state")]
    first = subprocess.run(command, env=env, capture_output=True)
    assert first.returncode == 0, first.stderr
    assert all(Path(stage["outputs"][0]).exists() for stage in data["stages"])
    before = (tmp_path / "state/stage-ledger.jsonl").read_bytes()
    assert subprocess.run(command, env=env, capture_output=True).returncode == 0
    assert (tmp_path / "state/stage-ledger.jsonl").read_bytes() == before
    source.write_text("{}")
    assert subprocess.run(command, env=env, capture_output=True).returncode == 2
