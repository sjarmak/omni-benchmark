"""Structural guardrails for the autoresearch command-line interface."""

from __future__ import annotations

import ast
from pathlib import Path


def test_autoresearch_cli_functions_remain_focused() -> None:
    """Keep parser construction and command dispatch split into focused helpers."""
    source = Path("src/omni_benchmark/autoresearch_cli.py").read_text()
    module = ast.parse(source)
    oversized = {
        node.name: node.end_lineno - node.lineno + 1
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.end_lineno is not None
        and node.end_lineno - node.lineno + 1 >= 50
    }

    assert oversized == {}
