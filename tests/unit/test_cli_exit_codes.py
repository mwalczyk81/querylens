"""Unit tests verifying the CLI exit code contract (T013).

Ensures deterministic exit codes:
- 0: Success
- 1: Validation / usage error
- 3: Connection / Resource not found error
- 5: Authentication / Authorization failure
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from click.testing import CliRunner

from querylens.cli import cli
from querylens.model import QueryCost


class TestCliExitCodesContract:
    """Tests strictly verifying exit codes 0, 1, 3, and 5."""

    def test_exit_code_1_missing_file(self) -> None:
        """Exit code 1 on non-existent workload file."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "non_existent_workload.yaml"])
        assert result.exit_code == 1
        assert "Error" in result.output or "error" in result.output

    def test_exit_code_1_invalid_yaml(self, tmp_path: pytest.TempPathFactory) -> None:
        """Exit code 1 on malformed YAML syntax."""
        bad_yaml = tmp_path / "bad.yaml"  # pyrefly: ignore
        bad_yaml.write_text("invalid: yaml: [unclosed", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(bad_yaml)])
        assert result.exit_code == 1

    def test_exit_code_1_invalid_partition_key(self, tmp_path: pytest.TempPathFactory) -> None:
        """Exit code 1 on partition_key validation error (e.g. empty list)."""
        workload_yaml = tmp_path / "bad_pk.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
    partition_key: []
