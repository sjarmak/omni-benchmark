from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml

import omni_benchmark.measure_treatment_bundle_cli as bundle_cli
from omni_benchmark.measure_review_catalog import canonical_catalog_bytes
from omni_benchmark.measure_treatment_bundle import (
    BALANCED_AI_SETTINGS,
    BALANCED_AI_SETTINGS_YAML,
    EXPECTED_ACCEPTED_CATALOG_SHA256,
    MeasureBundleError,
    MeasureBundleSet,
    build_database_measure_bundle_pair,
    build_workspace_measure_bundle_set,
    verify_measure_bundle_set,
    write_measure_bundle_set,
)
from omni_benchmark.omni_semantic_deployment import build_semantic_deployment_plan


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
VIEW_FILE = "db.public__orders.view"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_records(files: dict[str, bytes]) -> list[dict[str, object]]:
    return [
        {
            "file": name,
            "sha256": _sha256(content),
            "size_bytes": len(content),
        }
        for name, content in sorted(files.items())
    ]


def _c5_bundle() -> tuple[dict[str, bytes], dict[str, object]]:
    files = {
        "db_public__orders.topic": (b"label: Orders\nbase_view: db_public__orders\n"),
        VIEW_FILE: (
            b"label: Orders\n"
            b"description: Public orders.\n"
            b"catalog: db\n"
            b"schema: public\n"
            b"table_name: orders\n"
            b"dimensions:\n"
            b"  id:\n"
            b"    description: Public identity.\n"
            b"    sql: id\n"
            b"  amount:\n"
            b"    description: Public amount.\n"
            b"    sql: amount\n"
        ),
        "model": b"ai_context: Public context.\n",
        "relationships": b"[]\n",
    }
    manifest: dict[str, object] = {
        "database": "db",
        "direct_physical_bindings": [],
        "files": _file_records(files),
        "kind": "public-omni-semantic-bundle",
        "schema_version": 1,
        "source": {
            "bundle_spec": {"sha256": "1" * 64},
            "hkb_ir": {"sha256": "2" * 64},
            "mapping": {"sha256": "3" * 64},
            "mapping_manifest": {"sha256": "4" * 64},
            "schema_ir": {"sha256": "5" * 64},
        },
    }
    return files, manifest


def _candidate(
    *,
    suffix: str = "1",
    measure_name: str = "count",
    sql: str = "${db_public__orders.id}",
    view_file: str = VIEW_FILE,
) -> dict[str, object]:
    definition = {
        "aggregate_type": "count_distinct",
        "description": "Count of distinct Orders public identity values.",
        "label": "Orders Count",
        "sql": sql,
    }
    return {
        "candidate_class": "entity_count",
        "candidate_id": f"r2m1-{'a' * 63}{suffix}",
        "database": "db",
        "evidence": {
            "identity_field_stable_id": "db:column:orders:id",
            "identity_kind": "primary_key",
            "public_records": [],
            "table_stable_id": "db:table:orders",
        },
        "inline_equivalent_signature": {
            "aggregate_type": "count_distinct",
            "source_field_stable_ids": ["db:column:orders:id"],
        },
        "measure": {"definition": definition, "name": measure_name},
        "measure_id": f"r2m1m-{'b' * 63}{suffix}",
        "proposed_omni_yaml": yaml.safe_dump(
            {"measures": {measure_name: definition}},
            allow_unicode=True,
            sort_keys=True,
            width=1000,
        ),
        "view": {
            "file_name": view_file,
            "table_stable_id": "db:table:orders",
            "view_name": "db_public__orders",
        },
    }


def _catalog_bytes(
    candidates: list[dict[str, object]] | None = None,
) -> bytes:
    accepted = candidates or [_candidate()]
    accepted.sort(key=lambda item: str(item["candidate_id"]))
    databases = sorted({str(item["database"]) for item in accepted})
    counts = {
        database: sum(item["database"] == database for item in accepted)
        for database in databases
    }
    artifact: dict[str, object] = {
        "accepted_candidates": accepted,
        "catalog_version": "public-evidence-measure-catalog-v1",
        "generator": {
            "database_count": len(databases),
            "databases": databases,
            "input_files": [
                {
                    "path": "semantic_models/public_schema_ir/db.schema.jsonl",
                    "sha256": "9" * 64,
                }
            ],
            "version": "r2-public-evidence-measure-candidates-v1",
        },
        "kind": "public-evidence-measure-catalog",
        "manifest": {
            "ordered_candidate_ids": [item["candidate_id"] for item in accepted],
            "ordered_measure_ids": [item["measure_id"] for item in accepted],
        },
        "schema_version": 1,
        "source": {"decision_artifact_sha256": "8" * 64},
        "summary": {
            "accepted_candidate_count": len(accepted),
            "accepted_database_count": len(databases),
            "accepted_databases": databases,
            "candidate_count_by_class": {"entity_count": len(accepted)},
            "measure_count_by_database": counts,
        },
    }
    manifest = artifact["manifest"]
    assert isinstance(manifest, dict)
    manifest["artifact_sha256"] = _sha256(canonical_catalog_bytes(artifact))
    return canonical_catalog_bytes(artifact)


