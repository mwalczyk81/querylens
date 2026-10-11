"""Atheris fuzz target for escape_kql_string."""

import sys

try:
    import atheris
except ImportError:
    print("Atheris is required to run this fuzz target. Install atheris or run via Docker.")
    sys.exit(1)

with atheris.instrument_imports():
    from querylens.discovery.kql import escape_kql_string


def TestOneInput(data: bytes) -> None:
    """Fuzz escape_kql_string with arbitrary unicode strings and check invariants."""
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    escaped = escape_kql_string(text)
    assert "\0" not in escaped
    assert "\r" not in escaped
    assert "\n" not in escaped
    assert "\t" not in escaped


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
