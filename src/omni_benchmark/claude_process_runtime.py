"""Mechanical subprocess boundary for the restricted Claude transport."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Protocol

from .claude_direct_contract import ClaudeProcessResult
from .claude_resource_identity import PinnedClaudeResources


class ClaudeProcessRunner(Protocol):
    def __call__(
        self,
        command: tuple[str, ...],
        *,
        stdin: str,
        cwd: Path,
        env: dict[str, str],
        pass_fds: tuple[int, ...],
        timeout_seconds: float,
    ) -> ClaudeProcessResult: ...


def proc_fd_path(descriptor: int) -> str:
    """Return the inherited descriptor path visible inside the child process."""
    return f"/proc/self/fd/{descriptor}"


def claude_environment(resources: PinnedClaudeResources) -> dict[str, str]:
    """Construct the minimal environment for one restricted Claude invocation."""
    return {
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "CLAUDE_CONFIG_DIR": proc_fd_path(resources.config_fd),
        "HOME": proc_fd_path(resources.home_fd),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "TMPDIR": proc_fd_path(resources.temp_fd),
    }


def run_claude_process(
    command: tuple[str, ...],
    *,
    stdin: str,
    cwd: Path,
    env: dict[str, str],
    pass_fds: tuple[int, ...],
    timeout_seconds: float,
) -> ClaudeProcessResult:
    """Invoke the pinned CLI and retain only its observable process result."""
    started = time.monotonic()
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        cwd=cwd,
        env=env,
        input=stdin,
        pass_fds=pass_fds,
        text=True,
        timeout=timeout_seconds,
    )
    return ClaudeProcessResult(
        duration_seconds=max(0.0, time.monotonic() - started),
        returncode=completed.returncode,
        stderr=completed.stderr,
        stdout=completed.stdout,
    )