def _reseal_catalog(value: dict[str, object]) -> bytes:
    manifest = value["manifest"]
    assert isinstance(manifest, dict)
    manifest.pop("artifact_sha256", None)
    manifest["artifact_sha256"] = _sha256(canonical_catalog_bytes(value))
    return canonical_catalog_bytes(value)


def _pair(
    *,
    files: dict[str, bytes] | None = None,
    manifest: dict[str, object] | None = None,
    catalog: bytes | None = None,
):
    base_files, base_manifest = _c5_bundle()
    selected_files = files or base_files
    selected_manifest = manifest or base_manifest
    catalog_bytes = catalog or _catalog_bytes()
    return build_database_measure_bundle_pair(
        "db",
        selected_files,
        selected_manifest,
        catalog_bytes,
        expected_catalog_sha256=_sha256(catalog_bytes),
    )


def test_pair_materializes_balanced_settings_and_only_treatment_measures() -> None:
    base_files, _manifest = _c5_bundle()

    pair = _pair()

    expected_model = base_files["model"] + BALANCED_AI_SETTINGS_YAML
    assert pair.control_files["model"] == expected_model
    assert pair.treatment_files["model"] == expected_model
    assert yaml.safe_load(expected_model)["ai_settings"] == BALANCED_AI_SETTINGS
    assert pair.control_files[VIEW_FILE] == base_files[VIEW_FILE]
    assert pair.treatment_files[VIEW_FILE] == (
        base_files[VIEW_FILE] + _candidate()["proposed_omni_yaml"].encode()
    )
    assert "measures" not in yaml.safe_load(pair.control_files[VIEW_FILE])
    assert yaml.safe_load(pair.treatment_files[VIEW_FILE])["measures"] == {
        "count": _candidate()["measure"]["definition"]
    }
    assert pair.record["changed_view_files"] == [VIEW_FILE]
    assert pair.record["measure_count"] == 1
    assert pair.record["measure_ids"] == [_candidate()["measure_id"]]

    control_r2 = pair.control_manifest["r2_public_evidence_measures"]
    treatment_r2 = pair.treatment_manifest["r2_public_evidence_measures"]
    assert control_r2["condition_id"] == "R2-C5B"
    assert control_r2["measure_count"] == 0
    assert control_r2["measure_ids"] == []
    assert treatment_r2["condition_id"] == "R2-M1"
    assert treatment_r2["measure_count"] == 1
    assert treatment_r2["measure_ids"] == [_candidate()["measure_id"]]
    for metadata in (control_r2, treatment_r2):
        assert metadata["balanced_ai_settings"] == BALANCED_AI_SETTINGS
        assert metadata["accepted_catalog_sha256"] == _sha256(_catalog_bytes())
        assert len(metadata["source_c5_manifest_sha256"]) == 64


