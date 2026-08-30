from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github/workflows/quality.yml"


def test_quality_workflow_enforces_the_local_contract_without_live_access() -> None:
    document = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert document["permissions"] == {"contents": "read"}
    assert set(document["on"]) == {"push", "pull_request"}
    assert document["on"]["push"]["branches"] == ["main"]
    assert document["on"]["pull_request"]["branches"] == ["main"]

    job = document["jobs"]["quality"]
    assert job["runs-on"] == "ubuntu-24.04"
    assert int(job["timeout-minutes"]) <= 30
    steps = job["steps"]
    uses = [step["uses"] for step in steps if "uses" in step]
    commands = [step["run"] for step in steps if "run" in step]

    assert all("@" in action and len(action.rsplit("@", 1)[1]) == 40 for action in uses)
    assert commands == [
        "uv python install 3.11",
        "uv sync --locked --dev",
        "uv run --frozen pytest --cov=omni_benchmark --cov-branch",
        "uv run --frozen ruff check .",
        "uv run --frozen ruff format --check .",
    ]

    serialized = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in ("secrets.", "OMNI_", "execute-live", "execute-sealed"):
        assert forbidden not in serialized
