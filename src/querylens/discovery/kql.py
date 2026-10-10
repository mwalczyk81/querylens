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

    return f"""let reqs = AzureDiagnostics
    | where Category == "DataPlaneRequests" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
{acct_clause}    | summarize
        total_charge = sum(todouble({REQUEST_CHARGE_EXPR})),
        is_429 = max(iff({STATUS_CODE_EXPR} == "429", 1, 0)),
        client_ip = take_any({CLIENT_IP_EXPR}),
        aad_principal = take_any({AAD_PRINCIPAL_EXPR})
      by activityId_g = {ACTIVITY_ID_EXPR};
let queries = AzureDiagnostics
    | where Category == "QueryRuntimeStatistics" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
{acct_clause}    | extend
        db_name = {DATABASE_NAME_EXPR},
        coll_name = {COLLECTION_NAME_EXPR},
        shape_sig = {SHAPE_SIGNATURE_EXPR},
        raw_text = {QUERY_TEXT_EXPR},
        returned_count = todouble({NUMBER_OF_ROWS_RETURNED_EXPR})
    | extend shape_key = iff(isnotempty(shape_sig), shape_sig, hash_sha256(raw_text))
    | summarize
        db_name = take_any(db_name),
        coll_name = take_any(coll_name),
        shape_id = take_any(shape_key),
        sample_query_text = take_any(raw_text),
        returned_rows = sum(returned_count)
      by activityId_g = {ACTIVITY_ID_EXPR};
let joined = materialize(
    queries
    | join kind=inner reqs on activityId_g
);
let top_shapes = materialize(
    joined
    | summarize
        execution_count = count(),
        total_ru = sum(total_charge),
        max_ru = max(total_charge),
        total_returned_rows = sum(returned_rows),
        throttled_count = sum(is_429),
        sample_text = take_any(sample_query_text)
      by db_name, coll_name, shape_id
    | top {top_n} by total_ru desc
);
top_shapes
| project
    db_name, coll_name, shape_id, sample_text,
    execution_count, total_ru, max_ru, total_returned_rows,
    throttled_count"""


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

    return f"""let reqs = materialize(
    AzureDiagnostics
    | where Category == "DataPlaneRequests" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
{acct_clause}    | summarize
        total_charge = sum(todouble({REQUEST_CHARGE_EXPR})),
        earliest_time = min(TimeGenerated)
      by activityId_g = {ACTIVITY_ID_EXPR}
);
let queries = AzureDiagnostics
    | where Category == "QueryRuntimeStatistics" and ResourceProvider =~ "MICROSOFT.DOCUMENTDB"
{acct_clause}    | summarize by activityId_g = {ACTIVITY_ID_EXPR};
let window_total = toscalar(reqs | summarize sum(total_charge));
let min_time = toscalar(reqs | summarize min(earliest_time));
queries
| join kind=inner reqs on activityId_g
| summarize
    attributed_total_ru = sum(total_charge),
    total_executions = count()
| extend
    window_total_ru = window_total,
    min_time_generated = min_time"""


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

    return f"""let base = AzureDiagnostics
    | where ResourceProvider =~ "MICROSOFT.DOCUMENTDB"{acct_filter_line};
let counts = base
| summarize
    dataplane_count = countif(Category == "DataPlaneRequests"),
    queryruntime_count = countif(Category == "QueryRuntimeStatistics"),
    earliest_time = min(TimeGenerated),
    latest_time = max(TimeGenerated),
    has_shapesignature = countif(
        Category == "QueryRuntimeStatistics" and isnotempty({SHAPE_SIGNATURE_EXPR})
    ),
    has_querytext = countif(
        Category == "QueryRuntimeStatistics" and isnotempty({QUERY_TEXT_EXPR})
    ),
    has_aad_guid = countif(isnotempty({AAD_PRINCIPAL_EXPR})),
    has_aad_str = countif(isnotempty({AAD_PRINCIPAL_STR_EXPR})),
    has_client_ip = countif(isnotempty({CLIENT_IP_EXPR})),
    has_useragent = countif(isnotempty({USER_AGENT_EXPR}));
let auth = toscalar(
    base
    | where isnotempty({AUTH_TOKEN_TYPE_EXPR})
    | summarize count() by auth_type = {AUTH_TOKEN_TYPE_EXPR}
    | summarize make_bag(bag_pack(auth_type, count_))
);
counts
| extend auth_breakdown = auth"""