def test_pair_is_byte_deterministic_and_manifests_authenticate_every_file() -> None:
    first = _pair()
    second = _pair()

    assert first == second
    for files, manifest in (
        (first.control_files, first.control_manifest),
        (first.treatment_files, first.treatment_manifest),
    ):
        assert manifest["files"] == _file_records(files)
    assert first.record["control_manifest_sha256"] == _sha256(
        canonical_catalog_bytes(first.control_manifest)
    )
    assert first.record["treatment_manifest_sha256"] == _sha256(
        canonical_catalog_bytes(first.treatment_manifest)
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("catalog_hash", "accepted catalog SHA-256"),
        ("catalog_internal_hash", "internal artifact hash"),
        ("c5_file_hash", "C5 manifest file record"),
        ("missing_view", "bound view file is missing"),
        ("existing_measures", "already declares measures"),
        ("wrong_view_binding", "SQL view binding"),
        ("missing_field_binding", "SQL field binding"),
        ("changed_proposed_yaml", "proposed Omni YAML"),
        ("duplicate_measure_name", "duplicate measure name"),
        ("forbidden_field", "protected field"),
    ],
)
def test_pair_fails_closed_on_catalog_c5_and_binding_mutations(
    mutation: str, message: str
) -> None:
    files, manifest = _c5_bundle()
    candidates = [_candidate()]
    catalog = _catalog_bytes(candidates)
    expected_hash = _sha256(catalog)

    if mutation == "catalog_hash":
        expected_hash = "0" * 64
    elif mutation == "catalog_internal_hash":
        value = json.loads(catalog)
        value["manifest"]["artifact_sha256"] = "0" * 64
        catalog = canonical_catalog_bytes(value)
        expected_hash = _sha256(catalog)
    elif mutation == "c5_file_hash":
        files["model"] += b"changed: true\n"
    elif mutation == "missing_view":
        del files[VIEW_FILE]
        manifest["files"] = _file_records(files)
    elif mutation == "existing_measures":
        files[VIEW_FILE] += b"measures: {}\n"
        manifest["files"] = _file_records(files)
    elif mutation == "wrong_view_binding":
        candidates[0] = _candidate(sql="${db_public__other.id}")
        catalog = _catalog_bytes(candidates)
        expected_hash = _sha256(catalog)
    elif mutation == "missing_field_binding":
        candidates[0] = _candidate(sql="${db_public__orders.missing}")
        catalog = _catalog_bytes(candidates)
        expected_hash = _sha256(catalog)
    elif mutation == "changed_proposed_yaml":
        candidates[0]["proposed_omni_yaml"] = "measures: {}\n"
        catalog = _catalog_bytes(candidates)
        expected_hash = _sha256(catalog)
    elif mutation == "duplicate_measure_name":
        candidates.append(_candidate(suffix="2"))
        catalog = _catalog_bytes(candidates)
        expected_hash = _sha256(catalog)
    else:
        candidates[0]["evidence"]["gold_sql"] = "SELECT 1"
        catalog = _catalog_bytes(candidates)
        expected_hash = _sha256(catalog)

    with pytest.raises(MeasureBundleError, match=message):
        build_database_measure_bundle_pair(
            "db",
            files,
            manifest,
            catalog,
            expected_catalog_sha256=expected_hash,
        )


def test_pair_rejects_catalog_database_omission_and_cross_database_candidate() -> None:
    files, manifest = _c5_bundle()
    candidate = _candidate()
    candidate["database"] = "other"
    catalog = _catalog_bytes([candidate])

    with pytest.raises(MeasureBundleError, match="accepted catalog has no measures"):
        build_database_measure_bundle_pair(
            "db",
            files,
            manifest,
            catalog,
            expected_catalog_sha256=_sha256(catalog),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("top_shape", "catalog shape"),
        ("identity", "catalog identity"),
        ("manifest_shape", "manifest shape"),
        ("empty_candidates", "catalog candidates"),
        ("candidate_shape", "candidate shape"),
        ("candidate_id", "candidate ID"),
        ("measure_id", "measure ID"),
        ("ordered_ids", "ordered identities"),
        ("summary", "catalog summary"),
        ("generator", "generator inventory"),
    ],
)
def test_pair_rejects_malformed_frozen_catalog_shapes(
    mutation: str, message: str
) -> None:
    value = json.loads(_catalog_bytes())
    if mutation == "top_shape":
        value["extra"] = True
    elif mutation == "identity":
        value["kind"] = "other"
    elif mutation == "manifest_shape":
        value["manifest"]["extra"] = True
    elif mutation == "empty_candidates":
        value["accepted_candidates"] = []
    elif mutation == "candidate_shape":
        value["accepted_candidates"][0]["extra"] = True
    elif mutation == "candidate_id":
        value["accepted_candidates"][0]["candidate_id"] = "bad"
    elif mutation == "measure_id":
        value["accepted_candidates"][0]["measure_id"] = "bad"
    elif mutation == "ordered_ids":
        value["manifest"]["ordered_measure_ids"] = []
    elif mutation == "summary":
        value["summary"]["accepted_candidate_count"] = 2
    else:
        value["generator"]["database_count"] = 2
    catalog = _reseal_catalog(value)
    files, manifest = _c5_bundle()

    with pytest.raises(MeasureBundleError, match=message):
        build_database_measure_bundle_pair(
            "db",
            files,
            manifest,
            catalog,
            expected_catalog_sha256=_sha256(catalog),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("empty_files", "non-empty mapping"),
        ("unterminated_file", "bytes are invalid"),
        ("manifest_identity", "manifest identity"),
        ("records_type", "file records"),
        ("record_shape", "record is malformed"),
        ("duplicate_record", "record is duplicated"),
        ("record_set", "record set"),
        ("relationships_mapping", "relationships must"),
        ("topic_sequence", "must be a YAML mapping"),
        ("missing_model", "no model file"),
        ("existing_settings", "already declares ai_settings"),
        ("duplicate_yaml_key", "duplicate key"),
        ("protected_yaml", "protected field"),
    ],
)
def test_pair_rejects_malformed_c5_files_and_manifest(
    mutation: str, message: str
) -> None:
    files, manifest = _c5_bundle()
    if mutation == "empty_files":
        files = {}
    elif mutation == "unterminated_file":
        files["model"] = b"ai_context: x"
        manifest["files"] = _file_records(files)
    elif mutation == "manifest_identity":
        manifest["database"] = "other"
    elif mutation == "records_type":
        manifest["files"] = "bad"
    elif mutation == "record_shape":
        manifest["files"][0]["extra"] = True
    elif mutation == "duplicate_record":
        manifest["files"].append(copy.deepcopy(manifest["files"][0]))
    elif mutation == "record_set":
        del files["relationships"]
    elif mutation == "relationships_mapping":
        files["relationships"] = b"unexpected: mapping\n"
        manifest["files"] = _file_records(files)
    elif mutation == "topic_sequence":
        files["db_public__orders.topic"] = b"[]\n"
        manifest["files"] = _file_records(files)
    elif mutation == "missing_model":
        del files["model"]
        manifest["files"] = _file_records(files)
    elif mutation == "existing_settings":
        files["model"] += BALANCED_AI_SETTINGS_YAML
        manifest["files"] = _file_records(files)
    elif mutation == "duplicate_yaml_key":
        files["model"] = b"ai_context: first\nai_context: second\n"
        manifest["files"] = _file_records(files)
    else:
        files[VIEW_FILE] += b"gold_sql: SELECT 1\n"
        manifest["files"] = _file_records(files)
    catalog = _catalog_bytes()

    with pytest.raises(MeasureBundleError, match=message):
        build_database_measure_bundle_pair(
            "db",
            files,
            manifest,
            catalog,
            expected_catalog_sha256=_sha256(catalog),
        )


