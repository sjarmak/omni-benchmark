from __future__ import annotations

import hashlib

import pytest

import omni_benchmark.claude_direct_transport as claude_transport


@pytest.fixture(scope="session", autouse=True)
def _use_synthetic_claude_binary_for_mocked_transports(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Keep mocked transport tests independent of a host-installed Claude CLI."""
    binary = tmp_path_factory.mktemp("claude-test-runtime") / "claude"
    content = b"#!/bin/sh\nexit 97\n"
    binary.write_bytes(content)
    binary.chmod(0o700)

    patch = pytest.MonkeyPatch()
    # An operator who set the override in their shell must not steer the suite.
    patch.delenv(claude_transport.CLAUDE_BINARY_PATH_ENV, raising=False)
    patch.setattr(claude_transport, "PINNED_CLAUDE_BINARY", binary)
    patch.setattr(
        claude_transport,
        "PINNED_CLAUDE_BINARY_SHA256",
        hashlib.sha256(content).hexdigest(),
    )
    yield
    patch.undo()
