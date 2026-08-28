from __future__ import annotations

import json
from pathlib import Path

from omni_benchmark import semantic_bundle_cli


def test_main_publishes_requested_public_bundle(monkeypatch, capsys) -> None:
    observed: tuple[Path, ...] | None = None

    def fake_publish(*paths: Path) -> dict[str, object]:
        nonlocal observed
        observed = paths
        return {"database": "db", "validation": {"status": "passed"}}

    monkeypatch.setattr(semantic_bundle_cli, "publish_bundle_artifacts", fake_publish)

    result = semantic_bundle_cli.main(
        [
            "--spec",
            "spec.json",
            "--hkb-ir",
            "hkb.jsonl",
            "--schema-ir",
            "schema.jsonl",
            "--mapping",
            "mapping.jsonl",
            "--mapping-manifest",
            "mapping-manifest.json",
            "--output-root",
            "bundle",
        ]
    )

    assert result == 0
    assert observed == (
        Path("spec.json"),
        Path("hkb.jsonl"),
        Path("schema.jsonl"),
        Path("mapping.jsonl"),
        Path("mapping-manifest.json"),
        Path("bundle"),
    )
    assert json.loads(capsys.readouterr().out)["validation"]["status"] == "passed"
