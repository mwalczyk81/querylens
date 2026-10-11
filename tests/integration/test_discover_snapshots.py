"""End-to-end output format snapshot tests using syrupy for discover and check (T038)."""

import json
from datetime import UTC, datetime, tzinfo
from typing import Self
from unittest.mock import MagicMock, patch

from click.testing import CliRunner
from syrupy.assertion import SnapshotAssertion

from querylens.cli import cli
from tests.fixtures.synthetic_logs import (
    make_logs_query_result,
    make_sample_preflight_table,
    make_sample_shapes_table_with_callers,
    make_sample_totals_table,
)

FIXED_NOW = datetime(2026, 10, 11, 12, 0, 0, tzinfo=UTC)


class FrozenDatetime(datetime):
    """Deterministic datetime mock for repeatable snapshot testing."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> Self:
        return cls(2026, 10, 11, 12, 0, 0, tzinfo=UTC)


class TestDiscoverSnapshots:
    """Snapshot regression tests for discover and check outputs."""

    # Force legacy_windows=False so Rich renders deterministic unicode box styling
    # (rounded panels, heavy-head tables) identically across Windows and Linux CI runners.
    @patch("rich.console.detect_legacy_windows", lambda: False)
    @patch("querylens.discovery.service.datetime", FrozenDatetime)
    @patch("querylens.discover_cli.get_logs_client")
    def test_discover_console_table_snapshot(
        self,
        mock_get_client: MagicMock,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Capture deterministic snapshot of discovery console table output."""
        mock_client = MagicMock()
        shapes_table = make_sample_shapes_table_with_callers()
        totals_table = make_sample_totals_table(window_total_ru=1000.0, attributed_total_ru=500.0)
        mock_client.query_workspace.side_effect = [
            make_logs_query_result([shapes_table]),
            make_logs_query_result([totals_table]),
        ]
        mock_get_client.return_value = mock_client

        runner = CliRunner(env={"COLUMNS": "160", "NO_COLOR": "1", "TERM": "dumb"})
        result = runner.invoke(
            cli,
            ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc"],
        )
        assert result.exit_code == 0
        assert "Top Query Shapes" in result.output
        assert "ecommerce" in result.output
        assert result.output == snapshot

    @patch("querylens.discovery.service.datetime", FrozenDatetime)
    @patch("querylens.discover_cli.get_logs_client")
    def test_discover_json_snapshot(
        self,
        mock_get_client: MagicMock,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Capture deterministic snapshot of discovery --json output."""
        mock_client = MagicMock()
        shapes_table = make_sample_shapes_table_with_callers()
        totals_table = make_sample_totals_table(window_total_ru=1000.0, attributed_total_ru=500.0)
        mock_client.query_workspace.side_effect = [
            make_logs_query_result([shapes_table]),
            make_logs_query_result([totals_table]),
        ]
        mock_get_client.return_value = mock_client

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--json"],
        )
        assert result.exit_code == 0
        parsed = json.loads(result.output)
        assert parsed == snapshot

    # Force legacy_windows=False so Rich renders deterministic unicode box styling
    # (rounded panels, heavy-head tables) identically across Windows and Linux CI runners.
    @patch("rich.console.detect_legacy_windows", lambda: False)
    @patch("querylens.discovery.service.datetime", FrozenDatetime)
    @patch("querylens.discover_cli.get_logs_client")
    def test_check_console_report_snapshot(
        self,
        mock_get_client: MagicMock,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Capture deterministic snapshot of --check preflight console report."""
        mock_client = MagicMock()
        preflight_table = make_sample_preflight_table()
        mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])
        mock_get_client.return_value = mock_client

        runner = CliRunner(env={"COLUMNS": "160", "NO_COLOR": "1", "TERM": "dumb"})
        result = runner.invoke(
            cli,
            ["discover", "--workspace-id", "12345678-1234-1234-1234-123456789abc", "--check"],
        )
        assert result.exit_code == 0
        assert "Log Analytics Diagnostic Preflight Check" in result.output
        assert result.output == snapshot

    @patch("querylens.discovery.service.datetime", FrozenDatetime)
    @patch("querylens.discover_cli.get_logs_client")
    def test_check_json_snapshot(
        self,
        mock_get_client: MagicMock,
        snapshot: SnapshotAssertion,
    ) -> None:
        """Capture deterministic snapshot of --check --json preflight output."""
        mock_client = MagicMock()
        preflight_table = make_sample_preflight_table()
        mock_client.query_workspace.return_value = make_logs_query_result([preflight_table])
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
        parsed = json.loads(result.output)
        assert parsed == snapshot