def test_writer_is_append_only_private_and_deployment_plan_compatible(
    tmp_path: Path,
) -> None:
    pair = _pair()
    root_manifest: dict[str, object] = {
        "kind": "r2-public-evidence-measure-bundle-set",
        "manifest": {},
        "schema_version": 1,
        "summary": {"database_count": 1, "measure_count": 1},
    }
    files = {
        **{
            f"r2-c5b/db/{name}": content for name, content in pair.control_files.items()
        },
        "r2-c5b/db/manifest.json": canonical_catalog_bytes(pair.control_manifest),
        **{
            f"r2-m1/db/{name}": content
            for name, content in pair.treatment_files.items()
        },
        "r2-m1/db/manifest.json": canonical_catalog_bytes(pair.treatment_manifest),
    }
    root_manifest["manifest"]["files"] = [
        {
            "path": name,
            "sha256": _sha256(content),
            "size_bytes": len(content),
        }
        for name, content in sorted(files.items())
    ]
    root_manifest["manifest"]["artifact_sha256"] = _sha256(
        canonical_catalog_bytes(root_manifest)
    )
    bundle = MeasureBundleSet(files=files, manifest=root_manifest)
    destination = tmp_path / "offline-bundles"

    write_measure_bundle_set(destination, bundle)

    assert destination.stat().st_mode & 0o777 == 0o700
    assert (destination / "r2-c5b").stat().st_mode & 0o777 == 0o700
    assert (destination / "r2-c5b/db").stat().st_mode & 0o777 == 0o700
    assert (destination / "r2-m1").stat().st_mode & 0o777 == 0o700
    assert (destination / "r2-m1/db").stat().st_mode & 0o777 == 0o700
    assert (destination / "manifest.json").stat().st_mode & 0o777 == 0o600
    assert (destination / "r2-m1/db/model").stat().st_mode & 0o777 == 0o600
    assert build_semantic_deployment_plan(destination / "r2-c5b/db").database == "db"
    assert build_semantic_deployment_plan(destination / "r2-m1/db").database == "db"
    assert verify_measure_bundle_set(destination) == bundle
    with pytest.raises(MeasureBundleError, match="already exists"):
        write_measure_bundle_set(destination, bundle)

    (destination / "r2-m1/db/model").write_bytes(b"changed: true\n")
    with pytest.raises(MeasureBundleError, match="published file record"):
        verify_measure_bundle_set(destination)


