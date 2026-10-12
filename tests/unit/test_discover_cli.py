"""Unit tests for querylens discover CLI options, exit codes, and print-kql."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
)
from click.testing import CliRunner

from querylens.cli import cli
from tests.fixtures.synthetic_logs import (
    make_logs_query_result,
    make_sample_preflight_table,
    make_sample_preflight_table_with_unscoped_aad_guid,
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
    """Verify CLI exits 1 on invalid workspace ID with clean message and no pydantic dump."""
    runner = CliRunner()
    result = runner.invoke(cli, ["discover", "--workspace-id", "not-a-uuid"])
    assert result.exit_code == 1
    assert "Invalid workspace ID" in result.output
    assert "ValidationError" not in result.output


def test_cli_invalid_account_filter() -> None:
    """Verify CLI exits 1 on invalid account filter with clean message and no pydantic dump."""
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
    assert "ValidationError" not in result.output


def test_cli_invalid_time_window() -> None:
    """Verify CLI exits 1 on invalid time window with clean message and no pydantic dump."""
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
    assert "ValidationError" not in result.output


def test_cli_invalid_top_n_below_min() -> None:
    """Verify CLI exits 1 with range message when --top is below 1."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--top",
            "0",
        ],
    )
    assert result.exit_code == 1
    assert "0 is not in the range 1<=x<=100" in result.output
    assert "ValidationError" not in result.output


def test_cli_invalid_top_n_above_max() -> None:
    """Verify CLI exits 1 with range message when --top is above 100."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--top",
            "101",
        ],
    )
    assert result.exit_code == 1
    assert "101 is not in the range 1<=x<=100" in result.output
    assert "ValidationError" not in result.output


def test_cli_invalid_timeout_below_min() -> None:
    """Verify CLI exits 1 with range message when --timeout is below 10."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--timeout",
            "5",
        ],
    )
    assert result.exit_code == 1
    assert "5 is not in the range 10<=x<=600" in result.output
    assert "ValidationError" not in result.output


def test_cli_invalid_timeout_above_max() -> None:
    """Verify CLI exits 1 with range message when --timeout is above 600."""
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "discover",
            "--workspace-id",
            "12345678-1234-1234-1234-123456789abc",
            "--timeout",
            "601",
        ],
    )
    assert result.exit_code == 1
    assert "601 is not in the range 10<=x<=600" in result.output
    assert "ValidationError" not in result.output


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


