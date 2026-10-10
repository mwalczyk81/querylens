"""QueryLens Command Line Interface using Click."""

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import click
import yaml
from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
from azure.cosmos.exceptions import (
    CosmosClientTimeoutError,
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
)
from pydantic import ValidationError

from querylens.adapters.cosmos import BudgetExceededError, CosmosAdapter
from querylens.adapters.protocol import DatabaseAdapter
from querylens.config import Settings
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


def get_adapter(settings: Settings) -> DatabaseAdapter:
    """Factory creating database adapter instance.

    Args:
        settings: QueryLens runtime configuration.

    Returns:
        DatabaseAdapter: Instantiated adapter conforming to protocol.
    """
    return CosmosAdapter(settings)


@click.group()
@click.option("--debug", is_flag=True, default=False, help="Enable verbose debug logging.")
@click.version_option(version="0.1.0")
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
@click.option("--max-item-count", type=int, default=None, help="Page batch size limit.")
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

    # 6. Execute Workload
    start_time = datetime.now(UTC).isoformat()
    results: list[QueryResultSummary] = []
    budget_exceeded = False
    total_ru = 0.0

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
    except ClientAuthenticationError as exc:
        click.echo(f"Authentication failure: {exc}", err=True)
        sys.exit(5)
    except CosmosHttpResponseError as exc:
        if exc.status_code in (401, 403):
            click.echo(
                f"Authentication / Authorization failure (HTTP {exc.status_code}): {exc.message}",
                err=True,
            )
            sys.exit(5)
        if exc.status_code == 404:
            click.echo(f"Connection error: Resource not found: {exc.message}", err=True)
            sys.exit(3)
        click.echo(f"Cosmos HTTP error (status {exc.status_code}): {exc.message}", err=True)
        sys.exit(3)
    except (CosmosResourceNotFoundError, ServiceRequestError, CosmosClientTimeoutError) as exc:
        click.echo(f"Connection error: {exc}", err=True)
        sys.exit(3)

    summary = WorkloadRunSummary(
        timestamp=start_time,
        database=resolved_database,
        container=resolved_container,
        total_queries=len(workload.queries),
        completed_queries=len(results),
        total_ru_consumed=round(total_ru, 2),
        ru_budget=settings.ru_budget or workload.ru_budget,
        budget_exceeded=budget_exceeded,
        results=results,
    )

    # 7. Render Output
    if json_output:
        click.echo(serialize_summary_json(summary))
    else:
        render_console_report(summary)

    # 8. Check Exit Codes
    if budget_exceeded:
        sys.exit(2)

    if settings.fail_on:
        threshold = Severity(settings.fail_on.upper())
        all_findings: list[Finding] = [f for r in results for f in r.findings]
        if any(f.severity >= threshold for f in all_findings):
            sys.exit(4)

    sys.exit(0)