def test_cli_builds_writes_and_reports_only_bounded_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pair = _pair()
    files = {
        **{
            f"r2-c5b/db/{name}": content for name, content in pair.control_files.items()
        },
        "r2-c5b/db/manifest.json": canonical_catalog_bytes(pair.control_manifest),
        **{
            f"r2-m1/db/{name}": content
            for name, content in pair.treatment_files.items()
        },
        "r2-m1/db/manifest.json": canonical_catalog_bytes(pair.treatment_manifest),
    }
    manifest: dict[str, object] = {
        "kind": "r2-public-evidence-measure-bundle-set",
        "manifest": {
            "files": [
                {
                    "path": name,
                    "sha256": _sha256(content),
                    "size_bytes": len(content),
                }
                for name, content in sorted(files.items())
            ]
        },
        "schema_version": 1,
        "summary": {
            "control_measure_count": 0,
            "database_count": 1,
            "treatment_measure_count": 1,
        },
    }
    manifest["manifest"]["artifact_sha256"] = _sha256(canonical_catalog_bytes(manifest))
    bundle = MeasureBundleSet(files=files, manifest=manifest)
    monkeypatch.setattr(
        bundle_cli,
        "build_workspace_measure_bundle_set",
        lambda *_arguments: bundle,
    )
    destination = tmp_path / "cli-output"

    result = bundle_cli.main(
        [
            "--workspace",
            str(tmp_path),
            "--target-config",
            str(tmp_path / "targets.json"),
            "--accepted-catalog",
            str(tmp_path / "catalog.json"),
            "--output-root",
            str(destination),
        ]
    )

    assert result == 0
    reported = json.loads(capsys.readouterr().out)
    assert reported == {
        "artifact_sha256": manifest["manifest"]["artifact_sha256"],
        "control_measure_count": 0,
        "database_count": 1,
        "output_root": str(destination),
        "treatment_measure_count": 1,
    }
    assert destination.is_dir()


def test_real_workspace_build_is_complete_public_only_read_only_and_deterministic() -> (
    None
):
    target_config = (
        REPOSITORY_ROOT
        / "config/conditions/r2-public-evidence-measure-databases-v1.json"
    )
    accepted_catalog = (
        REPOSITORY_ROOT / "experiments/r2-public-evidence-measures/"
        "public-evidence-measure-catalog-v1.json"
    )
    before = _tree_digest(REPOSITORY_ROOT / "semantic_models")

    first = build_workspace_measure_bundle_set(
        REPOSITORY_ROOT,
        target_config,
        accepted_catalog,
    )
    second = build_workspace_measure_bundle_set(
        REPOSITORY_ROOT,
        target_config,
        accepted_catalog,
    )

    assert first == second
    assert first.manifest["accepted_catalog"]["sha256"] == (
        EXPECTED_ACCEPTED_CATALOG_SHA256
    )
    assert first.manifest["summary"] == {
        "control_measure_count": 0,
        "database_count": 16,
        "treatment_measure_count": 812,
    }
    assert first.manifest["manifest"]["artifact_sha256"] == (
        "13475da89c59d7267cb2ece4859c95d89c4671d3953846f64b2bbd45f9b5ec86"
    )
    assert _sha256(canonical_catalog_bytes(first.manifest)) == (
        "bbea478ed6947387607cfcdf043fee2cb1845122c9eabcb4e1487d573901a1a2"
    )
    assert len(first.manifest["databases"]) == 16
    assert sum(item["measure_count"] for item in first.manifest["databases"]) == 812
    assert _tree_digest(REPOSITORY_ROOT / "semantic_models") == before
    assert _bundle_digest(first) == _bundle_digest(second)

    treatment_measure_count = 0
    for record in first.manifest["databases"]:
        database = record["database"]
        control_prefix = f"r2-c5b/{database}/"
        treatment_prefix = f"r2-m1/{database}/"
        for view_name in record["changed_view_files"]:
            control = first.files[control_prefix + view_name]
            treatment = first.files[treatment_prefix + view_name]
            assert treatment.startswith(control)
            treatment_measure_count += len(yaml.safe_load(treatment)["measures"])
        control_model = first.files[control_prefix + "model"]
        treatment_model = first.files[treatment_prefix + "model"]
        assert control_model == treatment_model
        assert yaml.safe_load(control_model)["ai_settings"] == BALANCED_AI_SETTINGS
    assert treatment_measure_count == 812

    serialized_manifest = canonical_catalog_bytes(first.manifest)
    for forbidden in (
        b'"question"',
        b'"question_id"',
        b'"normal_query"',
        b'"gold_sql"',
        b'"correctness"',
        b'"outcome"',
    ):
        assert forbidden not in serialized_manifest


def _bundle_digest(bundle: MeasureBundleSet) -> str:
    digest = hashlib.sha256(canonical_catalog_bytes(bundle.manifest))
    for name, content in sorted(bundle.files.items()):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
