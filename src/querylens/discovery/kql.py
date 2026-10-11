"""KQL query builders, string escaping, and query formatting for discovery."""

from querylens.discovery.columns import (
    AAD_PRINCIPAL_EXPR,
    AAD_PRINCIPAL_STR_EXPR,
    ACTIVITY_ID_EXPR,
    AUTH_TOKEN_TYPE_EXPR,
    CLIENT_IP_EXPR,
    COLLECTION_NAME_EXPR,
    DATABASE_NAME_EXPR,
    NUMBER_OF_ROWS_RETURNED_EXPR,
    QUERY_TEXT_EXPR,
    REQUEST_CHARGE_EXPR,
    SHAPE_SIGNATURE_EXPR,
    STATUS_CODE_EXPR,
    USER_AGENT_EXPR,
)


def escape_kql_string(value: str) -> str:
    """Escape a string for safe embedding inside a KQL double-quoted string literal.

    Replaces backslashes with double backslashes, double quotes with escaped quotes,
    control characters (newlines, carriage returns, tabs) with escape sequences,
    and strips null bytes.

    Args:
        value: Input raw string.

    Returns:
        Escaped string safe to embed inside KQL double quotes.
    """
    # Backslashes must be escaped first before escaping other sequences
    result = value.replace("\\", "\\\\")
    # Double quotes are escaped
    result = result.replace('"', '\\"')
    # Control characters are escaped
    result = result.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    # Null characters are stripped
    result = result.replace("\0", "")
    return result


def _build_account_clause(account_filter: str | None) -> str:
    """Generate KQL account filter clause if account_filter is set."""
    if not account_filter:
        return ""
    escaped_account = escape_kql_string(account_filter)
    return f'    | where _ResourceId endswith "/databaseaccounts/{escaped_account}"\n'


def build_shapes_query(top_n: int = 20, account_filter: str | None = None) -> str:
    """Build Query 1: Top Query Shapes Query.

    Pre-aggregates both DataPlaneRequests and QueryRuntimeStatistics by activityId_g
    before joining, materializes the join, and retrieves top shapes without callers (US1 baseline).

    Args:
        top_n: Maximum number of query shapes to return.
        account_filter: Optional Cosmos DB account name.

    Returns:
        KQL query string.
    """
    acct_clause = _build_account_clause(account_filter)

    return f"""let ql_reqs = AzureDiagnostics
    | where Category == "DataPlaneRequests" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
{acct_clause}    | summarize
        ql_total_charge = sum(todouble({REQUEST_CHARGE_EXPR})),
        ql_is_429 = max(iff({STATUS_CODE_EXPR} == "429", 1, 0)),
        ql_client_ip = take_any({CLIENT_IP_EXPR}),
        ql_aad_principal = take_any({AAD_PRINCIPAL_EXPR})
      by ql_activity_id = {ACTIVITY_ID_EXPR};
let ql_qrs = AzureDiagnostics
    | where Category == "QueryRuntimeStatistics" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
{acct_clause}    | extend
        ql_db_name = {DATABASE_NAME_EXPR},
        ql_coll_name = {COLLECTION_NAME_EXPR},
        ql_shape_sig = {SHAPE_SIGNATURE_EXPR},
        ql_raw_text = {QUERY_TEXT_EXPR},
        ql_returned_count = todouble({NUMBER_OF_ROWS_RETURNED_EXPR})
    | extend ql_shape_key = iff(isnotempty(ql_shape_sig), ql_shape_sig, hash_sha256(ql_raw_text))
    | summarize
        ql_db_name = take_anyif(ql_db_name, isnotempty(ql_db_name)),
        ql_coll_name = take_anyif(ql_coll_name, isnotempty(ql_coll_name)),
        ql_shape_id = take_anyif(ql_shape_key, isnotempty(ql_shape_key)),
        ql_sample_query_text = take_anyif(ql_raw_text, isnotempty(ql_raw_text)),
        ql_returned_rows = sum(ql_returned_count)
      by ql_activity_id = {ACTIVITY_ID_EXPR};
let ql_joined = materialize(
    ql_qrs
    | join kind=inner ql_reqs on ql_activity_id
);
let ql_known_pairs = ql_joined
| where isnotempty(ql_db_name) and isnotempty(ql_coll_name)
    and ql_db_name != "(unknown)" and ql_coll_name != "(unknown)"
| summarize by ql_shape_id, ql_known_db = ql_db_name, ql_known_coll = ql_coll_name;
let ql_single_pair_shapes = ql_known_pairs
| summarize
    ql_pair_count = count(),
    ql_resolved_db = take_any(ql_known_db),
    ql_resolved_coll = take_any(ql_known_coll)
  by ql_shape_id
| where ql_pair_count == 1;
let ql_resolved_activities = ql_joined
| join kind=leftouter ql_single_pair_shapes on ql_shape_id
| extend
    ql_db_name = iff(
        isnotempty(ql_db_name) and ql_db_name != "(unknown)",
        ql_db_name,
        coalesce(ql_resolved_db, "(unknown)")
    ),
    ql_coll_name = iff(
        isnotempty(ql_coll_name) and ql_coll_name != "(unknown)",
        ql_coll_name,
        coalesce(ql_resolved_coll, "(unknown)")
    );
let ql_top_shapes = materialize(
    ql_resolved_activities
    | summarize
        ql_execution_count = count(),
        ql_total_ru = sum(ql_total_charge),
        ql_max_ru = max(ql_total_charge),
        ql_total_returned_rows = sum(ql_returned_rows),
        ql_throttled_count = sum(ql_is_429),
        ql_sample_text = take_anyif(ql_sample_query_text, isnotempty(ql_sample_query_text))
      by ql_db_name, ql_coll_name, ql_shape_id
    | top {top_n} by ql_total_ru desc
);
ql_top_shapes
| project
    ql_db_name, ql_coll_name, ql_shape_id, ql_sample_text,
    ql_execution_count, ql_total_ru, ql_max_ru, ql_total_returned_rows,
    ql_throttled_count"""


