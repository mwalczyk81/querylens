"""Synthetic Azure Monitor Logs fixtures for offline testing.

Provides helper factories to construct authentic LogsTable and LogsQueryResult
objects conforming to azure.monitor.query without initiating network connections.
"""

from typing import Any

from azure.monitor.query import LogsQueryResult, LogsTable


def make_logs_table(
    columns: list[str],
    rows: list[list[Any]],
    name: str = "PrimaryResult",
    column_types: list[str] | None = None,
) -> LogsTable:
    """Create a synthetic LogsTable instance.

    Args:
        columns: List of column names.
        rows: List of row values as lists.
        name: Name of the table.
        column_types: Optional list of column types.

    Returns:
        LogsTable instance populated with synthetic rows.
    """
    types = column_types if column_types is not None else ["string"] * len(columns)
    return LogsTable(
        name=name,
        columns=columns,
        columns_types=types,
        rows=rows,
    )


def make_logs_query_result(tables: list[LogsTable] | None = None) -> LogsQueryResult:
    """Create a synthetic LogsQueryResult wrapping one or more tables.

    Args:
        tables: List of LogsTable objects.

    Returns:
        LogsQueryResult instance.
    """
    return LogsQueryResult(tables=tables or [])


def make_sample_shapes_table(
    shapes: list[dict[str, Any]] | None = None,
) -> LogsTable:
    """Create a sample Top Shapes table (Query 1 result).

    Args:
        shapes: Optional list of row dictionaries.

    Returns:
        LogsTable populated with sample query shape records.
    """
    columns = [
        "ql_db_name",
        "ql_coll_name",
        "ql_shape_id",
        "ql_sample_text",
        "ql_execution_count",
        "ql_total_ru",
        "ql_max_ru",
        "ql_total_returned_rows",
        "ql_throttled_count",
        "ql_top_callers",
    ]
    if shapes is None:
        rows = [
            [
                "ecommerce",
                "orders",
                "shape_hash_1",
                "SELECT * FROM c WHERE c.customer_id = @id",
                100,
                550.0,
                12.5,
                200.0,
                0,
                [],
            ],
            [
                "ecommerce",
                "items",
                "shape_hash_2",
                "SELECT * FROM c WHERE c.category = @cat",
                40,
                320.0,
                15.0,
                80.0,
                2,
                [],
            ],
        ]
    else:
        rows = [
            [s.get(col, [] if col == "ql_top_callers" else None) for col in columns] for s in shapes
        ]

    return make_logs_table(columns=columns, rows=rows)


