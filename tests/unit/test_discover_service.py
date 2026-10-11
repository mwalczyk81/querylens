"""Unit tests for discovery service execution using synthetic LogsTable fixtures."""

import json
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Self
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from querylens.discovery.models import (
    DiscoveryOptions,
    InternalConsistencyError,
    TelemetryMisconfigurationError,
)
from querylens.discovery.service import run_discovery, run_preflight_check
from tests.fixtures.synthetic_logs import (
    make_logs_query_result,
    make_sample_preflight_table,
    make_sample_preflight_table_with_unscoped_aad_guid,
    make_sample_shapes_table,
    make_sample_shapes_table_with_empty_database,
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


def test_run_discovery_with_empty_database_and_container() -> None:
    """Verify run_discovery does not drop rows with empty database/container."""
    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_empty_database()
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=550.0,
        total_executions=110,
        min_time_generated=(datetime.now(UTC) - timedelta(hours=25)).isoformat(),
    )

    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    # Invariant: Spend is NOT discarded, exactly 2 shapes preserved
    assert summary.discovered_query_count == 2
    assert len(summary.results) == 2
    assert summary.total_ru == 1000.0
    assert summary.attributed_total_ru == 550.0
    assert summary.unattributed_ru == 450.0

    # First shape has empty strings -> (unknown)
    shape1 = summary.results[0]
    assert shape1.database == "(unknown)"
    assert shape1.container == "(unknown)"
    assert shape1.total_ru == 400.0

    # Second shape has None db_name and "orders" coll_name
    shape2 = summary.results[1]
    assert shape2.database == "(unknown)"
    assert shape2.container == "orders"
    assert shape2.total_ru == 150.0


def test_run_preflight_check_unscoped_coverage_ratio_exceeds_one_raises_error() -> None:
    """Verify run_preflight_check raises InternalConsistencyError when population exceeds total."""
    mock_client = MagicMock()
    preflight_table = make_sample_preflight_table_with_unscoped_aad_guid()
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(
        InternalConsistencyError,
        match="field coverage ratio for 'aadPrincipalId_g' exceeded 1.0",
    ):
        run_preflight_check(options=options, client=mock_client)


def test_run_preflight_check_queryruntime_coverage_ratio_exceeds_one_raises_error() -> None:
    """Verify run_preflight_check raises error when queryruntime coverage > 1.0."""
    mock_client = MagicMock()
    preflight_table = make_sample_preflight_table(
        queryruntime_count=100,
        has_shapesignature=100,
        has_querytext=120,
    )
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(
        InternalConsistencyError, match="field coverage ratio for 'querytext_s' exceeded 1.0"
    ):
        run_preflight_check(options=options, client=mock_client)


def test_run_discovery_ru_share_pct_exceeds_100_raises_error() -> None:
    """Verify run_discovery raises InternalConsistencyError when shape RU exceeds window RU."""
    mock_client = MagicMock()
    shapes = [
        {
            "ql_db_name": "db",
            "ql_coll_name": "coll",
            "ql_shape_id": "shape_1",
            "ql_sample_text": "SELECT * FROM c",
            "ql_execution_count": 10,
            "ql_total_ru": 1500.0,
            "ql_max_ru": 150.0,
            "ql_total_returned_rows": 100.0,
            "ql_throttled_count": 0,
        }
    ]
    shapes_table = make_sample_shapes_table(shapes=shapes)
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=1000.0,
    )
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(InternalConsistencyError, match="query shape RU share exceeded 100.0%"):
        run_discovery(options=options, client=mock_client)


def test_run_preflight_check_auth_breakdown_as_dict() -> None:
    """Verify run_preflight_check parses dict and JSON-serialized dict of auth counts."""
    mock_client = MagicMock()
    # (a) JSON-serialized dict
    json_dict = '{"AadToken": 62135, "PrimaryMasterKey": 12511}'
    preflight_table = make_sample_preflight_table(
        dataplane_count=1000,
        queryruntime_count=200,
        has_shapesignature=190,
        has_querytext=200,
        has_aad_guid=900,
        has_client_ip=1000,
        has_useragent=950,
        auth_breakdown=json_dict,  # type: ignore[arg-type]
    )
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    report = run_preflight_check(options=options, client=mock_client)
    assert report.auth_breakdown == {"AadToken": 62135, "PrimaryMasterKey": 12511}


