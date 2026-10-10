"""Unit tests for console and JSON reporting."""

import json

from rich.console import Console

from querylens.model import (
    Finding,
    QueryCost,
    QueryResultSummary,
    Severity,
    WorkloadRunSummary,
)
from querylens.report.console import render_console_report
from querylens.report.json_out import serialize_summary_json


def create_sample_summary(budget_exceeded: bool = False) -> WorkloadRunSummary:
    """Helper creating sample WorkloadRunSummary with various finding severities."""
    cost1 = QueryCost(
        query_id="q1-high-ru",
        query_text="SELECT * FROM c",
        request_charge=250.0,
        latency_ms=45.0,
        documents_scanned=5000,
        documents_returned=10,
        is_cross_partition=True,
        is_partial=budget_exceeded,
    )
    cost2 = QueryCost(
        query_id="q2-med-ru",
        query_text="SELECT c.id FROM c",
        request_charge=75.0,
        latency_ms=15.0,
        documents_scanned=200,
        documents_returned=50,
        is_cross_partition=False,
    )
    cost3 = QueryCost(
        query_id="q3-low-ru",
        query_text="SELECT * FROM c WHERE c.id = '1'",
        request_charge=2.5,
        latency_ms=3.0,
        documents_scanned=1,
        documents_returned=1,
        is_cross_partition=False,
    )

    findings1 = [
        Finding(
            rule_id="QL001",
            rule_name="High RU Cost",
            severity=Severity.CRITICAL,
            summary="RU charge exceeds critical threshold",
            evidence={"request_charge": 250.0},
        ),
        Finding(
            rule_id="QL002",
            rule_name="Cross-Partition Fan-Out",
            severity=Severity.HIGH,
            summary="Query fanned out across multiple partitions",
            evidence={"fan_out": True},
        ),
    ]
    findings2 = [
        Finding(
            rule_id="QL003",
            rule_name="Scan-to-Return Gap",
            severity=Severity.MEDIUM,
            summary="Scanned 200 documents but returned only 50",
            evidence={"scanned": 200, "returned": 50},
        ),
        Finding(
            rule_id="QL004",
            rule_name="Point Query Recommendation",
            severity=Severity.INFO,
            summary="Query could be optimized",
            evidence={},
        ),
    ]

    return WorkloadRunSummary(
        timestamp="2026-10-10T12:00:00Z",
        database="test-db",
        container="orders",
        total_queries=3,
        completed_queries=3,
        total_ru_consumed=327.5,
        ru_budget=300.0 if budget_exceeded else None,
        budget_exceeded=budget_exceeded,
        results=[
            QueryResultSummary(cost=cost1, findings=findings1),
            QueryResultSummary(cost=cost2, findings=findings2),
            QueryResultSummary(cost=cost3, findings=[]),
        ],
    )


class TestReports:
    """Tests covering console table rendering and JSON serialization."""

    def test_json_serialization(self) -> None:
        """Verify serialize_summary_json produces valid JSON matching structure."""
        summary = create_sample_summary()
        json_str = serialize_summary_json(summary)
        parsed = json.loads(json_str)

        assert parsed["database"] == "test-db"
        assert parsed["container"] == "orders"
        assert len(parsed["results"]) == 3
        assert parsed["total_ru_consumed"] == 327.5

    def test_render_console_report_normal(self) -> None:
        """Render console report to memory Console."""
        console = Console(record=True, width=120)
        summary = create_sample_summary(budget_exceeded=False)

        render_console_report(summary, console=console)
        output = console.export_text()

        assert "QueryLens Workload Profile" in output
        assert "q1-high-ru" in output
        assert "q2-med-ru" in output
        assert "q3-low-ru" in output
        assert "Server time" in output
        assert "Budget: none" in output
        assert "Diagnostic Details:" in output
        assert "High RU Cost" in output

    def test_render_console_report_budget_exceeded(self) -> None:
        """Render console report with budget exceeded banner."""
        console = Console(record=True, width=120)
        summary = create_sample_summary(budget_exceeded=True)

        render_console_report(summary, console=console)
        output = console.export_text()

        assert "EXCEEDED" in output
        assert "Budget: 300.00 RUs (EXCEEDED)" in output
        assert "Execution aborted: Cumulative RU budget ceiling reached" in output
        assert "(partial)" in output

    def test_render_console_report_with_query_error(self) -> None:
        """Render console report with query execution error showing [ERROR] badge and message."""
        console = Console(record=True, width=120)
        error_cost = QueryCost(
            query_id="q_bad",
            query_text="SELECT FROM c",
            request_charge=0.0,
            latency_ms=0.0,
            documents_scanned=0,
            documents_returned=0,
            is_cross_partition=False,
            error_message="Syntax error near 'FROM'",
        )
        summary = WorkloadRunSummary(
            timestamp="2026-10-10T12:00:00Z",
            database="test-db",
            container="orders",
            total_queries=1,
            completed_queries=1,
            total_ru_consumed=0.0,
            ru_budget=None,
            budget_exceeded=False,
            results=[QueryResultSummary(cost=error_cost, findings=[])],
        )

        render_console_report(summary, console=console)
        output = console.export_text()

        assert "[ERROR]" in output
        assert "Diagnostic Details:" in output
        assert "Query Execution Error: Syntax error near 'FROM'" in output
