"""Contract tests validating discovery JSON serialization against discover-output-schema.json."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from querylens.discovery.models import (
    DiscoveredQueryShape,
    PreflightCheckReport,
    WorkloadDiscoverySummary,
)
from querylens.report.discover_json import (
    serialize_check_json,
    serialize_discovery_json,
)


def test_discover_json_matches_contract_schema() -> None:
    """Verify serialized discovery output adheres to discover-output-schema.json."""
    schema_path = (
        Path(__file__).parents[2]
        / "specs"
        / "002-query-cost-discovery"
        / "contracts"
        / "discover-output-schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    now = datetime.now(UTC)
    shape = DiscoveredQueryShape(
        database="ecommerce",
        container="orders",
        shape_id="hash_abc123",
        execution_count=50,
        total_ru=250.0,
        avg_ru=5.0,
        max_ru=12.0,
        ru_share_pct=25.0,
        avg_returned_rows=1.5,
        ru_per_returned_row=3.33,
        throttled_count=0,
    )
    summary = WorkloadDiscoverySummary(
        window_start=now - timedelta(hours=24),
        window_end=now,
        total_ru=1000.0,
        attributed_total_ru=800.0,
        unattributed_ru=200.0,
        unattributed_ru_pct=20.0,
        discovered_query_count=1,
        results=[shape],
        retention_warning=False,
        masked_workspace_id="...9abc",
    )

    json_str = serialize_discovery_json(summary)
    data = json.loads(json_str)

    # Validate required top-level fields
    for field in schema["required"]:
        assert field in data, f"Missing required top-level field: {field}"

    # Validate result item required fields
    result_schema = schema["properties"]["results"]["items"]
    assert len(data["results"]) == 1
    item = data["results"][0]
    for field in result_schema["required"]:
        assert field in item, f"Missing required item field: {field}"

    # Verify default JSON omits sample_query_text
    assert "sample_query_text" not in item


def test_check_json_matches_contract_schema() -> None:
    """Verify serialized preflight check output adheres to check-output-schema.json (T022)."""
    schema_path = (
        Path(__file__).parents[2]
        / "specs"
        / "002-query-cost-discovery"
        / "contracts"
        / "check-output-schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    now = datetime.now(UTC)
    report = PreflightCheckReport(
        categories_detected=["DataPlaneRequests", "QueryRuntimeStatistics"],
        row_counts={"DataPlaneRequests": 1500, "QueryRuntimeStatistics": 400},
        window_start=now - timedelta(hours=24),
        window_end=now,
        earliest_record=now - timedelta(hours=23),
        latest_record=now - timedelta(minutes=5),
        field_coverage={
            "shapesignature_s": 0.98,
            "querytext_s": 1.0,
            "aadPrincipalId_g": 0.85,
            "aadPrincipalId_s": 0.0,
            "clientIpAddress_s": 1.0,
            "useragent_s": 0.95,
        },
        auth_breakdown={"AAD": 1200, "PrimaryMasterKey": 300},
        retention_warning=False,
        masked_workspace_id="...9abc",
    )

    json_str = serialize_check_json(report)
    data = json.loads(json_str)

    # Validate required top-level fields
    for field in schema["required"]:
        assert field in data, f"Missing required preflight check field: {field}"

    # Assert no extraneous fields (additionalProperties: false)
    assert set(data.keys()) == set(schema["required"])
    assert data["masked_workspace_id"] == "...9abc"
    assert data["retention_warning"] is False
    assert data["row_counts"]["DataPlaneRequests"] == 1500
    assert data["field_coverage"]["shapesignature_s"] == 0.98


def test_discover_json_matches_contract_schema_with_unknown_database() -> None:
    """Verify serialized discovery output with (unknown) database adheres to schema."""
    schema_path = (
        Path(__file__).parents[2]
        / "specs"
        / "002-query-cost-discovery"
        / "contracts"
        / "discover-output-schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    now = datetime.now(UTC)
    shape = DiscoveredQueryShape(
        database="",
        container="",
        shape_id="hash_unknown123",
        execution_count=10,
        total_ru=100.0,
        avg_ru=10.0,
        max_ru=20.0,
        ru_share_pct=10.0,
        avg_returned_rows=2.0,
        ru_per_returned_row=5.0,
        throttled_count=0,
    )
    summary = WorkloadDiscoverySummary(
        window_start=now - timedelta(hours=24),
        window_end=now,
        total_ru=1000.0,
        attributed_total_ru=800.0,
        unattributed_ru=200.0,
        unattributed_ru_pct=20.0,
        discovered_query_count=1,
        results=[shape],
        retention_warning=False,
        masked_workspace_id="...9abc",
    )

    json_str = serialize_discovery_json(summary)
    data = json.loads(json_str)

    # Validate schema compliance
    result_schema = schema["properties"]["results"]["items"]
    item = data["results"][0]
    for field in result_schema["required"]:
        assert field in item, f"Missing required item field: {field}"

    assert item["database"] == "(unknown)"
    assert item["container"] == "(unknown)"
