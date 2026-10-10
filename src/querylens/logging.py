"""Structured logging configuration for QueryLens using structlog."""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog


def drop_payload_keys(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Safety filter ensuring sensitive payload dictionaries are never logged.

    Args:
        _logger: Unused logger reference.
        _method_name: Unused method name.
        event_dict: Event dictionary containing log fields.

    Returns:
        dict[str, Any]: Filtered event dictionary with payload fields scrubbed.
    """
    blacklisted_keys = {
        "payload",
        "document",
        "documents",
        "item",
        "items",
        "body",
        "response_body",
    }
    for key in list(event_dict.keys()):
        if key.lower() in blacklisted_keys:
            event_dict[key] = "<REDACTED_PAYLOAD>"
    return event_dict


def configure_logging(debug: bool = False, json_format: bool = False) -> None:
    """Configure structlog and standard logging to stderr.

    All log records are routed to stderr to ensure that stdout remains
    exclusively reserved for clean JSON output when --json is used.

    Args:
        debug: If True, set log level to DEBUG; otherwise INFO.
        json_format: If True, render logs as structured JSON lines on stderr.
    """
    log_level = logging.DEBUG if debug else logging.INFO

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        drop_payload_keys,
    ]

    if json_format:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Silence verbose Azure SDK internal logs unless debug is explicitly enabled
    azure_logger = logging.getLogger("azure")
    azure_logger.setLevel(logging.DEBUG if debug else logging.WARNING)
