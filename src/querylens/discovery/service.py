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
    CallerAttribution,
    DiscoveredQueryShape,
    DiscoveryOptions,
    InternalConsistencyError,
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


def _parse_top_callers(raw_callers: Any, shape_total_ru: float) -> list[CallerAttribution]:
    """Parse and strictly validate top_callers dynamic property bags from Query 1 row.

    Args:
        raw_callers: Raw column value from row["ql_top_callers"].
        shape_total_ru: Total RU of the containing query shape.

    Returns:
        List of up to 3 validated CallerAttribution models.

    Raises:
        InternalConsistencyError: If the caller list or its items violate shape or type invariants.
    """
    if raw_callers is None:
        return []

    if isinstance(raw_callers, str):
        val = raw_callers.strip()
        if not val or val == "[]":
            return []
        try:
            parsed = json.loads(val)
        except (ValueError, TypeError) as err:
            raise InternalConsistencyError(f"Failed to parse callers JSON: {err}") from err
    else:
        parsed = raw_callers

    if not isinstance(parsed, list):
        msg = (
            f"Unexpected top callers shape: expected list of caller objects, "
            f"got {type(parsed).__name__}: {parsed!r}"
        )
        raise InternalConsistencyError(msg)

    if not parsed:
        return []

    for item in parsed:
        if not isinstance(item, dict):
            msg = (
                f"Unexpected caller item shape: expected dict of caller properties, "
                f"got {type(item).__name__}: {item!r}"
            )
            raise InternalConsistencyError(msg)

    if len(parsed) > 3:
        raise InternalConsistencyError(
            f"Top callers exceeded maximum of 3 callers per shape: got {len(parsed)}"
        )

    callers: list[CallerAttribution] = []
    for item in parsed:
        if "identifier" not in item or "caller_ru" not in item or "identifier_type" not in item:
            missing = [k for k in ("identifier", "caller_ru", "identifier_type") if k not in item]
            msg = f"Caller item missing required keys {missing}: {item!r}"
            raise InternalConsistencyError(msg)

        raw_id = item["identifier"]
        raw_ru = item["caller_ru"]
        raw_type = item["identifier_type"]

        if not isinstance(raw_id, str) or not raw_id.strip():
            raise InternalConsistencyError(
                f"Caller identifier must be non-empty string, got {raw_id!r}"
            )

        if isinstance(raw_ru, bool) or not isinstance(raw_ru, (int, float)) or raw_ru < 0:
            raise InternalConsistencyError(
                f"Caller caller_ru must be non-negative number, got {raw_ru!r}"
            )

        if raw_type not in ("aad_principal", "client_ip"):
            raise InternalConsistencyError(
                f"Caller identifier_type must be 'aad_principal' or 'client_ip', got {raw_type!r}"
            )

        caller_ru_float = float(raw_ru)
        if shape_total_ru > 0.0:
            ru_share = (caller_ru_float / shape_total_ru) * 100.0
            if ru_share > 100.0:
                if ru_share <= 100.001:  # Floating-point tolerance
                    ru_share = 100.0
                else:
                    msg = (
                        f"Caller RU share exceeded 100.0%: {ru_share:.2f}% "
                        f"({caller_ru_float}/{shape_total_ru}). "
                        "Caller RU cannot exceed shape total RU."
                    )
                    raise InternalConsistencyError(msg)
            elif ru_share < 0.0:
                raise InternalConsistencyError(
                    f"Caller RU share cannot be negative: {ru_share:.2f}%"
                )
        else:
            ru_share = 0.0

        callers.append(
            CallerAttribution(
                identifier=raw_id.strip(),
                ru_share_pct=ru_share,
                identifier_type=raw_type,
            )
        )

    return callers


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
        window_total_ru = float(row["ql_window_total_ru"] or 0.0)
        attributed_total_ru = float(row["ql_attributed_total_ru"] or 0.0)
        min_time_generated = _parse_timestamp(row["ql_min_time_generated"])

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
            tot_ru = float(row["ql_total_ru"] or 0.0)
            tot_rows = float(row["ql_total_returned_rows"] or 0.0)
            exec_count = int(row["ql_execution_count"] or 1)
            avg_ru = tot_ru / exec_count if exec_count > 0 else 0.0
            avg_returned = tot_rows / exec_count if exec_count > 0 else 0.0
            ru_per_row = (tot_ru / tot_rows) if tot_rows > 0 else None
            if window_total_ru > 0.0:
                ru_share = (tot_ru / window_total_ru) * 100.0
                if ru_share > 100.0:
                    if ru_share <= 100.001:
                        ru_share = 100.0
                    else:
                        msg = (
                            f"query shape RU share exceeded 100.0%: "
                            f"{ru_share:.2f}% ({tot_ru}/{window_total_ru}). "
                            "Shape RU cannot exceed total window RU."
                        )
                        raise InternalConsistencyError(msg)
            else:
                ru_share = 0.0

            sample_text = None
            try:
                sample_text = str(row["ql_sample_text"]) if row["ql_sample_text"] else None
            except (KeyError, IndexError):
                sample_text = None

            callers: list[CallerAttribution] = []
            try:
                raw_callers = row["ql_top_callers"]
                callers = _parse_top_callers(raw_callers, tot_ru)
            except (KeyError, IndexError):
                callers = []

            raw_db = row["ql_db_name"]
            raw_coll = row["ql_coll_name"]
            db_val = str(raw_db).strip() if raw_db else "(unknown)"
            coll_val = str(raw_coll).strip() if raw_coll else "(unknown)"

            shapes.append(
                DiscoveredQueryShape(
                    database=db_val,
                    container=coll_val,
                    shape_id=str(row["ql_shape_id"] or ""),
                    sample_query_text=sample_text,
                    execution_count=exec_count,
                    total_ru=tot_ru,
                    avg_ru=avg_ru,
                    max_ru=float(row["ql_max_ru"] or 0.0),
                    ru_share_pct=ru_share,
                    avg_returned_rows=avg_returned,
                    ru_per_returned_row=ru_per_row,
                    throttled_count=int(row["ql_throttled_count"] or 0),
                    top_callers=callers,
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


def _compute_coverage_ratio(numerator: int, denominator: int, field_name: str) -> float:
    """Compute field coverage ratio, ensuring numerator does not exceed denominator.

    Args:
        numerator: Count of records where field is populated.
        denominator: Total records in the category.
        field_name: Diagnostic field name for error reporting.

    Returns:
        Coverage ratio between 0.0 and 1.0.

    Raises:
        InternalConsistencyError: If numerator exceeds denominator,
            indicating an internal query scoping bug.
    """
    if denominator == 0:
        return 0.0
    ratio = numerator / denominator
    if ratio > 1.0:
        msg = (
            f"field coverage ratio for '{field_name}' "
            f"exceeded 1.0 ({numerator}/{denominator} = {ratio:.4f}). "
            "Population count must not exceed category row count."
        )
        raise InternalConsistencyError(msg)
    return ratio


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
        dataplane_count = int(row["ql_dataplane_count"] or 0)
        queryruntime_count = int(row["ql_queryruntime_count"] or 0)
        earliest_record = _parse_timestamp(row["ql_earliest_time"])
        latest_record = _parse_timestamp(row["ql_latest_time"])
        has_shapesignature = int(row["ql_has_shapesignature"] or 0)
        has_querytext = int(row["ql_has_querytext"] or 0)
        has_aad_guid = int(row["ql_has_aad_guid"] or 0)
        has_aad_str = int(row["ql_has_aad_str"] or 0)
        has_client_ip = int(row["ql_has_client_ip"] or 0)
        has_useragent = int(row["ql_has_useragent"] or 0)
        raw_auth = row["ql_auth_breakdown"]

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
        "shapesignature_s": _compute_coverage_ratio(
            has_shapesignature, queryruntime_count, "shapesignature_s"
        ),
        "querytext_s": _compute_coverage_ratio(has_querytext, queryruntime_count, "querytext_s"),
        "aadPrincipalId_g": _compute_coverage_ratio(
            has_aad_guid, dataplane_count, "aadPrincipalId_g"
        ),
        "aadPrincipalId_s": _compute_coverage_ratio(
            has_aad_str, dataplane_count, "aadPrincipalId_s"
        ),
        "clientIpAddress_s": _compute_coverage_ratio(
            has_client_ip, dataplane_count, "clientIpAddress_s"
        ),
        "useragent_s": _compute_coverage_ratio(has_useragent, dataplane_count, "useragent_s"),
    }

    auth_breakdown: dict[str, int] = {}
    if raw_auth is not None:
        if isinstance(raw_auth, str):
            if raw_auth.strip():
                try:
                    parsed = json.loads(raw_auth)
                except (ValueError, TypeError) as err:
                    raise InternalConsistencyError(
                        f"Failed to parse auth breakdown JSON: {err}"
                    ) from err
            else:
                parsed = {}
        else:
            parsed = raw_auth

        if isinstance(parsed, dict):
            try:
                auth_breakdown = {str(k): int(v) for k, v in parsed.items()}
            except (ValueError, TypeError) as err:
                raise InternalConsistencyError(f"Invalid count in auth breakdown: {err}") from err
        else:
            msg = (
                "Unexpected auth breakdown shape: expected dict of auth type to count, "
                f"got {type(parsed).__name__}: {parsed!r}"
            )
            raise InternalConsistencyError(msg)

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
