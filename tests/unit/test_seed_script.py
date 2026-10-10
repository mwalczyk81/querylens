"""Unit tests for emulator seeding script validation."""

import pytest
from seed_emulator import validate_local_endpoint


class TestSeedEmulatorValidation:
    """Verify endpoint validation constraints for seed_emulator script."""

    def test_allow_localhost_endpoints(self) -> None:
        """Allow localhost and 127.0.0.1 emulator endpoints."""
        validate_local_endpoint("https://localhost:8081/")
        validate_local_endpoint("https://127.0.0.1:8081/")
        validate_local_endpoint("http://localhost:8081/")

    def test_reject_remote_endpoints(self) -> None:
        """Reject remote Azure Cosmos DB endpoints to prevent accidental writes."""
        with pytest.raises(ValueError, match="ONLY permitted for local emulator"):
            validate_local_endpoint("https://myaccount.documents.azure.com:443/")

        with pytest.raises(ValueError, match="ONLY permitted for local emulator"):
            validate_local_endpoint("https://cosmos.azure.com/")
