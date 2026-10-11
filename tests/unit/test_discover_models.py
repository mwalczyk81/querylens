"""Unit tests for discovery domain models, options parsing, and exceptions."""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import pytest
from pydantic import ValidationError

from querylens.discovery.models import (
    CallerAttribution,
    DiscoveredQueryShape,
    DiscoveryAuthError,
    DiscoveryConnectionError,
    DiscoveryOptions,
    DiscoveryValidationError,
    PreflightCheckReport,
    TelemetryMisconfigurationError,
    WorkloadDiscoverySummary,
)


def test_discovery_options_valid_defaults() -> None:
    """Verify DiscoveryOptions parses valid UUID and applies defaults."""
    options = DiscoveryOptions(workspace_id="12345678-1234-1234-1234-123456789abc")
    assert options.workspace_id == UUID("12345678-1234-1234-1234-123456789abc")
    assert options.account_filter is None
    assert options.time_window == timedelta(hours=24)
    assert options.top_n == 20
    assert options.server_timeout_seconds == 180
    assert options.show_text is False
    assert options.check_only is False
    assert options.print_kql is False
    assert options.json_output is False


def test_discovery_options_custom_valid() -> None:
    """Verify DiscoveryOptions accepts custom valid inputs."""
    options = DiscoveryOptions(
        workspace_id="12345678-1234-1234-1234-123456789abc",
        account_filter="my-cosmos-account-01",
        time_window="7d",
        top_n=50,
        server_timeout_seconds=300,
        show_text=True,
        check_only=True,
    )
    assert options.account_filter == "my-cosmos-account-01"
    assert options.time_window == timedelta(days=7)
    assert options.top_n == 50
    assert options.server_timeout_seconds == 300
    assert options.show_text is True
    assert options.check_only is True


@pytest.mark.parametrize(
    "invalid_ws",
    ["", "not-a-uuid", "12345678-1234-1234-1234-123456789abz", "12345"],
)
def test_discovery_options_invalid_workspace(invalid_ws: str) -> None:
    """Verify DiscoveryOptions rejects invalid workspace UUIDs."""
    with pytest.raises((DiscoveryValidationError, ValidationError)):
        DiscoveryOptions(workspace_id=invalid_ws)


@pytest.mark.parametrize(
    "invalid_account",
    [
        "a",  # too short (< 3 chars)
        "-leading-dash",
        "trailing-dash-",
        "has spaces",
        "has;semicolon",
        'has"quotes',
        "a" * 45,  # too long (> 44 chars)
    ],
)
def test_discovery_options_invalid_account_filter(invalid_account: str) -> None:
    """Verify DiscoveryOptions enforces Cosmos DB account name regex."""
    with pytest.raises((DiscoveryValidationError, ValidationError)):
        DiscoveryOptions(
            workspace_id="12345678-1234-1234-1234-123456789abc",
            account_filter=invalid_account,
        )


@pytest.mark.parametrize(
    "invalid_window",
    [
        "0h",
        "abc",
        "2m",
        "91d",
        "-5h",
        "10y",
        "7555555555555555555555555555555555555555555555555555555555555555555555555555555557d",
    ],
)
def test_discovery_options_invalid_time_window(invalid_window: str) -> None:
    """Verify DiscoveryOptions bounds time window between 5m and 90d."""
    with pytest.raises((DiscoveryValidationError, ValidationError)):
        DiscoveryOptions(
            workspace_id="12345678-1234-1234-1234-123456789abc",
            time_window=invalid_window,
        )


@pytest.mark.parametrize("invalid_top", [0, -1, 101, 500])
def test_discovery_options_invalid_top_n(invalid_top: int) -> None:
    """Verify DiscoveryOptions bounds top_n between 1 and 100."""
    with pytest.raises((DiscoveryValidationError, ValidationError)):
        DiscoveryOptions(
            workspace_id="12345678-1234-1234-1234-123456789abc",
            top_n=invalid_top,
        )


@pytest.mark.parametrize("invalid_timeout", [5, 9, 601, 1000])
def test_discovery_options_invalid_timeout(invalid_timeout: int) -> None:
    """Verify DiscoveryOptions bounds timeout between 10 and 600 seconds."""
    with pytest.raises((DiscoveryValidationError, ValidationError)):
        DiscoveryOptions(
            workspace_id="12345678-1234-1234-1234-123456789abc",
            server_timeout_seconds=invalid_timeout,
        )


