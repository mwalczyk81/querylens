"""Golden snapshot tests for discovery KQL query strings."""

from syrupy.assertion import SnapshotAssertion

from querylens.discovery.kql import (
    build_preflight_check_query,
    build_shapes_query,
    build_totals_query,
)


def test_discover_kql_default_snapshots(snapshot: SnapshotAssertion) -> None:
    """Verify default generated KQL matches golden snapshot."""
    shapes_kql = build_shapes_query(top_n=20)
    totals_kql = build_totals_query()

    combined_kql = (
        f"// Run each query separately in the Logs editor.\n"
        f"// === Query 1: Top Query Shapes Query ===\n{shapes_kql}\n\n"
        f"// === Query 2: Window & Attributed Totals Query ===\n{totals_kql}\n"
    )
    assert combined_kql == snapshot


def test_discover_kql_with_account_snapshots(snapshot: SnapshotAssertion) -> None:
    """Verify generated KQL with account filter matches golden snapshot."""
    shapes_kql = build_shapes_query(top_n=10, account_filter="cosmos-prod-eastus")
    totals_kql = build_totals_query(account_filter="cosmos-prod-eastus")

    combined_kql = (
        f"// Run each query separately in the Logs editor.\n"
        f"// === Query 1: Top Query Shapes Query ===\n{shapes_kql}\n\n"
        f"// === Query 2: Window & Attributed Totals Query ===\n{totals_kql}\n"
    )
    assert combined_kql == snapshot


def test_discover_kql_check_snapshots(snapshot: SnapshotAssertion) -> None:
    """Verify preflight check KQL matches golden snapshot."""
    check_kql = build_preflight_check_query()
    banner = f"// === Preflight Diagnostic Check Query ===\n{check_kql}\n"
    assert banner == snapshot


def test_discover_kql_check_with_account_snapshots(snapshot: SnapshotAssertion) -> None:
    """Verify preflight check KQL with account filter matches golden snapshot."""
    check_kql = build_preflight_check_query(account_filter="cosmos-prod-eastus")
    banner = f"// === Preflight Diagnostic Check Query ===\n{check_kql}\n"
    assert banner == snapshot
