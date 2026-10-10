"""Unit tests for discovery KQL query construction."""

from querylens.discovery.kql import build_shapes_query, build_totals_query


def test_build_shapes_query_default() -> None:
    """Verify build_shapes_query builds valid KQL without account filter and top 20."""
    query = build_shapes_query(top_n=20)
    assert 'Category == "DataPlaneRequests"' in query
    assert 'Category == "QueryRuntimeStatistics"' in query
    assert 'ResourceProvider =~ "MICROSOFT.DOCUMENTDB"' in query
    assert "materialize(" in query
    assert "top 20 by total_ru desc" in query
    assert "hash_sha256(raw_text)" in query
    assert "_ResourceId endswith" not in query
    # In US1, top_callers_per_shape is omitted
    assert "top_callers" not in query
    assert "bag_pack" not in query


def test_build_shapes_query_with_account_filter() -> None:
    """Verify build_shapes_query injects account filter safely into both sub-queries."""
    query = build_shapes_query(top_n=10, account_filter="my-cosmos-account")
    expected_clause = '| where _ResourceId endswith "/databaseaccounts/my-cosmos-account"'
    assert query.count(expected_clause) == 2
    assert "top 10 by total_ru desc" in query


def test_build_totals_query_default() -> None:
    """Verify build_totals_query builds valid totals KQL."""
    query = build_totals_query()
    assert 'Category == "DataPlaneRequests"' in query
    assert 'Category == "QueryRuntimeStatistics"' in query
    assert "attributed_total_ru = sum(total_charge)" in query
    assert "window_total_ru = window_total" in query
    assert "min_time_generated = min_time" in query
    assert "_ResourceId endswith" not in query


def test_build_totals_query_with_account_filter() -> None:
    """Verify build_totals_query applies account filter to both sub-queries."""
    query = build_totals_query(account_filter="prod-account-01")
    expected_clause = '| where _ResourceId endswith "/databaseaccounts/prod-account-01"'
    assert query.count(expected_clause) == 2
