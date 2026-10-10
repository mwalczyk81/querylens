"""Unit tests for QueryLens domain models and partition_key validation."""

import pytest
from pydantic import ValidationError

from querylens.model import (
    Finding,
    IndexUtilization,
    QueryCost,
    QueryDefinition,
    QueryParameter,
    QueryResultSummary,
    Severity,
    Workload,
    WorkloadRunSummary,
)


class TestSeverity:
    """Tests covering Severity enum ranking, comparison, and string equality."""

    def test_severity_ordering(self) -> None:
        """Verify strict ordering INFO < MEDIUM < HIGH < CRITICAL."""
        assert Severity.INFO < Severity.MEDIUM
        assert Severity.MEDIUM < Severity.HIGH
        assert Severity.HIGH < Severity.CRITICAL
        assert Severity.CRITICAL > Severity.INFO
        assert Severity.HIGH >= Severity.MEDIUM
        assert Severity.MEDIUM >= Severity.MEDIUM

    def test_severity_levels(self) -> None:
        """Verify numeric levels match 1, 2, 3, 4."""
        assert Severity.INFO.level == 1
        assert Severity.MEDIUM.level == 2
        assert Severity.HIGH.level == 3
        assert Severity.CRITICAL.level == 4

    def test_severity_equality_with_strings(self) -> None:
        """Verify case-insensitive string equality."""
        assert Severity.CRITICAL == "CRITICAL"
        assert Severity.CRITICAL == "critical"
        assert Severity.HIGH != "LOW"
        assert Severity.HIGH != 123
        assert hash(Severity.HIGH) == hash("HIGH")

    def test_severity_rich_comparisons(self) -> None:
        """Verify __le__, __gt__, __ge__ and comparisons with string names."""
        assert Severity.INFO <= Severity.MEDIUM
        assert Severity.INFO <= Severity.INFO
        assert Severity.CRITICAL >= Severity.HIGH
        assert Severity.HIGH > Severity.MEDIUM
        assert Severity.INFO < "HIGH"
        assert Severity.HIGH > "MEDIUM"
        assert Severity.HIGH >= "HIGH"
        assert Severity.INFO <= "MEDIUM"
        with pytest.raises(TypeError):
            _ = Severity.INFO < 42


class TestQueryParameter:
    """Tests covering query parameter name and value constraints."""

    def test_valid_parameter(self) -> None:
        """Accept parameter names starting with @."""
        param = QueryParameter(name="@tenantId", value="contoso")
        assert param.name == "@tenantId"
        assert param.value == "contoso"

    def test_invalid_parameter_name(self) -> None:
        """Reject parameter names not starting with @."""
        with pytest.raises(ValidationError):
            QueryParameter(name="tenantId", value="contoso")


class TestPartitionKeyValidation:
    """Tests covering partition_key validation rules specified in FR-001."""

    @pytest.mark.parametrize(
        "valid_pk",
        [
            None,
            "tenant-123",
            1001,
            99.9,
            True,
            ["tenant-123"],
            ["tenant-123", 42],
            ["tenant-123", 42, False],
        ],
    )
    def test_valid_partition_keys(self, valid_pk: object) -> None:
        """Valid partition key scalars or 1-3 element lists are accepted."""
        query_def = QueryDefinition(
            id="q1",
            query="SELECT * FROM c",
            partition_key=valid_pk,  # pyrefly: ignore
        )
        assert query_def.partition_key == valid_pk

    def test_reject_empty_list(self) -> None:
        """Empty lists [] must be rejected with ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            QueryDefinition(id="q1", query="SELECT * FROM c", partition_key=[])  # pyrefly: ignore
        assert "partition_key list cannot be empty" in str(exc_info.value)

    def test_reject_more_than_three_items(self) -> None:
        """Lists with > 3 items must be rejected with ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            QueryDefinition(
                id="q1",
                query="SELECT * FROM c",
                partition_key=["a", "b", "c", "d"],  # pyrefly: ignore
            )
        assert "partition_key list cannot exceed 3 elements" in str(exc_info.value)

    def test_reject_nested_list(self) -> None:
        """Nested lists within partition_key must be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            QueryDefinition(
                id="q1",
                query="SELECT * FROM c",
                partition_key=[["a"]],  # pyrefly: ignore
            )
        assert "partition_key list items must be primitive scalars" in str(exc_info.value)

    def test_reject_null_in_list(self) -> None:
        """Null items within partition_key list must be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            QueryDefinition(
                id="q1",
                query="SELECT * FROM c",
                partition_key=["tenant-1", None],  # pyrefly: ignore
            )
        assert "partition_key list items cannot be null" in str(exc_info.value)

    def test_reject_dict_partition_key(self) -> None:
        """Dict partition key must be rejected."""
        with pytest.raises(ValidationError) as exc_info:
            QueryDefinition(
                id="q1",
                query="SELECT * FROM c",
                partition_key={"key": "val"},  # pyrefly: ignore
            )
        assert "partition_key must be a scalar, list of 1-3 scalars, or null" in str(exc_info.value)


class TestWorkloadModel:
    """Tests covering Workload model and query list constraints."""

    def test_valid_workload(self) -> None:
        """Construct valid workload with 2 queries."""
        workload = Workload(
            version="1",
            database="db1",
            container="c1",
            ru_budget=500.0,
            queries=[
                QueryDefinition(id="q1", query="SELECT * FROM c"),
                QueryDefinition(
                    id="q2",
                    query="SELECT c.id FROM c WHERE c.active = @active",
                    parameters=[QueryParameter(name="@active", value=True)],
                ),
            ],
        )
        assert len(workload.queries) == 2
        assert workload.ru_budget == 500.0

    def test_reject_empty_queries(self) -> None:
        """Reject workloads with 0 queries."""
        with pytest.raises(ValidationError):
            Workload(queries=[])


class TestCostAndSummaryModels:
    """Tests covering QueryCost, Finding, and WorkloadRunSummary."""

    def test_query_cost_and_findings(self) -> None:
        """Construct QueryCost and associate with Findings."""
        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=120.5,
            latency_ms=45.2,
            documents_scanned=1000,
            documents_returned=5,
            is_cross_partition=True,
            is_partial=False,
            index_metrics=IndexUtilization(
                utilized_single=[{"path": "/id/?"}],
                potential_single=[{"path": "/category/?"}],
            ),
        )
        assert cost.request_charge == 120.5
        assert cost.is_partial is False
        assert cost.index_metrics is not None
        assert len(cost.index_metrics.potential_single) == 1

        finding = Finding(
            rule_id="QL003",
            rule_name="Scan-to-Return Gap",
            severity=Severity.HIGH,
            summary="Scanned 1000 documents but returned only 5",
            evidence={"documents_scanned": 1000, "documents_returned": 5},
        )
        summary = QueryResultSummary(cost=cost, findings=[finding])
        assert summary.cost.query_id == "q1"
        assert summary.findings[0].severity == Severity.HIGH

    def test_workload_run_summary(self) -> None:
        """Construct aggregate WorkloadRunSummary."""
        run_summary = WorkloadRunSummary(
            timestamp="2026-10-10T12:00:00Z",
            database="testdb",
            container="testc",
            total_queries=1,
            completed_queries=1,
            total_ru_consumed=12.5,
            ru_budget=100.0,
            budget_exceeded=False,
            results=[],
        )
        assert run_summary.budget_exceeded is False
        assert run_summary.total_ru_consumed == 12.5
