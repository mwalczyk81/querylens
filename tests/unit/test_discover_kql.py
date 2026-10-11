"""Unit tests for discovery KQL query construction."""

from querylens.discovery.kql import (
    build_preflight_check_query,
    build_shapes_query,
    build_totals_query,
)


def test_build_shapes_query_default() -> None:
    """Verify build_shapes_query builds valid KQL without account filter and top 20."""
    query = build_shapes_query(top_n=20)
    assert 'Category == "DataPlaneRequests"' in query
    assert 'Category == "QueryRuntimeStatistics"' in query
    assert 'ResourceProvider =~ "MICROSOFT.DOCUMENTDB"' in query
    assert "materialize(" in query
    assert "top 20 by ql_total_ru desc" in query
    assert "hash_sha256(ql_raw_text)" in query
    assert "by ql_db_name, ql_coll_name, ql_shape_id" in query
    assert "ql_db_name, ql_coll_name, ql_shape_id, ql_sample_text" in query
    assert "let ql_known_db_by_shape_container = " in query
    assert "by ql_shape_id, ql_coll_name, ql_known_db = ql_db_name" in query
    assert "let ql_single_db_shape_containers = " in query
    assert "where ql_db_count == 1" in query
    assert "join kind=leftouter ql_single_db_shape_containers on ql_shape_id, ql_coll_name" in query
    assert "let ql_resolved_activities = " in query
    assert 'coalesce(ql_resolved_db, "(unknown)")' in query
    assert "ql_known_pairs" not in query
    assert "ql_single_pair_shapes" not in query
    assert "_ResourceId endswith" not in query
    # In US3, top callers are aggregated and packed into dynamic property bags
    assert "let ql_top_shape_keys = ql_top_shapes" in query
    assert "let ql_top_callers_per_shape = ql_resolved_activities" in query
    assert "join kind=inner ql_top_shape_keys on ql_db_name, ql_coll_name, ql_shape_id" in query
    assert "bag_pack(" in query
    assert "make_list(" in query
    assert "ql_top_callers = coalesce(ql_top_callers, dynamic([]))" in query


def test_build_shapes_query_callers_ranking_and_packing() -> None:
    """Verify build_shapes_query implements per-shape caller ranking and packing (US3, T031)."""
    query = build_shapes_query(top_n=20)
    # Principal GUID preferred over client IP, omitted if both empty
    assert (
        "ql_caller_id = iff(isnotempty(ql_aad_principal), ql_aad_principal, ql_client_ip)" in query
    )
    assert "ql_caller_type = iff(" in query
    assert '"aad_principal"' in query
    assert '"client_ip"' in query
    assert 'where isnotempty(ql_caller_id) and ql_caller_type != "none"' in query
    # Ordered by partition keys, caller RU descending, and identifier tie-breaker
    assert (
        "order by ql_db_name asc, ql_coll_name asc, ql_shape_id asc, "
        "ql_caller_ru desc, ql_caller_id asc" in query
    )
    assert "serialize ql_caller_rank = row_number(" in query
    assert "where ql_caller_rank <= 3" in query
    # Bounded to at most 3 callers per shape
    assert "bag_pack(" in query
    assert '"identifier", ql_caller_id' in query
    assert '"caller_ru", ql_caller_ru' in query
    assert '"identifier_type", ql_caller_type' in query
    assert "make_list(" in query
    # Left outer join preserves shapes without callers
    assert (
        "ql_top_shapes\n"
        "| join kind=leftouter ql_top_callers_per_shape on ql_db_name, ql_coll_name, ql_shape_id"
        in query
    )


def test_build_shapes_query_with_account_filter() -> None:
    """Verify build_shapes_query injects account filter safely into both sub-queries."""
    query = build_shapes_query(top_n=10, account_filter="my-cosmos-account")
    expected_clause = '| where _ResourceId endswith "/databaseaccounts/my-cosmos-account"'
    assert query.count(expected_clause) == 2
    assert "top 10 by ql_total_ru desc" in query


def test_build_totals_query_default() -> None:
    """Verify build_totals_query builds valid totals KQL."""
    query = build_totals_query()
    assert 'Category == "DataPlaneRequests"' in query
    assert 'Category == "QueryRuntimeStatistics"' in query
    assert "ql_attributed_total_ru = sum(ql_total_charge)" in query
    assert "let ql_reqs = materialize(" in query
    assert "ql_window_total_ru = ql_window_total" in query
    assert "ql_min_time_generated = ql_min_time" in query
    assert "_ResourceId endswith" not in query


def test_build_totals_query_with_account_filter() -> None:
    """Verify build_totals_query applies account filter to both sub-queries."""
    query = build_totals_query(account_filter="prod-account-01")
    expected_clause = '| where _ResourceId endswith "/databaseaccounts/prod-account-01"'
    assert query.count(expected_clause) == 2


