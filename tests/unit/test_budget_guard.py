"""Unit tests for per-page RU budget tracking and mid-query abort (T027)."""

import json
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from querylens.adapters.cosmos import BudgetExceededError, CosmosAdapter
from querylens.cli import cli
from querylens.config import Settings
from querylens.model import QueryDefinition, Workload


class TestBudgetGuard:
    """Tests covering budget containment, mid-query abort, and exit code 2."""

    def test_per_page_budget_abort_in_adapter(self) -> None:
        """Abort pagination loop on the exact page exceeding cumulative budget."""
        settings = Settings(
            endpoint="https://localhost:8081/",
            database="testdb",
            container="testc",
            ru_budget=7.0,
        )

        with patch("querylens.adapters.cosmos.CosmosClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_db = MagicMock()
            mock_container = MagicMock()
            mock_client.get_database_client.return_value = mock_db
            mock_db.get_container_client.return_value = mock_container

            # Simulate 3 pages with 4 RUs each (page 1: 4 RUs, page 2: 4 RUs -> 8 RUs > 7 RUs limit)
            pages_yielded = 0

            def fake_query_items(*args: object, **kwargs: object) -> MagicMock:
                hook = kwargs.get("response_hook")

                def fake_by_page() -> Iterator[list[dict[str, str]]]:
                    nonlocal pages_yielded
                    for page_idx in range(1, 4):
                        if callable(hook):
                            hook(
                                {
                                    "x-ms-request-charge": "4.0",
                                    "x-ms-documentdb-query-metrics": (
                                        "retrievedDocumentCount=10;outputDocumentCount=1;"
                                        "totalExecutionTimeInMs=5.0"
                                    ),
                                },
                                {},
                            )
                        pages_yielded += 1
                        yield [{"id": f"item-{page_idx}"}]

                mock_paged = MagicMock()
                mock_paged.by_page.side_effect = fake_by_page
                return mock_paged

            mock_container.query_items.side_effect = fake_query_items

            adapter = CosmosAdapter(settings)
            workload = Workload(
                database="testdb",
                container="testc",
                queries=[
                    QueryDefinition(id="q1", query="SELECT * FROM c"),
                    QueryDefinition(id="q2", query="SELECT * FROM c WHERE c.active = true"),
                ],
            )

            with pytest.raises(BudgetExceededError) as exc_info:
                list(adapter.collect(workload))

            err = exc_info.value
            assert err.partial_cost.is_partial is True
            assert err.partial_cost.query_id == "q1"
            assert err.cumulative_ru == 8.0
            assert pages_yielded == 2

    def test_cumulative_ru_equals_request_charge_for_completed_query(self) -> None:
        """Assert cumulative RU calculation matches request_charge for completed query."""
        settings = Settings(
            endpoint="https://localhost:8081/",
            database="testdb",
            container="testc",
            ru_budget=50.0,
        )

        with patch("querylens.adapters.cosmos.CosmosClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_db = MagicMock()
            mock_container = MagicMock()
            mock_client.get_database_client.return_value = mock_db
            mock_db.get_container_client.return_value = mock_container

            def fake_query_items(*args: object, **kwargs: object) -> MagicMock:
                hook = kwargs.get("response_hook")

                def fake_by_page() -> Iterator[list[dict[str, str]]]:
                    for page_idx, ru in enumerate([3.5, 4.5, 2.0], start=1):
                        if callable(hook):
                            hook(
                                {
                                    "x-ms-request-charge": str(ru),
                                    "x-ms-documentdb-query-metrics": (
                                        "retrievedDocumentCount=10;outputDocumentCount=5;"
                                        "totalExecutionTimeInMs=4.0"
                                    ),
                                },
                                {},
                            )
                        yield [{"id": f"item-{page_idx}"}]

                mock_paged = MagicMock()
                mock_paged.by_page.side_effect = fake_by_page
                return mock_paged

            mock_container.query_items.side_effect = fake_query_items

            adapter = CosmosAdapter(settings)
            workload = Workload(
                database="testdb",
                container="testc",
                queries=[QueryDefinition(id="q1", query="SELECT * FROM c")],
            )

            results = list(adapter.collect(workload))
            assert len(results) == 1
            cost = results[0]
            assert cost.request_charge == 10.0
            assert cost.is_partial is False

    def test_per_page_accounting_order_by_or_cross_partition_multiple_headers(self) -> None:
        """Sum all headers received per page in ORDER BY or cross-partition queries."""
        settings = Settings(
            endpoint="https://localhost:8081/",
            database="testdb",
            container="testc",
            ru_budget=8.0,
        )

        with patch("querylens.adapters.cosmos.CosmosClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_db = MagicMock()
            mock_container = MagicMock()
            mock_client.get_database_client.return_value = mock_db
            mock_db.get_container_client.return_value = mock_container

            def fake_query_items(*args: object, **kwargs: object) -> MagicMock:
                hook = kwargs.get("response_hook")

                def fake_by_page() -> Iterator[list[dict[str, str]]]:
                    # Page 1: 3 response headers received
                    if callable(hook):
                        hook({"x-ms-request-charge": "1.5"}, {})
                        hook({"x-ms-request-charge": "2.0"}, {})
                        hook({"x-ms-request-charge": "1.0"}, {})
                    yield [{"id": "item-1"}]

                    # Page 2: 2 response headers received
                    if callable(hook):
                        hook({"x-ms-request-charge": "3.0"}, {})
                        hook({"x-ms-request-charge": "2.5"}, {})
                    yield [{"id": "item-2"}]

                mock_paged = MagicMock()
                mock_paged.by_page.side_effect = fake_by_page
                return mock_paged

            mock_container.query_items.side_effect = fake_query_items

            adapter = CosmosAdapter(settings)
            workload = Workload(
                database="testdb",
                container="testc",
                queries=[
                    QueryDefinition(id="q_order_by", query="SELECT * FROM c ORDER BY c.price")
                ],
            )

            with pytest.raises(BudgetExceededError) as exc_info:
                list(adapter.collect(workload))

            err = exc_info.value
            assert err.partial_cost.is_partial is True
            # All headers across pages were correctly summed (4.5 + 5.5 = 10.0 > 8.0)
            assert err.cumulative_ru == 10.0
            assert err.partial_cost.request_charge == 10.0

    @patch("querylens.cli.get_adapter")
    def test_cli_exit_code_2_on_budget_exceeded(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 2 when budget is exceeded in terminal console mode."""
        workload_yaml = tmp_path / "workload.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
ru_budget: 15.0
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        from querylens.model import QueryCost

        partial_cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=16.5,
            latency_ms=25.0,
            documents_scanned=100,
            documents_returned=5,
            is_cross_partition=False,
            is_partial=True,
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = BudgetExceededError(partial_cost, 16.5)
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 2
        assert "EXCEEDED" in result.output
        assert "Cumulative RU budget ceiling reached" in result.output

    @patch("querylens.cli.get_adapter")
    def test_cli_exit_code_2_with_json_output(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 2 when budget is exceeded in --json output mode."""
        workload_yaml = tmp_path / "workload.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
ru_budget: 15.0
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        from querylens.model import QueryCost

        partial_cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=16.5,
            latency_ms=25.0,
            documents_scanned=100,
            documents_returned=5,
            is_cross_partition=False,
            is_partial=True,
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = BudgetExceededError(partial_cost, 16.5)
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/", "--json"],
        )
        assert result.exit_code == 2
        parsed = json.loads(result.output)
        assert parsed["budget_exceeded"] is True
        assert parsed["results"][0]["cost"]["is_partial"] is True
