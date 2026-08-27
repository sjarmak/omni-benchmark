"""Release private dev-A labels without exposing dev-B or held-out labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


PRIVATE_FIELDS = ("sol_sql", "test_cases", "external_knowledge")
RELEASE_FIELDS = ("instance_id", *PRIVATE_FIELDS)
REQUIRED_FIELDS = frozenset(RELEASE_FIELDS)
CANONICAL_DEV_A_IDS = Path("data/manifests/dev_a_ids.txt")
CANONICAL_DEVELOPMENT_SPLIT_METADATA = Path(
    "data/manifests/development_split_metadata.json"
)
CANONICAL_AUTORESEARCH_CONFIG = Path("config/autoresearch.json")


class CustodyError(ValueError):
    """Raised when a custody operation would be unsafe or non-reproducible."""


@dataclass(frozen=True)
class ReleaseReport:
    """Non-sensitive provenance emitted by a selected-label release."""

    source_sha256: str
    output_sha256: str
    source_count: int
    released_count: int
    ignored_count: int

    def as_dict(self) -> dict[str, object]:
        """Return the fields safe to print or persist in experiment metadata."""
        return {
            "counts": {
                "ignored": self.ignored_count,
                "released": self.released_count,
                "source": self.source_count,
            },
            "output_sha256": self.output_sha256,
            "source_sha256": self.source_sha256,
        }


def _normalise_train_ids(train_ids: Iterable[str]) -> frozenset[str]:
    normalised: set[str] = set()
    for train_id in train_ids:
        if not isinstance(train_id, str) or not train_id:
            raise CustodyError("train IDs must be non-empty strings")
        if train_id in normalised:
            raise CustodyError("train IDs contain a duplicate")
        normalised.add(train_id)
    if not normalised:
        raise CustodyError("train IDs must not be empty")
    return frozenset(normalised)


def read_id_file(path: Path) -> tuple[str, ...]:
    """Read a newline-delimited ID manifest without accepting ambiguous blanks."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as error:
        raise CustodyError("cannot read train ID file") from error
    return _parse_id_lines(lines)


def _parse_id_lines(lines: Sequence[str]) -> tuple[str, ...]:
    if not lines:
        raise CustodyError("train ID file is empty")
    ids: list[str] = []
    seen: set[str] = set()
    for line_number, train_id in enumerate(lines, start=1):
        if not train_id:
            raise CustodyError(f"blank ID at line {line_number}")
        if train_id in seen:
            raise CustodyError(f"duplicate ID at line {line_number}")
        seen.add(train_id)
        ids.append(train_id)
    return tuple(ids)


def _validate_private_record(value: Any, line_number: int) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CustodyError(f"line {line_number}: record must be a JSON object")
    missing = REQUIRED_FIELDS - value.keys()
    if missing:
        raise CustodyError(f"line {line_number}: missing required fields")

    instance_id = value["instance_id"]
    if not isinstance(instance_id, str) or not instance_id:
        raise CustodyError(
            f"line {line_number}: instance_id must be a non-empty string"
        )
    sol_sql = value["sol_sql"]
    if not isinstance(sol_sql, list):
        raise CustodyError(f"line {line_number}: sol_sql must be an array")
    if not all(isinstance(item, str) for item in sol_sql):
        raise CustodyError(f"line {line_number}: sol_sql must be an array of strings")

    test_cases = value["test_cases"]
    if not isinstance(test_cases, list):
        raise CustodyError(f"line {line_number}: test_cases must be an array")

    external_knowledge = value["external_knowledge"]
    if not isinstance(external_knowledge, list):
        raise CustodyError(f"line {line_number}: external_knowledge must be an array")
    if not all(isinstance(item, str) for item in external_knowledge):
        raise CustodyError(
            f"line {line_number}: external_knowledge must be an array of strings"
        )
    return {field: value[field] for field in RELEASE_FIELDS}


def _private_instance_id(value: Any, line_number: int) -> str:
    """Read only the membership key before inspecting hidden record fields."""
    if not isinstance(value, dict):
        raise CustodyError(f"line {line_number}: record must be a JSON object")
    instance_id = value.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        raise CustodyError(
            f"line {line_number}: instance_id must be a non-empty string"
        )
    return instance_id


