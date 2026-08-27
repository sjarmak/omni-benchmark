from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from omni_benchmark.hkb_cli import main


REPOSITORY_ROOT = Path(__file__).parents[1]


def _source_and_inventory(tmp_path: Path) -> tuple[Path, Path]:
    row = {
        "id": 0,
        "knowledge": "Revenue",
        "description": "Recognized revenue",
        "definition": "Revenue definition",
        "type": "domain_knowledge",
        "children_knowledge": -1,
    }
    content = (json.dumps(row) + "\n").encode()
    source = tmp_path / "source"
    source_file = source / "alpha_large" / "alpha_large_kb.jsonl"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(content)
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset": "birdsql/livesqlbench-large-v1",
                "revision": "a" * 40,
                "files": [
                    {
                        "database": "alpha_large",
                        "path": "alpha_large/alpha_large_kb.jsonl",
                        "oid": hashlib.sha1(
                            f"blob {len(content)}\0".encode() + content,
                            usedforsecurity=False,
                        ).hexdigest(),
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                ],
            }
        )
    )
    return source, inventory


def test_build_cli_emits_manifest_summary(tmp_path: Path, capsys) -> None:
    source, inventory = _source_and_inventory(tmp_path)
    output = tmp_path / "output"

    assert (
        main(
            [
                "build",
                "--inventory",
                str(inventory),
                "--source-root",
                str(source),
                "--output-root",
                str(output),
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    assert result["kind"] == "public-hkb-intermediate-representation"
    assert result["counts"]["entries"] == 1
    assert (output / "manifest.json").exists()


def test_prepare_hkb_script_is_a_thin_executable_wrapper() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/prepare_hkb.py", "--help"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "fetch" in result.stdout
    assert "build" in result.stdout
