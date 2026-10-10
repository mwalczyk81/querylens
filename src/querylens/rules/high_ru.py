"""Diagnostic rule QL001: High Request Unit Cost."""

from querylens.config import Settings
from querylens.model import Finding, QueryCost, Severity


def rule_high_ru_cost(cost: QueryCost, settings: Settings) -> list[Finding]:
    """Diagnose excessive Request Unit consumption.

    Args:
        cost: Captured query cost metrics.
        settings: Configuration thresholds for high RU warnings and critical findings.

    Returns:
        list[Finding]: Diagnostic findings if RU charge exceeds thresholds.
    """
    if cost.request_charge >= settings.high_ru_critical:
        return [
            Finding(
                rule_id="QL001",
                rule_name="High RU Cost",
                severity=Severity.CRITICAL,
                summary=(
                    f"Query consumed {cost.request_charge:.2f} RUs exceeding "
                    f"critical threshold ({settings.high_ru_critical:.2f} RUs)."
                ),
                evidence={
                    "request_charge": cost.request_charge,
                    "threshold": settings.high_ru_critical,
                },
            )
        ]

    if cost.request_charge >= settings.high_ru_warning:
        return [
            Finding(
                rule_id="QL001",
                rule_name="High RU Cost",
                severity=Severity.HIGH,
                summary=(
                    f"Query consumed {cost.request_charge:.2f} RUs exceeding "
                    f"warning threshold ({settings.high_ru_warning:.2f} RUs)."
                ),
                evidence={
                    "request_charge": cost.request_charge,
                    "threshold": settings.high_ru_warning,
                },
            )
        ]

    return []
