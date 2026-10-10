"""Property-based tests for diagnostic rule invariants using Hypothesis (T019)."""

from hypothesis import given
from hypothesis import strategies as st

from querylens.config import Settings
from querylens.model import QueryCost, Severity
from querylens.rules.fanout import rule_cross_partition_fanout
from querylens.rules.high_ru import rule_high_ru_cost
from querylens.rules.scan_gap import rule_scan_to_return_gap


class TestRulesPropertyInvariants:
    """Property tests verifying monotonicity and no-crash safety across all inputs."""

    @given(
        request_charge=st.floats(min_value=0.0, max_value=100_000.0, allow_nan=False),
        warn_threshold=st.floats(min_value=1.0, max_value=500.0, allow_nan=False),
        crit_factor=st.floats(min_value=1.1, max_value=10.0, allow_nan=False),
    )
    def test_high_ru_monotonicity_and_validity(
        self, request_charge: float, warn_threshold: float, crit_factor: float
    ) -> None:
        """Verify high RU rule produces valid severity and never crashes."""
        crit_threshold = warn_threshold * crit_factor
        settings = Settings(high_ru_warning=warn_threshold, high_ru_critical=crit_threshold)

        cost = QueryCost(
            query_id="q_prop",
            query_text="SELECT * FROM c",
            request_charge=request_charge,
            latency_ms=10.0,
            documents_scanned=10,
            documents_returned=10,
            is_cross_partition=False,
        )

        findings = rule_high_ru_cost(cost, settings)
        if request_charge < warn_threshold:
            assert len(findings) == 0
        elif request_charge < crit_threshold:
            assert len(findings) == 1
            assert findings[0].severity == Severity.HIGH
            assert "request_charge" in findings[0].evidence
        else:
            assert len(findings) == 1
            assert findings[0].severity == Severity.CRITICAL
            assert "request_charge" in findings[0].evidence

    @given(is_cross_partition=st.booleans() | st.none())
    def test_fanout_invariant(self, is_cross_partition: bool | None) -> None:
        """Verify fanout rule strictly mirrors is_cross_partition flag."""
        settings = Settings()
        cost = QueryCost(
            query_id="q_prop",
            query_text="SELECT * FROM c",
            request_charge=5.0,
            latency_ms=2.0,
            documents_scanned=5,
            documents_returned=5,
            is_cross_partition=is_cross_partition,
        )

        findings = rule_cross_partition_fanout(cost, settings)
        if is_cross_partition is True:
            assert len(findings) == 1
            assert findings[0].severity == Severity.MEDIUM
        else:
            assert len(findings) == 0

    @given(
        scanned=st.integers(min_value=0, max_value=1_000_000),
        returned=st.integers(min_value=0, max_value=10_000),
    )
    def test_scan_gap_invariants(self, scanned: int, returned: int) -> None:
        """Verify scan gap rule behaves predictably without crashes."""
        settings = Settings(
            scan_gap_ratio_warning=10.0,
            scan_gap_ratio_critical=100.0,
            scan_gap_absolute_threshold=1000,
        )
        cost = QueryCost(
            query_id="q_prop",
            query_text="SELECT * FROM c",
            request_charge=10.0,
            latency_ms=5.0,
            documents_scanned=scanned,
            documents_returned=returned,
            is_cross_partition=False,
        )

        findings = rule_scan_to_return_gap(cost, settings)
        assert len(findings) in (0, 1)

        if findings:
            f = findings[0]
            assert f.rule_id == "QL003"
            assert f.severity in (Severity.HIGH, Severity.CRITICAL)
            assert bool(f.evidence) is True
