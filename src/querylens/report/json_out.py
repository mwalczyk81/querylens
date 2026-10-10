"""JSON output serialization for QueryLens conforming to run-output-schema.json."""

import json
from typing import Any

from querylens.model import WorkloadRunSummary


def serialize_summary_json(summary: WorkloadRunSummary, indent: int = 2) -> str:
    """Serialize WorkloadRunSummary to JSON matching run-output-schema.json.

    Args:
        summary: The WorkloadRunSummary object to serialize.
        indent: Indentation level for pretty-printed JSON (default: 2).

    Returns:
        str: Validated JSON string.
    """
    raw_dict: dict[str, Any] = summary.model_dump(mode="json")
    return json.dumps(raw_dict, indent=indent)
