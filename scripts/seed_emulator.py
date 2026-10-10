"""Deterministic data seeder for local Cosmos DB emulator.

Populates local Cosmos DB emulator with reproducible workloads for testing and profiling:
1. Two containers: one with default indexing ('items'), and one with an excluded
   indexing policy ('unindexed_items') to demonstrate scan-to-return gap anti-patterns.
2. Deterministic data generation via standard library random.Random(42).
3. Enforces localhost / 127.0.0.1 safety check to reject remote Azure endpoints.
"""

import argparse
import random
import time
from contextlib import suppress
from typing import Any
from urllib.parse import urlparse

from azure.cosmos import CosmosClient, PartitionKey

# Public well-known Microsoft Azure Cosmos DB Emulator master key.
# Published in official Microsoft documentation: https://learn.microsoft.com/azure/cosmos-db/emulator
EMULATOR_KEY = (
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="  # noqa: S105 - Public well-known emulator key
)

DEFAULT_ENDPOINT = "https://localhost:8081/"
DEFAULT_DATABASE = "querylens_dev"
DEFAULT_CONTAINER_1 = "items"
DEFAULT_CONTAINER_2 = "unindexed_items"


def validate_local_endpoint(endpoint: str) -> None:
    """Ensure target endpoint resolves to localhost or 127.0.0.1.

    Args:
        endpoint: Cosmos DB endpoint URL string.

    Raises:
        ValueError: If host is not localhost or 127.0.0.1.
    """
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1"):
        raise ValueError(
            f"Seeding is ONLY permitted for local emulator (localhost / 127.0.0.1). "
            f"Refusing remote endpoint: '{endpoint}'"
        )


def seed(
    endpoint: str = DEFAULT_ENDPOINT,
    key: str = EMULATOR_KEY,
    database_name: str = DEFAULT_DATABASE,
    container_default_name: str = DEFAULT_CONTAINER_1,
    container_unindexed_name: str = DEFAULT_CONTAINER_2,
    reset: bool = False,
    doc_count: int = 1200,
    large_doc_count: int = 20,
    num_partitions: int = 60,
    seed_value: int = 42,
) -> None:
    """Seed local Cosmos DB emulator with deterministic sample workloads.

    Args:
        endpoint: Local Cosmos DB emulator endpoint URL.
        key: Emulator master key.
        database_name: Target database name.
        container_default_name: Name of container with default indexing policy.
        container_unindexed_name: Name of container with excluded indexing path.
        reset: If True, drops database before seeding.
        doc_count: Number of small documents to generate across partition keys.
        large_doc_count: Number of multi-KB large documents to generate.
        num_partitions: Number of distinct partition key values (50+).
        seed_value: Random seed for deterministic data generation.

    Raises:
        ValueError: If endpoint is not localhost or 127.0.0.1.
    """
    validate_local_endpoint(endpoint)

    print(f"Connecting to Cosmos DB emulator at {endpoint}...")
    client = CosmosClient(
        url=endpoint,
        credential=key,
        connection_verify=False,
    )

    if reset:
        print(f"Resetting existing database '{database_name}'...")
        with suppress(Exception):
            client.delete_database(database_name)
            for _ in range(10):
                time.sleep(0.5)
                try:
                    client.get_database_client(database_name).read()
                except Exception:
                    break
            print(f"Database '{database_name}' dropped.")

    # Provision shared database throughput (10,500 RU/s forces physical partition splits)
    print(f"Creating database '{database_name}' with shared 10,500 RU/s throughput...")
    database = None
    for attempt in range(5):
        try:
            database = client.create_database_if_not_exists(
                id=database_name, offer_throughput=10500
            )
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(1.0)
    if database is None:
        msg = f"Failed to create database '{database_name}' after retries."
        raise RuntimeError(msg)

    # 1. Container with default indexing policy
    print(f"Creating container '{container_default_name}' (default indexing)...")
    container_default = database.create_container_if_not_exists(
        id=container_default_name,
        partition_key=PartitionKey(path="/category"),
    )

    # 2. Container with excluded indexing path on '/unindexed_tag/*'
    print(
        f"Creating container '{container_unindexed_name}' "
        "(excluded indexing on /unindexed_tag/*)..."
    )
    indexing_policy = {
        "indexingMode": "consistent",
        "automatic": True,
        "includedPaths": [{"path": "/*"}],
        "excludedPaths": [
            {"path": "/unindexed_tag/*"},
            {"path": "/_etag/?"},
        ],
    }
    container_unindexed = database.create_container_if_not_exists(
        id=container_unindexed_name,
        partition_key=PartitionKey(path="/category"),
        indexing_policy=indexing_policy,
    )

    # 3. Generate deterministic documents
    print(f"Generating deterministic dataset (seed={seed_value})...")
    rng = random.Random(seed_value)
    docs: list[dict[str, Any]] = []

    # A few thousand small docs across 50+ partition key values (fan-out)
    for i in range(doc_count):
        cat_id = f"cat-{i % num_partitions}"
        is_rare_target = i == 42
        doc = {
            "id": f"item-{i:04d}",
            "category": cat_id,
            "name": f"Product-{i:04d}",
            "status": "active" if i % 4 != 0 else "inactive",
            "price": round(rng.uniform(5.0, 500.0), 2),
            "quantity": rng.randint(1, 100),
            "doc_type": "standard",
            "unindexed_tag": "target" if is_rare_target else f"common_{i % 10}",
            "payload": "s" * 200,
        }
        docs.append(doc)

    # ~20 large multi-KB docs (high RU)
    for j in range(large_doc_count):
        cat_id = f"cat-{j % num_partitions}"
        large_doc = {
            "id": f"large-item-{j:02d}",
            "category": cat_id,
            "name": f"Large Document {j:02d}",
            "status": "active",
            "doc_type": "large",
            "price": 1000.0 + j,
            "quantity": 1,
            "unindexed_tag": f"large_{j}",
            "description": "x" * 25000,  # ~25 KB payload per document
        }
        docs.append(large_doc)

    # 4. Upsert documents into both containers
    total_docs = len(docs)
    print(
        f"Upserting {total_docs} documents into '{container_default_name}' "
        f"and '{container_unindexed_name}'..."
    )
    for idx, doc in enumerate(docs):
        container_default.upsert_item(doc)
        container_unindexed.upsert_item(doc)
        if (idx + 1) % 400 == 0 or idx + 1 == total_docs:
            print(f"  Progress: {idx + 1}/{total_docs} items upserted...")

    print(
        f"Seeding complete: {total_docs} documents seeded across {num_partitions} partition keys "
        f"in database '{database_name}'."
    )


def main() -> None:
    """CLI entrypoint for seeding local Cosmos DB emulator."""
    parser = argparse.ArgumentParser(
        description="Seed local Cosmos DB emulator with deterministic test data."
    )
    parser.add_argument(
        "--endpoint",
        default=DEFAULT_ENDPOINT,
        help=f"Cosmos DB endpoint (must be localhost or 127.0.0.1, default: {DEFAULT_ENDPOINT})",
    )
    parser.add_argument(
        "--key",
        default=EMULATOR_KEY,
        help="Cosmos DB emulator key (default: well-known public emulator key)",
    )
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"Database name (default: {DEFAULT_DATABASE})",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Drop and recreate database before seeding",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1200,
        help="Number of small documents across partition keys (default: 1200)",
    )
    args = parser.parse_args()

    seed(
        endpoint=args.endpoint,
        key=args.key,
        database_name=args.database,
        reset=args.reset,
        doc_count=args.count,
    )


if __name__ == "__main__":
    main()
