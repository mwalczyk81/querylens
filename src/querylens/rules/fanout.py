"""Diagnostic rule QL002: Cross-Partition Fan-Out."""

from querylens.config import Settings
from querylens.model import Finding, QueryCost, Severity


def rule_cross_partition_fanout(cost: QueryCost, _settings: Settings) -> list[Finding]:
    """Diagnose un-partitioned query fan-out across multiple physical partitions.

    Args:
        cost: Captured query cost metrics.
        _settings: QueryLens configuration settings.

    Returns:
        list[Finding]: Diagnostic finding if query executed cross-partition.
    """
    if cost.is_partial:
        return []

    if cost.is_cross_partition is True:
        return [
            Finding(
                rule_id="QL002",
                rule_name="Cross-Partition Fan-Out",
                severity=Severity.MEDIUM,
                summary=(
                    "Query execution fanned out across multiple physical partitions "
                    "without a scoped partition key."
                ),
                evidence={"is_cross_partition": True},
            )
        ]
    return []
