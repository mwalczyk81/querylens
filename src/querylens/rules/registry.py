"""Diagnostic rule registry and evaluation runner."""

from collections.abc import Callable

from querylens.config import Settings
from querylens.model import Finding, QueryCost
from querylens.rules.fanout import rule_cross_partition_fanout
from querylens.rules.high_ru import rule_high_ru_cost
from querylens.rules.scan_gap import rule_scan_to_return_gap

RuleCallable = Callable[[QueryCost, Settings], list[Finding]]

DEFAULT_RULES: list[RuleCallable] = [
    rule_high_ru_cost,
    rule_cross_partition_fanout,
    rule_scan_to_return_gap,
]


def evaluate_rules(
    cost: QueryCost,
    settings: Settings,
    rules: list[RuleCallable] | None = None,
) -> list[Finding]:
    """Evaluate diagnostic rules against query cost metrics.

    Args:
        cost: Captured query cost metrics.
        settings: QueryLens configuration settings containing threshold limits.
        rules: Optional custom list of rule functions (defaults to DEFAULT_RULES).

    Returns:
        list[Finding]: Collection of findings flagged by the evaluated rules.
    """
    active_rules = rules if rules is not None else DEFAULT_RULES
    all_findings: list[Finding] = []

    for rule in active_rules:
        all_findings.extend(rule(cost, settings))

    return all_findings
