"""Arm assignment for dev-A runs, read from a committed mapping file.

Which run stands for which arm is a fact about the study, not about the
harness: the C5 deployment writes condition ``C4`` into its records because
the scaffold is unchanged. The mapping file records that; this module only
reads it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .generation_rows import ReaderError
from .sources import load_json_object

ARMS_SCHEMA_VERSION = 1
_ENTRY_KEYS = frozenset({"arm", "canonical"})


@dataclass(frozen=True)
class ArmEntry:
    arm: str | None
    canonical: bool


@dataclass(frozen=True)
class ArmMapping:
    runs: Mapping[str, ArmEntry]

    def arm_for(self, run_id: str, condition: str) -> str:
        entry = self.runs.get(run_id)
        if entry is None or entry.arm is None:
            return condition
        return entry.arm

    def canonical(self, run_id: str) -> bool:
        entry = self.runs.get(run_id)
        return entry.canonical if entry is not None else False

    def mapped(self, run_id: str) -> bool:
        return run_id in self.runs


def read_arms(path: Path) -> ArmMapping:
    """Parse the arm mapping file, rejecting any entry that is not well-formed."""
    payload = load_json_object(path)
    if payload.get("schema_version") != ARMS_SCHEMA_VERSION:
        raise ReaderError(f"{path}: schema_version must be {ARMS_SCHEMA_VERSION}")
    runs = payload.get("runs")
    if not isinstance(runs, dict):
        raise ReaderError(f"{path}: runs must be an object keyed by run_id")
    return ArmMapping(
        MappingProxyType(
            {
                run_id: _parse_entry(run_id, entry, path)
                for run_id, entry in runs.items()
            }
        )
    )


def _parse_entry(run_id: str, entry: Any, path: Path) -> ArmEntry:
    context = f"{path}: runs[{run_id!r}]"
    if not isinstance(entry, dict) or set(entry) != _ENTRY_KEYS:
        raise ReaderError(f"{context}: entry must have exactly keys arm and canonical")
    arm = entry["arm"]
    if arm is not None and (not isinstance(arm, str) or not arm):
        raise ReaderError(f"{context}: arm must be a non-empty string or null")
    if not isinstance(entry["canonical"], bool):
        raise ReaderError(f"{context}: canonical must be a boolean")
    return ArmEntry(arm=arm, canonical=entry["canonical"])
