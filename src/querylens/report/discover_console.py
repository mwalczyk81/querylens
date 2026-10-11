"""Console reporting for discovery and preflight check results using Rich."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from querylens.discovery.models import (
    PreflightCheckReport,
    WorkloadDiscoverySummary,
)


def render_discover_console_report(
    summary: WorkloadDiscoverySummary,
    show_text: bool = False,
    console: Console | None = None,
) -> None:
    """Render discovery summary as formatted Rich console tables and panels.

    Args:
        summary: Populated WorkloadDiscoverySummary.
        show_text: Whether to display full query text without truncation.
        console: Optional Rich Console instance for output redirection.
    """
    out = console or Console()

    # 1. Header panel
    w_start = summary.window_start.strftime("%Y-%m-%d %H:%M")
    w_end = summary.window_end.strftime("%Y-%m-%d %H:%M UTC")
    unattr_ru = f"{summary.unattributed_ru:,.1f}"
    unattr_pct = f"{summary.unattributed_ru_pct:.1f}%"
    header_lines = [
        f"[bold]Target Workspace:[/bold] {summary.masked_workspace_id}",
        f"[bold]Evaluation Window:[/bold] {w_start} to {w_end}",
        f"[bold]Total Database RU:[/bold] {summary.total_ru:,.1f}",
        f"[bold]Unattributed RU:[/bold]   {unattr_ru} ({unattr_pct} of total spend)",
        f"[bold]Discovered Shapes:[/bold] {summary.discovered_query_count}",
    ]
    if summary.retention_warning:
        header_lines.append(
            "[bold yellow]Retention Notice:[/bold yellow] "
            "Telemetry data does not span the requested lookback duration."
        )

    out.print(
        Panel(
            "\n".join(header_lines),
            title="[bold cyan]Azure Cosmos DB Query Cost Discovery[/bold cyan]",
            border_style="cyan",
        )
    )

    if not summary.results:
        out.print(
            "\n[dim]No query shapes discovered in the specified window matching filters.[/dim]\n"
        )
        return

    # 2. Ranked table
    table = Table(
        title="[bold]Top Query Shapes by Total RU Consumption[/bold]",
        show_header=True,
        header_style="bold magenta",
        expand=True,
    )

    table.add_column("Database", style="cyan", no_wrap=True)
    table.add_column("Container", style="cyan", no_wrap=True)
    table.add_column("Shape ID", style="dim", no_wrap=True)
    table.add_column("Execs", justify="right")
    table.add_column("Total RU", justify="right", style="bold red")
    table.add_column("Avg RU", justify="right")
    table.add_column("Max RU", justify="right")
    table.add_column("RU %", justify="right", style="bold yellow")
    table.add_column("Avg Rows", justify="right")
    table.add_column("RU/Row", justify="right")
    table.add_column("429s", justify="right", style="red")
    table.add_column("Top Callers", style="dim")
    table.add_column("Sample Query", style="green")

    for shape in summary.results:
        shape_short = f"{shape.shape_id[:8]}..." if len(shape.shape_id) > 8 else shape.shape_id
        ru_per_row_str = (
            f"{shape.ru_per_returned_row:.2f}" if shape.ru_per_returned_row is not None else "n/a"
        )

        if shape.top_callers:
            callers_display = "\n".join(
                f"{c.identifier} ({c.ru_share_pct:.1f}%)" for c in shape.top_callers
            )
        else:
            callers_display = "n/a"

        query_text = shape.sample_query_text or "n/a"
        if not show_text and len(query_text) > 200:
            query_display = f"{query_text[:197]}..."
        else:
            query_display = query_text

        table.add_row(
            shape.database,
            shape.container,
            shape_short,
            f"{shape.execution_count:,}",
            f"{shape.total_ru:,.1f}",
            f"{shape.avg_ru:,.1f}",
            f"{shape.max_ru:,.1f}",
            f"{shape.ru_share_pct:.1f}%",
            f"{shape.avg_returned_rows:.1f}",
            ru_per_row_str,
            str(shape.throttled_count),
            callers_display,
            query_display,
        )

    out.print(table)


def render_check_console_report(
    report: PreflightCheckReport,
    console: Console | None = None,
) -> None:
    """Render preflight check health report as formatted Rich console tables.

    Args:
        report: Populated PreflightCheckReport.
        console: Optional Rich Console instance for output redirection.
    """
    out = console or Console()

    w_start = report.window_start.strftime("%Y-%m-%d %H:%M")
    w_end = report.window_end.strftime("%Y-%m-%d %H:%M UTC")
    out.print(
        Panel(
            f"[bold]Workspace:[/bold] {report.masked_workspace_id}\n"
            f"[bold]Window:[/bold] {w_start} to {w_end}",
            title="[bold cyan]Log Analytics Diagnostic Preflight Check[/bold cyan]",
            border_style="cyan",
        )
    )

    # Categories
    cat_table = Table(title="Diagnostic Categories", show_header=True, header_style="bold magenta")
    cat_table.add_column("Category", style="cyan")
    cat_table.add_column("Row Count", justify="right")

    for cat in ["DataPlaneRequests", "QueryRuntimeStatistics"]:
        count = report.row_counts.get(cat, 0)
        status = f"{count:,} records" if count > 0 else "[yellow]0 records (missing)[/yellow]"
        cat_table.add_row(cat, status)

    out.print(cat_table)

    # Time boundaries
    earliest_str = (
        report.earliest_record.strftime("%Y-%m-%d %H:%M:%S UTC")
        if report.earliest_record
        else "n/a"
    )
    latest_str = (
        report.latest_record.strftime("%Y-%m-%d %H:%M:%S UTC") if report.latest_record else "n/a"
    )
    retention_status = (
        "[yellow]Warning: data does not span requested window[/yellow]"
        if report.retention_warning
        else "[green]Healthy (data spans requested window)[/green]"
    )

    out.print(
        Panel(
            f"Earliest Record: {earliest_str}\n"
            f"Latest Record:   {latest_str}\n"
            f"Retention:       {retention_status}",
            title="[bold]Log Retention & Boundaries[/bold]",
            border_style="blue",
        )
    )

    # Field coverage
    cov_table = Table(title="Key Field Coverage", show_header=True, header_style="bold magenta")
    cov_table.add_column("Field Name", style="cyan")
    cov_table.add_column("Population %", justify="right")

    for field, pct in sorted(report.field_coverage.items()):
        cov_table.add_row(field, f"{pct * 100:.1f}%")

    out.print(cov_table)

    # Auth breakdown
    if report.auth_breakdown:
        auth_table = Table(
            title="Authentication Token Types",
            show_header=True,
            header_style="bold magenta",
        )
        auth_table.add_column("Token Type", style="cyan")
        auth_table.add_column("Count", justify="right")
        for token, count in sorted(report.auth_breakdown.items()):
            auth_table.add_row(token or "(blank)", f"{count:,}")
        out.print(auth_table)
