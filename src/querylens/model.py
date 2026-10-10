"""Domain models and schemas for QueryLens."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Severity(StrEnum):
    """Diagnostic severity levels for rule findings."""

    INFO = "INFO"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def level(self) -> int:
        """Numeric rank for threshold comparisons (INFO=1, MEDIUM=2, HIGH=3, CRITICAL=4).

        Returns:
            int: Integer ranking from 1 to 4.
        """
        ranks = {"INFO": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        return ranks[self.value]

    def __lt__(self, other: object) -> bool:
        """Compare severity ordering based on rank.

        Args:
            other: Other object to compare against.

        Returns:
            bool: True if this severity rank is less than the other rank.
        """
        if isinstance(other, Severity):
            return self.level < other.level
        if isinstance(other, str):
            try:
                return self.level < Severity(other.upper()).level
            except ValueError:
                return NotImplemented
        return NotImplemented

    def __le__(self, other: object) -> bool:
        """Compare severity ordering based on rank.

        Args:
            other: Other object to compare against.

        Returns:
            bool: True if this severity rank is less than or equal to the other rank.
        """
        if isinstance(other, Severity):
            return self.level <= other.level
        if isinstance(other, str):
            try:
                return self.level <= Severity(other.upper()).level
            except ValueError:
                return NotImplemented
        return NotImplemented

    def __gt__(self, other: object) -> bool:
        """Compare severity ordering based on rank.

        Args:
            other: Other object to compare against.

        Returns:
            bool: True if this severity rank is greater than the other rank.
        """
        if isinstance(other, Severity):
            return self.level > other.level
        if isinstance(other, str):
            try:
                return self.level > Severity(other.upper()).level
            except ValueError:
                return NotImplemented
        return NotImplemented

    def __ge__(self, other: object) -> bool:
        """Compare severity ordering based on rank.

        Args:
            other: Other object to compare against.

        Returns:
            bool: True if this severity rank is greater than or equal to the other rank.
        """
        if isinstance(other, Severity):
            return self.level >= other.level
        if isinstance(other, str):
            try:
                return self.level >= Severity(other.upper()).level
            except ValueError:
                return NotImplemented
        return NotImplemented

    def __eq__(self, other: object) -> bool:
        """Compare severity equality based on rank or string value.

        Args:
            other: Other object to compare against.

        Returns:
            bool: True if values match.
        """
        if isinstance(other, Severity):
            return self.level == other.level
        if isinstance(other, str):
            return self.value == other.upper()
        return NotImplemented

    def __hash__(self) -> int:
        """Hash method consistent with string equality.

        Returns:
            int: Hash of string value.
        """
        return hash(self.value)


class QueryParameter(BaseModel):
    """SQL query parameter binding."""

    name: str = Field(..., pattern=r"^@.+", description="Parameter name starting with @")
    value: Any = Field(..., description="Parameter literal value")


ScalarPartitionKey = str | int | float | bool
PartitionKeyType = ScalarPartitionKey | list[ScalarPartitionKey] | None


class QueryDefinition(BaseModel):
    """Specification of an individual SQL query in a workload."""

    id: str = Field(..., description="Unique identifier for the query")
    query: str = Field(..., description="Cosmos DB SQL query statement")
    parameters: list[QueryParameter] = Field(
        default_factory=list, description="Bound parameters for parameterized queries"
    )
    partition_key: PartitionKeyType = Field(
        default=None,
        description=(
            "Partition key scalar or list of 1 to 3 scalars for hierarchical partition keys"
        ),
    )

    @field_validator("partition_key", mode="before")
    @classmethod
    def validate_partition_key(cls, v: Any) -> PartitionKeyType:
        """Validate partition key scalar or hierarchical list constraints.

        Args:
            v: The partition key value to validate.

        Returns:
            PartitionKeyType: Validated partition key or None.

        Raises:
            ValueError: If the partition key format or constraints are violated.
        """
        if v is None:
            return None

        # Check single scalar (rejecting collections like list/dict/set/tuple)
        if isinstance(v, (str, int, float, bool)) and not isinstance(v, (list, dict, set, tuple)):
            return v

        if isinstance(v, list):
            if len(v) == 0:
                raise ValueError("partition_key list cannot be empty")
            if len(v) > 3:
                raise ValueError("partition_key list cannot exceed 3 elements")

            for item in v:
                if item is None:
                    raise ValueError("partition_key list items cannot be null")
                if not isinstance(item, (str, int, float, bool)) or isinstance(
                    item, (list, dict, set, tuple)
                ):
                    item_type = type(item).__name__
                    raise ValueError(
                        "partition_key list items must be primitive scalars "
                        f"(str, int, float, bool), got {item_type}"
                    )
            return v

        raise ValueError(
            f"partition_key must be a scalar, list of 1-3 scalars, or null, got {type(v).__name__}"
        )


class Workload(BaseModel):
    """Root workload parsed from YAML specification file."""

    version: str = Field(default="1", description="Workload schema version")
    database: str | None = Field(default=None, description="Target database name")
    container: str | None = Field(default=None, description="Target container name")
    ru_budget: float | None = Field(
        default=None, ge=0.0, description="Optional maximum cumulative RU limit"
    )
    queries: list[QueryDefinition] = Field(
        ..., min_length=1, description="List of queries to profile"
    )


class IndexUtilization(BaseModel):
    """Cosmos DB index utilization metrics extracted from response headers."""

    utilized_single: list[dict[str, Any]] = Field(
        default_factory=list, description="Utilized single field index paths"
    )
    potential_single: list[dict[str, Any]] = Field(
        default_factory=list, description="Recommended single field index paths"
    )
    utilized_composite: list[dict[str, Any]] = Field(
        default_factory=list, description="Utilized composite index paths"
    )
    potential_composite: list[dict[str, Any]] = Field(
        default_factory=list, description="Recommended composite index paths"
    )


class QueryCost(BaseModel):
    """Captured runtime cost metrics for an individual query execution."""

    query_id: str = Field(..., description="Reference to QueryDefinition.id")
    query_text: str = Field(..., description="Query SQL statement executed")
    request_charge: float = Field(..., ge=0.0, description="Request Units consumed")
    latency_ms: float = Field(..., ge=0.0, description="Server execution latency in ms")
    documents_scanned: int = Field(..., ge=0, description="Number of documents scanned")
    documents_returned: int = Field(..., ge=0, description="Number of documents returned")
    is_cross_partition: bool = Field(
        ..., description="Whether execution fanned out across multiple partitions"
    )
    is_partial: bool = Field(
        default=False, description="Whether execution was terminated early by budget guard"
    )
    index_metrics: IndexUtilization | None = Field(
        default=None, description="Index metrics extracted from response headers"
    )
    error_message: str | None = Field(
        default=None, description="Error message if query execution failed"
    )
    activity_id: str | None = Field(
        default=None, description="Cosmos DB activity ID for the request"
    )


class Finding(BaseModel):
    """Diagnostic issue detected on an executed query."""

    rule_id: str = Field(..., description="Unique rule code, e.g. QL001")
    rule_name: str = Field(..., description="Human-readable rule title")
    severity: Severity = Field(..., description="Severity classification")
    summary: str = Field(..., description="Actionable summary of the diagnostic finding")
    evidence: dict[str, Any] = Field(
        default_factory=dict, description="Quantitative proof data for the finding"
    )


class QueryResultSummary(BaseModel):
    """Consolidated summary combining query cost with diagnostic findings."""

    cost: QueryCost = Field(..., description="Execution cost metrics")
    findings: list[Finding] = Field(
        default_factory=list, description="Diagnostic findings detected for this query"
    )


class WorkloadRunSummary(BaseModel):
    """Aggregate run summary artifact produced by QueryLens."""

    timestamp: str = Field(..., description="Execution start timestamp in ISO 8601 format")
    database: str = Field(..., description="Target database name")
    container: str = Field(..., description="Target container name")
    total_queries: int = Field(..., ge=0, description="Total queries defined in workload")
    completed_queries: int = Field(..., ge=0, description="Number of queries successfully executed")
    total_ru_consumed: float = Field(..., ge=0.0, description="Cumulative Request Units consumed")
    ru_budget: float | None = Field(
        default=None, description="Workload cumulative RU limit if specified"
    )
    budget_exceeded: bool = Field(
        ..., description="Whether run was halted due to exceeding RU budget"
    )
    max_item_count: int = Field(
        default=100, ge=1, description="Cosmos DB query page batch size (max_item_count)"
    )
    results: list[QueryResultSummary] = Field(
        default_factory=list, description="Queries ranked descending by Request Units"
    )
