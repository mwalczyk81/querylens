"""Atheris fuzz target for parse_index_utilization_header."""

import sys

try:
    import atheris
except ImportError:
    print("Atheris is required to run this fuzz target. Install atheris or run via Docker.")
    sys.exit(1)

with atheris.instrument_imports():
    from querylens.adapters.cosmos import parse_index_utilization_header
    from querylens.model import IndexUtilization


def TestOneInput(data: bytes) -> None:
    """Fuzz parse_index_utilization_header with arbitrary unicode strings."""
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    result = parse_index_utilization_header(text)
    assert result is None or isinstance(result, IndexUtilization)


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
