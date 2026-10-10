"""Unit tests verifying --fail-on <severity> exit code 4 gating (T020)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from querylens.cli import cli
from querylens.model import QueryCost


class TestCliFailOnGating:
    """Tests covering exit code 4 when findings breach --fail-on threshold."""

    @patch("querylens.cli.get_adapter")
    def test_fail_on_critical_triggers_exit_4_on_critical(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 4 when a CRITICAL finding is detected under --fail-on critical."""
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

        # 250 RUs triggers CRITICAL (threshold 200)
        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c",
                request_charge=250.0,
                latency_ms=50.0,
                documents_scanned=100,
                documents_returned=100,
                is_cross_partition=False,
            )
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

    @patch("querylens.cli.get_adapter")
    def test_fail_on_critical_ignores_high_severity(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 0 when only HIGH findings exist and --fail-on is critical."""
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

        # 80 RUs triggers HIGH (50 <= RU < 200)
        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c",
                request_charge=80.0,
                latency_ms=20.0,
                documents_scanned=50,
                documents_returned=50,
                is_cross_partition=False,
            )
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
        assert result.exit_code == 0

    @patch("querylens.cli.get_adapter")
    def test_fail_on_high_triggers_on_high_and_critical(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 4 when HIGH finding is detected under --fail-on high."""
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

        # 80 RUs triggers HIGH
        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c",
                request_charge=80.0,
                latency_ms=20.0,
                documents_scanned=50,
                documents_returned=50,
                is_cross_partition=False,
            )
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
                "high",
            ],
        )
        assert result.exit_code == 4

    @patch("querylens.cli.get_adapter")
    def test_fail_on_medium_triggers_on_fanout(
        self, mock_get_adapter: MagicMock, tmp_path: Path
    ) -> None:
        """Exit code 4 when MEDIUM finding (fan-out) is detected under --fail-on medium."""
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

        # Cross partition triggers MEDIUM
        mock_adapter = MagicMock()
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c",
                request_charge=10.0,
                latency_ms=10.0,
                documents_scanned=10,
                documents_returned=10,
                is_cross_partition=True,
            )
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
                "medium",
            ],
        )
        assert result.exit_code == 4

    @patch("querylens.cli.get_adapter")
    def test_fail_on_off_by_default(self, mock_get_adapter: MagicMock, tmp_path: Path) -> None:
        """Exit code 0 when --fail-on is omitted even if CRITICAL findings exist."""
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
        mock_adapter.collect.return_value = [
            QueryCost(
                query_id="q1",
                query_text="SELECT * FROM c",
                request_charge=500.0,
                latency_ms=100.0,
                documents_scanned=1000,
                documents_returned=10,
                is_cross_partition=True,
            )
        ]
        mock_get_adapter.return_value = mock_adapter

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", str(workload_yaml), "--endpoint", "https://localhost:8081/"],
        )
        assert result.exit_code == 0