""",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 1
        assert "partition_key list cannot be empty" in result.output

    def test_exit_code_1_missing_database_or_container(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 1 when target database or container is missing from file, options, and env."""
        workload_yaml = tmp_path / "no_target.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 1
        assert "database" in result.output.lower() or "container" in result.output.lower()

    def test_exit_code_1_unknown_flag(self) -> None:
        """Exit code 1 on CLI usage error: unknown command-line option."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "workload.yaml", "--non-existent-option"])
        assert result.exit_code == 1
        assert "no such option" in result.output.lower() or "error" in result.output.lower()

    def test_exit_code_1_missing_argument(self) -> None:
        """Exit code 1 on CLI usage error: missing required argument."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run"])
        assert result.exit_code == 1
        assert "missing argument" in result.output.lower() or "error" in result.output.lower()

    @patch("querylens.cli.get_adapter")
    def test_exit_code_0_success(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 0 when all queries execute successfully."""
        workload_yaml = tmp_path / "valid.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c",
                request_charge=5.0,
                latency_ms=10.0,
                documents_scanned=10,
                documents_returned=10,
                is_cross_partition=False,
            )
        ]
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 0

    @patch("querylens.cli.get_adapter")
    def test_exit_code_3_connection_error(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 3 on network unreachable or host resolution failure."""
        workload_yaml = tmp_path / "valid.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = ServiceRequestError(
            "Failed to establish a new connection"
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://invalid-host:443/"],
        )
        assert result.exit_code == 3
        assert "Connection error" in result.output

    @patch("querylens.cli.get_adapter")
    def test_exit_code_3_container_not_found(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 3 on CosmosResourceNotFoundError (database/container not found)."""
        workload_yaml = tmp_path / "valid.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "nonexistent"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = CosmosResourceNotFoundError(
            status_code=404, message="Resource Not Found"
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 3

    @patch("querylens.cli.get_adapter")
    def test_exit_code_5_auth_credential_error(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 5 on ClientAuthenticationError."""
        workload_yaml = tmp_path / "valid.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = ClientAuthenticationError("Authentication token failed")
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert "Authentication" in result.output

    @patch("querylens.cli.get_adapter")
    def test_exit_code_5_auth_http_403_forbidden(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 5 on HTTP 403 Forbidden (missing Cosmos DB Data Reader role)."""
        workload_yaml = tmp_path / "valid.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = CosmosHttpResponseError(
            status_code=403, message="Forbidden: User lacks Data Reader role"
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert "Authentication" in result.output or "Authorization" in result.output

    @patch("querylens.cli.get_adapter")
    def test_exit_code_0_with_json_and_options(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Verify --json produces valid JSON stdout and option flags apply cleanly."""
        import json

        workload_yaml = tmp_path / "valid.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c",
                request_charge=10.0,
                latency_ms=5.0,
                documents_scanned=20,
                documents_returned=5,
                is_cross_partition=False,
            )
        ]
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--debug",
                "run",
                str(workload_yaml),
                "--endpoint",
                "https://localhost:8081/",
                "--database",
                "custom-db",
                "--container",
                "custom-c",
                "--ru-budget",
                "250.0",
                "--max-item-count",
                "50",
                "--high-ru-warn",
                "40.0",
                "--high-ru-crit",
                "150.0",
                "--scan-gap-warn",
                "8.0",
                "--scan-gap-crit",
                "80.0",
                "--json",
            ],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed["database"] == "custom-db"
        assert parsed["container"] == "custom-c"
        assert parsed["total_ru_consumed"] == 10.0
        assert len(parsed["results"]) == 1

    def test_exit_code_1_yaml_not_a_mapping(self, tmp_path: pytest.TempPathFactory) -> None:
        """Exit code 1 when YAML root is a list or scalar instead of a dict."""
        workload_yaml = tmp_path / "list_root.yaml"  # pyrefly: ignore
        workload_yaml.write_text("- item1\n- item2\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 1
        assert "must be a mapping" in result.output

    @patch("querylens.cli.get_adapter")
    def test_exit_code_3_mid_run_connection_error_renders_partial(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Render partial results table before exiting with code 3 on mid-run connection error."""
        workload_yaml = tmp_path / "workload.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q1"
    query: "SELECT * FROM c WHERE c.id = '1'"
  - id: "q2"
    query: "SELECT * FROM c WHERE c.id = '2'"
""",
            encoding="utf-8",
        )

        def mock_collect(w: Any) -> Any:
            yield QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c WHERE c.id = '1'",
                request_charge=4.2,
                latency_ms=8.0,
                documents_scanned=1,
                documents_returned=1,
                is_cross_partition=False,
            )
            raise ServiceRequestError("Network dropped mid-run")

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = mock_collect
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 3
        assert "q1" in result.output
        assert "Connection error: Network dropped mid-run" in result.output

    @patch("querylens.cli.get_adapter")
    def test_exit_code_3_mid_run_connection_error_renders_partial_json(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Render partial JSON summary before exiting with code 3 on mid-run server error."""
        workload_yaml = tmp_path / "workload.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q1"
    query: "SELECT * FROM c WHERE c.id = '1'"
  - id: "q2"
    query: "SELECT * FROM c WHERE c.id = '2'"
""",
            encoding="utf-8",
        )

        def mock_collect(w: Any) -> Any:
            yield QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c WHERE c.id = '1'",
                request_charge=4.2,
                latency_ms=8.0,
                documents_scanned=1,
                documents_returned=1,
                is_cross_partition=False,
            )
            raise CosmosHttpResponseError(status_code=503, message="Service Unavailable")

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = mock_collect
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/", "--json"],
        )
        assert result.exit_code == 3
        # JSON is printed before the error message; check it contains partial summary
        assert '"completed_queries": 1' in result.output
        assert '"total_queries": 2' in result.output
        assert "Cosmos server error (HTTP 503)" in result.output

    @patch("querylens.cli.get_adapter")
    def test_exit_code_3_rate_limit_429(
        self, mock_get_adapter: MagicMock, tmp_path: pytest.TempPathFactory
    ) -> None:
        """Exit code 3 with rate limit message when Cosmos DB returns HTTP 429."""
        workload_yaml = tmp_path / "workload.yaml"  # pyrefly: ignore
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = CosmosHttpResponseError(
            status_code=429, message="Request rate is large"
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 3
        assert "Rate limit exceeded (HTTP 429 RequestRateTooLarge)" in result.output
