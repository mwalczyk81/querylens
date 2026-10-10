"""Unit tests for QueryLens logging configuration and payload redaction."""

import logging

from querylens.logging import configure_logging, drop_payload_keys


class TestLogging:
    """Tests covering logging setup and safety redaction."""

    def test_drop_payload_keys(self) -> None:
        """Verify blacklisted payload keys are replaced with <REDACTED_PAYLOAD>."""
        event_dict = {
            "event": "query executed",
            "payload": {"sensitive": "data"},
            "document": {"id": "1"},
            "documents": [{"id": "2"}],
            "item": {"val": 3},
            "items": [{"val": 4}],
            "body": "raw body",
            "response_body": '{"secret": true}',
            "request_charge": 12.5,
        }
        filtered = drop_payload_keys(None, "info", event_dict)

        assert filtered["payload"] == "<REDACTED_PAYLOAD>"
        assert filtered["document"] == "<REDACTED_PAYLOAD>"
        assert filtered["documents"] == "<REDACTED_PAYLOAD>"
        assert filtered["item"] == "<REDACTED_PAYLOAD>"
        assert filtered["items"] == "<REDACTED_PAYLOAD>"
        assert filtered["body"] == "<REDACTED_PAYLOAD>"
        assert filtered["response_body"] == "<REDACTED_PAYLOAD>"
        assert filtered["request_charge"] == 12.5

    def test_configure_logging_console(self) -> None:
        """Configure logging in standard console mode."""
        configure_logging(debug=False, json_format=False)
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_configure_logging_debug_and_json(self) -> None:
        """Configure logging in debug and json mode."""
        configure_logging(debug=True, json_format=True)
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG
