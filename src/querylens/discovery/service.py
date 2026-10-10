"""Discovery execution service interacting with Azure Monitor Logs."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryResult

from querylens.discovery.kql import build_shapes_query, build_totals_query
from querylens.discovery.models import (
    DiscoveredQueryShape,
    DiscoveryOptions,
    PreflightCheckReport,
    TelemetryMisconfigurationError,
    WorkloadDiscoverySummary,
)


def _mask_workspace_id(workspace_id: UUID) -> str:
    """Mask workspace ID to display only its last 4 characters."""
    return f"...{str(workspace_id)[-4:]}"


def _parse_timestamp(ts: Any) -> datetime | None:
    """Parse various timestamp representations into a UTC datetime."""
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def run_discovery(
    options: DiscoveryOptions,
    client: LogsQueryClient | None = None,
) -> WorkloadDiscoverySummary:
    """Execute query cost discovery against an Azure Log Analytics workspace.

    Executes Query 1 (Top Shapes) and Query 2 (Totals) server-side, derives
    unattributed RU, evaluates retention warning, enforces the Silent-Zero Guard,
    and returns a WorkloadDiscoverySummary.

    Args:
        options: Validated DiscoveryOptions.
        client: Optional injected LogsQueryClient for testing without network calls.

    Returns:
        Populated WorkloadDiscoverySummary.

    Raises:
        TelemetryMisconfigurationError: If window RU > 0 but attributed RU == 0.
    """
    if client is None:
        credential = DefaultAzureCredential()
        client = LogsQueryClient(credential=credential)

    shapes_kql = build_shapes_query(top_n=options.top_n, account_filter=options.account_filter)
    totals_kql = build_totals_query(account_filter=options.account_filter)

    now = datetime.now(UTC)
    window_start = now - options.time_window
    window_end = now

    # Execute Query 1: Top Shapes
    shapes_res = client.query_workspace(
        workspace_id=str(options.workspace_id),
        query=shapes_kql,
        timespan=options.time_window,
        server_timeout=options.server_timeout_seconds,
    )
    shapes_tables = (
        shapes_res.tables
        if isinstance(shapes_res, LogsQueryResult)
        else getattr(shapes_res, "partial_data", [])
    )

    # Execute Query 2: Totals
    totals_res = client.query_workspace(
        workspace_id=str(options.workspace_id),
        query=totals_kql,
        timespan=options.time_window,
        server_timeout=options.server_timeout_seconds,
    )
    totals_tables = (
        totals_res.tables
        if isinstance(totals_res, LogsQueryResult)
        else getattr(totals_res, "partial_data", [])
    )

    # Parse Totals
    window_total_ru = 0.0
    attributed_total_ru = 0.0
    min_time_generated: datetime | None = None

    if totals_tables and len(totals_tables[0].rows) > 0:
        row = totals_tables[0].rows[0]
        window_total_ru = float(row["window_total_ru"] or 0.0)
        attributed_total_ru = float(row["attributed_total_ru"] or 0.0)
        min_time_generated = _parse_timestamp(row["min_time_generated"])

    # Enforce Silent-Zero Guard invariant
    if window_total_ru > 0.0 and attributed_total_ru == 0.0:
        raise TelemetryMisconfigurationError(
            "Diagnostic telemetry misconfigured: DataPlaneRequests exist but query-level "
            "telemetry was not attributed. "
            "Run 'querylens discover --check' to verify workspace settings."
        )

    unattributed_ru = max(0.0, window_total_ru - attributed_total_ru)
    unattributed_ru_pct = (
        (unattributed_ru / window_total_ru * 100.0) if window_total_ru > 0.0 else 0.0
    )

    # Parse Shapes
    shapes: list[DiscoveredQueryShape] = []
    if shapes_tables and len(shapes_tables[0].rows) > 0:
        for row in shapes_tables[0].rows:
            tot_ru = float(row["total_ru"] or 0.0)
            tot_rows = float(row["total_returned_rows"] or 0.0)
            exec_count = int(row["execution_count"] or 1)
            avg_ru = tot_ru / exec_count if exec_count > 0 else 0.0
            avg_returned = tot_rows / exec_count if exec_count > 0 else 0.0
            ru_per_row = (tot_ru / tot_rows) if tot_rows > 0 else None
            ru_share = (
                min(100.0, (tot_ru / window_total_ru * 100.0)) if window_total_ru > 0.0 else 0.0
            )

            sample_text = None
            try:
                sample_text = str(row["sample_text"]) if row["sample_text"] else None
            except (KeyError, IndexError):
                sample_text = None

            shapes.append(
                DiscoveredQueryShape(
                    database=str(row["database"] or ""),
                    container=str(row["container"] or ""),
                    shape_id=str(row["shape_id"] or ""),
                    sample_query_text=sample_text,
                    execution_count=exec_count,
                    total_ru=tot_ru,
                    avg_ru=avg_ru,
                    max_ru=float(row["max_ru"] or 0.0),
                    ru_share_pct=ru_share,
                    avg_returned_rows=avg_returned,
                    ru_per_returned_row=ru_per_row,
                    throttled_count=int(row["throttled_count"] or 0),
                    top_callers=[],
                )
            )

    # Evaluate Retention Warning
    retention_warning = False
    if min_time_generated is not None:
        threshold = window_start + max(timedelta(hours=1), 0.05 * options.time_window)
        if min_time_generated > threshold:
            retention_warning = True

    return WorkloadDiscoverySummary(
        window_start=window_start,
        window_end=window_end,
        total_ru=window_total_ru,
        attributed_total_ru=attributed_total_ru,
        unattributed_ru=unattributed_ru,
        unattributed_ru_pct=unattributed_ru_pct,
        discovered_query_count=len(shapes),
        results=shapes,
        retention_warning=retention_warning,
        masked_workspace_id=_mask_workspace_id(options.workspace_id),
    )


def run_preflight_check(
    options: DiscoveryOptions,
    client: LogsQueryClient | None = None,
) -> PreflightCheckReport:
    """Execute preflight diagnostic telemetry check (US2)."""
    raise NotImplementedError
