"""Generate visual demo assets for README and documentation.

Loads deterministic sample workload metrics (docs/assets/sample-run.json), validates
them into a WorkloadRunSummary, renders using render_console_report with a 140-column
Rich Console, and exports a clean, byte-identical SVG (docs/assets/querylens-demo.svg).

Optionally refreshes sample data by executing against the local Cosmos DB emulator
when invoked with --refresh.
"""

import argparse
import io
import json
import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

from click.testing import CliRunner
from rich.console import Console

from querylens.cli import cli
from querylens.model import WorkloadRunSummary
from querylens.report.console import render_console_report

# Default file paths
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE_JSON = REPO_ROOT / "docs" / "assets" / "sample-run.json"
DEFAULT_DEMO_SVG = REPO_ROOT / "docs" / "assets" / "querylens-demo.svg"
DEFAULT_WORKLOAD_YAML = REPO_ROOT / "examples" / "workload.yaml"

DEFAULT_ENDPOINT = "https://localhost:8081/"
# Public well-known Microsoft Azure Cosmos DB Emulator master key
DEFAULT_EMULATOR_KEY = (
    "C2y6yDjf5/R+ob0N8A7Cgv30VRDJIWEHLM+4QDU5DE2nQ9nDuVTqobD4b8mGGyPMbIZnqyMsEcaGQy67XIw/Jw=="  # noqa: S105
)

SVG_TITLE = "QueryLens Workload Profile"


def is_emulator_reachable(endpoint: str = DEFAULT_ENDPOINT) -> bool:
    """Check if the target emulator endpoint is accepting connections.

    Args:
        endpoint: Target Cosmos DB endpoint URL.

    Returns:
        bool: True if reachable, False otherwise.
    """
    try:
        parsed = urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port or 8081
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except (OSError, TimeoutError):
        return False


def refresh_sample_run(
    output_path: Path,
    workload_path: Path = DEFAULT_WORKLOAD_YAML,
    endpoint: str = DEFAULT_ENDPOINT,
    key: str | None = None,
) -> WorkloadRunSummary:
    """Execute workload against local emulator and update sample-run.json.

    Args:
        output_path: Path where JSON output should be saved.
        workload_path: Workload YAML file path.
        endpoint: Target Cosmos DB emulator endpoint.
        key: Cosmos DB master key (defaults to well-known emulator key).

    Returns:
        Validated WorkloadRunSummary instance.
    """
    resolved_key = key or os.getenv("QUERYLENS_COSMOS_KEY") or DEFAULT_EMULATOR_KEY

    if not is_emulator_reachable(endpoint):
        sys.stderr.write(
            f"Error: Cannot connect to Azure Cosmos DB emulator at {endpoint}.\n\n"
            "To start the local emulator container:\n"
            "  docker compose up -d\n\n"
            "Wait until the service health check succeeds:\n"
            "  curl -k -f https://localhost:8081/_explorer/emulator.pem\n\n"
            "Seed deterministic test data:\n"
            "  uv run python scripts/seed_emulator.py --reset\n\n"
            "Then retry running this script with --refresh.\n"
        )
        sys.exit(1)

    runner = CliRunner(env={"QUERYLENS_COSMOS_KEY": resolved_key, "COLUMNS": "140"})
    result = runner.invoke(
        cli,
        [
            "run",
            str(workload_path),
            "--endpoint",
            endpoint,
            "--json",
        ],
    )

    if result.exit_code != 0:
        sys.stderr.write(
            f"Error: Profiling workload failed (exit code {result.exit_code}):\n{result.output}\n"
        )
        sys.exit(1)

    # Extract JSON portion from runner output
    json_start = result.output.index("{")
    json_content = result.output[json_start:]
    parsed_json = json.loads(json_content)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(parsed_json, indent=2) + "\n")

    return WorkloadRunSummary.model_validate(parsed_json)


def render_svg(
    summary: WorkloadRunSummary,
    output_path: Path,
    title: str = SVG_TITLE,
) -> None:
    """Render console report and save as SVG with byte-identical line endings.

    Args:
        summary: Validated WorkloadRunSummary instance.
        output_path: Destination path for SVG file.
        title: Fixed window title for SVG terminal frame.
    """
    output_buffer = io.StringIO()
    console = Console(
        record=True,
        width=140,
        file=output_buffer,
        legacy_windows=False,
        safe_box=False,
    )
    render_console_report(summary, console=console)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(output_path, title=title)

    # Ensure byte-identical LF line endings and strip trailing whitespace so pre-commit stays clean
    raw_content = output_path.read_text(encoding="utf-8")
    cleaned_lines = [line.rstrip() for line in raw_content.splitlines()]
    clean_content = "\n".join(cleaned_lines) + "\n"
    with open(output_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(clean_content)


def main() -> None:
    """CLI entry point for README asset generation."""
    parser = argparse.ArgumentParser(
        description="Generate visual demo SVG and sample run JSON for documentation."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-run against local Cosmos DB emulator to regenerate sample-run.json.",
    )
    parser.add_argument(
        "--sample-json",
        type=Path,
        default=DEFAULT_SAMPLE_JSON,
        help="Path to sample-run.json input/output file.",
    )
    parser.add_argument(
        "--output-svg",
        type=Path,
        default=DEFAULT_DEMO_SVG,
        help="Path to output SVG file.",
    )
    parser.add_argument(
        "--endpoint",
        type=str,
        default=DEFAULT_ENDPOINT,
        help="Cosmos DB emulator endpoint (used only with --refresh).",
    )
    args = parser.parse_args()

    if args.refresh:
        print(f"Refreshing sample data against emulator at {args.endpoint}...")
        summary = refresh_sample_run(output_path=args.sample_json, endpoint=args.endpoint)
        print(f"Saved fresh sample metrics to {args.sample_json}")
    else:
        if not args.sample_json.is_file():
            sys.stderr.write(
                f"Error: Sample data file not found at {args.sample_json}.\n"
                "Run with --refresh to generate it from the local emulator.\n"
            )
            sys.exit(1)
        raw_content = args.sample_json.read_text(encoding="utf-8")
        summary = WorkloadRunSummary.model_validate_json(raw_content)

    render_svg(summary=summary, output_path=args.output_svg)
    print(f"Generated {args.output_svg} successfully.")


if __name__ == "__main__":
    main()
