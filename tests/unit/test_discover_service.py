"""Unit tests for discovery service execution using synthetic LogsTable fixtures."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from querylens.discovery.models import (
    DiscoveryOptions,
    TelemetryMisconfigurationError,
)
from querylens.discovery.service import run_discovery
from tests.fixtures.synthetic_logs import (
    make_logs_query_result,
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
