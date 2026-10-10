"""Unit tests for diagnostic rule functions (T018).

Evaluates detection logic, severities, and quantitative evidence for:
- QL001: High RU Cost
- QL002: Cross-Partition Fan-Out
- QL003: Scan-to-Return Gap
"""

from querylens.config import Settings
from querylens.model import QueryCost, Severity
from querylens.rules.fanout import rule_cross_partition_fanout
from querylens.rules.high_ru import rule_high_ru_cost
from querylens.rules.scan_gap import rule_scan_to_return_gap


class TestHighRuCostRule:
    """Tests covering QL001 high Request Unit cost detection."""

    def test_high_ru_below_threshold(self) -> None:
        """Return no findings when Request Units are below warning threshold."""
        settings = Settings(high_ru_warning=50.0, high_ru_critical=200.0)
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=45.0,
            latency_ms=10.0,
            documents_scanned=10,
            documents_returned=10,
            is_cross_partition=False,
        )
        findings = rule_high_ru_cost(cost, settings)
        assert len(findings) == 0

    def test_high_ru_warning_level(self) -> None:
        """Flag HIGH severity when RU charge meets or exceeds warning threshold."""
        settings = Settings(high_ru_warning=50.0, high_ru_critical=200.0)
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=75.0,
            latency_ms=20.0,
            documents_scanned=10,
            documents_returned=10,
            is_cross_partition=False,
        )
        findings = rule_high_ru_cost(cost, settings)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule_id == "QL001"
        assert finding.severity == Severity.HIGH
        assert finding.evidence["request_charge"] == 75.0
        assert finding.evidence["threshold"] == 50.0

    def test_high_ru_critical_level(self) -> None:
        """Flag CRITICAL severity when RU charge meets or exceeds critical threshold."""
        settings = Settings(high_ru_warning=50.0, high_ru_critical=200.0)
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=250.0,
            latency_ms=80.0,
            documents_scanned=100,
            documents_returned=100,
            is_cross_partition=False,
        )
        findings = rule_high_ru_cost(cost, settings)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule_id == "QL001"
        assert finding.severity == Severity.CRITICAL
        assert finding.evidence["request_charge"] == 250.0
        assert finding.evidence["threshold"] == 200.0


class TestCrossPartitionFanoutRule:
    """Tests covering QL002 cross-partition fan-out detection."""

    def test_single_partition_no_finding(self) -> None:
        """Return no findings when query is scoped to single partition."""
        settings = Settings()
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=5.0,
            latency_ms=2.0,
            documents_scanned=5,
            documents_returned=5,
            is_cross_partition=False,
        )
        findings = rule_cross_partition_fanout(cost, settings)
        assert len(findings) == 0

    def test_cross_partition_detected(self) -> None:
        """Flag MEDIUM severity when query spans multiple partitions."""
        settings = Settings()
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=35.0,
            latency_ms=15.0,
            documents_scanned=20,
            documents_returned=10,
            is_cross_partition=True,
        )
        findings = rule_cross_partition_fanout(cost, settings)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule_id == "QL002"
        assert finding.severity == Severity.MEDIUM
        assert finding.evidence["is_cross_partition"] is True


class TestScanToReturnGapRule:
    """Tests covering QL003 scan-to-return gap detection."""

    def test_low_gap_no_finding(self) -> None:
        """Return no findings when scanned-to-returned ratio is healthy (< 10x)."""
        settings = Settings(
            scan_gap_ratio_warning=10.0,
            scan_gap_ratio_critical=100.0,
            scan_gap_absolute_threshold=1000,
        )
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=10.0,
            latency_ms=5.0,
            documents_scanned=50,
            documents_returned=10,  # 5x ratio
            is_cross_partition=False,
        )
        findings = rule_scan_to_return_gap(cost, settings)
        assert len(findings) == 0

    def test_warning_ratio_gap(self) -> None:
        """Flag HIGH severity when ratio meets warning threshold (>= 10x)."""
        settings = Settings(
            scan_gap_ratio_warning=10.0,
            scan_gap_ratio_critical=100.0,
            scan_gap_absolute_threshold=1000,
        )
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=30.0,
            latency_ms=12.0,
            documents_scanned=200,
            documents_returned=10,  # 20x ratio
            is_cross_partition=False,
        )
        findings = rule_scan_to_return_gap(cost, settings)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule_id == "QL003"
        assert finding.severity == Severity.HIGH
        assert finding.evidence["ratio"] == 20.0

    def test_critical_ratio_gap(self) -> None:
        """Flag CRITICAL severity when ratio meets critical threshold (>= 100x)."""
        settings = Settings(
            scan_gap_ratio_warning=10.0,
            scan_gap_ratio_critical=100.0,
            scan_gap_absolute_threshold=1000,
        )
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=120.0,
            latency_ms=45.0,
            documents_scanned=1500,
            documents_returned=10,  # 150x ratio
            is_cross_partition=False,
        )
        findings = rule_scan_to_return_gap(cost, settings)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule_id == "QL003"
        assert finding.severity == Severity.CRITICAL
        assert finding.evidence["ratio"] == 150.0

    def test_zero_returned_absolute_threshold(self) -> None:
        """Flag CRITICAL severity when zero docs returned and scanned >= threshold."""
        settings = Settings(
            scan_gap_ratio_warning=10.0,
            scan_gap_ratio_critical=100.0,
            scan_gap_absolute_threshold=1000,
        )
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=95.0,
            latency_ms=30.0,
            documents_scanned=1200,
            documents_returned=0,
            is_cross_partition=False,
        )
        findings = rule_scan_to_return_gap(cost, settings)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule_id == "QL003"
        assert finding.severity == Severity.CRITICAL
        assert finding.evidence["documents_scanned"] == 1200
        assert finding.evidence["documents_returned"] == 0
