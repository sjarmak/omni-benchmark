from __future__ import annotations

import json
from pathlib import Path
from typing import Any


OFFICIAL_QUERY_COUNTS = {
    "archeology_scan_large": 10,
    "cross_border_large": 20,
    "cybermarket_pattern_large": 20,
    "disaster_relief_large": 12,
    "exchange_traded_funds_large": 19,
    "fake_account_large": 24,
    "labor_certification_applications_large": 19,
    "mental_healths_large": 20,
    "museum_artifact_large": 20,
    "organ_transplant_large": 19,
    "planets_data_large": 19,
    "polar_equipment_large": 20,
    "residential_data_large": 21,
    "reverse_logistics_large": 20,
    "robot_fault_prediction_large": 10,
    "solar_panel_large": 20,
    "sports_events_large": 20,
    "virtual_idol_large": 19,
}


def public_record(
    instance_id: str,
    *,
    database: str = "example_large",
    category: str = "Query",
    high_level: bool = False,
    decimal: int = -1,
    distinct: bool = False,
    order: bool = False,
) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "selected_database": database,
        "query": f"Question π for {instance_id}?",
        "normal_query": f"Normal question for {instance_id}?",
        "preprocess_sql": [],
        "clean_up_sqls": [],
        "sol_sql": [],
        "external_knowledge": [],
        "test_cases": [],
        "category": category,
        "high_level": high_level,
        "conditions": {
            "decimal": decimal,
            "distinct": distinct,
            "order": order,
        },
    }


def official_shape_records() -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for database, count in OFFICIAL_QUERY_COUNTS.items():
        for index in range(count):
            records.append(
                public_record(
                    f"{database}_{index + 1}",
                    database=database,
                    high_level=index % 3 == 0,
                    decimal=2 if index % 2 else -1,
                    order=index % 4 != 0,
                )
            )
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )
