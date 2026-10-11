"""QueryLens Command Line Interface using Click."""

import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import click
import yaml
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.cosmos.exceptions import (
    CosmosClientTimeoutError,
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
)
from pydantic import ValidationError

from querylens.adapters.cosmos import (
    BudgetExceededError,
    CosmosAdapter,
    extract_error_details,
)
from querylens.adapters.protocol import DatabaseAdapter
from querylens.config import Settings
from querylens.discover_cli import discover
from querylens.logging import configure_logging
from querylens.model import (
    Finding,
    QueryResultSummary,
    Severity,
    Workload,
    WorkloadRunSummary,
)
from querylens.report.console import render_console_report
from querylens.report.json_out import serialize_summary_json
from querylens.rules import evaluate_rules

# Align Click usage errors with QueryLens exit code 1 (Validation / Usage Error)
# Click defaults UsageError to 2, which collides with QueryLens code 2 (RU Budget Exceeded).
click.exceptions.UsageError.exit_code = 1


def get_adapter(settings: Settings) -> DatabaseAdapter:
    """Factory creating database adapter instance.

    Args:
        settings: QueryLens runtime configuration.

    Returns:
        DatabaseAdapter: Instantiated adapter conforming to protocol.
    """
    return CosmosAdapter(settings)


def map_adapter_exception(exc: Exception) -> tuple[str, int]:
    """Map adapter exceptions to user-facing error message and exit code.

    Strips duplicated raw SDK banners, ActivityId, and stack traces, extracting concise messages.

    Args:
        exc: Exception caught during adapter instantiation or query collection.

    Returns:
        tuple[str, int]: (stderr_message, exit_code)
    """
    if isinstance(exc, ClientAuthenticationError):
        clean_msg = str(getattr(exc, "message", None) or exc).splitlines()[0].strip()
        return f"Authentication failure: {clean_msg}", 5

    if isinstance(exc, CosmosHttpResponseError):
        concise_msg, _ = extract_error_details(exc)
        clean_text = (
            concise_msg.removeprefix(f"HTTP {exc.status_code}: ")
            if exc.status_code
            else concise_msg
        )
        if exc.status_code == 403:
            hint = (
                "The identity needs the Cosmos DB Built-in Data Reader data-plane "
                "role on this account (Azure control-plane roles do not grant data access)."
            )
            return (
                f"Authentication / Authorization failure (HTTP 403): {clean_text}\n{hint}",
                5,
            )
        if exc.status_code == 401:
            return (
                f"Authentication / Authorization failure (HTTP 401): {clean_text}",
                5,
            )
        if exc.status_code == 404 or isinstance(exc, CosmosResourceNotFoundError):
            return f"Connection error: Resource not found: {clean_text}", 3
        if exc.status_code == 429:
            return (
                f"Rate limit exceeded (HTTP 429 RequestRateTooLarge): {clean_text}",
                3,
            )
        if exc.status_code is not None and exc.status_code >= 500:
            return f"Cosmos server error (HTTP {exc.status_code}): {clean_text}", 3
        return f"Cosmos HTTP error (status {exc.status_code}): {clean_text}", 3

    if isinstance(exc, (ServiceRequestError, CosmosClientTimeoutError)):
        clean_msg = (
            str(getattr(exc, "message", None) or exc)
            .split("ActivityId:")[0]
            .splitlines()[0]
            .strip()
        )
        return f"Connection error: {clean_msg}", 3

    clean_msg = str(getattr(exc, "message", None) or exc).splitlines()[0].strip()
    return f"Error: {clean_msg}", 3


def handle_adapter_exception(
    exc: Exception,
    *,
    before_exit: Callable[[], None] | None = None,
) -> NoReturn:
    """Print mapped adapter exception to stderr and exit with the appropriate status code.

    Args:
        exc: Exception caught during adapter instantiation or execution.
        before_exit: Optional callback invoked before exit if exit code is not 5.
    """
    msg, exit_code = map_adapter_exception(exc)
    if before_exit and exit_code != 5:
        before_exit()
    click.echo(msg, err=True)
    sys.exit(exit_code)


