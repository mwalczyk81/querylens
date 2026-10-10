"""Unit tests for DatabaseAdapter protocol."""

from collections.abc import Iterator

from querylens.adapters.protocol import DatabaseAdapter
from querylens.model import QueryCost, Workload


class DummyAdapter:
    """Mock implementation conforming to DatabaseAdapter."""

    def collect(self, workload: Workload) -> Iterator[QueryCost]:
        """Yield empty iterator."""
        return iter([])


class IncompleteAdapter:
    """Mock implementation missing collect method."""

    def other_method(self) -> None:
        """Irrelevant method."""
        pass


def test_database_adapter_protocol() -> None:
    """Verify isinstance checks with runtime_checkable DatabaseAdapter."""
    adapter = DummyAdapter()
    assert isinstance(adapter, DatabaseAdapter)

    incomplete = IncompleteAdapter()
    assert not isinstance(incomplete, DatabaseAdapter)
