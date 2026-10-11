"""Unit tests for querylens discover CLI options, exit codes, and print-kql."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from querylens.cli import cli
from tests.fixtures.synthetic_logs import (
    make_logs_query_result,
    make_sample_preflight_table,
    make_sample_shapes_table,
    make_sample_totals_table,
)


def test_cli_print_kql_success() -> None:
    """Verify --print-kql prints both KQL queries to stdout and exits 0."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--print-kql"],
    )
    assert result.exit_code == 0
    assert "Run each query separately in the Logs editor." in result.output
    assert "Query 1: Top Query Shapes Query" in result.output
    assert "Query 2: Window & Attributed Totals Query" in result.output


def test_cli_print_kql_credential_isolation() -> None:
    """Verify --print-kql never instantiates credentials or makes network calls (T014)."""
    runner = CliRunner()
    with patch(
        "azure.identity.DefaultAzureCredential",
        side_effect=AssertionError("DefaultAzureCredential must not be instantiated"),
    ):
        result = runner.invoke(
            cli,
            [
                "discover",
                "--workspace-id",
                "12345678-1234-1234-1234-123456789abc",
                "--print-kql",
            ],
        )
        assert result.exit_code == 0
        assert "Query 1: Top Query Shapes Query" in result.output


def test_cli_print_kql_check_success() -> None:
    """Verify --print-kql combined with --check prints preflight check query and exits 0."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--check",
            "--print-kql",
        ],
    )
    assert result.exit_code == 0
    assert "Preflight Diagnostic Check Query" in result.output
    assert 'ResourceProvider =~ "MICROSOFT.DOCUMENTDB"' in result.output
    assert "Query 1: Top Query Shapes Query" not in result.output


def test_cli_print_kql_check_credential_isolation() -> None:
    """Verify --print-kql --check never instantiates credentials or makes network calls."""
    runner = CliRunner()
    with patch(
        "azure.identity.DefaultAzureCredential",
        side_effect=AssertionError("DefaultAzureCredential must not be instantiated"),
    ):
        result = runner.invoke(
            cli,
            [
                "discover",
                "--workspace-id",
                "12345678-1234-1234-1234-123456789abc",
                "--check",
                "--print-kql",
            ],
        )
        assert result.exit_code == 0
        assert "Preflight Diagnostic Check Query" in result.output


def test_cli_print_kql_check_with_account_filter() -> None:
    """Verify --print-kql --check includes account filter in query."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--check",
            "--print-kql",
            "--account",
            "my-prod-cosmos",
        ],
    )
    assert result.exit_code == 0
    assert 'endswith "/databaseaccounts/my-prod-cosmos"' in result.output


def test_cli_invalid_workspace_id() -> None:
    """Verify CLI exits 1 on invalid workspace ID."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "--workspace-id", "not-a-uuid"])
    assert result.exit_code == 1
    assert "Invalid workspace ID" in result.output


def test_cli_invalid_account_filter() -> None:
    """Verify CLI exits 1 on invalid account filter."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--account",
            "bad;name",
        ],
    )
    assert result.exit_code == 1
    assert "Invalid account filter" in result.output


def test_cli_invalid_time_window() -> None:
    """Verify CLI exits 1 on invalid time window."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--time-window",
            "invalid",
        ],
    )
    assert result.exit_code == 1
    assert "Invalid time window" in result.output


def test_cli_invalid_top_n() -> None:
    """Verify CLI exits 1 on invalid top_n."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--top",
            "200",
        ],
    )
    assert result.exit_code == 1


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_success_console(mock_get_client: MagicMock) -> None:
    """Verify standard discovery renders Rich table and exits 0."""
    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table()]),
        make_logs_query_result([make_sample_totals_table()]),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 0
    assert "Top Query Shapes" in result.output or "ecommerce" in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_success_json(mock_get_client: MagicMock) -> None:
    """Verify discovery with --json outputs valid JSON and exits 0."""
    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table()]),
        make_logs_query_result([make_sample_totals_table()]),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_ru"] == 1200.0
    assert len(data["results"]) == 2


@patch("querylens.discover_cli.get_logs_client")
def test_cli_silent_zero_guard_exit_1(mock_get_client: MagicMock) -> None:
    """Verify Silent-Zero Guard causes CLI to exit 1 with advice to run --check."""
    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table(shapes=[])]),
        make_logs_query_result(
            [make_sample_totals_table(window_total_ru=500.0, attributed_total_ru=0.0)]
        ),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 1
    assert "--check" in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_connection_error_exit_3(mock_get_client: MagicMock) -> None:
    """Verify network or workspace connection failures exit 3."""
    mock_client = MagicMock()
    from azure.core.exceptions import ServiceRequestError

    mock_client.query_workspace.side_effect = ServiceRequestError("Connection timed out")
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 3


@patch("querylens.discover_cli.get_logs_client")
def test_cli_auth_error_exit_5(mock_get_client: MagicMock) -> None:
    """Verify authentication or RBAC permission failures exit 5."""
    mock_client = MagicMock()
    from azure.core.exceptions import ClientAuthenticationError

    mock_client.query_workspace.side_effect = ClientAuthenticationError("Authentication failed")
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 5


@patch("querylens.discover_cli.get_logs_client")
def test_cli_check_console_success(mock_get_client: MagicMock) -> None:
    """Verify discover --check renders preflight console report and exits 0 (T024)."""
    mock_client = MagicMock()
    mock_client.query_workspace.return_value = make_logs_query_result(
        [make_sample_preflight_table()]
    )
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--check",
        ],
    )
    assert result.exit_code == 0
    assert "Log Analytics Diagnostic Preflight Check" in result.output
    assert "DataPlaneRequests" in result.output
    assert "QueryRuntimeStatistics" in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_check_json_success(mock_get_client: MagicMock) -> None:
    """Verify discover --check --json emits valid JSON and exits 0 (T024)."""
    mock_client = MagicMock()
    mock_client.query_workspace.return_value = make_logs_query_result(
        [make_sample_preflight_table()]
    )
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--check",
            "--json",
        ],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["masked_workspace_id"] == "...9abc"
    assert "DataPlaneRequests" in data["categories_detected"]
    assert "QueryRuntimeStatistics" in data["categories_detected"]
    assert data["row_counts"]["DataPlaneRequests"] == 1500
    assert data["field_coverage"]["querytext_s"] == 1.0


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_empty_results_console(mock_get_client: MagicMock) -> None:
    """Verify empty result set in console mode exits 0 with clean informational message."""
    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table(shapes=[])]),
        make_logs_query_result(
            [
                make_sample_totals_table(
                    window_total_ru=0.0,
                    attributed_total_ru=0.0,
                    total_executions=0,
                )
            ]
        ),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 0
    assert "No query shapes discovered in the specified window matching filters." in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_empty_results_json(mock_get_client: MagicMock) -> None:
    """Verify empty result set with --json exits 0 and outputs valid empty JSON."""
    schema_path = (
        Path(__file__).parents[2]
        / "specs"
        / "002-query-cost-discovery"
        / "contracts"
        / "discover-output-schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table(shapes=[])]),
        make_logs_query_result(
            [
                make_sample_totals_table(
                    window_total_ru=0.0,
                    attributed_total_ru=0.0,
                    total_executions=0,
                )
            ]
        ),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["total_ru"] == 0.0
    assert data["attributed_total_ru"] == 0.0
    assert data["discovered_query_count"] == 0
    assert data["results"] == []

    # Validate against schema
    for field in schema["required"]:
        assert field in data
