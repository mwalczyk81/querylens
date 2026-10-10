"""Cosmos DB adapter implementing DatabaseAdapter protocol.

See docs/adr/0005-azure-cosmos-sdk-contracts-and-metrics-extraction.md for
verification of azure-cosmos==4.17.1 contracts, query_items signatures,
and HttpHeaders constants.
"""

import base64
import json
from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import urlparse

from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import (
    CosmosClientTimeoutError,
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
)
from azure.cosmos.http_constants import HttpHeaders
from azure.identity import DefaultAzureCredential

from querylens.config import Settings
from querylens.model import IndexUtilization, QueryCost, Workload


def parse_query_metrics_header(header_val: str | None) -> dict[str, Any]:
    """Parse semicolon-delimited key=value query metrics header.

    SDK Header: HttpHeaders.QueryMetrics ('x-ms-documentdb-query-metrics')

    Args:
        header_val: Raw query metrics string from Cosmos DB response.

    Returns:
        dict[str, Any]: Parsed numeric metric fields.
    """
    metrics: dict[str, Any] = {
        "retrievedDocumentCount": 0,
        "outputDocumentCount": 0,
        "totalExecutionTimeInMs": 0.0,
    }
    if not header_val:
        return metrics

    for part in header_val.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip()
        val = val.strip()
        if key in ("retrievedDocumentCount", "outputDocumentCount"):
            try:
                metrics[key] = int(val)
            except ValueError:
                pass
        elif key == "totalExecutionTimeInMs":
            try:
                metrics[key] = float(val)
            except ValueError:
                pass
    return metrics


def parse_index_utilization_header(b64_val: str | None) -> IndexUtilization | None:
    """Decode and parse Base64-encoded UTF-8 JSON index utilization header.

    SDK Header: HttpHeaders.IndexUtilization ('x-ms-cosmos-index-utilization')

    Args:
        b64_val: Base64 string from Cosmos DB response header.

    Returns:
        IndexUtilization | None: Decoded index utilization object or None.
    """
    if not b64_val:
        return None
    try:
        raw_json = base64.b64decode(b64_val).decode("utf-8")
        parsed = json.loads(raw_json)
        return IndexUtilization(
            utilized_single=parsed.get("UtilizedSingleIndexes", []),
            potential_single=parsed.get("PotentialSingleIndexes", []),
            utilized_composite=parsed.get("UtilizedCompositeIndexes", []),
            potential_composite=parsed.get("PotentialCompositeIndexes", []),
        )
    except Exception:
        return None


