"""CLI command handler for querylens discover."""

import sys

import click
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ServiceRequestError,
    ServiceRequestTimeoutError,
)
from azure.identity import DefaultAzureCredential
from azure.monitor.query import LogsQueryClient
from rich.console import Console

from querylens.discovery.kql import (
    build_preflight_check_query,
    build_shapes_query,
    build_totals_query,
)
from querylens.discovery.models import (
    DiscoveryOptions,
    DiscoveryValidationError,
    TelemetryMisconfigurationError,
)
from querylens.discovery.service import run_discovery
from querylens.report.discover_console import (
    render_discover_console_report,
)
from querylens.report.discover_json import (
    serialize_discovery_json,
)


def get_logs_client() -> LogsQueryClient:
    """Instantiate and return an Azure Monitor LogsQueryClient with Entra ID credentials."""
    credential = DefaultAzureCredential()
    return LogsQueryClient(credential=credential)


@click.command(name="discover")
@click.option(
    "-w",
    "--workspace-id",
    envvar="QUERYLENS_WORKSPACE_ID",
    required=True,
    help="Target Azure Log Analytics workspace GUID (RFC 4122 UUID).",
)
@click.option(
    "-a",
    "--account",
    "account_filter",
    default=None,
    help="Optional Cosmos DB account name to filter diagnostic records.",
)
@click.option(
    "-t",
    "--time-window",
    default="24h",
    help="Lookback time window duration (e.g. '1h', '24h', '7d'). Default: 24h.",
)
@click.option(
    "-n",
    "--top",
    "top_n",
    default=20,
    type=int,
    help="Maximum number of query shapes to return (1-100). Default: 20.",
)
@click.option(
    "--timeout",
    "server_timeout_seconds",
    default=180,
    type=int,
    help="Azure Monitor query server timeout in seconds (10-600). Default: 180.",
)
@click.option(
    "--print-kql",
    is_flag=True,
    default=False,
    help="Build and print generated KQL queries to stdout without network calls or credentials.",
)
@click.option(
    "--show-text",
    is_flag=True,
    default=False,
    help="Expose full obfuscated query text without 200-char truncation.",
)
@click.option(
    "--check",
    "check_only",
    is_flag=True,
    default=False,
    help="Execute preflight diagnostic telemetry inspection instead of discovery.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Output machine-readable JSON to stdout.",
)
def discover(
    workspace_id: str,
    account_filter: str | None,
    time_window: str,
    top_n: int,
    server_timeout_seconds: int,
    print_kql: bool,
    show_text: bool,
    check_only: bool,
    json_output: bool,
) -> None:
    """Discover high-cost Cosmos DB query shapes from Azure Log Analytics diagnostic logs."""
    err_console = Console(stderr=True)

    # Validate options
    try:
        options = DiscoveryOptions(
            workspace_id=workspace_id,  # type: ignore[arg-type]
            account_filter=account_filter,
            time_window=time_window,  # type: ignore[arg-type]
            top_n=top_n,
            server_timeout_seconds=server_timeout_seconds,
            show_text=show_text,
            check_only=check_only,
            print_kql=print_kql,
            json_output=json_output,
        )
    except (DiscoveryValidationError, ValueError) as err:
        err_console.print(f"[bold red]Error:[/bold red] {err}")
        sys.exit(1)

    # Offline KQL inspection
    if options.print_kql:
        if options.check_only:
            check_kql = build_preflight_check_query(account_filter=options.account_filter)
            click.echo("// === Preflight Diagnostic Check Query ===")
            click.echo(check_kql)
            sys.exit(0)

        shapes_kql = build_shapes_query(top_n=options.top_n, account_filter=options.account_filter)
        totals_kql = build_totals_query(account_filter=options.account_filter)

        click.echo("// Run each query separately in the Logs editor.")
        click.echo("// === Query 1: Top Query Shapes Query ===")
        click.echo(shapes_kql)
        click.echo("\n// === Query 2: Window & Attributed Totals Query ===")
        click.echo(totals_kql)
        sys.exit(0)

    # Check mode handler (stubbed for US2 implementation)
    if options.check_only:
        # Handled in Phase 4 / US2
        from querylens.discovery.service import run_preflight_check
        from querylens.report.discover_console import render_check_console_report
        from querylens.report.discover_json import serialize_check_json

        try:
            client = get_logs_client()
            check_report = run_preflight_check(options, client=client)
            if options.json_output:
                click.echo(serialize_check_json(check_report))
            else:
                render_check_console_report(check_report)
            sys.exit(0)
        except ClientAuthenticationError as err:
            err_console.print(f"[bold red]Authentication Error:[/bold red] {err}")
            sys.exit(5)
        except HttpResponseError as err:
            if err.status_code in (401, 403):
                err_console.print(f"[bold red]Authorization Error:[/bold red] {err}")
                sys.exit(5)
            if err.status_code == 404:
                err_console.print(f"[bold red]Workspace Not Found:[/bold red] {err}")
                sys.exit(3)
            err_console.print(f"[bold red]API Error:[/bold red] {err}")
            sys.exit(1)
        except (ServiceRequestError, ServiceRequestTimeoutError) as err:
            err_console.print(f"[bold red]Connection Error:[/bold red] {err}")
            sys.exit(3)

    # Standard discovery execution
    try:
        client = get_logs_client()
        summary = run_discovery(options=options, client=client)

        if options.json_output:
            click.echo(serialize_discovery_json(summary, show_text=options.show_text))
        else:
            render_discover_console_report(summary, show_text=options.show_text)
        sys.exit(0)

    except TelemetryMisconfigurationError as err:
        err_console.print(f"[bold red]Error:[/bold red] {err}")
        sys.exit(1)
    except ClientAuthenticationError as err:
        err_console.print(f"[bold red]Authentication Error:[/bold red] {err}")
        sys.exit(5)
    except HttpResponseError as err:
        if err.status_code in (401, 403):
            err_console.print(f"[bold red]Authorization Error:[/bold red] {err}")
            sys.exit(5)
        if err.status_code == 404:
            err_console.print(f"[bold red]Workspace Not Found:[/bold red] {err}")
            sys.exit(3)
        err_console.print(f"[bold red]API Error:[/bold red] {err}")
        sys.exit(1)
    except (ServiceRequestError, ServiceRequestTimeoutError) as err:
        err_console.print(f"[bold red]Connection Error:[/bold red] {err}")
        sys.exit(3)
