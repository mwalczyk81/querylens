"""Atheris fuzz target for parse_duration_string."""

import sys
from datetime import timedelta

try:
    import atheris
except ImportError:
    print("Atheris is required to run this fuzz target. Install atheris or run via Docker.")
    sys.exit(1)

with atheris.instrument_imports():
    from querylens.discovery.models import (
        MAX_DURATION,
        MIN_DURATION,
        DiscoveryValidationError,
        parse_duration_string,
    )


def TestOneInput(data: bytes) -> None:
    """Fuzz parse_duration_string with arbitrary unicode strings."""
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    try:
        td = parse_duration_string(text)
        assert isinstance(td, timedelta)
        assert MIN_DURATION <= td <= MAX_DURATION
    except DiscoveryValidationError:
        pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