@patch("querylens.discover_cli.get_logs_client")
def test_cli_check_internal_consistency_error_exit_1(mock_get_client: MagicMock) -> None:
    """Verify --check surfaces InternalConsistencyError cleanly and exits 1 with no traceback."""
    mock_client = MagicMock()
    mock_client.query_workspace.return_value = make_logs_query_result(
        [make_sample_preflight_table_with_unscoped_aad_guid()]
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
    assert result.exit_code == 1
    assert "Internal consistency error:" in result.output
    assert "aadPrincipalId_g" in result.output
    normalized = " ".join(result.output.split())
    assert (
        "This is a bug in querylens; please report it with the output of 'discover --check'"
        in normalized
    )
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_internal_consistency_error_exit_1(mock_get_client: MagicMock) -> None:
    """Verify discovery surfaces InternalConsistencyError cleanly and exits 1 with no traceback."""
    mock_client = MagicMock()
    shapes = [
        {
            "ql_db_name": "db",
            "ql_coll_name": "coll",
            "ql_shape_id": "shape_1",
            "ql_sample_text": "SELECT * FROM c",
            "ql_execution_count": 10,
            "ql_total_ru": 1500.0,
            "ql_max_ru": 150.0,
            "ql_total_returned_rows": 100.0,
            "ql_throttled_count": 0,
        }
    ]
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table(shapes=shapes)]),
        make_logs_query_result(
            [make_sample_totals_table(window_total_ru=1000.0, attributed_total_ru=1000.0)]
        ),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 1
    assert "Internal consistency error:" in result.output
    assert "query shape RU share exceeded 100.0%" in result.output
    normalized = " ".join(result.output.split())
    assert (
        "This is a bug in querylens; please report it with the output of 'discover --check'"
        in normalized
    )
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_console_truncates_query_text_by_default(mock_get_client: MagicMock) -> None:
    """Verify console table truncates query text to 200 characters by default (FR-012, T033)."""
    long_query = "SELECT * FROM c WHERE " + " AND ".join([f"c.field_{i} == {i}" for i in range(25)])
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_long",
            "ql_sample_text": long_query,
            "ql_execution_count": 10,
            "ql_total_ru": 100.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 20.0,
            "ql_throttled_count": 0,
            "ql_top_callers": [],
        }
    ]
    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table(shapes=shapes)]),
        make_logs_query_result([make_sample_totals_table()]),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
        env={"COLUMNS": "400"},
    )
    assert result.exit_code == 0
    assert "..." in result.output
    assert "c.field_24" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_console_shows_full_query_text_with_flag(mock_get_client: MagicMock) -> None:
    """Verify console table preserves full query text when --show-text is specified (T033)."""
    long_query = "SELECT * FROM c WHERE " + " AND ".join([f"c.field_{i} == {i}" for i in range(25)])
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_long",
            "ql_sample_text": long_query,
            "ql_execution_count": 10,
            "ql_total_ru": 100.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 20.0,
            "ql_throttled_count": 0,
            "ql_top_callers": [],
        }
    ]
    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table(shapes=shapes)]),
        make_logs_query_result([make_sample_totals_table()]),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--show-text"],
        env={"COLUMNS": "400"},
    )
    assert result.exit_code == 0
    assert "c.field_24" in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_never_logs_query_text(
    mock_get_client: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify query text is never logged to internal application logs (FR-012, T033)."""
    import logging

    secret_query = "SELECT * FROM c WHERE c.secret_token = 'SUPER_SECRET_PAYLOAD_TOKEN'"
    shapes = [
        {
            "ql_db_name": "ecommerce",
            "ql_coll_name": "orders",
            "ql_shape_id": "shape_hash_secret",
            "ql_sample_text": secret_query,
            "ql_execution_count": 10,
            "ql_total_ru": 100.0,
            "ql_max_ru": 10.0,
            "ql_total_returned_rows": 20.0,
            "ql_throttled_count": 0,
            "ql_top_callers": [],
        }
    ]
    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table(shapes=shapes)]),
        make_logs_query_result([make_sample_totals_table()]),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    with caplog.at_level(logging.DEBUG):
        result = runner.invoke(
            cli,
            ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
        )
    assert result.exit_code == 0
    assert "SUPER_SECRET_PAYLOAD_TOKEN" not in caplog.text


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_renders_callers_in_console_and_json(mock_get_client: MagicMock) -> None:
    """Verify discovery renders top callers in console and outputs top_callers in JSON (US3)."""
    from tests.fixtures.synthetic_logs import make_sample_shapes_table_with_callers

    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        make_logs_query_result([make_sample_shapes_table_with_callers()]),
        make_logs_query_result([make_sample_totals_table()]),
        make_logs_query_result([make_sample_shapes_table_with_callers()]),
        make_logs_query_result([make_sample_totals_table()]),
    ]
    mock_get_client.return_value = mock_client

    runner = CliRunner()
    # 1. Console
    res_console = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
        env={"COLUMNS": "400"},
    )
    assert res_console.exit_code == 0
    assert "00000000-0000-0000-0000-000000000001" in res_console.output
    assert "70.0%" in res_console.output
    assert "192.168.1.1" in res_console.output

    # 2. JSON
    res_json = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--json"],
    )
    assert res_json.exit_code == 0
    data = json.loads(res_json.output)
    assert len(data["results"]) == 1
    callers = data["results"][0].get("top_callers", [])
    assert len(callers) == 2
    assert callers[0]["identifier"] == "00000000-0000-0000-0000-000000000001"
    assert callers[0]["ru_share_pct"] == 70.0


def test_cli_discover_and_check_render_exact_absolute_window() -> None:
    """Verify CLI reports exact absolute window in console and JSON with frozen clock."""
    from datetime import UTC, datetime, tzinfo
    from typing import Self
    from unittest.mock import patch

    from tests.fixtures.synthetic_logs import (
        make_sample_preflight_table,
        make_sample_shapes_table,
        make_sample_totals_table,
    )

    frozen_now = datetime(2026, 10, 11, 15, 0, 0, tzinfo=UTC)

    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> Self:
            return cls(
                frozen_now.year,
                frozen_now.month,
                frozen_now.day,
                frozen_now.hour,
                frozen_now.minute,
                frozen_now.second,
                tzinfo=UTC,
            )

    mock_client = MagicMock()
    mock_client.query_workspace.side_effect = [
        # discover console
        make_logs_query_result([make_sample_shapes_table()]),
        make_logs_query_result([make_sample_totals_table()]),
        # discover json
        make_logs_query_result([make_sample_shapes_table()]),
        make_logs_query_result([make_sample_totals_table()]),
        # check console
        make_logs_query_result([make_sample_preflight_table()]),
        # check json
        make_logs_query_result([make_sample_preflight_table()]),
    ]

    with (
        patch("querylens.discover_cli.get_logs_client", return_value=mock_client),
        patch("querylens.discover_cli.datetime", FrozenClock),
        patch("querylens.discovery.service.datetime", FrozenClock),
    ):
        runner = CliRunner()

        # 1. Discover Console
        res_disc = runner.invoke(
            cli,
            ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
            env={"COLUMNS": "200"},
        )
        assert res_disc.exit_code == 0
        assert "2026-10-10 15:00 to 2026-10-11 15:00 UTC" in res_disc.output

        # 2. Discover JSON
        res_disc_json = runner.invoke(
            cli,
            ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--json"],
        )
        assert res_disc_json.exit_code == 0
        parsed_disc = json.loads(res_disc_json.output)
        assert parsed_disc["window_start"] == "2026-10-10T15:00:00+00:00"
        assert parsed_disc["window_end"] == "2026-10-11T15:00:00+00:00"

        # 3. Check Console
        res_check = runner.invoke(
            cli,
            ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--check"],
            env={"COLUMNS": "200"},
        )
        assert res_check.exit_code == 0
        assert "2026-10-10 15:00 to 2026-10-11 15:00 UTC" in res_check.output

        # 4. Check JSON
        res_check_json = runner.invoke(
            cli,
            [
                "discover",
                "--workspace-id",
                "12345678-1234-1234-1234-123456789abc",
                "--check",
                "--json",
            ],
        )
        assert res_check_json.exit_code == 0
        parsed_check = json.loads(res_check_json.output)
        assert parsed_check["window_start"] == "2026-10-10T15:00:00+00:00"
        assert parsed_check["window_end"] == "2026-10-11T15:00:00+00:00"


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_client_init_auth_error_exits_5_without_traceback(
    mock_get_client: MagicMock,
) -> None:
    """Verify discovery exits 5 with clean message and no traceback on client auth error."""
    mock_get_client.side_effect = ClientAuthenticationError("Credential acquisition failed")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 5
    assert "Authentication Error:" in result.output
    assert "Credential acquisition failed" in result.output
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_client_init_http_403_exits_5_without_traceback(
    mock_get_client: MagicMock,
) -> None:
    """Verify discovery exits 5 with clean message and no traceback on client HTTP 403."""
    mock_resp = MagicMock(status_code=403, reason="Forbidden")
    mock_get_client.side_effect = HttpResponseError(
        message="Forbidden: Principal lacks Log Analytics Reader",
        response=mock_resp,
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 5
    assert "Authorization Error:" in result.output
    assert "Forbidden: Principal lacks Log Analytics Reader" in result.output
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_client_init_http_404_exits_3_without_traceback(
    mock_get_client: MagicMock,
) -> None:
    """Verify discovery exits 3 with clean message and no traceback on client HTTP 404."""
    mock_resp = MagicMock(status_code=404, reason="Not Found")
    mock_get_client.side_effect = HttpResponseError(
        message="Workspace not found",
        response=mock_resp,
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 3
    assert "Workspace Not Found:" in result.output
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_discover_client_init_service_request_error_exits_3_without_traceback(
    mock_get_client: MagicMock,
) -> None:
    """Verify discovery exits 3 with clean message and no traceback on client connection error."""
    mock_get_client.side_effect = ServiceRequestError("Network connection reset by peer")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
    )
    assert result.exit_code == 3
    assert "Connection Error:" in result.output
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_check_client_init_auth_error_exits_5_without_traceback(
    mock_get_client: MagicMock,
) -> None:
    """Verify check mode exits 5 with clean message and no traceback on client auth error."""
    mock_get_client.side_effect = ClientAuthenticationError("Credential acquisition failed")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--check"],
    )
    assert result.exit_code == 5
    assert "Authentication Error:" in result.output
    assert "Credential acquisition failed" in result.output
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_check_client_init_http_403_exits_5_without_traceback(
    mock_get_client: MagicMock,
) -> None:
    """Verify check mode exits 5 with clean message and no traceback on client HTTP 403."""
    mock_resp = MagicMock(status_code=403, reason="Forbidden")
    mock_get_client.side_effect = HttpResponseError(
        message="Forbidden: Principal lacks Log Analytics Reader",
        response=mock_resp,
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--check"],
    )
    assert result.exit_code == 5
    assert "Authorization Error:" in result.output
    assert "Forbidden: Principal lacks Log Analytics Reader" in result.output
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_check_client_init_http_404_exits_3_without_traceback(
    mock_get_client: MagicMock,
) -> None:
    """Verify check mode exits 3 with clean message and no traceback on client HTTP 404."""
    mock_resp = MagicMock(status_code=404, reason="Not Found")
    mock_get_client.side_effect = HttpResponseError(
        message="Workspace not found",
        response=mock_resp,
    )
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--check"],
    )
    assert result.exit_code == 3
    assert "Workspace Not Found:" in result.output
    assert "Traceback" not in result.output


@patch("querylens.discover_cli.get_logs_client")
def test_cli_check_client_init_service_request_error_exits_3_without_traceback(
    mock_get_client: MagicMock,
) -> None:
    """Verify check mode exits 3 with clean message and no traceback on client connection error."""
    mock_get_client.side_effect = ServiceRequestError("Network connection reset by peer")
    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--check"],
    )
    assert result.exit_code == 3
    assert "Connection Error:" in result.output
    assert "Traceback" not in result.output
