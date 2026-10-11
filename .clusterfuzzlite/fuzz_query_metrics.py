"""Atheris fuzz target for parse_query_metrics_header."""

import sys

try:
    import atheris
except ImportError:
    print("Atheris is required to run this fuzz target. Install atheris or run via Docker.")
    sys.exit(1)

with atheris.instrument_imports():
    from querylens.adapters.cosmos import parse_query_metrics_header


def TestOneInput(data: bytes) -> None:
    """Fuzz parse_query_metrics_header with arbitrary unicode strings."""
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(fdp.remaining_bytes())
    metrics = parse_query_metrics_header(text)
    assert isinstance(metrics, dict)
    assert "retrievedDocumentCount" in metrics
    assert "outputDocumentCount" in metrics
    assert "totalExecutionTimeInMs" in metrics


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
