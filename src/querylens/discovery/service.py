"""Discovery execution service interacting with Azure Monitor Logs."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient, LogsQueryResult

from querylens.discovery.kql import (
    build_preflight_check_query,
    build_shapes_query,
    build_totals_query,
)
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
    """Execute preflight diagnostic telemetry check against target Log Analytics workspace.

    Verifies workspace connectivity, detected diagnostic categories, row counts,
    earliest and latest record timestamps, key field coverage percentages, and auth
    token distributions. Emits 100% quantitative metrics with zero query text.

    Args:
        options: Validated DiscoveryOptions configuration.
        client: Optional injected LogsQueryClient instance for testing.

    Returns:
        PreflightCheckReport containing quantitative telemetry health summary.
    """
    logs_client = client or LogsQueryClient(credential=DefaultAzureCredential())

    window_end = datetime.now(UTC)
    window_start = window_end - options.time_window

    check_kql = build_preflight_check_query(account_filter=options.account_filter)

    res = logs_client.query_workspace(
        workspace_id=str(options.workspace_id),
        query=check_kql,
        timespan=options.time_window,
        server_timeout=options.server_timeout_seconds,
    )
    tables = (
        res.tables
        if isinstance(res, LogsQueryResult)
        else (res.partial_data if hasattr(res, "partial_data") else [])
    )

    dataplane_count = 0
    queryruntime_count = 0
    earliest_record: datetime | None = None
    latest_record: datetime | None = None
    has_shapesignature = 0
    has_querytext = 0
    has_aad_guid = 0
    has_aad_str = 0
    has_client_ip = 0
    has_useragent = 0
    raw_auth: Any = None

    if tables and len(tables[0].rows) > 0:
        row = tables[0].rows[0]
        dataplane_count = int(row["dataplane_count"] or 0)
        queryruntime_count = int(row["queryruntime_count"] or 0)
        earliest_record = _parse_timestamp(row["earliest_time"])
        latest_record = _parse_timestamp(row["latest_time"])
        has_shapesignature = int(row["has_shapesignature"] or 0)
        has_querytext = int(row["has_querytext"] or 0)
        has_aad_guid = int(row["has_aad_guid"] or 0)
        has_aad_str = int(row["has_aad_str"] or 0)
        has_client_ip = int(row["has_client_ip"] or 0)
        has_useragent = int(row["has_useragent"] or 0)
        raw_auth = row["auth_breakdown"]

    categories_detected: list[str] = []
    if dataplane_count > 0:
        categories_detected.append("DataPlaneRequests")
    if queryruntime_count > 0:
        categories_detected.append("QueryRuntimeStatistics")

    row_counts: dict[str, int] = {
        "DataPlaneRequests": dataplane_count,
        "QueryRuntimeStatistics": queryruntime_count,
    }

    field_coverage: dict[str, float] = {
        "shapesignature_s": (
            min(1.0, has_shapesignature / queryruntime_count) if queryruntime_count > 0 else 0.0
        ),
        "querytext_s": (
            min(1.0, has_querytext / queryruntime_count) if queryruntime_count > 0 else 0.0
        ),
        "aadPrincipalId_g": (
            min(1.0, has_aad_guid / dataplane_count) if dataplane_count > 0 else 0.0
        ),
        "aadPrincipalId_s": (
            min(1.0, has_aad_str / dataplane_count) if dataplane_count > 0 else 0.0
        ),
        "clientIpAddress_s": (
            min(1.0, has_client_ip / dataplane_count) if dataplane_count > 0 else 0.0
        ),
        "useragent_s": (min(1.0, has_useragent / dataplane_count) if dataplane_count > 0 else 0.0),
    }

    auth_breakdown: dict[str, int] = {}
    if isinstance(raw_auth, str):
        try:
            parsed = json.loads(raw_auth)
            if isinstance(parsed, dict):
                auth_breakdown = {str(k): int(v or 0) for k, v in parsed.items()}
        except (ValueError, TypeError):
            pass
    elif isinstance(raw_auth, dict):
        auth_breakdown = {str(k): int(v or 0) for k, v in raw_auth.items()}

    retention_warning = False
    if earliest_record is not None:
        threshold = window_start + max(timedelta(hours=1), 0.05 * options.time_window)
        if earliest_record > threshold:
            retention_warning = True

    return PreflightCheckReport(
        categories_detected=categories_detected,
        row_counts=row_counts,
        window_start=window_start,
        window_end=window_end,
        earliest_record=earliest_record,
        latest_record=latest_record,
        field_coverage=field_coverage,
        auth_breakdown=auth_breakdown,
        retention_warning=retention_warning,
        masked_workspace_id=_mask_workspace_id(options.workspace_id),
    )
