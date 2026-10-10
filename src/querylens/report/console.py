"""Console reporting module using Rich tables and formatting."""

from rich.box import ROUNDED
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from querylens.model import Severity, WorkloadRunSummary


def render_console_report(summary: WorkloadRunSummary, console: Console | None = None) -> None:
    """Render human-friendly Rich terminal report sorted descending by RU cost.

    Args:
        summary: The workload run summary containing executed query metrics.
        console: Optional Rich Console instance.
    """
    if console is None:
        console = Console()

    # Header Panel
    status_str = (
        "[bold red]EXCEEDED[/bold red]"
        if summary.budget_exceeded
        else "[bold green]OK[/bold green]"
    )
    if summary.ru_budget is not None:
        budget_field = f"[bold cyan]Budget:[/bold cyan] {summary.ru_budget:.2f} RUs ({status_str})"
    else:
        budget_field = "[bold cyan]Budget:[/bold cyan] none"

    header_text = (
        f"[bold cyan]Database:[/bold cyan] {summary.database}  |  "
        f"[bold cyan]Container:[/bold cyan] {summary.container}  |  "
        f"[bold cyan]Page size:[/bold cyan] {summary.max_item_count}\n"
        f"[bold cyan]Executed:[/bold cyan] "
        f"{summary.completed_queries}/{summary.total_queries} queries  |  "
        f"[bold cyan]Total RUs:[/bold cyan] {summary.total_ru_consumed:.2f} RUs  |  "
        f"{budget_field}"
    )
    console.print(Panel(header_text, title="[bold]QueryLens Workload Profile[/bold]", box=ROUNDED))

    # Cost Table
    table = Table(box=ROUNDED, show_header=True, header_style="bold magenta")
    table.add_column("Rank", justify="right", style="dim", width=5)
    table.add_column("Query ID", style="cyan", min_width=15)
    table.add_column("RU Cost", justify="right", min_width=10)
    table.add_column("Server time", justify="right", min_width=12)
    table.add_column("Scanned", justify="right", min_width=9)
    table.add_column("Returned", justify="right", min_width=9)
    table.add_column("Fan-Out", justify="center", width=8)
    table.add_column("Findings", min_width=20)

    # Sort results descending by Request Units
    sorted_results = sorted(
        summary.results,
        key=lambda r: r.cost.request_charge,
        reverse=True,
    )

    for rank, res in enumerate(sorted_results, start=1):
        cost = res.cost

        # RU color threshold
        if cost.request_charge >= 200.0:
            ru_str = f"[bold red]{cost.request_charge:.2f}[/bold red]"
        elif cost.request_charge >= 50.0:
            ru_str = f"[yellow]{cost.request_charge:.2f}[/yellow]"
        else:
            ru_str = f"[green]{cost.request_charge:.2f}[/green]"

        if cost.is_partial:
            ru_str += " [italic red](partial)[/italic red]"

        if cost.is_cross_partition is None:
            fan_out_str = "[yellow]unknown[/yellow]"
        elif cost.is_cross_partition:
            fan_out_str = "[bold red]Yes[/bold red]"
        else:
            fan_out_str = "[green]No[/green]"

        finding_badges: list[str] = []
        if cost.error_message:
            finding_badges.append("[bold red][ERROR][/bold red]")
        for finding in res.findings:
            if finding.severity == Severity.CRITICAL:
                finding_badges.append(f"[bold red][CRIT] {finding.rule_id}[/bold red]")
            elif finding.severity == Severity.HIGH:
                finding_badges.append(f"[red][HIGH] {finding.rule_id}[/red]")
            elif finding.severity == Severity.MEDIUM:
                finding_badges.append(f"[yellow][MED] {finding.rule_id}[/yellow]")
            else:
                finding_badges.append(f"[blue][INFO] {finding.rule_id}[/blue]")

        if finding_badges:
            findings_str = ", ".join(finding_badges)
        elif cost.is_partial:
            findings_str = "[dim]n/a (partial)[/dim]"
        else:
            findings_str = "[dim]None[/dim]"

        table.add_row(
            str(rank),
            cost.query_id,
            ru_str,
            f"{cost.latency_ms:.1f} ms",
            str(cost.documents_scanned),
            str(cost.documents_returned),
            fan_out_str,
            findings_str,
        )

    console.print(table)

    # Detailed Findings Breakdown
    has_details = any(r.findings or r.cost.error_message for r in sorted_results)
    if has_details:
        console.print("\n[bold]Diagnostic Details:[/bold]")
        for res in sorted_results:
            if not res.findings and not res.cost.error_message:
                continue
            console.print(f"\n[cyan]• Query: {res.cost.query_id}[/cyan]")
            if res.cost.error_message:
                escaped_error = escape(res.cost.error_message)
                console.print(f"  - [bold red]Query Execution Error:[/bold red] {escaped_error}")
            for f in res.findings:
                severity_tag = f"[{f.severity.value}]"
                console.print(
                    f"  - [bold]{f.rule_name}[/bold] ({f.rule_id}) {severity_tag}: {f.summary}"
                )
                if f.evidence:
                    console.print(f"    Evidence: {f.evidence}")

    if summary.budget_exceeded:
        console.print(
            f"\n[bold red]⚠️ Execution aborted: Cumulative RU budget ceiling reached "
            f"({summary.total_ru_consumed:.2f} / {summary.ru_budget:.2f} RUs)[/bold red]"
        )
