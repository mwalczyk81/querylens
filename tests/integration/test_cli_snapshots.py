"""CLI snapshot tests using syrupy for terminal formatting and JSON structure (T031)."""

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from syrupy.assertion import SnapshotAssertion

from querylens.adapters.cosmos import BudgetExceededError
from querylens.cli import cli
from querylens.model import QueryCost


class TestCliSnapshots:
    """Snapshot regression tests for terminal rendering and JSON outputs."""

    @patch("querylens.cli.get_adapter")
    def test_cli_table_snapshot(
        self,
        mock_get_adapter: MagicMock,
        tmp_path: Path,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Capture deterministic snapshot of CLI terminal report."""
        workload_yaml = tmp_path / "workload.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "snap-db"
container: "orders"
ru_budget: 1000.0
queries:
  - id: "q1-fast"
    query: "SELECT * FROM c WHERE c.id = '1'"
  - id: "q2-heavy"
    query: "SELECT * FROM c WHERE c.category = 'books'"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1-fast",
                query_text="SELECT * FROM c WHERE c.id = '1'",
                request_charge=2.8,
                latency_ms=3.5,
                documents_scanned=1,
                documents_returned=1,
                is_cross_partition=False,
            ),
            QueryCost(
                query_id="q2-heavy",
                query_text="SELECT * FROM c WHERE c.category = 'books'",
                request_charge=240.0,
                latency_ms=65.2,
                documents_scanned=1200,
                documents_returned=10,
                is_cross_partition=True,
            ),
        ]
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 0
        assert "QueryLens Workload Profile" in result.output
        assert "Page size: 100" in result.output
        assert "q2-heavy" in result.output
        assert "q1-fast" in result.output
        # Verify ranking: q2-heavy with 240 RUs appears before q1-fast with 2.8 RUs
        assert result.output.index("q2-heavy") < result.output.index("q1-fast")

    @patch("querylens.cli.get_adapter")
    def test_cli_json_snapshot(
        self,
        mock_get_adapter: MagicMock,
        tmp_path: Path,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Capture deterministic snapshot of CLI --json schema output."""
        workload_yaml = tmp_path / "workload.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "snap-db"
container: "orders"
queries:
  - id: "q1-fast"
    query: "SELECT * FROM c WHERE c.id = '1'"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1-fast",
                query_text="SELECT * FROM c WHERE c.id = '1'",
                request_charge=2.8,
                latency_ms=3.5,
                documents_scanned=1,
                documents_returned=1,
                is_cross_partition=False,
            )
        ]
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/", "--json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["database"] == "snap-db"
        assert parsed["container"] == "orders"
        assert parsed["max_item_count"] == 100
        assert parsed["total_queries"] == 1
        assert parsed["completed_queries"] == 1
        assert parsed["results"][0]["cost"]["query_id"] == "q1-fast"

    @patch("querylens.cli.get_adapter")
    def test_cli_error_query_snapshot(
        self,
        mock_get_adapter: MagicMock,
        tmp_path: Path,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Capture deterministic snapshot of CLI table and --json output for query with error."""
        workload_yaml = tmp_path / "workload_error.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "snap-db"
container: "orders"
queries:
  - id: "q_bad_syntax"
    query: "SELECT FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q_bad_syntax",
                query_text="SELECT FROM c",
                request_charge=0.0,
                latency_ms=0.0,
                documents_scanned=0,
                documents_returned=0,
                is_cross_partition=False,
                error_message="HTTP 400: Syntax error, incorrect syntax near 'FROM'.",
                activity_id="00000000-0000-0000-0000-000000000001",
            )
        ]
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner(env={"COLUMNS": "120"})
        # Test table rendering
        table_result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert table_result.exit_code == 1
        assert "[ERROR]" in table_result.output
        assert "HTTP 400: Syntax error, incorrect syntax near 'FROM'." in table_result.output

        # Test JSON rendering
        json_result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/", "--json"],
        )
        assert json_result.exit_code == 1
        parsed = json.loads(json_result.output)
        assert (
            parsed["results"][0]["cost"]["error_message"]
            == "HTTP 400: Syntax error, incorrect syntax near 'FROM'."
        )
        assert parsed["results"][0]["cost"]["activity_id"] == "00000000-0000-0000-0000-000000000001"
        assert parsed["results"][0]["cost"] == snapshot

    @patch("querylens.cli.get_adapter")
    def test_cli_partial_results_table_snapshot(
        self,
        mock_get_adapter: MagicMock,
        tmp_path: Path,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Capture snapshot of CLI terminal report with partial results and budget exceeded."""
        workload_yaml = tmp_path / "workload_partial.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "snap-db"
container: "orders"
ru_budget: 20.0
queries:
  - id: "q_unscoped"
    query: "SELECT * FROM c WHERE c.category = 'books'"
  - id: "q_scoped"
    query: "SELECT * FROM c WHERE c.pk = 'A1'"
    partition_key: "A1"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()

        def fake_collect(_workload: object) -> Iterator[QueryCost]:
            yield QueryCost(
                query_id="q_scoped",
                query_text="SELECT * FROM c WHERE c.pk = 'A1'",
                request_charge=10.0,
                latency_ms=8.0,
                documents_scanned=100,
                documents_returned=30,
                is_cross_partition=False,
                is_partial=True,
                has_partition_key=True,
            )
            raise BudgetExceededError(
                partial_cost=QueryCost(
                    query_id="q_unscoped",
                    query_text="SELECT * FROM c WHERE c.category = 'books'",
                    request_charge=15.0,
                    latency_ms=12.5,
                    documents_scanned=200,
                    documents_returned=50,
                    is_cross_partition=False,
                    is_partial=True,
                    has_partition_key=False,
                ),
                cumulative_ru=25.0,
            )

        mock_adapter.collect.side_effect = fake_collect
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner(env={"COLUMNS": "120"})
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 2
        assert "(partial)" in result.output
        assert "unknown" in result.output
        assert "n/a (partial)" in result.output
        assert "⚠️ Execution aborted: Cumulative RU budget ceiling reached" in result.output
        assert result.output == snapshot

    @patch("querylens.cli.get_adapter")
    def test_cli_partial_no_partition_key_json(
        self,
        mock_get_adapter: MagicMock,
        tmp_path: Path,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Assert JSON emits null for is_cross_partition on partial row without partition key."""
        workload_yaml = tmp_path / "workload_partial_unscoped.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "snap-db"
container: "orders"
ru_budget: 10.0
queries:
  - id: "q_unscoped"
    query: "SELECT * FROM c WHERE c.category = 'books'"
""",
            encoding="utf-8",
        )

        partial_cost = QueryCost(
            query_id="q_unscoped",
            query_text="SELECT * FROM c WHERE c.category = 'books'",
            request_charge=15.0,
            latency_ms=12.5,
            documents_scanned=200,
            documents_returned=50,
            is_cross_partition=None,
            is_partial=True,
            has_partition_key=False,
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = BudgetExceededError(partial_cost, 15.0)
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/", "--json"],
        )
        assert result.exit_code == 2
        parsed = json.loads(result.output)
        cost = parsed["results"][0]["cost"]
        assert cost["query_id"] == "q_unscoped"
        assert cost["is_partial"] is True
        assert cost["has_partition_key"] is False
        assert cost["is_cross_partition"] is None
        assert cost == snapshot
