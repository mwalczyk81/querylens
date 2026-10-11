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
    assert "top 20 by total_ru desc" in query
    assert "hash_sha256(ql_raw_text)" in query
    assert "by db_name, coll_name, shape_id" in query
    assert "db_name, coll_name, shape_id, sample_text" in query
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
    assert "attributed_total_ru = sum(ql_total_charge)" in query
    assert "let ql_reqs = materialize(" in query
    assert "window_total_ru = ql_window_total" in query
    assert "min_time_generated = ql_min_time" in query
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
    assert "dataplane_count = countif(Category == " in query
    assert "queryruntime_count = countif(Category == " in query
    assert "earliest_time = min(TimeGenerated)" in query
    assert "latest_time = max(TimeGenerated)" in query
    assert "has_shapesignature = countif(" in query
    assert "has_querytext = countif(" in query
    assert "has_aad_guid = countif(" in query
    assert "has_client_ip = countif(" in query
    assert "has_useragent = countif(" in query
    assert "make_bag(bag_pack(auth_type, count_))" in query
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


KQL_RESERVED_WORDS: frozenset[str] = frozenset(
    {
        # System entities / management keywords that collision caused bug
        "queries",
        "database",
        "databases",
        "table",
        "tables",
        "workspace",
        "workspaces",
        "cluster",
        "clusters",
        "external_table",
        "materialized_view",
        "function",
        "functions",
        "view",
        "views",
        "schema",
        # Query operators and statement keywords
        "as",
        "by",
        "consume",
        "count",
        "distinct",
        "evaluate",
        "extend",
        "facet",
        "filter",
        "find",
        "fork",
        "getschema",
        "invoke",
        "join",
        "let",
        "limit",
        "lookup",
        "make-series",
        "materialize",
        "mv-apply",
        "mv-expand",
        "order",
        "parse",
        "parse-where",
        "partition",
        "pattern",
        "plugin",
        "print",
        "project",
        "project-away",
        "project-keep",
        "project-rename",
        "project-reorder",
        "range",
        "reduce",
        "render",
        "sample",
        "sample-distinct",
        "scan",
        "search",
        "serialize",
        "set",
        "sort",
        "summarize",
        "take",
        "top",
        "top-hitters",
        "top-nested",
        "toscalar",
        "union",
        "where",
        # Logical & comparison operators
        "and",
        "or",
        "not",
        "between",
        "contains",
        "containscs",
        "endswith",
        "endswithcs",
        "has",
        "has_all",
        "has_any",
        "has_cs",
        "hasprefix",
        "hasprefixcs",
        "hassuffix",
        "hassuffixcs",
        "in",
        "like",
        "matches",
        "regex",
        "startswith",
        "startswithcs",
        # Literals and primitive scalar types
        "true",
        "false",
        "null",
        "bool",
        "boolean",
        "datetime",
        "date",
        "decimal",
        "double",
        "dynamic",
        "guid",
        "int",
        "long",
        "real",
        "string",
        "time",
        "timespan",
    }
)


def test_no_kql_reserved_words_collision() -> None:
    """Verify no let variable, computed alias, or output column collides with KQL reserved words."""
    import re

    queries = [
        build_shapes_query(top_n=20),
        build_totals_query(),
        build_preflight_check_query(),
    ]

    # Explicit check: "queries" and "database" are reserved and must NOT appear as let/alias names
    assert "queries" in KQL_RESERVED_WORDS
    assert "database" in KQL_RESERVED_WORDS

    for query in queries:
        # Extract let variable names: 'let <var> ='
        let_names = re.findall(r"\blet\s+([a-zA-Z0-9_]+)\s*=", query)
        for name in let_names:
            assert name.lower() not in KQL_RESERVED_WORDS, (
                f"Let variable '{name}' collides with KQL reserved word"
            )

        # Extract computed column aliases: '<alias> = <expr>' (excluding ==, =~, !=, <=, >=)
        aliases = re.findall(r"(?<![=!<>~])\b([a-zA-Z0-9_]+)\s*=(?!=|~)", query)
        for alias in aliases:
            if alias == "let":
                continue
            assert alias.lower() not in KQL_RESERVED_WORDS, (
                f"Computed alias '{alias}' collides with KQL reserved word"
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
                # Handle possible alias assignment inside project like 'alias = expr'
                col_name = col.split("=")[0].strip()
                assert col_name.lower() not in KQL_RESERVED_WORDS, (
                    f"Projected output column '{col_name}' collides with KQL reserved word"
                )
