"""Atheris fuzz target for DiscoveryOptions validators."""

import sys

try:
    import atheris
except ImportError:
    print("Atheris is required to run this fuzz target. Install atheris or run via Docker.")
    sys.exit(1)

with atheris.instrument_imports():
    from pydantic import ValidationError

    from querylens.discovery.models import DiscoveryOptions, DiscoveryValidationError


def TestOneInput(data: bytes) -> None:
    """Fuzz DiscoveryOptions fields and validators."""
    fdp = atheris.FuzzedDataProvider(data)
    workspace = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 50))
    account = (
        None if fdp.ConsumeBool() else fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 60))
    )
    window = fdp.ConsumeUnicodeNoSurrogates(fdp.ConsumeIntInRange(0, 20))
    top_n = fdp.ConsumeIntInRange(-50, 200)
    timeout = fdp.ConsumeIntInRange(-50, 1000)
    show_text = fdp.ConsumeBool()
    check_only = fdp.ConsumeBool()
    print_kql = fdp.ConsumeBool()
    json_output = fdp.ConsumeBool()

    try:
        DiscoveryOptions(
            workspace_id=workspace,  # type: ignore[arg-type]
            account_filter=account,
            time_window=window,  # type: ignore[arg-type]
            top_n=top_n,
            server_timeout_seconds=timeout,
            show_text=show_text,
            check_only=check_only,
            print_kql=print_kql,
            json_output=json_output,
        )
    except (DiscoveryValidationError, ValidationError, ValueError, TypeError, OverflowError):
        pass


def main() -> None:
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
