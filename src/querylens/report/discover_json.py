"""JSON output serialization for discovery and preflight check reports."""

import json
from typing import Any

from querylens.discovery.models import (
    PreflightCheckReport,
    WorkloadDiscoverySummary,
)


def serialize_discovery_json(
    summary: WorkloadDiscoverySummary,
    show_text: bool = False,
) -> str:
    """Serialize WorkloadDiscoverySummary to JSON matching discover-output-schema.json.

    By default (show_text=False), sample_query_text is omitted from all result items
    to uphold privacy invariant FR-012.

    Args:
        summary: The WorkloadDiscoverySummary object to serialize.
        show_text: Whether to include sample_query_text in results.

    Returns:
        Formatted JSON string.
    """
    results: list[dict[str, Any]] = []
    for s in summary.results:
        item: dict[str, Any] = {
            "database": s.database,
            "container": s.container,
            "shape_id": s.shape_id,
            "execution_count": s.execution_count,
            "total_ru": round(s.total_ru, 2),
            "avg_ru": round(s.avg_ru, 2),
            "max_ru": round(s.max_ru, 2),
            "ru_share_pct": round(s.ru_share_pct, 2),
            "avg_returned_rows": round(s.avg_returned_rows, 2),
            "ru_per_returned_row": (
                round(s.ru_per_returned_row, 2) if s.ru_per_returned_row is not None else None
            ),
            "throttled_count": s.throttled_count,
        }
        if show_text and s.sample_query_text is not None:
            item["sample_query_text"] = s.sample_query_text
        if s.top_callers:
            item["top_callers"] = [
                {
                    "identifier": c.identifier,
                    "ru_share_pct": round(c.ru_share_pct, 2),
                    "identifier_type": c.identifier_type,
                }
                for c in s.top_callers
            ]
        results.append(item)

    data: dict[str, Any] = {
        "window_start": summary.window_start.isoformat(),
        "window_end": summary.window_end.isoformat(),
        "total_ru": round(summary.total_ru, 2),
        "attributed_total_ru": round(summary.attributed_total_ru, 2),
        "unattributed_ru": round(summary.unattributed_ru, 2),
        "unattributed_ru_pct": round(summary.unattributed_ru_pct, 2),
        "discovered_query_count": summary.discovered_query_count,
        "results": results,
        "retention_warning": summary.retention_warning,
        "masked_workspace_id": summary.masked_workspace_id,
    }
    return json.dumps(data, indent=2)


def serialize_check_json(report: PreflightCheckReport) -> str:
    """Serialize PreflightCheckReport to JSON matching check-output-schema.json.

    Contains 100% quantitative metrics with zero customer data or query text.

    Args:
        report: The PreflightCheckReport object to serialize.

    Returns:
        Formatted JSON string.
    """
    data: dict[str, Any] = {
        "categories_detected": report.categories_detected,
        "row_counts": report.row_counts,
        "window_start": report.window_start.isoformat(),
        "window_end": report.window_end.isoformat(),
        "earliest_record": (
            report.earliest_record.isoformat() if report.earliest_record is not None else None
        ),
        "latest_record": (
            report.latest_record.isoformat() if report.latest_record is not None else None
        ),
        "field_coverage": {k: round(v, 4) for k, v in report.field_coverage.items()},
        "auth_breakdown": report.auth_breakdown,
        "retention_warning": report.retention_warning,
        "masked_workspace_id": report.masked_workspace_id,
    }
    return json.dumps(data, indent=2)
