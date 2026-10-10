"""Drift test verifying README SVG assets match the deterministic sample metrics."""

import json
import re
from pathlib import Path

from gen_readme_assets import DEFAULT_DEMO_SVG, DEFAULT_SAMPLE_JSON, render_svg

from querylens.model import WorkloadRunSummary

ROOT_DIR = Path(__file__).resolve().parents[2]
README_MD = ROOT_DIR / "README.md"


def test_readme_svg_asset_no_drift(tmp_path: Path) -> None:
    """Regenerate README demo SVG and assert byte equality against committed asset."""
    assert DEFAULT_SAMPLE_JSON.is_file(), (
        f"Missing sample run metrics at {DEFAULT_SAMPLE_JSON}. "
        "Run 'uv run python scripts/gen_readme_assets.py --refresh' to capture metrics."
    )
    assert DEFAULT_DEMO_SVG.is_file(), (
        f"Missing committed demo SVG at {DEFAULT_DEMO_SVG}. "
        "Run 'uv run python scripts/gen_readme_assets.py' to generate it."
    )

    raw_sample = DEFAULT_SAMPLE_JSON.read_text(encoding="utf-8")
    summary = WorkloadRunSummary.model_validate_json(raw_sample)

    generated_svg = tmp_path / "querylens-demo.svg"
    render_svg(summary=summary, output_path=generated_svg)

    committed_text = DEFAULT_DEMO_SVG.read_text(encoding="utf-8").replace("\r\n", "\n")
    generated_text = generated_svg.read_text(encoding="utf-8").replace("\r\n", "\n")

    assert generated_text == committed_text, (
        "docs/assets/querylens-demo.svg is out of sync with sample metrics. "
        "Run 'uv run python scripts/gen_readme_assets.py' to regenerate it."
    )


def test_readme_json_excerpt_matches_sample_run() -> None:
    """Assert that the single-query JSON excerpt in README matches sample-run.json."""
    assert README_MD.is_file(), f"Missing README.md at {README_MD}"
    assert DEFAULT_SAMPLE_JSON.is_file(), f"Missing sample run metrics at {DEFAULT_SAMPLE_JSON}"

    readme_content = README_MD.read_text(encoding="utf-8")
    sample_text = DEFAULT_SAMPLE_JSON.read_text(encoding="utf-8")
    sample_data = json.loads(sample_text)

    # Extract JSON code blocks from README.md
    json_blocks = re.findall(r"```json\s*\n(.*?)\n```", readme_content, re.DOTALL)
    assert json_blocks, "No ```json code block found in README.md"

    # Find the excerpt containing 'query_id'
    excerpt_str = next((b for b in json_blocks if '"query_id"' in b), None)
    assert excerpt_str is not None, "No JSON excerpt with query_id found in README.md"

    parsed_excerpt = json.loads(excerpt_str)

    # Assert that this excerpt exists verbatim in sample-run.json's results list
    results = sample_data.get("results", [])
    matching_result = next(
        (
            r
            for r in results
            if r.get("cost", {}).get("query_id") == parsed_excerpt["cost"]["query_id"]
        ),
        None,
    )
    assert matching_result is not None, (
        f"Query {parsed_excerpt['cost']['query_id']} not found in sample-run.json. "
        "Update the README excerpt or regenerate sample-run.json."
    )
    assert parsed_excerpt == matching_result, (
        "README.md JSON excerpt does not match sample-run.json. "
        "Run 'uv run python scripts/gen_readme_assets.py --refresh' and update the README excerpt."
    )