def _read_private_jsonl(
    source: Path,
    *,
    permitted_ids: frozenset[str],
    reject_foreign_ids: bool,
) -> tuple[dict[str, dict[str, Any]], int, str]:
    records: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    source_count = 0
    source_hash = hashlib.sha256()

    try:
        with source.open("rb") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                source_hash.update(raw_line)
                source_count += 1
                if not raw_line.strip():
                    raise CustodyError(f"line {line_number}: blank JSONL record")
                try:
                    decoded = json.loads(raw_line)
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise CustodyError(
                        f"line {line_number} is not valid JSON"
                    ) from error
                instance_id = _private_instance_id(decoded, line_number)
                if instance_id in seen:
                    raise CustodyError(f"line {line_number}: duplicate instance_id")
                seen.add(instance_id)
                if instance_id not in permitted_ids:
                    if reject_foreign_ids:
                        raise CustodyError(
                            f"line {line_number}: record outside the committed train partition"
                        )
                    continue
                record = _validate_private_record(decoded, line_number)
                records[instance_id] = record
    except CustodyError:
        raise
    except OSError as error:
        raise CustodyError("cannot read private source") from error

    if source_count == 0:
        raise CustodyError("private source contains no records")
    missing_count = len(permitted_ids - records.keys())
    if missing_count:
        raise CustodyError(f"private source is missing {missing_count} train records")
    return records, source_count, source_hash.hexdigest()


