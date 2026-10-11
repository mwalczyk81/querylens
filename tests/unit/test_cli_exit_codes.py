"""Unit tests verifying the CLI exit code contract (T013).

Ensures deterministic exit codes:
- 0: Success
- 1: Validation / usage error
- 3: Connection / Resource not found error
- 5: Authentication / Authorization failure
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.cosmos.exceptions import (
    CosmosClientTimeoutError,
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
)
from click.testing import CliRunner

from querylens.adapters.cosmos import BudgetExceededError
from querylens.cli import cli, map_adapter_exception
from querylens.model import QueryCost


class TestCliExitCodesContract:
    """Tests strictly verifying exit codes 0, 1, 3, and 5."""

    def test_version_option_reports_installed_version(self) -> None:
        """Verify querylens --version reports the package metadata version and exits 0."""
        from importlib.metadata import version

        expected_version = version("querylens")
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert f"version {expected_version}" in result.output

    def test_exit_code_1_missing_file(self) -> None:
        """Exit code 1 on non-existent workload file."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "non_existent_workload.yaml"])
        assert result.exit_code == 1
        assert "Error" in result.output or "error" in result.output

    def test_exit_code_1_invalid_yaml(self, tmp_path: Path) -> None:
        """Exit code 1 on malformed YAML syntax."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("invalid: yaml: [unclosed", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(bad_yaml)])
        assert result.exit_code == 1

    def test_exit_code_1_invalid_partition_key(self, tmp_path: Path) -> None:
        """Exit code 1 on partition_key validation error (e.g. empty list)."""
        workload_yaml = tmp_path / "bad_pk.yaml"
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

    def test_exit_code_1_missing_database_or_container(self, tmp_path: Path) -> None:
        """Exit code 1 when target database or container is missing from file, options, and env."""
        workload_yaml = tmp_path / "no_target.yaml"
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
    def test_exit_code_0_success(self, mock_get_adapter: MagicMock, tmp_path: Path) -> None:
        """Exit code 0 when all queries execute successfully."""
        workload_yaml = tmp_path / "valid.yaml"
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
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 3 on network unreachable or host resolution failure."""
        workload_yaml = tmp_path / "valid.yaml"
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
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 3 on CosmosResourceNotFoundError (database/container not found)."""
        workload_yaml = tmp_path / "valid.yaml"
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
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 5 on ClientAuthenticationError."""
        workload_yaml = tmp_path / "valid.yaml"
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
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 5 on HTTP 403 Forbidden (missing Cosmos DB Data Reader role)."""
        workload_yaml = tmp_path / "valid.yaml"
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
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Verify --json produces valid JSON stdout and option flags apply cleanly."""
        import json

        workload_yaml = tmp_path / "valid.yaml"
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

    def test_exit_code_1_yaml_not_a_mapping(self, tmp_path: Path) -> None:
        """Exit code 1 when YAML root is a list or scalar instead of a dict."""
        workload_yaml = tmp_path / "list_root.yaml"
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
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Render partial results table before exiting with code 3 on mid-run connection error."""
        workload_yaml = tmp_path / "workload.yaml"
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
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Render partial JSON summary before exiting with code 3 on mid-run server error."""
        workload_yaml = tmp_path / "workload.yaml"
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
    def test_exit_code_3_rate_limit_429(self, mock_get_adapter: MagicMock, tmp_path: Path) -> None:
        """Exit code 3 with rate limit message when Cosmos DB returns HTTP 429."""
        workload_yaml = tmp_path / "workload.yaml"
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

    @patch("querylens.cli.get_adapter")
    def test_exit_code_1_on_query_execution_error(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 1 after rendering report when a query ends with error_message."""
        workload_yaml = tmp_path / "workload.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q_err"
    query: "SELECT FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q_err",
                query_text="SELECT FROM c",
                request_charge=0.0,
                latency_ms=0.0,
                documents_scanned=0,
                documents_returned=0,
                is_cross_partition=False,
                error_message="HTTP 400: Syntax error near FROM",
            )
        ]
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner(env={"COLUMNS": "120"})
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 1
        assert "[ERROR]" in result.output
        assert "HTTP 400: Syntax error near FROM" in result.output

    @patch("querylens.cli.get_adapter")
    def test_exit_code_precedence_budget_exceeded_over_fail_on(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Budget exceeded (exit 2) takes precedence over --fail-on gate breach (exit 4)."""
        workload_yaml = tmp_path / "workload.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
ru_budget: 50.0
queries:
  - id: "q1"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        cost = QueryCost(
            query_id="q1",
            query_text="SELECT * FROM c",
            request_charge=60.0,  # Breaches budget (50.0) and triggers QL001 (>50.0)
            latency_ms=20.0,
            documents_scanned=100,
            documents_returned=100,
            is_cross_partition=False,
        )
        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = BudgetExceededError(cost, 60.0)
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                str(workload_yaml),
                "--endpoint",
                "https://localhost:8081/",
                "--fail-on",
                "high",
            ],
        )
        assert result.exit_code == 2

    @patch("querylens.cli.get_adapter")
    def test_exit_code_precedence_budget_exceeded_over_query_error(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Budget exceeded (exit 2) takes precedence over query execution error (exit 1)."""
        workload_yaml = tmp_path / "workload.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
ru_budget: 50.0
queries:
  - id: "q_err"
    query: "SELECT FROM c"
  - id: "q_heavy"
    query: "SELECT * FROM c"
""",
            encoding="utf-8",
        )

        def mock_collect(w: Any) -> Any:
            yield QueryCost(
                query_id="q_err",
                query_text="SELECT FROM c",
                request_charge=0.0,
                latency_ms=0.0,
                documents_scanned=0,
                documents_returned=0,
                is_cross_partition=False,
                error_message="HTTP 400: Syntax error",
            )
            partial = QueryCost(
                query_id="q_heavy",
                query_text="SELECT * FROM c",
                request_charge=60.0,
                latency_ms=20.0,
                documents_scanned=100,
                documents_returned=100,
                is_cross_partition=False,
            )
            raise BudgetExceededError(partial, 60.0)

        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = mock_collect
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 2

    @patch("querylens.cli.get_adapter")
    def test_exit_code_precedence_fail_on_over_query_error(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Fail-on gate breach (exit 4) takes precedence over query execution error (exit 1)."""
        workload_yaml = tmp_path / "workload.yaml"
        workload_yaml.write_text(
            """
version: "1"
database: "db"
container: "c"
queries:
  - id: "q_heavy"
    query: "SELECT * FROM c"
  - id: "q_err"
    query: "SELECT FROM c"
""",
            encoding="utf-8",
        )

        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q_heavy",
                query_text="SELECT * FROM c",
                request_charge=250.0,  # CRITICAL severity finding
                latency_ms=50.0,
                documents_scanned=100,
                documents_returned=100,
                is_cross_partition=False,
            ),
            QueryCost(
                query_id="q_err",
                query_text="SELECT FROM c",
                request_charge=0.0,
                latency_ms=0.0,
                documents_scanned=0,
                documents_returned=0,
                is_cross_partition=False,
                error_message="HTTP 400: Syntax error",
            ),
        ]
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                str(workload_yaml),
                "--endpoint",
                "https://localhost:8081/",
                "--fail-on",
                "critical",
            ],
        )
        assert result.exit_code == 4

    # -------------------------------------------------------------------------
    # Regression Tests: Adapter Initialization & Collection Error Mapping (T013)
    # -------------------------------------------------------------------------

    REALISTIC_COSMOS_RBAC_403_MESSAGE = (
        '(Forbidden) Message: {"Errors":["The requested operation cannot be performed '
        "because the principal does not have the required data plane action "
        "'Microsoft.DocumentDB/databaseAccounts/readMetadata'.\"]}\r\n"
        "ActivityId: 6f846d0c-60db-4fc4-ba65-c33503aa2b1d, Request URI: "
        "rntbd://cdb-ms-prod-eastus1-fd42.documents.azure.com:14000/apps/db/services/cdb/partitions/0/replicas/1p/,\r\n"
        "Microsoft.Azure.Cosmos.Direct/2.14.0"
    )
    HINT_403 = (
        "The identity needs the Cosmos DB Built-in Data Reader data-plane "
        "role on this account (Azure control-plane roles do not grant data access)."
    )
    VALID_WORKLOAD_YAML = (
        'version: "1"\n'
        'database: "db"\n'
        'container: "c"\n'
        "queries:\n"
        '  - id: "q1"\n'
        '    query: "SELECT * FROM c"\n'
    )

    @patch("querylens.cli.get_adapter")
    def test_init_adapter_error_403_rbac_exits_5_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 5 with clean message and role hint when adapter init raises HTTP 403 RBAC."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_get_adapter.side_effect = CosmosHttpResponseError(
            status_code=403, message=self.REALISTIC_COSMOS_RBAC_403_MESSAGE
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert self.HINT_403 in result.output
        assert "Authentication / Authorization failure (HTTP 403)" in result.output
        assert "Microsoft.DocumentDB/databaseAccounts/readMetadata" in result.output
        assert "Traceback" not in result.output
        assert "ActivityId: 6f846d0c" not in result.output
        assert "Microsoft.Azure.Cosmos.Direct" not in result.output
        assert "rntbd://" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_init_adapter_error_401_unauthorized_exits_5_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 5 with clean message when adapter init raises HTTP 401 Unauthorized."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_get_adapter.side_effect = CosmosHttpResponseError(
            status_code=401,
            message=(
                '(Unauthorized) Message: {"errors":[{"message":"Invalid MAC signature"}]}\r\n'
                "ActivityId: aid-401"
            ),
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert (
            "Authentication / Authorization failure (HTTP 401): Invalid MAC signature"
            in result.output
        )
        assert "Traceback" not in result.output
        assert "aid-401" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_init_adapter_error_client_authentication_exits_5_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 5 with clean message when adapter init raises ClientAuthenticationError."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_get_adapter.side_effect = ClientAuthenticationError(
            "DefaultAzureCredential token acquisition failed"
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert (
            "Authentication failure: DefaultAzureCredential token acquisition failed"
            in result.output
        )
        assert "Traceback" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_init_adapter_error_service_request_exits_3_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 3 with clean message when adapter init raises ServiceRequestError."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_get_adapter.side_effect = ServiceRequestError(
            "Failed to establish a new connection: [Errno 111] Connection refused\r\n"
            "ActivityId: aid-srv"
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://invalid-host:443/"],
        )
        assert result.exit_code == 3
        assert (
            "Connection error: Failed to establish a new connection: [Errno 111] Connection refused"
            in result.output
        )
        assert "Traceback" not in result.output
        assert "aid-srv" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_init_adapter_error_404_not_found_exits_3_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 3 with clean message when adapter init raises HTTP 404."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_get_adapter.side_effect = CosmosHttpResponseError(
            status_code=404,
            message=(
                '(NotFound) Message: {"errors":[{"message":"Resource Not Found"}]}\r\n'
                "ActivityId: aid-404"
            ),
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 3
        assert "Connection error: Resource not found: Resource Not Found" in result.output
        assert "Traceback" not in result.output
        assert "aid-404" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_collect_error_403_rbac_exits_5_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 5 with clean message and role hint when collect raises HTTP 403 RBAC."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = CosmosHttpResponseError(
            status_code=403, message=self.REALISTIC_COSMOS_RBAC_403_MESSAGE
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert self.HINT_403 in result.output
        assert "Authentication / Authorization failure (HTTP 403)" in result.output
        assert "Microsoft.DocumentDB/databaseAccounts/readMetadata" in result.output
        assert "Traceback" not in result.output
        assert "ActivityId: 6f846d0c" not in result.output
        assert "Microsoft.Azure.Cosmos.Direct" not in result.output
        assert "rntbd://" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_collect_error_401_unauthorized_exits_5_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 5 with clean message when collect raises HTTP 401 Unauthorized."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = CosmosHttpResponseError(
            status_code=401,
            message=(
                '(Unauthorized) Message: {"errors":[{"message":"Invalid MAC signature"}]}\r\n'
                "ActivityId: aid-401"
            ),
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert (
            "Authentication / Authorization failure (HTTP 401): Invalid MAC signature"
            in result.output
        )
        assert "Traceback" not in result.output
        assert "aid-401" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_collect_error_client_authentication_exits_5_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 5 with clean message when collect raises ClientAuthenticationError."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = ClientAuthenticationError(
            "DefaultAzureCredential token acquisition failed"
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert (
            "Authentication failure: DefaultAzureCredential token acquisition failed"
            in result.output
        )
        assert "Traceback" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_collect_error_service_request_exits_3_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 3 with clean message when collect raises ServiceRequestError."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = ServiceRequestError(
            "Failed to establish a new connection: [Errno 111] Connection refused\r\n"
            "ActivityId: aid-srv"
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://invalid-host:443/"],
        )
        assert result.exit_code == 3
        assert (
            "Connection error: Failed to establish a new connection: [Errno 111] Connection refused"
            in result.output
        )
        assert "Traceback" not in result.output
        assert "aid-srv" not in result.output

    @patch("querylens.cli.get_adapter")
    def test_collect_error_404_not_found_exits_3_without_traceback(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 3 with clean message when collect raises HTTP 404."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_adapter = MagicMock()
        mock_adapter.collect.side_effect = CosmosHttpResponseError(
            status_code=404,
            message=(
                '(NotFound) Message: {"errors":[{"message":"Resource Not Found"}]}\r\n'
                "ActivityId: aid-404"
            ),
        )
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 3
        assert "Connection error: Resource not found: Resource Not Found" in result.output
        assert "Traceback" not in result.output
        assert "aid-404" not in result.output

    @patch("querylens.adapters.cosmos.CosmosClient")
    def test_init_adapter_end_to_end_cosmos_client_raises_403(
        self, mock_cosmos_client: MagicMock, tmp_path: Path
    ) -> None:
        """End-to-end: CosmosClient constructor raises HTTP 403, exits 5 without traceback."""
        workload_yaml = tmp_path / "valid.yaml"
        workload_yaml.write_text(self.VALID_WORKLOAD_YAML, encoding="utf-8")
        mock_cosmos_client.side_effect = CosmosHttpResponseError(
            status_code=403, message=self.REALISTIC_COSMOS_RBAC_403_MESSAGE
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://myaccount.documents.azure.com:443/"],
        )
        assert result.exit_code == 5
        assert self.HINT_403 in result.output
        assert "Authentication / Authorization failure (HTTP 403)" in result.output
        assert "Traceback" not in result.output

    def test_map_adapter_exception_direct_mappings(self) -> None:
        """Directly verify map_adapter_exception returns expected (message, exit_code) pairs."""
        # 1. ClientAuthenticationError -> 5
        msg, code = map_adapter_exception(
            ClientAuthenticationError("Auth token expired\nMore details")
        )
        assert code == 5
        assert msg == "Authentication failure: Auth token expired"

        # 2. HTTP 403 -> 5 with hint
        exc_403 = CosmosHttpResponseError(
            status_code=403, message=self.REALISTIC_COSMOS_RBAC_403_MESSAGE
        )
        msg, code = map_adapter_exception(exc_403)
        assert code == 5
        assert self.HINT_403 in msg
        assert "Authentication / Authorization failure (HTTP 403)" in msg
        assert "ActivityId" not in msg

        # 3. HTTP 401 -> 5
        exc_401 = CosmosHttpResponseError(
            status_code=401,
            message='(Unauthorized) Message: {"errors":[{"message":"Bad key"}]}',
        )
        msg, code = map_adapter_exception(exc_401)
        assert code == 5
        assert msg == "Authentication / Authorization failure (HTTP 401): Bad key"

        # 4. HTTP 404 -> 3
        exc_404 = CosmosResourceNotFoundError(status_code=404, message="Container missing")
        msg, code = map_adapter_exception(exc_404)
        assert code == 3
        assert msg == "Connection error: Resource not found: Container missing"

        # 5. HTTP 429 -> 3
        exc_429 = CosmosHttpResponseError(status_code=429, message="Rate limited")
        msg, code = map_adapter_exception(exc_429)
        assert code == 3
        assert "Rate limit exceeded (HTTP 429 RequestRateTooLarge): Rate limited" in msg

        # 6. HTTP 500 -> 3
        exc_500 = CosmosHttpResponseError(status_code=500, message="Internal error")
        msg, code = map_adapter_exception(exc_500)
        assert code == 3
        assert msg == "Cosmos server error (HTTP 500): Internal error"

        # 7. ServiceRequestError -> 3
        msg, code = map_adapter_exception(ServiceRequestError("Host unreachable"))
        assert code == 3
        assert msg == "Connection error: Host unreachable"

        # 8. CosmosClientTimeoutError -> 3
        msg, code = map_adapter_exception(CosmosClientTimeoutError("Timed out"))
        assert code == 3
        assert msg == "Connection error: Timed out"
