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

            def fake_by_page() -> Iterator[list[dict[str, str]]]:
                nonlocal pages_yielded
                for page_idx in range(1, 4):
                    pages_yielded += 1
                    yield [{"id": f"item-{page_idx}"}]

            mock_paged = MagicMock()
            mock_paged.by_page.side_effect = fake_by_page

            page_call_count = 0

            def fake_query_items(*args: object, **kwargs: object) -> MagicMock:
                hook = kwargs.get("response_hook")

                def hook_wrapper(*_h_args: object, **_h_kwargs: object) -> None:
                    nonlocal page_call_count
                    page_call_count += 1
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

                # Call hook once before first page and on each iteration
                hook_wrapper()
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
            assert err.cumulative_ru >= 7.0

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