def _canonical_record(record: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _resolve_private_destination(
    destination: Path, resolved_workspace: Path
) -> tuple[Path, Path]:
    private_root = resolved_workspace / "data" / "private"
    requested_destination = (
        destination if destination.is_absolute() else resolved_workspace / destination
    )
    try:
        prospective_private_root = private_root.resolve(strict=False)
        prospective_destination = requested_destination.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise CustodyError("cannot resolve destination directory") from error

    if (
        prospective_private_root != private_root
        or not prospective_destination.is_relative_to(prospective_private_root)
    ):
        raise CustodyError("destination must resolve inside workspace/data/private")
    if os.path.lexists(requested_destination) and requested_destination.is_dir():
        raise CustodyError("destination must be a file path")

    try:
        requested_destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        resolved_private_root = private_root.resolve(strict=True)
        resolved_parent = requested_destination.parent.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise CustodyError("cannot resolve destination directory") from error
    resolved_destination = resolved_parent / requested_destination.name
    if resolved_private_root != private_root or not resolved_destination.is_relative_to(
        resolved_private_root
    ):
        raise CustodyError("destination must resolve inside workspace/data/private")
    if os.path.lexists(resolved_destination) and resolved_destination.is_dir():
        raise CustodyError("destination must be a file path")
    return resolved_destination, resolved_private_root


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _verify_directory_anchor(
    descriptor: int, expected_path: Path, private_root: Path
) -> None:
    """Verify a held directory still names the intended private-tree location."""
    try:
        resolved_path = expected_path.resolve(strict=True)
        path_stat = os.stat(expected_path, follow_symlinks=False)
        descriptor_stat = os.fstat(descriptor)
    except (OSError, RuntimeError) as error:
        raise CustodyError(
            "destination directory changed during publication"
        ) from error
    if (
        resolved_path != expected_path
        or not resolved_path.is_relative_to(private_root)
        or (path_stat.st_dev, path_stat.st_ino)
        != (descriptor_stat.st_dev, descriptor_stat.st_ino)
    ):
        raise CustodyError("destination directory changed during publication")


def _open_anchored_parent(destination: Path, private_root: Path) -> int:
    """Open each destination directory without following symlinks."""
    try:
        relative_parent = destination.parent.relative_to(private_root)
    except ValueError as error:
        raise CustodyError(
            "destination must resolve inside workspace/data/private"
        ) from error

    descriptor: int | None = None
    try:
        descriptor = os.open(private_root, _directory_flags())
        _verify_directory_anchor(descriptor, private_root, private_root)
        current_path = private_root
        for part in relative_parent.parts:
            child_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_descriptor
            current_path /= part
            _verify_directory_anchor(descriptor, current_path, private_root)
        return descriptor
    except CustodyError:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except OSError as error:
        if descriptor is not None:
            os.close(descriptor)
        raise CustodyError("cannot resolve destination directory") from error


def _directory_entry_exists(descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as error:
        raise CustodyError("cannot inspect train-only destination") from error
    return True


def _remove_published_entry(descriptor: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=descriptor)
        os.fsync(descriptor)
    except OSError as error:
        raise CustodyError("cannot remove unsafe partial publication") from error


def _write_temporary_records(
    parent_descriptor: int,
    temporary_name: str,
    records: Mapping[str, Mapping[str, Any]],
) -> str:
    output_hash = hashlib.sha256()
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_descriptor,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            for instance_id in sorted(records):
                encoded = _canonical_record(records[instance_id])
                handle.write(encoded)
                output_hash.update(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return output_hash.hexdigest()


def _link_temporary_entry(
    parent_descriptor: int, temporary_name: str, destination_name: str
) -> None:
    try:
        os.link(
            temporary_name,
            destination_name,
            src_dir_fd=parent_descriptor,
            dst_dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileExistsError as error:
        raise CustodyError("destination already exists; refusing overwrite") from error
    except OSError as error:
        raise CustodyError("could not atomically publish destination") from error


def _remove_temporary_entry(parent_descriptor: int, temporary_name: str) -> None:
    try:
        os.unlink(temporary_name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        return
    except OSError as error:
        raise CustodyError("cannot remove private temporary file") from error


def _publish_atomically(
    destination: Path,
    records: Mapping[str, Mapping[str, Any]],
    private_root: Path,
) -> str:
    parent_descriptor = _open_anchored_parent(destination, private_root)
    temporary_name = f".{destination.name}.{secrets.token_hex(12)}.tmp"
    published = False
    try:
        if _directory_entry_exists(parent_descriptor, destination.name):
            raise CustodyError("destination already exists; refusing overwrite")
        output_sha256 = _write_temporary_records(
            parent_descriptor, temporary_name, records
        )
        _verify_directory_anchor(parent_descriptor, destination.parent, private_root)
        _link_temporary_entry(parent_descriptor, temporary_name, destination.name)
        published = True
        _verify_directory_anchor(parent_descriptor, destination.parent, private_root)
        os.fsync(parent_descriptor)
    except CustodyError as error:
        if published:
            try:
                _remove_published_entry(parent_descriptor, destination.name)
            except CustodyError as cleanup_error:
                raise cleanup_error from error
        raise
    except OSError as error:
        if published:
            try:
                _remove_published_entry(parent_descriptor, destination.name)
            except CustodyError as cleanup_error:
                raise cleanup_error from error
        raise CustodyError("cannot create train-only destination") from error
    finally:
        try:
            _remove_temporary_entry(parent_descriptor, temporary_name)
        finally:
            os.close(parent_descriptor)
    return output_sha256


def _release_selected_records(
    *,
    source: Path,
    destination: Path,
    train_ids: Iterable[str],
    workspace: Path,
) -> ReleaseReport:
    """Copy only caller-selected records from an externally held JSONL source."""
    try:
        resolved_workspace = Path(workspace).resolve(strict=True)
        resolved_source = Path(source).resolve(strict=True)
    except OSError as error:
        raise CustodyError("cannot resolve workspace or private source") from error
    if resolved_source.is_relative_to(resolved_workspace):
        raise CustodyError("source must resolve outside the workspace")
    if not resolved_source.is_file():
        raise CustodyError("private source must be a regular file")

    permitted_ids = _normalise_train_ids(train_ids)
    resolved_destination, resolved_private_root = _resolve_private_destination(
        Path(destination), resolved_workspace
    )
    records, source_count, source_sha256 = _read_private_jsonl(
        resolved_source,
        permitted_ids=permitted_ids,
        reject_foreign_ids=False,
    )
    output_sha256 = _publish_atomically(
        resolved_destination, records, resolved_private_root
    )
    return ReleaseReport(
        source_sha256=source_sha256,
        output_sha256=output_sha256,
        source_count=source_count,
        released_count=len(records),
        ignored_count=source_count - len(records),
    )


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _deep_freeze(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, list):
        return tuple(_deep_freeze(item) for item in value)
    return value


def load_dev_a_records(
    source: Path, dev_a_ids: Iterable[str]
) -> Mapping[str, Mapping[str, Any]]:
    """Load an exact dev-A-only release into deeply immutable new objects."""
    permitted_ids = _normalise_train_ids(dev_a_ids)
    records, _, _ = _read_private_jsonl(
        Path(source),
        permitted_ids=permitted_ids,
        reject_foreign_ids=True,
    )
    return MappingProxyType(
        {
            instance_id: _deep_freeze(records[instance_id])
            for instance_id in sorted(records)
        }
    )


def _git_output(workspace: Path, arguments: Sequence[str]) -> str:
    try:
        return _git_bytes(workspace, arguments).decode("utf-8").strip()
    except UnicodeError as error:
        raise CustodyError("committed custody artifact is not UTF-8") from error


def _git_bytes(workspace: Path, arguments: Sequence[str]) -> bytes:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), *arguments],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise CustodyError("cannot verify committed custody artifacts") from error
    return completed.stdout


def _verify_committed_dev_a_ids(
    path: Path, workspace: Path, freeze_a_commit: str
) -> tuple[str, ...]:
    try:
        resolved_workspace = workspace.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        relative_path = resolved_path.relative_to(resolved_workspace)
    except (OSError, ValueError) as error:
        raise CustodyError("dev-A ID file must resolve inside the workspace") from error

    if relative_path != CANONICAL_DEV_A_IDS:
        raise CustodyError("dev-A IDs must use the canonical dev-A ID manifest")

    git_root = Path(
        _git_output(resolved_workspace, ["rev-parse", "--show-toplevel"])
    ).resolve()
    if git_root != resolved_workspace:
        raise CustodyError("workspace must be the git repository root")
    canonical_commit = _git_output(
        resolved_workspace, ["rev-parse", f"{freeze_a_commit}^{{commit}}"]
    )
    if canonical_commit != freeze_a_commit:
        raise CustodyError("Freeze-A commit must be the full canonical hash")
    _verify_committed_guardian_pin(resolved_workspace, freeze_a_commit)
    committed_hash = _git_output(
        resolved_workspace,
        ["rev-parse", f"{freeze_a_commit}:{relative_path.as_posix()}"],
    )
    current_hash = _git_output(resolved_workspace, ["hash-object", str(resolved_path)])
    if committed_hash != current_hash:
        raise CustodyError("dev-A ID file does not match the recorded Freeze-A commit")

    committed_id_bytes = _git_bytes(
        resolved_workspace,
        ["show", f"{freeze_a_commit}:{relative_path.as_posix()}"],
    )

    try:
        metadata = json.loads(
            _git_output(
                resolved_workspace,
                [
                    "show",
                    f"{freeze_a_commit}:{CANONICAL_DEVELOPMENT_SPLIT_METADATA.as_posix()}",
                ],
            )
        )
        dev_a_artifact = metadata["artifacts"]["dev_a_ids"]
        expected_file = dev_a_artifact["file"]
        expected_sha256 = dev_a_artifact["sha256"]
    except (CustodyError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise CustodyError("committed split metadata is invalid") from error

    try:
        committed_id_text = committed_id_bytes.decode("utf-8")
    except UnicodeError as error:
        raise CustodyError("committed dev-A ID file is not UTF-8") from error
    actual_sha256 = hashlib.sha256(committed_id_bytes).hexdigest()
    if (
        expected_file != CANONICAL_DEV_A_IDS.name
        or not isinstance(expected_sha256, str)
        or expected_sha256 != actual_sha256
    ):
        raise CustodyError("split metadata does not bind the committed dev-A IDs")
    return _parse_id_lines(committed_id_text.splitlines())


def _verify_committed_guardian_pin(workspace: Path, freeze_a_commit: str) -> None:
    try:
        config = json.loads(
            _git_output(
                workspace,
                [
                    "show",
                    f"{freeze_a_commit}:{CANONICAL_AUTORESEARCH_CONFIG.as_posix()}",
                ],
            )
        )
        guardian_pin = config["guardian_public_key_sha256"]
    except (CustodyError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise CustodyError("committed Freeze-A guardian config is invalid") from error
    if (
        not isinstance(guardian_pin, str)
        or re.fullmatch(r"[0-9a-f]{64}", guardian_pin) is None
    ):
        raise CustodyError("dev-B guardian key must be provisioned before Freeze A")


def release_main(argv: Sequence[str] | None = None) -> int:
    """Run the human-custody dev-A release from a committed split manifest."""
    parser = argparse.ArgumentParser(
        description="Release only committed dev-A labels from an external private JSONL."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dev-a-ids", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--freeze-a-commit", required=True)
    arguments = parser.parse_args(argv)

    dev_a_ids = _verify_committed_dev_a_ids(
        arguments.dev_a_ids, arguments.workspace, arguments.freeze_a_commit
    )
    report = _release_selected_records(
        source=arguments.source,
        destination=arguments.destination,
        train_ids=dev_a_ids,
        workspace=arguments.workspace,
    )
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0
