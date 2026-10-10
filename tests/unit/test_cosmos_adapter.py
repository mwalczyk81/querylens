"""Unit tests for CosmosAdapter security rules, initialization, and execution."""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from azure.cosmos.exceptions import CosmosHttpResponseError

from querylens.adapters.cosmos import CosmosAdapter
from querylens.config import Settings
from querylens.model import QueryDefinition, Workload


class TestCosmosAdapter:
    """Tests covering CosmosAdapter behavior and constraints."""

    def test_init_local_emulator_key_allowed(self) -> None:
        """Allow cosmos_key when endpoint points to localhost."""
        settings = Settings(
            endpoint="https://localhost:8081/",
            cosmos_key="emulator-key",
            database="db",
            container="c",
        )
        with patch("querylens.adapters.cosmos.CosmosClient") as mock_client:
            adapter = CosmosAdapter(settings)
            assert adapter.client is not None
            mock_client.assert_called_once()

    def test_init_remote_key_rejected(self) -> None:
        """Reject cosmos_key when endpoint points to remote Azure account."""
        settings = Settings(
            endpoint="https://myaccount.documents.azure.com:443/",
            cosmos_key="master-key-disallowed",
            database="db",
            container="c",
        )
        with pytest.raises(ValueError) as exc_info:
            CosmosAdapter(settings)
        assert "ONLY permitted for local emulator" in str(exc_info.value)

    def test_collect_missing_database_raises_value_error(self) -> None:
        """Raise ValueError if neither workload nor settings specify database."""
        settings = Settings(endpoint="https://localhost:8081/")
        with patch("querylens.adapters.cosmos.CosmosClient"):
            adapter = CosmosAdapter(settings)
            workload = Workload(queries=[QueryDefinition(id="q1", query="SELECT * FROM c")])
            with pytest.raises(ValueError) as exc_info:
                list(adapter.collect(workload))
            assert "database and container must be specified" in str(exc_info.value)

    def test_collect_query_execution_success(self) -> None:
        """Execute queries and capture cost metrics discarding payload."""
        settings = Settings(
            endpoint="https://localhost:8081/",
            database="testdb",
            container="testc",
        )
        with patch("querylens.adapters.cosmos.CosmosClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_db = MagicMock()
            mock_container = MagicMock()
            mock_client.get_database_client.return_value = mock_db
            mock_db.get_container_client.return_value = mock_container

            # Create mock paged item returning 1 page with 2 documents
            mock_paged = MagicMock()
            mock_page = [{"id": "item1", "secret": "data1"}, {"id": "item2", "secret": "data2"}]

            def fake_by_page() -> Iterator[list[dict[str, str]]]:
                yield mock_page

            mock_paged.by_page.side_effect = fake_by_page

            def fake_query_items(*args: object, **kwargs: object) -> MagicMock:
                hook = kwargs.get("response_hook")
                if callable(hook):
                    hook(
                        {
                            "x-ms-request-charge": "8.5",
                            "x-ms-documentdb-query-metrics": (
                                "retrievedDocumentCount=20;outputDocumentCount=2;"
                                "totalExecutionTimeInMs=12.0"
                            ),
                        },
                        {},
                    )
                return mock_paged

            mock_container.query_items.side_effect = fake_query_items

            adapter = CosmosAdapter(settings)
            workload = Workload(
                database="testdb",
                container="testc",
                queries=[QueryDefinition(id="q1", query="SELECT * FROM c")],
            )

            results = list(adapter.collect(workload))
            assert len(results) == 1
            cost = results[0]
            assert cost.query_id == "q1"
            assert cost.request_charge == 8.5
            assert cost.documents_scanned == 20
            assert cost.documents_returned == 2
            assert cost.latency_ms == 12.0

    def test_collect_query_syntax_error(self) -> None:
        """Handle individual query error without aborting entire workload."""
        settings = Settings(
            endpoint="https://localhost:8081/",
            database="testdb",
            container="testc",
        )
        with patch("querylens.adapters.cosmos.CosmosClient") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value = mock_client
            mock_db = MagicMock()
            mock_container = MagicMock()
            mock_client.get_database_client.return_value = mock_db
            mock_db.get_container_client.return_value = mock_container

            mock_paged = MagicMock()
            mock_paged.by_page.side_effect = CosmosHttpResponseError(
                status_code=400, message="Syntax error near SELECT"
            )
            mock_container.query_items.return_value = mock_paged

            adapter = CosmosAdapter(settings)
            workload = Workload(
                database="testdb",
                container="testc",
                queries=[QueryDefinition(id="q1", query="INVALID SQL")],
            )

            results = list(adapter.collect(workload))
            assert len(results) == 1
            assert results[0].error_message is not None
            assert "Syntax error" in results[0].error_message
