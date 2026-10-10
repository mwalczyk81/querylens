"""Unit tests for discovery service execution using synthetic LogsTable fixtures."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from querylens.discovery.models import (
    DiscoveryOptions,
    TelemetryMisconfigurationError,
)
from querylens.discovery.service import run_discovery, run_preflight_check
from tests.fixtures.synthetic_logs import (
    make_logs_query_result,
    make_sample_preflight_table,
    make_sample_shapes_table,
    make_sample_totals_table,
)


def test_run_discovery_success() -> None:
    """Verify run_discovery maps shapes and totals into WorkloadDiscoverySummary."""
    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table()
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=870.0,
        total_executions=140,
        min_time_generated=(datetime.now(UTC) - timedelta(hours=25)).isoformat(),
    )

    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    assert summary.total_ru == 1000.0
    assert summary.attributed_total_ru == 870.0
    assert summary.unattributed_ru == 130.0
    assert pytest.approx(summary.unattributed_ru_pct, 0.01) == 13.0
    assert summary.discovered_query_count == 2
    assert summary.masked_workspace_id == "...9abc"
    assert summary.retention_warning is False

    # Check top shape
    shape1 = summary.results[0]
    assert shape1.database == "ecommerce"
    assert shape1.total_ru == 550.0
    assert pytest.approx(shape1.ru_share_pct, 0.01) == 55.0


def test_run_discovery_silent_zero_guard() -> None:
    """Verify Silent-Zero Guard raises on zero attributed RU with positive window RU."""
    mock_client = MagicMock()
    # No joined shapes returned
    empty_shapes = make_sample_shapes_table(shapes=[])
    # Data plane requests exist (1000 RU), but attributed RU is 0
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=0.0,
        total_executions=0,
    )

    mock_client.query_workspace.side_effect = [
        make_logs_query_result([empty_shapes]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(TelemetryMisconfigurationError, match="Diagnostic telemetry misconfigured"):
        run_discovery(options=options, client=mock_client)


def test_run_discovery_clean_empty() -> None:
    """Verify run_discovery returns empty results when workspace has 0 records."""
    mock_client = MagicMock()
    empty_shapes = make_sample_shapes_table(shapes=[])
    zero_totals = make_sample_totals_table(
        window_total_ru=0.0,
        attributed_total_ru=0.0,
        total_executions=0,
    )

    mock_client.query_workspace.side_effect = [
        make_logs_query_result([empty_shapes]),
        make_logs_query_result([zero_totals]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    assert summary.total_ru == 0.0
    assert summary.attributed_total_ru == 0.0
    assert summary.unattributed_ru == 0.0
    assert summary.unattributed_ru_pct == 0.0
    assert summary.discovered_query_count == 0
    assert summary.results == []


def test_run_discovery_retention_warning() -> None:
    """Verify retention warning flag is set when earliest record is newer than window start."""
    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table()
    # Earliest record is only 2 hours old for a 24-hour window
    recent_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=1000.0,
        min_time_generated=recent_time,
    )

    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(
        workspace_id=UUID("12345678-1234-1234-1234-123456789abc"),
        time_window=timedelta(hours=24),
    )
    summary = run_discovery(options=options, client=mock_client)
    assert summary.retention_warning is True


def test_run_preflight_check_success() -> None:
    """Verify run_preflight_check returns structured PreflightCheckReport."""
    mock_client = MagicMock()
    preflight_table = make_sample_preflight_table(
        dataplane_count=1500,
        queryruntime_count=400,
        earliest_time="2026-10-09T18:00:00Z",
        latest_time="2026-10-10T18:00:00Z",
        has_shapesignature=390,
        has_querytext=400,
        has_aad_guid=1200,
        has_aad_str=0,
        has_client_ip=1500,
        has_useragent=1450,
        auth_breakdown={"AAD": 1200, "PrimaryMasterKey": 300},
    )
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(
        workspace_id=UUID("12345678-1234-1234-1234-123456789abc"),
        time_window=timedelta(hours=24),
    )
    report = run_preflight_check(options=options, client=mock_client)

    assert report.masked_workspace_id == "...9abc"
    assert "DataPlaneRequests" in report.categories_detected
    assert "QueryRuntimeStatistics" in report.categories_detected
    assert report.row_counts["DataPlaneRequests"] == 1500
    assert report.row_counts["QueryRuntimeStatistics"] == 400
    assert report.field_coverage["shapesignature_s"] == 390 / 400
    assert report.field_coverage["querytext_s"] == 1.0
    assert report.field_coverage["aadPrincipalId_g"] == 1200 / 1500
    assert report.field_coverage["clientIpAddress_s"] == 1.0
    assert report.auth_breakdown == {"AAD": 1200, "PrimaryMasterKey": 300}
    assert report.retention_warning is False


def test_run_preflight_check_missing_category() -> None:
    """Verify preflight check detects missing QueryRuntimeStatistics category."""
    mock_client = MagicMock()
    preflight_table = make_sample_preflight_table(
        dataplane_count=1500,
        queryruntime_count=0,
        has_shapesignature=0,
        has_querytext=0,
    )
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    report = run_preflight_check(options=options, client=mock_client)

    assert "DataPlaneRequests" in report.categories_detected
    assert "QueryRuntimeStatistics" not in report.categories_detected
    assert report.row_counts["QueryRuntimeStatistics"] == 0
    assert report.field_coverage["querytext_s"] == 0.0


def test_run_preflight_check_retention_warning() -> None:
    """Verify preflight check flags retention warning when logs are truncated."""
    mock_client = MagicMock()
    recent_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    preflight_table = make_sample_preflight_table(
        earliest_time=recent_time,
    )
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(
        workspace_id=UUID("12345678-1234-1234-1234-123456789abc"),
        time_window=timedelta(hours=24),
    )
    report = run_preflight_check(options=options, client=mock_client)
    assert report.retention_warning is True


def test_run_preflight_check_empty_workspace() -> None:
    """Verify preflight check handles empty workspace cleanly."""
    mock_client = MagicMock()
    empty_table = make_sample_preflight_table(
        dataplane_count=0,
        queryruntime_count=0,
        earliest_time=None,
        latest_time=None,
        has_shapesignature=0,
        has_querytext=0,
        has_aad_guid=0,
        has_aad_str=0,
        has_client_ip=0,
        has_useragent=0,
        auth_breakdown={},
    )
    mock_client.query_workspace.return_value = make_logs_query_result([empty_table])

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    report = run_preflight_check(options=options, client=mock_client)

    assert report.categories_detected == []
    assert report.earliest_record is None
    assert report.latest_record is None
    assert report.retention_warning is False
