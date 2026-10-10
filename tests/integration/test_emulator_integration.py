"""Integration tests connecting to local Cosmos DB Linux emulator (T030)."""

import os
import socket
from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml
from azure.cosmos import CosmosClient
from click.testing import CliRunner
from seed_emulator import EMULATOR_KEY, seed

from querylens.adapters.cosmos import CosmosAdapter
from querylens.cli import cli
from querylens.config import Settings
from querylens.model import QueryDefinition, Workload
from querylens.rules import evaluate_rules

EMULATOR_ENDPOINT = "https://localhost:8081/"


def is_emulator_reachable() -> bool:
    """Check if Cosmos DB emulator port 8081 is accepting connections.

    Returns:
        bool: True if reachable, False otherwise.
    """
    try:
        parsed = urlparse(EMULATOR_ENDPOINT)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8081
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (OSError, TimeoutError):
        return False


@pytest.mark.integration
class TestCosmosAdapterEmulatorIntegration:
    """Integration test suite executing queries against real Cosmos DB emulator."""

    @pytest.fixture(scope="class")
    @classmethod
    def setup_emulator_container(cls) -> None:
        """Seed integration test database and containers on emulator using seed_emulator."""
        if not is_emulator_reachable():
            if os.getenv("QUERYLENS_REQUIRE_EMULATOR") == "1":
                pytest.fail(
                    "Cosmos DB emulator is required (QUERYLENS_REQUIRE_EMULATOR=1) "
                    "but is not reachable on localhost:8081"
                )
            pytest.skip("Cosmos DB emulator is not running on localhost:8081")

        seed(
            endpoint=EMULATOR_ENDPOINT,
            key=EMULATOR_KEY,
            database_name="querylens_dev",
            reset=False,
            doc_count=1200,
            large_doc_count=20,
            num_partitions=60,
        )

    def test_collect_against_real_emulator(self, setup_emulator_container: None) -> None:
        """Execute point and fan-out queries against real emulator."""
        settings = Settings(
            endpoint=EMULATOR_ENDPOINT,
            cosmos_key=EMULATOR_KEY,
            database="querylens_dev",
            container="items",
        )
        adapter = CosmosAdapter(settings)
        workload = Workload(
            database="querylens_dev",
            container="items",
            queries=[
                QueryDefinition(
                    id="q_point",
                    query="SELECT * FROM c WHERE c.id = 'item-0000'",
                    partition_key="cat-0",
                ),
                QueryDefinition(
                    id="q_cross_partition",
                    query="SELECT * FROM c WHERE c.status = 'active'",
                ),
            ],
        )

        results = list(adapter.collect(workload))
        assert len(results) == 2

        point_query = results[0]
        assert point_query.query_id == "q_point"
        assert point_query.request_charge > 0.0
        assert point_query.documents_returned >= 1
        assert point_query.is_cross_partition is False

        fanout_query = results[1]
        assert fanout_query.query_id == "q_cross_partition"
        assert fanout_query.request_charge > 0.0
        assert fanout_query.documents_returned >= 30
        assert fanout_query.is_cross_partition is True

    def test_single_partition_multi_page_not_flagged(self, setup_emulator_container: None) -> None:
        """Assert multi-page queries with partition_key avoid QL002 and match direct run."""
        settings = Settings(
            endpoint=EMULATOR_ENDPOINT,
            cosmos_key=EMULATOR_KEY,
            database="querylens_dev",
            container="items",
            max_item_count=10,  # Force small page size to ensure multiple pages
        )
        adapter = CosmosAdapter(settings)
        workload = Workload(
            database="querylens_dev",
            container="items",
            queries=[
                QueryDefinition(
                    id="q_single_partition_pages",
                    query="SELECT * FROM c WHERE c.category = @cat",
                    partition_key="cat-0",
                    parameters=[{"name": "@cat", "value": "cat-0"}],
                ),
            ],
        )

        results = list(adapter.collect(workload))
        assert len(results) == 1
        query_cost = results[0]
        assert query_cost.query_id == "q_single_partition_pages"
        assert query_cost.documents_returned > 100
        assert query_cost.is_cross_partition is False

        # Verify QL002 is not triggered
        findings = evaluate_rules(query_cost, settings)
        finding_rule_ids = {f.rule_id for f in findings}
        assert "QL002" not in finding_rule_ids

        # Compare with direct SDK query_items run with the same query and partition_key
        client = CosmosClient(
            url=EMULATOR_ENDPOINT,
            credential=EMULATOR_KEY,
            connection_verify=False,
        )
        container = client.get_database_client("querylens_dev").get_container_client("items")
        direct_headers: list[dict[str, str]] = []
        direct_items = list(
            container.query_items(
                query="SELECT * FROM c WHERE c.category = @cat",
                parameters=[{"name": "@cat", "value": "cat-0"}],
                partition_key="cat-0",
                max_item_count=10,
                response_hook=lambda h, _: direct_headers.append(dict(h)),
            )
        )
        assert len(direct_items) == query_cost.documents_returned
        assert len(direct_headers) > 1  # Confirms multi-page iteration occurred
        direct_ru = round(
            sum(float(h.get("x-ms-request-charge", 0.0)) for h in direct_headers),
            2,
        )
        assert query_cost.request_charge == direct_ru

    def test_example_workload_findings(self, setup_emulator_container: None) -> None:
        """Verify examples/workload.yaml queries trigger expected findings and clean controls."""
        workload_path = Path(__file__).resolve().parent.parent.parent / "examples" / "workload.yaml"
        raw_yaml = workload_path.read_text(encoding="utf-8")
        workload_dict = yaml.safe_load(raw_yaml)
        workload = Workload.model_validate(workload_dict)

        settings = Settings(
            endpoint=EMULATOR_ENDPOINT,
            cosmos_key=EMULATOR_KEY,
            database=workload.database or "querylens_dev",
            container=workload.container or "unindexed_items",
        )
        adapter = CosmosAdapter(settings)
        results = list(adapter.collect(workload))
        assert len(results) == len(workload.queries)

        results_by_id = {r.query_id: r for r in results}

        # 1. High RU query: produces QL001 (High RU Cost) and QL002 (Fan-Out)
        r_high = results_by_id["high_ru_scan"]
        f_high = evaluate_rules(r_high, settings)
        high_rule_ids = {f.rule_id for f in f_high}
        assert "QL001" in high_rule_ids
        assert "QL002" in high_rule_ids
        assert r_high.request_charge >= 50.0

        # 2. Cross-partition fan-out: produces QL002 (Cross-Partition Fan-Out)
        r_fanout = results_by_id["cross_partition_fanout"]
        f_fanout = evaluate_rules(r_fanout, settings)
        fanout_rule_ids = {f.rule_id for f in f_fanout}
        assert "QL002" in fanout_rule_ids
        assert r_fanout.is_cross_partition is True

        # 3. Scan-to-return gap: produces QL003 (Scan-to-Return Gap)
        r_scangap = results_by_id["scan_gap_unindexed"]
        f_scangap = evaluate_rules(r_scangap, settings)
        scangap_rule_ids = {f.rule_id for f in f_scangap}
        assert "QL003" in scangap_rule_ids
        assert r_scangap.documents_scanned >= 1000
        assert r_scangap.documents_returned <= 5

        # 4. Control 1 (Point Read): produces NO findings
        r_point = results_by_id["control_point_read"]
        f_point = evaluate_rules(r_point, settings)
        assert len(f_point) == 0
        assert r_point.documents_scanned == 1
        assert r_point.documents_returned == 1
        assert r_point.is_cross_partition is False

        # 5. Control 2 (Single-Partition Query): produces NO findings
        r_single = results_by_id["control_single_partition_multipage"]
        f_single = evaluate_rules(r_single, settings)
        assert len(f_single) == 0
        assert r_single.is_cross_partition is False
        assert r_single.documents_returned > 100

        # Verify CLI execution on clean workload exits 0
        runner = CliRunner(env={"QUERYLENS_COSMOS_KEY": EMULATOR_KEY, "COLUMNS": "120"})
        res = runner.invoke(
            cli,
            [
                "run",
                str(workload_path),
                "--endpoint",
                EMULATOR_ENDPOINT,
            ],
        )
        assert res.exit_code == 0
        assert "[ERROR]" not in res.output

    def test_example_workload_with_error(self, setup_emulator_container: None) -> None:
        """Verify examples/workload-with-error.yaml captures syntax error and exits 1."""
        workload_path = Path("examples/workload-with-error.yaml")
        raw_yaml = yaml.safe_load(workload_path.read_text(encoding="utf-8"))
        workload = Workload.model_validate(raw_yaml)

        settings = Settings(
            endpoint=EMULATOR_ENDPOINT,
            cosmos_key=EMULATOR_KEY,
            database=workload.database or "querylens_dev",
            container=workload.container or "unindexed_items",
        )
        adapter = CosmosAdapter(settings)
        results = list(adapter.collect(workload))
        assert len(results) == len(workload.queries)

        results_by_id = {r.query_id: r for r in results}
        r_bad = results_by_id["bad_syntax_error"]
        f_bad = evaluate_rules(r_bad, settings)
        assert len(f_bad) == 0
        assert r_bad.request_charge == 0.0
        assert r_bad.error_message is not None
        assert "Syntax error" in r_bad.error_message

        # CLI execution on workload with errors must render the report and exit 1
        runner = CliRunner(env={"QUERYLENS_COSMOS_KEY": EMULATOR_KEY, "COLUMNS": "120"})
        res = runner.invoke(
            cli,
            [
                "run",
                str(workload_path),
                "--endpoint",
                EMULATOR_ENDPOINT,
            ],
        )
        assert res.exit_code == 1
        assert "[ERROR]" in res.output
        assert "Syntax error" in res.output