def build_totals_query(account_filter: str | None = None) -> str:
    """Build Query 2: Window & Attributed Totals Query.

    Computes window_total_ru (all data plane requests), attributed_total_ru
    (all joined query shapes), total executions, and min(TimeGenerated).

    Args:
        account_filter: Optional Cosmos DB account name.

    Returns:
        KQL query string.
    """
    acct_clause = _build_account_clause(account_filter)

    return f"""let ql_reqs = materialize(
    AzureDiagnostics
    | where Category == "DataPlaneRequests" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
{acct_clause}    | summarize
        ql_total_charge = sum(todouble({REQUEST_CHARGE_EXPR})),
        ql_earliest_time = min(TimeGenerated)
      by ql_activity_id = {ACTIVITY_ID_EXPR}
);
let ql_qrs = AzureDiagnostics
    | where Category == "QueryRuntimeStatistics" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
{acct_clause}    | summarize by ql_activity_id = {ACTIVITY_ID_EXPR};
let ql_window_total = toscalar(ql_reqs | summarize sum(ql_total_charge));
let ql_min_time = toscalar(ql_reqs | summarize min(ql_earliest_time));
ql_qrs
| join kind=inner ql_reqs on ql_activity_id
| summarize
    ql_attributed_total_ru = sum(ql_total_charge),
    ql_total_executions = count()
| extend
    ql_window_total_ru = ql_window_total,
    ql_min_time_generated = ql_min_time"""


def build_preflight_check_query(account_filter: str | None = None) -> str:
    """Build preflight check KQL query (US2).

    Queries AzureDiagnostics category counts, min/max TimeGenerated, non-empty
    record counts for key columns, and dynamic authTokenType_s breakdown.

    Args:
        account_filter: Optional Cosmos DB account name.

    Returns:
        KQL query string.
    """
    acct_clause = _build_account_clause(account_filter)
    acct_filter_line = f"\n{acct_clause.rstrip()}" if acct_clause else ""

    return f"""let ql_base = AzureDiagnostics
    | where ResourceProvider =~ "MICROSOFT.DOCUMENTDB"{acct_filter_line};
let ql_counts = ql_base
| summarize
    ql_dataplane_count = countif(Category == "DataPlaneRequests"),
    ql_queryruntime_count = countif(Category == "QueryRuntimeStatistics"),
    ql_earliest_time = min(TimeGenerated),
    ql_latest_time = max(TimeGenerated),
    ql_has_shapesignature = countif(
        Category == "QueryRuntimeStatistics" and isnotempty({SHAPE_SIGNATURE_EXPR})
    ),
    ql_has_querytext = countif(
        Category == "QueryRuntimeStatistics" and isnotempty({QUERY_TEXT_EXPR})
    ),
    ql_has_aad_guid = countif(
        Category == "DataPlaneRequests" and isnotempty({AAD_PRINCIPAL_EXPR})
    ),
    ql_has_aad_str = countif(
        Category == "DataPlaneRequests" and isnotempty({AAD_PRINCIPAL_STR_EXPR})
    ),
    ql_has_client_ip = countif(
        Category == "DataPlaneRequests" and isnotempty({CLIENT_IP_EXPR})
    ),
    ql_has_useragent = countif(
        Category == "DataPlaneRequests" and isnotempty({USER_AGENT_EXPR})
    );
let ql_auth = toscalar(
    ql_base
    | where Category == "DataPlaneRequests" and isnotempty({AUTH_TOKEN_TYPE_EXPR})
    | summarize ql_count = count() by ql_auth_type = {AUTH_TOKEN_TYPE_EXPR}
    | summarize make_bag(bag_pack(ql_auth_type, ql_count))
);
ql_counts
| extend ql_auth_breakdown = ql_auth"""