def aggregate_query_headers(headers_list: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate metric headers across multiple pages and physical partitions.

    Args:
        headers_list: Sequence of response header mappings.

    Returns:
        dict[str, Any]: Aggregated cost metrics.
    """
    total_ru = 0.0
    total_scanned = 0
    total_returned = 0
    total_latency = 0.0
    index_util: IndexUtilization | None = None

    for headers in headers_list:
        # Request Charge (HttpHeaders.RequestCharge: 'x-ms-request-charge')
        charge_str = headers.get(HttpHeaders.RequestCharge, "0")
        try:
            total_ru += float(charge_str)
        except (ValueError, TypeError):
            pass

        # Query Metrics (HttpHeaders.QueryMetrics: 'x-ms-documentdb-query-metrics')
        qm_str = headers.get(HttpHeaders.QueryMetrics)
        qm = parse_query_metrics_header(qm_str)
        total_scanned += qm["retrievedDocumentCount"]
        total_returned += qm["outputDocumentCount"]
        total_latency += qm["totalExecutionTimeInMs"]

        # Index Utilization (HttpHeaders.IndexUtilization: 'x-ms-cosmos-index-utilization')
        iu_str = headers.get(HttpHeaders.IndexUtilization)
        if iu_str and index_util is None:
            index_util = parse_index_utilization_header(iu_str)

    is_cross = len(headers_list) > 1

    return {
        "request_charge": round(total_ru, 2),
        "documents_scanned": total_scanned,
        "documents_returned": total_returned,
        "latency_ms": round(total_latency, 2),
        "is_cross_partition": is_cross,
        "index_metrics": index_util,
    }


class BudgetExceededError(Exception):
    """Raised when cumulative Request Units exceed the configured budget limit."""

    def __init__(self, partial_cost: QueryCost, cumulative_ru: float) -> None:
        """Initialize BudgetExceededError with partial cost details.

        Args:
            partial_cost: The partial QueryCost for the aborted query.
            cumulative_ru: Total RU consumed when budget was exceeded.
        """
        super().__init__(f"Cumulative RU budget exceeded: {cumulative_ru:.2f} RUs")
        self.partial_cost = partial_cost
        self.cumulative_ru = cumulative_ru


class CosmosAdapter:
    """Database adapter connecting to Azure Cosmos DB for NoSQL."""

    def __init__(self, settings: Settings) -> None:
        """Initialize Cosmos DB client following security and endpoint invariants.

        Args:
            settings: Runtime settings containing endpoint and credentials.

        Raises:
            ValueError: If key auth is attempted against a remote non-local endpoint.
        """
        self.settings = settings
        endpoint = settings.endpoint
        parsed = urlparse(endpoint)
        is_local = parsed.hostname in ("localhost", "127.0.0.1")

        if settings.cosmos_key:
            if not is_local:
                raise ValueError(
                    "Cosmos DB master key authentication is ONLY permitted for local emulator "
                    "(localhost / 127.0.0.1). Remote endpoints require DefaultAzureCredential."
                )
            credential = settings.cosmos_key
        else:
            credential = DefaultAzureCredential()

        self.client = CosmosClient(
            url=endpoint,
            credential=credential,
            connection_verify=not is_local,
        )

    def collect(self, workload: Workload) -> Iterator[QueryCost]:
        """Execute queries in workload, capture cost metrics, and discard payloads.

        Args:
            workload: The workload defining queries to profile.

        Yields:
            QueryCost: Captured cost and performance metrics for each query.

        Raises:
            ValueError: If database or container are not configured.
            ClientAuthenticationError: If authentication fails.
            CosmosHttpResponseError: If HTTP error occurs (e.g. 401/403 auth error).
            CosmosResourceNotFoundError: If database/container is not found.
            CosmosClientTimeoutError: If request times out.
            ServiceRequestError: If network connection fails.
            BudgetExceededError: If RU budget ceiling is exceeded mid-workload.
        """
        database_name = workload.database or self.settings.database
        container_name = workload.container or self.settings.container

        if not database_name or not container_name:
            raise ValueError("Target database and container must be specified.")

        try:
            database = self.client.get_database_client(database_name)
            container = database.get_container_client(container_name)
        except (ClientAuthenticationError, CosmosResourceNotFoundError, ServiceRequestError):
            raise
        except CosmosHttpResponseError as e:
            raise e

        ru_budget = self.settings.ru_budget or workload.ru_budget
        cumulative_ru = 0.0

        for query_def in workload.queries:
            page_headers: list[Mapping[str, Any]] = []

            def response_hook(
                headers: Mapping[str, Any],
                _body: Any,
                headers_target: list[Mapping[str, Any]] = page_headers,
            ) -> None:
                headers_target.append(dict(headers))

            params = (
                [{"name": p.name, "value": p.value} for p in query_def.parameters]
                if query_def.parameters
                else None
            )

            paged_items = container.query_items(
                query=query_def.query,
                parameters=params,
                partition_key=query_def.partition_key,
                enable_cross_partition_query=True,
                populate_query_metrics=True,
                populate_index_metrics=True,
                max_item_count=self.settings.max_item_count,
                response_hook=response_hook,
            )

            budget_breached = False
            try:
                for page in paged_items.by_page():
                    # Check RU budget per page
                    if page_headers:
                        last_header = page_headers[-1]
                        page_ru = float(last_header.get(HttpHeaders.RequestCharge, 0.0))
                        cumulative_ru += page_ru
                        if ru_budget is not None and cumulative_ru >= ru_budget:
                            budget_breached = True

                    # Constitution Principle I: Zero-Impact, Read-Only Payload Privacy
                    # Discard document payloads immediately without storing in memory or disk.
                    for _ in page:
                        pass

                    if budget_breached:
                        break
            except (
                ClientAuthenticationError,
                CosmosResourceNotFoundError,
                ServiceRequestError,
                CosmosClientTimeoutError,
            ):
                raise
            except CosmosHttpResponseError as exc:
                if exc.status_code in (401, 403, 404):
                    raise
                # Individual query execution error (e.g. syntax error in query)
                yield QueryCost(
                    query_id=query_def.id,
                    query_text=query_def.query,
                    request_charge=0.0,
                    latency_ms=0.0,
                    documents_scanned=0,
                    documents_returned=0,
                    is_cross_partition=False,
                    error_message=str(exc.message or exc),
                )
                continue

            agg = aggregate_query_headers(page_headers)
            cost = QueryCost(
                query_id=query_def.id,
                query_text=query_def.query,
                request_charge=agg["request_charge"],
                latency_ms=agg["latency_ms"],
                documents_scanned=agg["documents_scanned"],
                documents_returned=agg["documents_returned"],
                is_cross_partition=agg["is_cross_partition"],
                is_partial=budget_breached,
                index_metrics=agg["index_metrics"],
            )

            if budget_breached:
                raise BudgetExceededError(cost, cumulative_ru)

            yield cost
