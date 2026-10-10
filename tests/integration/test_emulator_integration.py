"""Integration tests connecting to local Cosmos DB Linux emulator (T030)."""

import os
import socket
from urllib.parse import urlparse

import pytest
from azure.cosmos import CosmosClient, PartitionKey

from querylens.adapters.cosmos import CosmosAdapter
from querylens.config import Settings
from querylens.model import QueryDefinition, Workload

EMULATOR_ENDPOINT = "https://localhost:8081/"
EMULATOR_KEY = (
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="
)


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
        """Create integration test database and container on emulator."""
        if not is_emulator_reachable():
            if os.getenv("QUERYLENS_REQUIRE_EMULATOR") == "1":
                pytest.fail(
                    "Cosmos DB emulator is required (QUERYLENS_REQUIRE_EMULATOR=1) "
                    "but is not reachable on localhost:8081"
                )
            pytest.skip("Cosmos DB emulator is not running on localhost:8081")

        client = CosmosClient(
            url=EMULATOR_ENDPOINT,
            credential=EMULATOR_KEY,
            connection_verify=False,
        )
        try:
            client.delete_database("querylens_integration_db")
        except Exception:
            pass
        db = client.create_database_if_not_exists(id="querylens_integration_db")
        # Create multi-partition container with 10500 RU/s throughput.
        # Provisioning > 10,000 RU/s forces Cosmos to split across physical partitions.
        container = db.create_container_if_not_exists(
            id="test_items",
            partition_key=PartitionKey(path="/category"),
            offer_throughput=10500,
        )

        # Seed sample documents across multiple partition key values
        for i in range(30):
            container.upsert_item(
                {
                    "id": f"item-{i}",
                    "category": f"cat-{i % 6}",
                    "price": 10.0 * i,
                    "active": True,
                }
            )

    def test_collect_against_real_emulator(self, setup_emulator_container: None) -> None:
        """Execute point and fan-out queries against real emulator."""
        settings = Settings(
            endpoint=EMULATOR_ENDPOINT,
            cosmos_key=EMULATOR_KEY,
            database="querylens_integration_db",
            container="test_items",
        )
        adapter = CosmosAdapter(settings)
        workload = Workload(
            database="querylens_integration_db",
            container="test_items",
            queries=[
                QueryDefinition(
                    id="q_point",
                    query="SELECT * FROM c WHERE c.id = 'item-0'",
                    partition_key="cat-0",
                ),
                QueryDefinition(
                    id="q_cross_partition",
                    query="SELECT * FROM c WHERE c.active = true",
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
        """Assert that single-partition multi-page queries are NOT flagged as cross-partition."""
        settings = Settings(
            endpoint=EMULATOR_ENDPOINT,
            cosmos_key=EMULATOR_KEY,
            database="querylens_integration_db",
            container="test_items",
            max_item_count=2,  # Force small page size to ensure multiple pages
        )
        adapter = CosmosAdapter(settings)
        workload = Workload(
            database="querylens_integration_db",
            container="test_items",
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
        assert query_cost.documents_returned >= 5
        assert query_cost.is_cross_partition is False
