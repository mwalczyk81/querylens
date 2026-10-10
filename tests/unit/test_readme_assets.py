"""Drift test verifying README SVG assets match the deterministic sample metrics."""

from pathlib import Path

from gen_readme_assets import DEFAULT_DEMO_SVG, DEFAULT_SAMPLE_JSON, render_svg

from querylens.model import WorkloadRunSummary


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

    committed_bytes = DEFAULT_DEMO_SVG.read_bytes()
    generated_bytes = generated_svg.read_bytes()

    assert generated_bytes == committed_bytes, (
        "docs/assets/querylens-demo.svg is out of sync with sample metrics. "
        "Run 'uv run python scripts/gen_readme_assets.py' to regenerate it."
    )