def test_run_preflight_check_auth_breakdown_flat_list_raises_error() -> None:
    """Verify (b) a flat list like ['AadToken', 62135, ...] raises InternalConsistencyError."""
    mock_client = MagicMock()
    flat_list = ["AadToken", 62135, "PrimaryMasterKey", 12511]
    preflight_table = make_sample_preflight_table(
        dataplane_count=1500,
        queryruntime_count=400,
        auth_breakdown=flat_list,  # type: ignore[arg-type]
    )
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(
        InternalConsistencyError,
        match="Unexpected auth breakdown shape: expected dict of auth type to count",
    ):
        run_preflight_check(options=options, client=mock_client)


def test_run_preflight_check_auth_breakdown_list_of_pairs_raises_error() -> None:
    """Verify (c) a list of pairs like [['AadToken', 62135]] raises InternalConsistencyError."""
    mock_client = MagicMock()
    pair_list = [["AadToken", 62135], ["PrimaryMasterKey", 12511]]
    preflight_table = make_sample_preflight_table(
        dataplane_count=1500,
        queryruntime_count=400,
        auth_breakdown=pair_list,  # type: ignore[arg-type]
    )
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(
        InternalConsistencyError,
        match="Unexpected auth breakdown shape: expected dict of auth type to count",
    ):
        run_preflight_check(options=options, client=mock_client)


def test_run_discovery_single_known_pair_shape_does_not_appear_twice() -> None:
    """Verify when a shape has 1 known pair, it does not appear twice (known and unknown)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_with_single_known_pair_resolution,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_single_known_pair_resolution()
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=500.0,
        total_executions=100,
    )
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    # Invariant: exactly 1 shape returned (resolved to ecommerce/orders), NOT split into two
    assert summary.discovered_query_count == 1
    assert len(summary.results) == 1
    shape = summary.results[0]
    assert shape.shape_id == "shape_single_pair_resolved"
    assert shape.database == "ecommerce"
    assert shape.container == "orders"
    assert shape.execution_count == 100
    assert shape.total_ru == 500.0
    # No duplicate shape with (unknown) database
    assert not any(s.database == "(unknown)" for s in summary.results)


def test_run_discovery_two_containers_one_known_database() -> None:
    """Verify (4a) 1 shape on 2 containers: known container resolves, other stays (unknown)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_two_containers_one_known_db,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_two_containers_one_known_db()
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=500.0,
        total_executions=100,
    )
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    assert summary.discovered_query_count == 2
    assert len(summary.results) == 2

    # Known container resolved to its database
    orders_shape = next(s for s in summary.results if s.container == "orders")
    assert orders_shape.database == "ecommerce"
    assert orders_shape.execution_count == 60

    # Other container remains (unknown) database
    items_shape = next(s for s in summary.results if s.container == "items")
    assert items_shape.database == "(unknown)"
    assert items_shape.execution_count == 40


def test_run_discovery_one_container_two_known_databases() -> None:
    """Verify (4b) 1 (shape, container) with 2 known dbs: unknown rows stay (unknown)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_one_container_two_known_dbs,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_one_container_two_known_dbs()
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=500.0,
        total_executions=100,
    )
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    assert summary.discovered_query_count == 3
    assert len(summary.results) == 3

    # Preserves both known databases and the unknown row stays (unknown)
    dbs = {s.database for s in summary.results}
    assert dbs == {"ecommerce_east", "ecommerce_west", "(unknown)"}
    for s in summary.results:
        assert s.container == "orders"


def test_run_discovery_empty_container_database_stays_unknown() -> None:
    """Verify (4d) when container is empty, database stays (unknown)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_empty_container,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_empty_container()
    totals_table = make_sample_totals_table(
        window_total_ru=500.0,
        attributed_total_ru=250.0,
        total_executions=50,
    )
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    assert summary.discovered_query_count == 1
    shape = summary.results[0]
    assert shape.database == "(unknown)"
    assert shape.container == "(unknown)"


