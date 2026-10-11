"""Azure Cosmos DB diagnostic query cost discovery package.

This package provides server-side KQL aggregation, telemetry inspection,
and cost ranking over Cosmos DB diagnostic telemetry in Azure Log Analytics.
"""

from typing import Final

from querylens.discovery.models import InternalConsistencyError

__all__: Final[list[str]] = [
    "InternalConsistencyError",
]