def test_caller_attribution_validation() -> None:
    """Verify CallerAttribution constraints and bounds."""
    caller = CallerAttribution(
        identifier="12345678-1234-1234-1234-123456789abc",
        ru_share_pct=42.5,
        identifier_type="aad_principal",
    )
    assert caller.identifier_type == "aad_principal"
    assert caller.ru_share_pct == 42.5

    with pytest.raises(ValidationError):
        CallerAttribution(identifier="", ru_share_pct=50.0, identifier_type="aad_principal")

    with pytest.raises(ValidationError):
        CallerAttribution(identifier="id", ru_share_pct=-1.0, identifier_type="aad_principal")

    with pytest.raises(ValidationError):
        CallerAttribution(identifier="id", ru_share_pct=101.0, identifier_type="aad_principal")

    # Boundary validation at 100.05 tolerance
    valid_tolerance_caller = CallerAttribution(
        identifier="id", ru_share_pct=100.05, identifier_type="aad_principal"
    )
    assert valid_tolerance_caller.ru_share_pct == 100.05

    with pytest.raises(ValidationError):
        CallerAttribution(identifier="id", ru_share_pct=100.06, identifier_type="aad_principal")

    with pytest.raises(ValidationError):
        CallerAttribution(identifier="id", ru_share_pct=50.0, identifier_type=cast(Any, "unknown"))


def test_discovered_query_shape_validation() -> None:
    """Verify DiscoveredQueryShape field constraints and defaults."""
    shape = DiscoveredQueryShape(
        database="ecommerce",
        container="orders",
        shape_id="hash1234",
        execution_count=10,
        total_ru=150.0,
        avg_ru=15.0,
        max_ru=25.0,
        ru_share_pct=12.5,
        avg_returned_rows=2.0,
        ru_per_returned_row=7.5,
        throttled_count=0,
    )
    assert shape.sample_query_text is None
    assert shape.top_callers == []

    # Invalid execution count
    with pytest.raises(ValidationError):
        DiscoveredQueryShape(
            database="db",
            container="col",
            shape_id="id",
            execution_count=cast(Any, 0),
            total_ru=10.0,
            avg_ru=10.0,
            max_ru=10.0,
            ru_share_pct=1.0,
            avg_returned_rows=1.0,
            ru_per_returned_row=1.0,
            throttled_count=0,
        )


def test_workload_discovery_summary_validation() -> None:
    """Verify WorkloadDiscoverySummary bounds and masked workspace id format."""
    now = datetime.now(UTC)
    summary = WorkloadDiscoverySummary(
        window_start=now - timedelta(days=1),
        window_end=now,
        total_ru=1000.0,
        attributed_total_ru=800.0,
        unattributed_ru=200.0,
        unattributed_ru_pct=20.0,
        discovered_query_count=1,
        results=[],
        retention_warning=False,
        masked_workspace_id="...9abc",
    )
    assert summary.masked_workspace_id == "...9abc"

    # Invalid masked workspace id
    with pytest.raises(ValidationError):
        WorkloadDiscoverySummary(
            window_start=now - timedelta(days=1),
            window_end=now,
            total_ru=100.0,
            attributed_total_ru=100.0,
            unattributed_ru=0.0,
            unattributed_ru_pct=0.0,
            discovered_query_count=0,
            results=[],
            retention_warning=False,
            masked_workspace_id="invalid",
        )


def test_preflight_check_report_validation() -> None:
    """Verify PreflightCheckReport fields and structure."""
    now = datetime.now(UTC)
    report = PreflightCheckReport(
        categories_detected=["DataPlaneRequests", "QueryRuntimeStatistics"],
        row_counts={"DataPlaneRequests": 100, "QueryRuntimeStatistics": 50},
        window_start=now - timedelta(days=1),
        window_end=now,
        earliest_record=now - timedelta(days=1),
        latest_record=now,
        field_coverage={"querytext_s": 1.0, "requestCharge_s": 0.95},
        auth_breakdown={"EntraID": 90, "MasterKey": 10},
        retention_warning=False,
        masked_workspace_id="...9abc",
    )
    assert len(report.categories_detected) == 2
    assert report.field_coverage["querytext_s"] == 1.0


def test_custom_exceptions_hierarchy() -> None:
    """Verify discovery custom exceptions can be caught and raised."""
    assert issubclass(TelemetryMisconfigurationError, Exception)
    assert issubclass(DiscoveryAuthError, Exception)
    assert issubclass(DiscoveryConnectionError, Exception)
    assert issubclass(DiscoveryValidationError, Exception)


def test_discovered_query_shape_empty_database_and_container_defaults() -> None:
    """Verify empty or None database and container default to '(unknown)'."""
    shape1 = DiscoveredQueryShape(
        database="",
        container="",
        shape_id="shape_1",
        execution_count=10,
        total_ru=100.0,
        avg_ru=10.0,
        max_ru=10.0,
        ru_share_pct=5.0,
        avg_returned_rows=1.0,
        throttled_count=0,
    )
    assert shape1.database == "(unknown)"
    assert shape1.container == "(unknown)"

    shape2 = DiscoveredQueryShape(
        database=cast(Any, None),
        container=cast(Any, "   "),
        shape_id="shape_2",
        execution_count=5,
        total_ru=50.0,
        avg_ru=10.0,
        max_ru=10.0,
        ru_share_pct=2.5,
        avg_returned_rows=1.0,
        throttled_count=0,
    )
    assert shape2.database == "(unknown)"
    assert shape2.container == "(unknown)"