def make_sample_shapes_table_with_empty_database() -> LogsTable:
    """Create a sample Top Shapes table with empty and null database/container records."""
    shapes = [
        {
            "ql_db_name": "",
            "ql_coll_name": "",
            "ql_shape_id": "shape_hash_empty_db",
            "ql_sample_text": "SELECT * FROM c WHERE c.active = true",
            "ql_execution_count": 80,
            "ql_total_ru": 400.0,
            "ql_max_ru": 12.0,
            "ql_total_returned_rows": 160.0,
            "ql_throttled_count": 1,
        },
        {
            "ql_db_name": None,
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_null_db",
            "ql_sample_text": "SELECT c.id FROM c",
            "ql_execution_count": 30,
            "ql_total_ru": 150.0,
            "ql_max_ru": 8.0,
            "ql_total_returned_rows": 60.0,
            "ql_throttled_count": 0,
        },
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_with_single_known_pair_resolution() -> LogsTable:
    """Create a sample Top Shapes table where a shape resolved unknown activities."""
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_single_pair_resolved",
            "ql_sample_text": "SELECT * FROM c WHERE c.customer_id = @id",
            "ql_execution_count": 100,  # 80 known activities + 20 resolved unknown activities
            "ql_total_ru": 500.0,
            "ql_max_ru": 12.5,
            "ql_total_returned_rows": 200.0,
            "ql_throttled_count": 0,
        }
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_two_containers_one_known_db() -> LogsTable:
    """Create a sample Top Shapes table for 1 shape on 2 containers where only 1 has known db."""
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_multi_cont",
            "ql_sample_text": "SELECT * FROM c WHERE c.active = true",
            "ql_execution_count": 60,
            "ql_total_ru": 300.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 120.0,
            "ql_throttled_count": 0,
        },
        {
            "ql_db_name": "(unknown)",
            "ql_coll_name": "items",
            "ql_shape_id": "shape_multi_cont",
            "ql_sample_text": "SELECT * FROM c WHERE c.active = true",
            "ql_execution_count": 40,
            "ql_total_ru": 200.0,
            "ql_max_ru": 8.0,
            "ql_total_returned_rows": 80.0,
            "ql_throttled_count": 0,
        },
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_one_container_two_known_dbs() -> LogsTable:
    """Create a sample Top Shapes table for 1 (shape, container) with 2 known dbs."""
    shapes = [
        {
            "ql_db_name": "ecommerce_east",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_two_dbs",
            "ql_sample_text": "SELECT * FROM c WHERE c.id = @id",
            "ql_execution_count": 50,
            "ql_total_ru": 250.0,
            "ql_max_ru": 12.0,
            "ql_total_returned_rows": 100.0,
            "ql_throttled_count": 0,
        },
        {
            "ql_db_name": "ecommerce_west",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_two_dbs",
            "ql_sample_text": "SELECT * FROM c WHERE c.id = @id",
            "ql_execution_count": 30,
            "ql_total_ru": 150.0,
            "ql_max_ru": 11.0,
            "ql_total_returned_rows": 60.0,
            "ql_throttled_count": 0,
        },
        {
            "ql_db_name": "(unknown)",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_two_dbs",
            "ql_sample_text": "SELECT * FROM c WHERE c.id = @id",
            "ql_execution_count": 20,
            "ql_total_ru": 100.0,
            "ql_max_ru": 9.0,
            "ql_total_returned_rows": 40.0,
            "ql_throttled_count": 0,
        },
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_empty_container() -> LogsTable:
    """Create a sample Top Shapes table where container is empty and db stays (unknown)."""
    shapes = [
        {
            "ql_db_name": "(unknown)",
            "ql_coll_name": "(unknown)",
            "ql_shape_id": "shape_no_container",
            "ql_sample_text": "SELECT * FROM c",
            "ql_execution_count": 50,
            "ql_total_ru": 250.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 100.0,
            "ql_throttled_count": 0,
        }
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_totals_table(
    window_total_ru: float = 1200.0,
    attributed_total_ru: float = 870.0,
    total_executions: int = 140,
    min_time_generated: str = "2026-10-09T18:00:00Z",
) -> LogsTable:
    """Create a sample Totals table (Query 2 result).

    Args:
        window_total_ru: Total RU across all DataPlaneRequests.
        attributed_total_ru: Total RU attributed to joined query shapes.
        total_executions: Cumulative executions of joined query shapes.
        min_time_generated: Earliest TimeGenerated observed in logs.

    Returns:
        LogsTable with a single totals row.
    """
    columns = [
        "ql_window_total_ru",
        "ql_attributed_total_ru",
        "ql_total_executions",
        "ql_min_time_generated",
    ]
    rows = [[window_total_ru, attributed_total_ru, total_executions, min_time_generated]]
    return make_logs_table(columns=columns, rows=rows)


def make_sample_preflight_table(
    dataplane_count: int = 1500,
    queryruntime_count: int = 400,
    earliest_time: str | None = "2026-10-09T18:00:00Z",
    latest_time: str | None = "2026-10-10T18:00:00Z",
    has_shapesignature: int = 390,
    has_querytext: int = 400,
    has_aad_guid: int = 1200,
    has_aad_str: int = 0,
    has_client_ip: int = 1500,
    has_useragent: int = 1450,
    auth_breakdown: list[list[Any]] | dict[str, int] | None = None,
) -> LogsTable:
    """Create a sample Preflight Check table result.

    Args:
        dataplane_count: Total DataPlaneRequests records.
        queryruntime_count: Total QueryRuntimeStatistics records.
        earliest_time: Earliest TimeGenerated observed in logs.
        latest_time: Latest TimeGenerated observed in logs.
        has_shapesignature: Count of non-empty shapesignature_s records.
        has_querytext: Count of non-empty querytext_s records.
        has_aad_guid: Count of non-empty aadPrincipalId_g records.
        has_aad_str: Count of non-empty aadPrincipalId_s records.
        has_client_ip: Count of non-empty clientIpAddress_s records.
        has_useragent: Count of non-empty useragent_s records.
        auth_breakdown: Breakdown list of [auth_type, count] pairs or dict.

    Returns:
        LogsTable with a single preflight diagnostic row.
    """
    columns = [
        "ql_dataplane_count",
        "ql_queryruntime_count",
        "ql_earliest_time",
        "ql_latest_time",
        "ql_has_shapesignature",
        "ql_has_querytext",
        "ql_has_aad_guid",
        "ql_has_aad_str",
        "ql_has_client_ip",
        "ql_has_useragent",
        "ql_auth_breakdown",
    ]
    auth: Any = (
        auth_breakdown if auth_breakdown is not None else {"AAD": 1200, "PrimaryMasterKey": 300}
    )
    rows = [
        [
            dataplane_count,
            queryruntime_count,
            earliest_time,
            latest_time,
            has_shapesignature,
            has_querytext,
            has_aad_guid,
            has_aad_str,
            has_client_ip,
            has_useragent,
            auth,
        ]
    ]
    return make_logs_table(columns=columns, rows=rows)


def make_sample_preflight_table_with_unscoped_aad_guid() -> LogsTable:
    """Create a sample Preflight Check table where non-DataPlaneRequests populated aadPrincipalId_g.

    Simulates an unscoped query bug where aadPrincipalId_g was populated on non-DataPlaneRequests
    (e.g., ControlPlaneRequests), resulting in has_aad_guid exceeding dataplane_count (1200 > 1000).
    """
    return make_sample_preflight_table(
        dataplane_count=1000,
        queryruntime_count=400,
        has_shapesignature=390,
        has_querytext=400,
        has_aad_guid=1200,
        has_aad_str=0,
        has_client_ip=1000,
        has_useragent=950,
        auth_breakdown={"AAD": 1000},
    )


def make_sample_shapes_table_with_callers(
    callers: list[dict[str, Any]] | None = None,
) -> LogsTable:
    """Create a sample Top Shapes table with populated callers."""
    if callers is None:
        callers = [
            {
                "identifier": "00000000-0000-0000-0000-000000000001",
                "caller_ru": 350.0,
                "identifier_type": "aad_principal",
            },
            {
                "identifier": "192.168.1.1",
                "caller_ru": 150.0,
                "identifier_type": "client_ip",
            },
        ]
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_with_callers",
            "ql_sample_text": "SELECT * FROM c WHERE c.customer_id = @id",
            "ql_execution_count": 100,
            "ql_total_ru": 500.0,
            "ql_max_ru": 12.5,
            "ql_total_returned_rows": 200.0,
            "ql_throttled_count": 0,
            "ql_top_callers": callers,
        }
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_with_flattened_callers() -> LogsTable:
    """Create sample Top Shapes table with flattened caller list (live gate regression fixture)."""
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_flat",
            "ql_sample_text": "SELECT * FROM c",
            "ql_execution_count": 10,
            "ql_total_ru": 100.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 20.0,
            "ql_throttled_count": 0,
            "ql_top_callers": ["00000000-0000-0000-0000-000000000001", 70.0, "192.168.1.1", 30.0],
        }
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_with_nested_pairs_callers() -> LogsTable:
    """Create a sample Top Shapes table with nested pair callers."""
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_pairs",
            "ql_sample_text": "SELECT * FROM c",
            "ql_execution_count": 10,
            "ql_total_ru": 100.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 20.0,
            "ql_throttled_count": 0,
            "ql_top_callers": [
                ["00000000-0000-0000-0000-000000000001", 70.0],
                ["192.168.1.1", 30.0],
            ],
        }
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_with_too_many_callers() -> LogsTable:
    """Create a sample Top Shapes table with 4 callers exceeding max 3."""
    callers = [
        {"identifier": f"10.0.0.{i}", "caller_ru": 25.0, "identifier_type": "client_ip"}
        for i in range(1, 5)
    ]
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_too_many",
            "ql_sample_text": "SELECT * FROM c",
            "ql_execution_count": 10,
            "ql_total_ru": 100.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 20.0,
            "ql_throttled_count": 0,
            "ql_top_callers": callers,
        }
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_with_invalid_caller_types() -> LogsTable:
    """Create a sample Top Shapes table with invalid types in caller dict."""
    callers = [
        {
            "identifier": "00000000-0000-0000-0000-000000000001",
            "caller_ru": "not_a_number",
            "identifier_type": "aad_principal",
        }
    ]
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_bad_type",
            "ql_sample_text": "SELECT * FROM c",
            "ql_execution_count": 10,
            "ql_total_ru": 100.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 20.0,
            "ql_throttled_count": 0,
            "ql_top_callers": callers,
        }
    ]
    return make_sample_shapes_table(shapes=shapes)


def make_sample_shapes_table_with_excess_caller_ru() -> LogsTable:
    """Create a sample Top Shapes table where caller RU exceeds shape total RU."""
    callers = [
        {
            "identifier": "00000000-0000-0000-0000-000000000001",
            "caller_ru": 600.0,
            "identifier_type": "aad_principal",
        }
    ]
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_excess_caller_ru",
            "ql_sample_text": "SELECT * FROM c",
            "ql_execution_count": 10,
            "ql_total_ru": 500.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 20.0,
            "ql_throttled_count": 0,
            "ql_top_callers": callers,
        }
    ]
    return make_sample_shapes_table(shapes=shapes)
