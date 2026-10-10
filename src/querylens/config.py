"""Configuration settings for QueryLens using pydantic-settings."""

from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration settings for QueryLens CLI and profiler engine."""

    # Target Connection
    endpoint: str = ""
    database: str = ""
    container: str = ""
    cosmos_key: SecretStr | None = None  # ONLY permitted for localhost/emulator

    # Execution & Safety
    ru_budget: float | None = None
    max_item_count: int = 100
    debug: bool = False
    fail_on: Literal["critical", "high", "medium"] | None = None

    # Rule Thresholds
    high_ru_warning: float = 50.0
    high_ru_critical: float = 200.0
    scan_gap_ratio_warning: float = 10.0
    scan_gap_ratio_critical: float = 100.0
    scan_gap_absolute_threshold: int = 1000

    model_config = SettingsConfigDict(
        env_prefix="QUERYLENS_",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("fail_on", mode="before")
    @classmethod
    def normalize_fail_on(cls, v: str | None) -> str | None:
        """Normalize fail_on string to lower case if provided.

        Args:
            v: The input fail_on value.

        Returns:
            Normalized lower-case string or None.

        Raises:
            ValueError: If the severity value is not recognized.
        """
        if v is None:
            return None
        v_str = str(v).strip().lower()
        if not v_str:
            return None
        if v_str not in ("critical", "high", "medium"):
            raise ValueError(
                f"Invalid --fail-on value: '{v}'. Must be 'critical', 'high', or 'medium'."
            )
        return v_str

    @field_validator("endpoint")
    @classmethod
    def validate_https_endpoint(cls, v: str) -> str:
        """Ensure endpoint uses HTTPS protocol.

        Args:
            v: The input endpoint string.

        Returns:
            Validated endpoint string.

        Raises:
            ValueError: If endpoint does not start with https://.
        """
        if v:
            stripped = v.strip()
            if not stripped.startswith("https://"):
                raise ValueError(f"Endpoint must use HTTPS protocol: '{v}'. HTTP is not permitted.")
            return stripped
        return v
