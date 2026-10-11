"""Unit tests for Cosmos DB response header parsing and aggregation."""

import base64
import json
from pathlib import Path

from azure.cosmos.exceptions import CosmosHttpResponseError

from querylens.adapters.cosmos import (
    aggregate_query_headers,
    extract_error_details,
    parse_index_utilization_header,
    parse_query_metrics_header,
)
from querylens.model import QueryDefinition


class TestCosmosParsing:
    """Tests covering HTTP header extraction from Azure Cosmos DB responses."""

    def test_parse_query_metrics_header_fixture(self) -> None:
        """Parse real Cosmos DB query metrics header from fixture file."""
        fixture_path = Path("tests/fixtures/headers/query_metrics.txt")
        raw_header = fixture_path.read_text(encoding="utf-8").strip()

        metrics = parse_query_metrics_header(raw_header)
        assert metrics["retrievedDocumentCount"] == 450
        assert metrics["outputDocumentCount"] == 12
        assert metrics["totalExecutionTimeInMs"] == 14.25

    def test_parse_query_metrics_header_empty_or_malformed(self) -> None:
        """Handle empty or malformed metrics string without crashing."""
        empty_metrics = parse_query_metrics_header("")
        assert empty_metrics["retrievedDocumentCount"] == 0
        assert empty_metrics["outputDocumentCount"] == 0
        assert empty_metrics["totalExecutionTimeInMs"] == 0.0

        malformed_metrics = parse_query_metrics_header(
            "invalid;bad_token=;retrievedDocumentCount=10"
        )
        assert malformed_metrics["retrievedDocumentCount"] == 10
        assert malformed_metrics["outputDocumentCount"] == 0

    def test_parse_index_utilization_header(self) -> None:
        """Decode base64 encoded index utilization JSON payload."""
        payload = {
            "UtilizedSingleIndexes": [{"IndexSpec": "/category/?"}],
            "PotentialSingleIndexes": [{"IndexSpec": "/total/?"}],
            "UtilizedCompositeIndexes": [],
            "PotentialCompositeIndexes": [],
        }
        b64_str = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")

        index_metrics = parse_index_utilization_header(b64_str)
        assert index_metrics is not None
        assert len(index_metrics.utilized_single) == 1
        assert index_metrics.utilized_single[0]["IndexSpec"] == "/category/?"
        assert len(index_metrics.potential_single) == 1
        assert index_metrics.potential_single[0]["IndexSpec"] == "/total/?"

    def test_parse_index_utilization_header_invalid_base64(self) -> None:
        """Return None when header contains invalid base64 or invalid json."""
        assert parse_index_utilization_header(None) is None
        assert parse_index_utilization_header("") is None
        assert parse_index_utilization_header("not-valid-base64===") is None

    def test_aggregate_query_headers_multi_page_cross_partition(self) -> None:
        """Aggregate metrics across multiple partitions with distinct partition key range IDs."""
        page1_headers = {
            "x-ms-request-charge": "12.5",
            "x-ms-documentdb-partitionkeyrangeid": "0",
            "x-ms-documentdb-query-metrics": (
                "retrievedDocumentCount=100;outputDocumentCount=5;totalExecutionTimeInMs=10.0"
            ),
        }
        page2_headers = {
            "x-ms-request-charge": "15.0",
            "x-ms-documentdb-partitionkeyrangeid": "1",
            "x-ms-documentdb-query-metrics": (
                "retrievedDocumentCount=200;outputDocumentCount=10;totalExecutionTimeInMs=12.5"
            ),
        }

        agg = aggregate_query_headers([page1_headers, page2_headers])
        assert agg["request_charge"] == 27.5
        assert agg["documents_scanned"] == 300
        assert agg["documents_returned"] == 15
        assert agg["latency_ms"] == 22.5
        assert agg["is_cross_partition"] is True

    def test_aggregate_query_headers_single_partition_multi_page(self) -> None:
        """Do not flag cross-partition when all pages share the same partition key range ID."""
        page1_headers = {
            "x-ms-request-charge": "5.0",
            "x-ms-documentdb-partitionkeyrangeid": "0",
            "x-ms-documentdb-query-metrics": (
                "retrievedDocumentCount=50;outputDocumentCount=25;totalExecutionTimeInMs=4.0"
            ),
        }
        page2_headers = {
            "x-ms-request-charge": "4.5",
            "x-ms-documentdb-partitionkeyrangeid": "0",
            "x-ms-documentdb-query-metrics": (
                "retrievedDocumentCount=40;outputDocumentCount=20;totalExecutionTimeInMs=3.5"
            ),
        }

        agg = aggregate_query_headers([page1_headers, page2_headers])
        assert agg["request_charge"] == 9.5
        assert agg["documents_scanned"] == 90
        assert agg["documents_returned"] == 45
        assert agg["is_cross_partition"] is False

    def test_aggregate_query_headers_partition_key_set_never_cross_partition(self) -> None:
        """Never flag cross-partition when query_def has partition_key explicitly configured."""
        page1_headers = {
            "x-ms-request-charge": "10.0",
            "x-ms-documentdb-partitionkeyrangeid": "0",
            "x-ms-documentdb-query-metrics": (
                "retrievedDocumentCount=10;outputDocumentCount=5;totalExecutionTimeInMs=2.0"
            ),
        }
        page2_headers = {
            "x-ms-request-charge": "10.0",
            "x-ms-documentdb-partitionkeyrangeid": "1",
            "x-ms-documentdb-query-metrics": (
                "retrievedDocumentCount=10;outputDocumentCount=5;totalExecutionTimeInMs=2.0"
            ),
        }
        query_def = QueryDefinition(
            id="q_single",
            query="SELECT * FROM c WHERE c.category = 'cat-1'",
            partition_key="cat-1",
        )

        agg = aggregate_query_headers([page1_headers, page2_headers], query_def=query_def)
        assert agg["is_cross_partition"] is False

    def test_extract_error_details_nested_json_with_activity_id(self) -> None:
        """Extract concise error message and activity id from raw Cosmos DB exception payload."""
        raw_msg = (
            'Message: {"errors":[{"severity":"Error","location":{"start":31,"end":35},'
            '"code":"SC1001","message":"Syntax error, incorrect syntax near \'FROM\'."}]}\r\n'
            "ActivityId: 64b85590-b146-444e-a10c-ca14923eef12, "
            "Microsoft.Azure.Documents.Common/2.14.0"
        )
        exc = CosmosHttpResponseError(status_code=400, message=raw_msg)
        msg, act_id = extract_error_details(exc)
        assert msg == "HTTP 400: Syntax error, incorrect syntax near 'FROM'."
        assert act_id == "64b85590-b146-444e-a10c-ca14923eef12"

    def test_extract_error_details_from_response_headers(self) -> None:
        """Extract activity id preferentially from HTTP response headers if available."""
        exc = CosmosHttpResponseError(status_code=400, message="Malformed query request")
        exc.headers = {"x-ms-activity-id": "header-act-id-123"}
        msg, act_id = extract_error_details(exc)
        assert msg == "HTTP 400: Malformed query request"
        assert act_id == "header-act-id-123"

    def test_extract_error_details_fallback_strips_activity_id_and_code(self) -> None:
        """Fallback cleans raw text when JSON errors array is not present in message."""
        raw_msg = "(BadRequest) Message: Query syntax error\r\nActivityId: abc-123"
        exc = CosmosHttpResponseError(status_code=400, message=raw_msg)
        msg, act_id = extract_error_details(exc)
        assert msg == "HTTP 400: Query syntax error"
        assert act_id == "abc-123"

    def test_extract_error_details_rbac_errors_string_array(self) -> None:
        """Extract concise message from realistic Cosmos RBAC 403 Errors string array."""
        raw_msg = (
            '(Forbidden) Message: {"Errors":["The requested operation cannot be performed '
            "because the principal does not have the required data plane action "
            "'Microsoft.DocumentDB/databaseAccounts/readMetadata'.\"]}\r\n"
            "ActivityId: 6f846d0c-60db-4fc4-ba65-c33503aa2b1d, Request URI: rntbd://...\r\n"
            "Microsoft.Azure.Cosmos.Direct/2.14.0"
        )
        exc = CosmosHttpResponseError(status_code=403, message=raw_msg)
        msg, act_id = extract_error_details(exc)
        expected = (
            "HTTP 403: The requested operation cannot be performed because the principal "
            "does not have the required data plane action "
            "'Microsoft.DocumentDB/databaseAccounts/readMetadata'."
        )
        assert msg == expected
        assert act_id == "6f846d0c-60db-4fc4-ba65-c33503aa2b1d"
