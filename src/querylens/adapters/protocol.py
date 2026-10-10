"""Database adapter protocol contract."""

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from querylens.model import QueryCost, Workload


@runtime_checkable
class DatabaseAdapter(Protocol):
    """Protocol interface defining database profiler adapters."""

    def collect(self, workload: Workload) -> Iterator[QueryCost]:
        """Execute workload queries and yield captured QueryCost metrics.

        Args:
            workload: The workload definition containing queries to profile.

        Yields:
            QueryCost: Captured cost and performance metrics for each query.
        """
        ...