def test_run_discovery_parses_top_callers_successfully() -> None:
    """Verify run_discovery parses top_callers bags into CallerAttribution models (US3, T032)."""
    from tests.fixtures.synthetic_logs import make_sample_shapes_table_with_callers

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_callers()
    totals_table = make_sample_totals_table(
        window_total_ru=1000.0,
        attributed_total_ru=500.0,
        total_executions=100,
    )
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    assert len(summary.results) == 1
    shape = summary.results[0]
    assert len(shape.top_callers) == 2

    # Principal GUID preferred
    caller1 = shape.top_callers[0]
    assert caller1.identifier == "00000000-0000-0000-0000-000000000001"
    assert caller1.identifier_type == "aad_principal"
    assert caller1.ru_share_pct == 70.0  # 350 / 500

    # Client IP fallback
    caller2 = shape.top_callers[1]
    assert caller2.identifier == "192.168.1.1"
    assert caller2.identifier_type == "client_ip"
    assert caller2.ru_share_pct == 30.0  # 150 / 500


def test_run_discovery_callers_flattened_list_raises_internal_consistency_error() -> None:
    """Verify strict parser rejects flattened caller list with InternalConsistencyError (T032)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_with_flattened_callers,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_flattened_callers()
    totals_table = make_sample_totals_table(window_total_ru=500.0, attributed_total_ru=100.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(InternalConsistencyError, match="Unexpected caller item shape"):
        run_discovery(options=options, client=mock_client)


def test_run_discovery_callers_nested_pairs_raises_internal_consistency_error() -> None:
    """Verify strict parser rejects nested pair callers with InternalConsistencyError (T032)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_with_nested_pairs_callers,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_nested_pairs_callers()
    totals_table = make_sample_totals_table(window_total_ru=500.0, attributed_total_ru=100.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(InternalConsistencyError, match="Unexpected caller item shape"):
        run_discovery(options=options, client=mock_client)


def test_run_discovery_callers_more_than_three_raises_internal_consistency_error() -> None:
    """Verify strict parser rejects > 3 callers per shape with InternalConsistencyError (T032)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_with_too_many_callers,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_too_many_callers()
    totals_table = make_sample_totals_table(window_total_ru=500.0, attributed_total_ru=100.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(InternalConsistencyError, match="Top callers exceeded maximum of 3"):
        run_discovery(options=options, client=mock_client)


def test_run_discovery_callers_invalid_types_raises_internal_consistency_error() -> None:
    """Verify strict parser rejects caller dict with wrong value types (T032)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_with_invalid_caller_types,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_invalid_caller_types()
    totals_table = make_sample_totals_table(window_total_ru=500.0, attributed_total_ru=100.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(InternalConsistencyError, match="Caller caller_ru must be non-negative"):
        run_discovery(options=options, client=mock_client)


def test_run_discovery_callers_excess_ru_raises_internal_consistency_error() -> None:
    """Verify strict parser validates caller RU <= shape total RU (T032)."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_with_excess_caller_ru,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_excess_caller_ru()
    totals_table = make_sample_totals_table(window_total_ru=1000.0, attributed_total_ru=500.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(InternalConsistencyError, match="Caller RU share exceeded 100.0%"):
        run_discovery(options=options, client=mock_client)


def test_run_discovery_caller_shares_unrounded_sum_valid_rounded_sum_100_01() -> None:
    """Verify caller shares are validated unrounded, and round to 100.01 in JSON."""
    from querylens.report.discover_json import serialize_discovery_json
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_with_caller_shares_sum_rounding_100_01,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_caller_shares_sum_rounding_100_01()
    totals_table = make_sample_totals_table(window_total_ru=10000.0, attributed_total_ru=10000.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    assert len(summary.results) == 1
    callers = summary.results[0].top_callers
    assert len(callers) == 3

    # Unrounded shares validate cleanly and sum to 100.0
    unrounded_sum = sum(c.ru_share_pct for c in callers)
    assert pytest.approx(unrounded_sum, abs=1e-5) == 100.0

    # Display / JSON serialization rounds each to 2 decimal places, summing to 100.01
    json_str = serialize_discovery_json(summary)
    data = json.loads(json_str)
    caller_items = data["results"][0]["top_callers"]
    rounded_shares = [c["ru_share_pct"] for c in caller_items]
    assert rounded_shares == [33.34, 33.34, 33.33]
    rounded_sum = sum(rounded_shares)
    assert round(rounded_sum, 2) == 100.01
    assert rounded_sum <= 100.05


def test_run_discovery_callers_shares_sum_exceeding_tolerance_raises_error() -> None:
    """Verify strict parser validates callers shares sum <= 100.05%."""
    from tests.fixtures.synthetic_logs import (
        make_sample_shapes_table_with_excess_caller_shares_sum,
    )

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table_with_excess_caller_shares_sum()
    totals_table = make_sample_totals_table(window_total_ru=1000.0, attributed_total_ru=1000.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(InternalConsistencyError, match="Top callers RU shares sum exceeded 100.0%"):
        run_discovery(options=options, client=mock_client)


def test_run_discovery_passes_exact_timespan_tuple_to_all_queries() -> None:
    """Verify run_discovery computes fixed window once and passes timespan tuple to all queries."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 10, 11, 14, 30, 0, tzinfo=UTC)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls(2026, 10, 11, 14, 30, 0, tzinfo=UTC)

    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table()
    totals_table = make_sample_totals_table(window_total_ru=1000.0, attributed_total_ru=550.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(
        workspace_id=UUID("12345678-1234-1234-1234-123456789abc"),
        time_window=timedelta(hours=2),
    )

    with patch("querylens.discovery.service.datetime", FixedClock):
        summary = run_discovery(options=options, client=mock_client)

    expected_start = fixed_now - timedelta(hours=2)
    expected_end = fixed_now
    expected_timespan = (expected_start, expected_end)

    assert mock_client.query_workspace.call_count == 2
    # Check Query 1 (shapes) received the exact absolute timespan tuple
    call1_kwargs = mock_client.query_workspace.call_args_list[0].kwargs
    assert call1_kwargs["timespan"] == expected_timespan
    # Check Query 2 (totals) received the exact same absolute timespan tuple
    call2_kwargs = mock_client.query_workspace.call_args_list[1].kwargs
    assert call2_kwargs["timespan"] == expected_timespan

    # Verify summary reflects the exact fixed absolute window
    assert summary.window_start == expected_start
    assert summary.window_end == expected_end


def test_run_preflight_check_passes_exact_timespan_tuple() -> None:
    """Verify run_preflight_check passes absolute timespan tuple and reflects it in the report."""
    from unittest.mock import patch

    fixed_now = datetime(2026, 10, 11, 14, 30, 0, tzinfo=UTC)

    class FixedClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls(2026, 10, 11, 14, 30, 0, tzinfo=UTC)

    mock_client = MagicMock()
    preflight_table = make_sample_preflight_table()
    mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])

    options = DiscoveryOptions(
        workspace_id=UUID("12345678-1234-1234-1234-123456789abc"),
        time_window=timedelta(hours=4),
    )

    with patch("querylens.discovery.service.datetime", FixedClock):
        report = run_preflight_check(options=options, client=mock_client)

    expected_start = fixed_now - timedelta(hours=4)
    expected_end = fixed_now
    expected_timespan = (expected_start, expected_end)

    assert mock_client.query_workspace.call_count == 1
    call_kwargs = mock_client.query_workspace.call_args.kwargs
    assert call_kwargs["timespan"] == expected_timespan
    assert report.window_start == expected_start
    assert report.window_end == expected_end


def test_run_discovery_attributed_exceeding_window_ru_beyond_tolerance_raises_error() -> None:
    """Verify error raised if attributed RU exceeds total window RU beyond float tolerance."""
    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table()
    # attributed 1050.0 > window 1000.0 (by 50.0 RU, which is > 0.01 tolerance)
    totals_table = make_sample_totals_table(window_total_ru=1000.0, attributed_total_ru=1050.0)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    with pytest.raises(InternalConsistencyError, match="exceeds total window RU .* by more than"):
        run_discovery(options=options, client=mock_client)


def test_run_discovery_attributed_exceeding_window_ru_within_tolerance_normalizes_to_zero() -> None:
    """Verify unattributed RU normalized to 0.0 when attributed exceeds window within 0.01."""
    mock_client = MagicMock()
    shapes_table = make_sample_shapes_table()
    # attributed 1000.005 > window 1000.0 (by 0.005 RU, which is <= 0.01 tolerance)
    totals_table = make_sample_totals_table(window_total_ru=1000.0, attributed_total_ru=1000.005)
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([shapes_table]),
        make_logs_query_result([totals_table]),
    ]

    options = DiscoveryOptions(workspace_id=UUID("12345678-1234-1234-1234-123456789abc"))
    summary = run_discovery(options=options, client=mock_client)

    assert summary.total_ru == 1000.0
    assert summary.attributed_total_ru == 1000.005
    assert summary.unattributed_ru == 0.0
    assert summary.unattributed_ru_pct == 0.0