def test_build_preflight_check_query_default() -> None:
    """Verify build_preflight_check_query creates valid preflight check KQL."""
    query = build_preflight_check_query()
    assert 'ResourceProvider =~ "MICROSOFT.DOCUMENTDB"' in query
    assert 'ql_dataplane_count = countif(Category == "DataPlaneRequests")' in query
    assert 'ql_queryruntime_count = countif(Category == "QueryRuntimeStatistics")' in query
    assert "ql_earliest_time = min(TimeGenerated)" in query
    assert "ql_latest_time = max(TimeGenerated)" in query
    assert 'ql_has_shapesignature = countif(\n        Category == "QueryRuntimeStatistics"' in query
    assert 'ql_has_querytext = countif(\n        Category == "QueryRuntimeStatistics"' in query
    assert 'ql_has_aad_guid = countif(\n        Category == "DataPlaneRequests"' in query
    assert 'ql_has_aad_str = countif(\n        Category == "DataPlaneRequests"' in query
    assert 'ql_has_client_ip = countif(\n        Category == "DataPlaneRequests"' in query
    assert 'ql_has_useragent = countif(\n        Category == "DataPlaneRequests"' in query
    assert '| where Category == "DataPlaneRequests" and isnotempty(' in query
    assert "make_bag(bag_pack(ql_auth_type, ql_count))" in query
    assert "_ResourceId endswith" not in query


def test_build_preflight_check_query_with_account() -> None:
    """Verify build_preflight_check_query injects account filter safely."""
    query = build_preflight_check_query(account_filter="my-cosmos-account")
    assert '| where _ResourceId endswith "/databaseaccounts/my-cosmos-account"' in query


def test_queries_have_no_internal_blank_lines() -> None:
    """Verify generated KQL queries have no internal blank lines (for Azure portal)."""
    for query in [
        build_shapes_query(top_n=20),
        build_totals_query(),
        build_preflight_check_query(),
    ]:
        lines = query.split("\n")
        for line in lines:
            assert line != "", "KQL query contains empty line that would break portal execution"


ALLOWED_EXTERNAL_COLUMNS: frozenset[str] = frozenset(
    {
        "Category",
        "ResourceProvider",
        "TimeGenerated",
        "_ResourceId",
    }
)


def test_kql_identifier_naming_conventions() -> None:
    """Verify all generated let variables, aliases, and output columns follow ql_ prefix convention.

    Microsoft documents quoting and naming rules but publishes no normative reserved-word
    list for Kusto/KQL. To prevent collisions structurally, all generated identifiers must
    match ^ql_[a-z0-9_]+$, must never start or end with double underscores, and only allow
    an explicit minimal set of external Azure schema columns.
    """
    import re

    queries = [
        build_shapes_query(top_n=20),
        build_totals_query(),
        build_preflight_check_query(),
    ]

    for query in queries:
        # Extract let variable names: 'let <var> ='
        let_names = re.findall(r"\blet\s+([a-zA-Z0-9_]+)\s*=", query)
        for name in let_names:
            assert re.match(r"^ql_[a-z0-9_]+$", name), (
                f"Let variable '{name}' does not match prefix pattern ^ql_[a-z0-9_]+$"
            )
            assert not name.startswith("__") and not name.endswith("__"), (
                f"Let variable '{name}' starts or ends with double underscore"
            )

        # Extract computed column aliases: '<alias> = <expr>'
        # (excluding ==, =~, !=, <=, >=, and let/kind)
        assignments = re.findall(r"(?<![=!<>~])\b([a-zA-Z0-9_]+)\s*=(?!=|~)", query)
        for alias in assignments:
            if alias in ("let", "kind"):
                continue
            if alias in ALLOWED_EXTERNAL_COLUMNS:
                continue
            assert re.match(r"^ql_[a-z0-9_]+$", alias), (
                f"Computed alias '{alias}' does not match prefix pattern ^ql_[a-z0-9_]+$"
            )
            assert not alias.startswith("__") and not alias.endswith("__"), (
                f"Computed alias '{alias}' starts or ends with double underscore"
            )

        # Extract projected output columns from '| project <col1>, <col2>...'
        project_match = re.search(r"\|\s*project\s+([^|;]+)", query)
        if project_match:
            projected_cols = [
                col.strip()
                for col in re.split(r"[,\n\r]+", project_match.group(1))
                if col.strip() and not col.strip().startswith("//")
            ]
            for col in projected_cols:
                col_name = col.split("=")[0].strip()
                if col_name in ALLOWED_EXTERNAL_COLUMNS:
                    continue
                assert re.match(r"^ql_[a-z0-9_]+$", col_name), (
                    f"Projected column '{col_name}' does not match prefix pattern ^ql_[a-z0-9_]+$"
                )
                assert not col_name.startswith("__") and not col_name.endswith("__"), (
                    f"Projected column '{col_name}' starts or ends with double underscore"
                )
