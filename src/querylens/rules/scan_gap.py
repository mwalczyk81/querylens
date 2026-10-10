"""Diagnostic rule QL003: Scan-to-Return Document Gap."""

from querylens.config import Settings
from querylens.model import Finding, QueryCost, Severity


def rule_scan_to_return_gap(cost: QueryCost, settings: Settings) -> list[Finding]:
    """Diagnose discrepancy between documents scanned from storage versus returned.

    Args:
        cost: Captured query cost metrics.
        settings: Thresholds for scan gap warning, critical ratios, and absolute
            zero-return ceiling.

    Returns:
        list[Finding]: Diagnostic findings if scan gap exceeds configured limits.
    """
    if cost.is_partial:
        return []

    scanned = cost.documents_scanned
    returned = cost.documents_returned

    if returned == 0:
        if scanned >= settings.scan_gap_absolute_threshold:
            return [
                Finding(
                    rule_id="QL003",
                    rule_name="Scan-to-Return Gap",
                    severity=Severity.CRITICAL,
                    summary=(
                        f"Query scanned {scanned} documents but returned 0 results, "
                        "indicating a costly unindexed predicate filter."
                    ),
                    evidence={
                        "documents_scanned": scanned,
                        "documents_returned": 0,
                        "threshold": settings.scan_gap_absolute_threshold,
                    },
                )
            ]
        return []

    ratio = scanned / returned
    if ratio >= settings.scan_gap_ratio_critical:
        return [
            Finding(
                rule_id="QL003",
                rule_name="Scan-to-Return Gap",
                severity=Severity.CRITICAL,
                summary=(
                    f"Scanned-to-returned ratio of {ratio:.1f}x exceeds "
                    f"critical threshold ({settings.scan_gap_ratio_critical:.1f}x)."
                ),
                evidence={
                    "ratio": round(ratio, 2),
                    "documents_scanned": scanned,
                    "documents_returned": returned,
                    "threshold": settings.scan_gap_ratio_critical,
                },
            )
        ]

    if ratio >= settings.scan_gap_ratio_warning:
        return [
            Finding(
                rule_id="QL003",
                rule_name="Scan-to-Return Gap",
                severity=Severity.HIGH,
                summary=(
                    f"Scanned-to-returned ratio of {ratio:.1f}x exceeds "
                    f"warning threshold ({settings.scan_gap_ratio_warning:.1f}x)."
                ),
                evidence={
                    "ratio": round(ratio, 2),
                    "documents_scanned": scanned,
                    "documents_returned": returned,
                    "threshold": settings.scan_gap_ratio_warning,
                },
            )
        ]

    return []
