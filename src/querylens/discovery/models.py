"""Domain models, configuration options, and custom exceptions for discovery."""

import re
from datetime import datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# --- Custom Exceptions ---


class DiscoveryValidationError(ValueError):
    """Raised when CLI arguments or input options fail validation."""


class TelemetryMisconfigurationError(RuntimeError):
    """Raised by the Silent-Zero Guard when diagnostic telemetry is misconfigured."""


class DiscoveryConnectionError(ConnectionError):
    """Raised when communication with Azure Monitor Log Analytics fails or times out."""


class DiscoveryAuthError(PermissionError):
    """Raised when authentication or RBAC authorization fails."""


class InternalConsistencyError(RuntimeError):
    """Raised when an internal mathematical invariant (coverage ratio, RU share) is violated."""


# --- Validation Helpers ---

ACCOUNT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][-a-zA-Z0-9]{1,42}[a-zA-Z0-9]$")
MASKED_WORKSPACE_PATTERN = re.compile(r"^\.\.\.[0-9a-fA-F]{4}$")
DURATION_PATTERN = re.compile(r"^([1-9][0-9]*)([mhd])$")

MIN_DURATION = timedelta(minutes=5)
MAX_DURATION = timedelta(days=90)


def parse_duration_string(val: str | timedelta) -> timedelta:
    """Parse a duration string (e.g., '1h', '24h', '7d') into a bounded timedelta.

    Args:
        val: Input duration string or timedelta.

    Returns:
        Validated timedelta between 5 minutes and 90 days.

    Raises:
        DiscoveryValidationError: If duration string format or bounds are invalid.
    """
    if isinstance(val, timedelta):
        td = val
    elif isinstance(val, str):
        match = DURATION_PATTERN.match(val.strip().lower())
        if not match:
            msg = f"Invalid time window '{val}'. Must match format '<number>[m|h|d]' (e.g. '24h')."
            raise DiscoveryValidationError(msg)
        amount, unit = int(match.group(1)), match.group(2)
        if unit == "m":
            td = timedelta(minutes=amount)
        elif unit == "h":
            td = timedelta(hours=amount)
        elif unit == "d":
            td = timedelta(days=amount)
        else:
            raise DiscoveryValidationError(f"Unknown time unit '{unit}' in '{val}'.")
    else:
        raise DiscoveryValidationError(f"Invalid duration type: {type(val)}")

    if td < MIN_DURATION or td > MAX_DURATION:
        raise DiscoveryValidationError(
            f"Time window {td} out of bounds. Must be between 5m and 90d."
        )
    return td


# --- Discovery Options ---


class DiscoveryOptions(BaseModel):
    """Configuration options for querylens discover CLI and execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: UUID
    account_filter: str | None = None
    time_window: timedelta = timedelta(hours=24)
    top_n: int = Field(default=20, ge=1, le=100)
    server_timeout_seconds: int = Field(default=180, ge=10, le=600)
    show_text: bool = False
    check_only: bool = False
    print_kql: bool = False
    json_output: bool = False

    @field_validator("workspace_id", mode="before")
    @classmethod
    def validate_workspace_id(cls, v: object) -> UUID:
        """Validate that workspace_id is a valid UUID."""
        if isinstance(v, UUID):
            return v
        if isinstance(v, str):
            try:
                return UUID(v.strip())
            except (ValueError, AttributeError) as err:
                raise DiscoveryValidationError(
                    f"Invalid workspace ID '{v}'. Must be a valid RFC 4122 UUID."
                ) from err
        raise DiscoveryValidationError(f"Invalid workspace ID type: {type(v)}")

    @field_validator("account_filter", mode="before")
    @classmethod
    def validate_account_filter(cls, v: object) -> str | None:
        """Validate account filter matches Cosmos DB account naming rules."""
        if v is None:
            return None
        if not isinstance(v, str):
            raise DiscoveryValidationError("Account filter must be a string.")
        val = v.strip()
        if not val:
            return None
        if not ACCOUNT_NAME_PATTERN.match(val):
            msg = f"Invalid account filter '{val}'. Must match Cosmos DB account naming pattern."
            raise DiscoveryValidationError(msg)
        return val

    @field_validator("time_window", mode="before")
    @classmethod
    def validate_time_window(cls, v: object) -> timedelta:
        """Validate and parse time window."""
        if isinstance(v, (str, timedelta)):
            return parse_duration_string(v)
        raise DiscoveryValidationError(f"Invalid time window type: {type(v)}")


# --- Domain Models ---


class CallerAttribution(BaseModel):
    """Caller identity and RU attribution for a query shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identifier: Annotated[str, Field(min_length=1)]
    ru_share_pct: Annotated[float, Field(ge=0.0, le=100.05)]
    identifier_type: Literal["aad_principal", "client_ip"]


class DiscoveredQueryShape(BaseModel):
    """Aggregated performance and cost metrics for a distinct query shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    database: str = "(unknown)"
    container: str = "(unknown)"
    shape_id: Annotated[str, Field(min_length=1)]
    sample_query_text: str | None = None
    execution_count: Annotated[int, Field(ge=1)]
    total_ru: Annotated[float, Field(ge=0.0)]
    avg_ru: Annotated[float, Field(ge=0.0)]
    max_ru: Annotated[float, Field(ge=0.0)]
    ru_share_pct: Annotated[float, Field(ge=0.0, le=100.0)]
    avg_returned_rows: Annotated[float, Field(ge=0.0)]
    ru_per_returned_row: float | None = Field(default=None, ge=0.0)
    throttled_count: Annotated[int, Field(ge=0)]
    top_callers: list[CallerAttribution] = Field(default_factory=list, max_length=3)

    @field_validator("database", "container", mode="before")
    @classmethod
    def default_empty_to_unknown(cls, v: object) -> str:
        """Default empty, whitespace, or None values to '(unknown)'."""
        if v is None:
            return "(unknown)"
        s = str(v).strip()
        return s if s else "(unknown)"


class WorkloadDiscoverySummary(BaseModel):
    """Top-level summary entity returned by querylens discover."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    window_start: datetime
    window_end: datetime
    total_ru: Annotated[float, Field(ge=0.0)]
    attributed_total_ru: Annotated[float, Field(ge=0.0)]
    unattributed_ru: Annotated[float, Field(ge=0.0)]
    unattributed_ru_pct: Annotated[float, Field(ge=0.0, le=100.0)]
    discovered_query_count: Annotated[int, Field(ge=0)]
    results: list[DiscoveredQueryShape]
    retention_warning: bool
    masked_workspace_id: Annotated[str, Field(pattern=r"^\.\.\.[0-9a-fA-F]{4}$")]

    @model_validator(mode="after")
    def validate_window_range(self) -> "WorkloadDiscoverySummary":
        """Verify window_end is greater than or equal to window_start."""
        if self.window_end < self.window_start:
            raise ValueError("window_end cannot be before window_start")
        return self


class PreflightCheckReport(BaseModel):
    """Quantitative diagnostic summary of Log Analytics workspace telemetry readiness."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    categories_detected: list[str]
    row_counts: dict[str, int]
    window_start: datetime
    window_end: datetime
    earliest_record: datetime | None = None
    latest_record: datetime | None = None
    field_coverage: dict[str, float]
    auth_breakdown: dict[str, int]
    retention_warning: bool
    masked_workspace_id: Annotated[str, Field(pattern=r"^\.\.\.[0-9a-fA-F]{4}$")]