@click.group()
@click.option("--debug", is_flag=True, default=False, help="Enable verbose debug logging.")
@click.version_option(package_name="querylens")
@click.pass_context
def cli(ctx: click.Context, debug: bool) -> None:
    """QueryLens: Azure Cosmos DB Query Cost Profiler and Anti-Pattern Diagnoser."""
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug


@cli.command(name="run")
@click.argument("workload_file", type=click.Path(exists=False, dir_okay=False))
@click.option("-e", "--endpoint", default=None, help="Cosmos DB endpoint URL.")
@click.option("-d", "--database", default=None, help="Cosmos DB database name.")
@click.option("-c", "--container", default=None, help="Cosmos DB container name.")
@click.option("-b", "--ru-budget", type=float, default=None, help="Max cumulative RU budget limit.")
@click.option("--json", "json_output", is_flag=True, default=False, help="Emit JSON to stdout.")
@click.option(
    "--max-item-count",
    type=int,
    default=None,
    help=(
        "Page batch size limit. Note: Cosmos DB levies a minimum ~2.9 RU charge per request page; "
        "total RU increases with smaller page sizes. Compare runs only at identical page sizes."
    ),
)
@click.option("--high-ru-warn", type=float, default=None, help="High RU warning threshold.")
@click.option("--high-ru-crit", type=float, default=None, help="High RU critical threshold.")
@click.option("--scan-gap-warn", type=float, default=None, help="Scan-to-return gap warning ratio.")
@click.option(
    "--scan-gap-crit", type=float, default=None, help="Scan-to-return gap critical ratio."
)
@click.option(
    "--fail-on",
    type=click.Choice(["critical", "high", "medium"], case_sensitive=False),
    default=None,
    help="Exit with code 4 if findings reach or exceed severity threshold.",
)
@click.pass_context
def run(
    ctx: click.Context,
    workload_file: str,
    endpoint: str | None,
    database: str | None,
    container: str | None,
    ru_budget: float | None,
    json_output: bool,
    max_item_count: int | None,
    high_ru_warn: float | None,
    high_ru_crit: float | None,
    scan_gap_warn: float | None,
    scan_gap_crit: float | None,
    fail_on: str | None,
) -> None:
    """Profile and analyze a workload of Cosmos DB queries."""
    debug = ctx.obj.get("debug", False)
    configure_logging(debug=debug, json_format=json_output)

    # 1. Validate Workload File Exists
    workload_path = Path(workload_file)
    if not workload_path.is_file():
        click.echo(f"Error: Workload file not found: {workload_file}", err=True)
        sys.exit(1)

    # 2. Parse YAML
    try:
        raw_content = workload_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw_content)
    except Exception as exc:
        click.echo(f"Error: Malformed YAML in workload file: {exc}", err=True)
        sys.exit(1)

    if not isinstance(data, dict):
        click.echo("Error: Workload YAML root must be a mapping.", err=True)
        sys.exit(1)

    # 3. Validate Workload Model
    try:
        workload = Workload.model_validate(data)
    except ValidationError as exc:
        click.echo(f"Error: Workload validation failed:\n{exc}", err=True)
        sys.exit(1)

    # 4. Resolve Settings and Target Database/Container
    settings_kwargs: dict[str, Any] = {"debug": debug}
    if endpoint:
        settings_kwargs["endpoint"] = endpoint
    if database:
        settings_kwargs["database"] = database
    if container:
        settings_kwargs["container"] = container
    if ru_budget is not None:
        settings_kwargs["ru_budget"] = ru_budget
    if max_item_count is not None:
        settings_kwargs["max_item_count"] = max_item_count
    if high_ru_warn is not None:
        settings_kwargs["high_ru_warning"] = high_ru_warn
    if high_ru_crit is not None:
        settings_kwargs["high_ru_critical"] = high_ru_crit
    if scan_gap_warn is not None:
        settings_kwargs["scan_gap_ratio_warning"] = scan_gap_warn
    if scan_gap_crit is not None:
        settings_kwargs["scan_gap_ratio_critical"] = scan_gap_crit
    if fail_on:
        settings_kwargs["fail_on"] = fail_on

    try:
        settings = Settings(**settings_kwargs)
    except ValidationError as exc:
        click.echo(f"Error: Configuration invalid:\n{exc}", err=True)
        sys.exit(1)

    resolved_database = database or workload.database or settings.database
    resolved_container = container or workload.container or settings.container

    if not settings.endpoint:
        click.echo(
            "Error: Endpoint must be specified via --endpoint or QUERYLENS_ENDPOINT.", err=True
        )
        sys.exit(1)
    if not resolved_database:
        click.echo(
            "Error: Target database must be specified in workload file or --database.", err=True
        )
        sys.exit(1)
    if not resolved_container:
        click.echo(
            "Error: Target container must be specified in workload file or --container.", err=True
        )
        sys.exit(1)

    # 5. Initialize Adapter
    try:
        adapter = get_adapter(settings)
    except ValueError as exc:
        click.echo(f"Error: Adapter initialization failed: {exc}", err=True)
        sys.exit(1)
    except (
        ClientAuthenticationError,
        CosmosHttpResponseError,
        ServiceRequestError,
        CosmosClientTimeoutError,
    ) as exc:
        handle_adapter_exception(exc)

    # 6. Execute Workload
    start_time = datetime.now(UTC).isoformat()
    results: list[QueryResultSummary] = []
    budget_exceeded = False
    total_ru = 0.0

    def _render_partial_if_present() -> None:
        if results:
            partial_summary = WorkloadRunSummary(
                timestamp=start_time,
                database=resolved_database,
                container=resolved_container,
                total_queries=len(workload.queries),
                completed_queries=len(results),
                total_ru_consumed=round(total_ru, 2),
                ru_budget=settings.ru_budget or workload.ru_budget,
                budget_exceeded=budget_exceeded,
                max_item_count=settings.max_item_count,
                results=results,
            )
            if json_output:
                click.echo(serialize_summary_json(partial_summary))
            else:
                render_console_report(partial_summary)

    try:
        for cost in adapter.collect(workload):
            total_ru += cost.request_charge
            findings = evaluate_rules(cost, settings)
            results.append(QueryResultSummary(cost=cost, findings=findings))
    except BudgetExceededError as exc:
        budget_exceeded = True
        total_ru = exc.cumulative_ru
        findings = evaluate_rules(exc.partial_cost, settings)
        results.append(QueryResultSummary(cost=exc.partial_cost, findings=findings))
    except (
        ClientAuthenticationError,
        CosmosHttpResponseError,
        ServiceRequestError,
        CosmosClientTimeoutError,
    ) as exc:
        handle_adapter_exception(exc, before_exit=_render_partial_if_present)

    summary = WorkloadRunSummary(
        timestamp=start_time,
        database=resolved_database,
        container=resolved_container,
        total_queries=len(workload.queries),
        completed_queries=len(results),
        total_ru_consumed=round(total_ru, 2),
        ru_budget=settings.ru_budget or workload.ru_budget,
        budget_exceeded=budget_exceeded,
        max_item_count=settings.max_item_count,
        results=results,
    )

    # 7. Render Output
    if json_output:
        click.echo(serialize_summary_json(summary))
    else:
        render_console_report(summary)

    # 8. Check Exit Codes
    # Precedence order:
    # 1. RU Budget Exceeded (2): Critical circuit breaker halted execution early
    # 2. Diagnostic Gate Breached (4): Finding severity met or exceeded --fail-on threshold
    # 3. Query Execution Error (1): One or more queries failed execution (e.g. syntax error)
    # 4. Success (0): All queries executed cleanly and no gates breached
    if budget_exceeded:
        sys.exit(2)

    if settings.fail_on:
        threshold = Severity(settings.fail_on.upper())
        all_findings: list[Finding] = [f for r in results for f in r.findings]
        if any(f.severity >= threshold for f in all_findings):
            sys.exit(4)

    if any(r.cost.error_message for r in results):
        sys.exit(1)

    sys.exit(0)


cli.add_command(discover)

main = cli

if __name__ == "__main__":
    main()
