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
