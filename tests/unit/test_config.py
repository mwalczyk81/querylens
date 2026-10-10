"""Unit tests for QueryLens Settings configuration."""

import pytest
from pydantic import ValidationError

from querylens.config import Settings


class TestSettings:
    """Tests covering configuration settings defaults and validation."""

    def test_default_settings(self) -> None:
        """Verify default settings values."""
        settings = Settings()
        assert settings.endpoint == ""
        assert settings.database == ""
        assert settings.container == ""
        assert settings.cosmos_key is None
        assert settings.ru_budget is None
        assert settings.max_item_count == 100
        assert settings.debug is False
        assert settings.fail_on is None
        assert settings.high_ru_warning == 50.0
        assert settings.high_ru_critical == 200.0
        assert settings.scan_gap_ratio_warning == 10.0
        assert settings.scan_gap_ratio_critical == 100.0
        assert settings.scan_gap_absolute_threshold == 1000

    @pytest.mark.parametrize(
        ("input_val", "expected"),
        [
            ("critical", "critical"),
            ("CRITICAL", "critical"),
            ("high", "high"),
            ("HIGH", "high"),
            ("medium", "medium"),
            ("MEDIUM", "medium"),
            (None, None),
            ("", None),
        ],
    )
    def test_fail_on_normalization(self, input_val: str | None, expected: str | None) -> None:
        """Normalize fail_on casing to lowercase."""
        settings = Settings(fail_on=input_val)  # pyrefly: ignore
        assert settings.fail_on == expected

    def test_invalid_fail_on_rejected(self) -> None:
        """Reject invalid fail_on severity values."""
        with pytest.raises(ValidationError) as exc_info:
            Settings(fail_on="invalid_severity")  # pyrefly: ignore
        assert "Invalid --fail-on value" in str(exc_info.value)

    def test_cosmos_key_secret_str(self) -> None:
        """Verify cosmos_key is stored as SecretStr and not exposed in repr."""
        settings = Settings(cosmos_key="secret-master-key-xyz")  # pyrefly: ignore
        assert settings.cosmos_key is not None
        assert settings.cosmos_key.get_secret_value() == "secret-master-key-xyz"
        assert "secret-master-key-xyz" not in repr(settings.cosmos_key)
        assert "secret-master-key-xyz" not in repr(settings)

    def test_endpoint_https_validation(self) -> None:
        """Reject non-HTTPS endpoints and accept valid HTTPS endpoints."""
        settings = Settings(endpoint="https://localhost:8081/")
        assert settings.endpoint == "https://localhost:8081/"

        with pytest.raises(ValidationError) as exc_info:
            Settings(endpoint="http://localhost:8081/")
        assert "Endpoint must use HTTPS protocol" in str(exc_info.value)

        with pytest.raises(ValidationError) as exc_info:
            Settings(endpoint="ftp://cosmos.azure.com/")
        assert "Endpoint must use HTTPS protocol" in str(exc_info.value)
