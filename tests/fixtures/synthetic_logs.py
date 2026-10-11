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
        "db_name",
        "coll_name",
        "shape_id",
        "sample_text",
        "execution_count",
        "total_ru",
        "max_ru",
        "total_returned_rows",
        "throttled_count",
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
            ],
        ]
    else:
        rows = [[s.get(col) for col in columns] for s in shapes]

    return make_logs_table(columns=columns, rows=rows)


def make_sample_shapes_table_with_empty_database() -> LogsTable:
    """Create a sample Top Shapes table with empty and null database/container records."""
    shapes = [
        {
            "db_name": "",
            "coll_name": "",
            "shape_id": "shape_hash_empty_db",
            "sample_text": "SELECT * FROM c WHERE c.active = true",
            "execution_count": 80,
            "total_ru": 400.0,
            "max_ru": 12.0,
            "total_returned_rows": 160.0,
            "throttled_count": 1,
        },
        {
            "db_name": None,
            "coll_name": "orders",
            "shape_id": "shape_hash_null_db",
            "sample_text": "SELECT c.id FROM c",
            "execution_count": 30,
            "total_ru": 150.0,
            "max_ru": 8.0,
            "total_returned_rows": 60.0,
            "throttled_count": 0,
        },
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
        "window_total_ru",
        "attributed_total_ru",
        "total_executions",
        "min_time_generated",
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
    auth_breakdown: dict[str, int] | None = None,
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
        auth_breakdown: Breakdown dictionary of authTokenType_s counts.

    Returns:
        LogsTable with a single preflight diagnostic row.
    """
    columns = [
        "dataplane_count",
        "queryruntime_count",
        "earliest_time",
        "latest_time",
        "has_shapesignature",
        "has_querytext",
        "has_aad_guid",
        "has_aad_str",
        "has_client_ip",
        "has_useragent",
        "auth_breakdown",
    ]
    auth = auth_breakdown if auth_breakdown is not None else {"AAD": 1200, "PrimaryMasterKey": 300}
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
