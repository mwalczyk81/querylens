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
        "database",
        "container",
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
