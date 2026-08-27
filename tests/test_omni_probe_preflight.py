from __future__ import annotations

import os
import py_compile
import stat
import subprocess
from pathlib import Path

import pytest

from omni_benchmark.omni_cli import OmniCliSettings
from omni_benchmark.omni_probe_preflight import (
    OmniProbePreflightError,
    observe_omni_cli_version,
    semantic_model_ref,
    verify_system_commit,
)


def _settings(*, branch_id: str | None = None, binary: str = "omni") -> OmniCliSettings:
    return OmniCliSettings(
        base_url="https://example.omniapp.co",
        model_id="semantic-model-1",
        profile=None,
        branch_id=branch_id,
        binary=binary,
    )


def test_semantic_model_reference_is_distinct_from_managed_llm_identity() -> None:
    assert semantic_model_ref(_settings()) == "model:semantic-model-1"
    assert semantic_model_ref(_settings(branch_id="revision-7")) == "branch:revision-7"


def test_cli_version_is_observed_from_binary_without_secret_environment(
    tmp_path: Path,
) -> None:
    binary = tmp_path / "omni-version-fixture"
    binary.write_text(
        "#!/bin/sh\n"
        'if [ -n "$OMNI_API_TOKEN" ]; then exit 19; fi\n'
        "printf 'omni version 1.2.3\\n'\n",
        encoding="utf-8",
    )
    binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    version = observe_omni_cli_version(
        _settings(binary=str(binary)),
        {"OMNI_API_TOKEN": "must-not-be-forwarded", "PATH": os.environ["PATH"]},
    )

    assert version == "1.2.3"


def test_cli_version_rejects_unrecognized_or_failed_output(tmp_path: Path) -> None:
    binary = tmp_path / "bad-omni-version"
    binary.write_text("#!/bin/sh\nprintf 'unknown build\\n'\n", encoding="utf-8")
    binary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)

    with pytest.raises(OmniProbePreflightError, match="invalid version response"):
        observe_omni_cli_version(
            _settings(binary=str(binary)),
            {"PATH": os.environ["PATH"]},
        )


def test_system_commit_rejects_ignored_runtime_bytecode(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "src" / "package"
    source.mkdir(parents=True)
    (workspace / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (source / "module.py").write_text("VALUE = 'safe'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=workspace)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=workspace)
    subprocess.run(["git", "add", "."], cwd=workspace, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=workspace, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    bytecode = source / "__pycache__" / "module.cpython-311.pyc"
    bytecode.parent.mkdir()
    py_compile.compile(str(source / "module.py"), cfile=str(bytecode), doraise=True)
    verify_system_commit(workspace, commit)
    safe_bytecode = bytecode.read_bytes()
    evil_source = workspace / "evil.py"
    evil_source.write_text("VALUE = 'evil'\n", encoding="utf-8")
    evil_bytecode = workspace / "evil.pyc"
    py_compile.compile(
        str(evil_source),
        cfile=str(evil_bytecode),
        dfile=str(source / "module.py"),
        doraise=True,
    )
    bytecode.write_bytes(safe_bytecode[:16] + evil_bytecode.read_bytes()[16:])

    with pytest.raises(OmniProbePreflightError, match="clean runtime tree"):
        verify_system_commit(workspace, commit)
