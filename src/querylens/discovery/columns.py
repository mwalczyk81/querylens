"""Type-safe KQL column mappings with safe fallbacks and case coalescence.

This module isolates all Azure Log Analytics column references to ensure type safety,
handle schema casing inconsistencies across regions, and support future migration
to resource-specific tables without modifying discovery logic.
"""

from typing import Final


def safe_str_column(column_names: list[str], default: str = "") -> str:
    """Generate a KQL coalesce expression wrapping column_ifexists with tostring().

    Args:
        column_names: List of column name variants to try in order.
        default: Fallback string value if all column variants are missing.

    Returns:
        KQL expression string, e.g.
        'coalesce(tostring(column_ifexists("col_a", "")), "default")'
    """
    wrapped_terms = [f'tostring(column_ifexists("{col}", ""))' for col in column_names]
    wrapped_terms.append(f'"{default}"')
    return f"coalesce({', '.join(wrapped_terms)})"


# Pre-computed KQL expressions for source columns
REQUEST_CHARGE_EXPR: Final[str] = safe_str_column(
    ["requestCharge_s", "RequestCharge_s"], default="0"
)
STATUS_CODE_EXPR: Final[str] = safe_str_column(["statusCode_s", "StatusCode_s"], default="")
CLIENT_IP_EXPR: Final[str] = safe_str_column(["clientIpAddress_s", "ClientIpAddress_s"], default="")
AAD_PRINCIPAL_EXPR: Final[str] = safe_str_column(
    ["aadPrincipalId_g", "AadPrincipalId_g"], default=""
)
ACTIVITY_ID_EXPR: Final[str] = safe_str_column(["activityId_g", "ActivityId_g"], default="")
QUERY_TEXT_EXPR: Final[str] = safe_str_column(
    ["querytext_s", "QueryText_s", "queryText_s"], default=""
)
SHAPE_SIGNATURE_EXPR: Final[str] = safe_str_column(
    ["shapesignature_s", "ShapeSignature_s", "shapeSignature_s"], default=""
)
NUMBER_OF_ROWS_RETURNED_EXPR: Final[str] = safe_str_column(
    ["numberofrowsreturned_s", "numberOfRowsReturned_s", "NumberOfRowsReturned_s"],
    default="0",
)
DATABASE_NAME_EXPR: Final[str] = safe_str_column(
    ["databaseName_s", "databasename_s", "DatabaseName_s"], default=""
)
COLLECTION_NAME_EXPR: Final[str] = safe_str_column(
    ["collectionName_s", "collectionname_s", "CollectionName_s"], default=""
)
USER_AGENT_EXPR: Final[str] = safe_str_column(
    ["userAgent_s", "useragent_s", "UserAgent_s"], default=""
)
AUTH_TOKEN_TYPE_EXPR: Final[str] = safe_str_column(
    ["authTokenType_s", "authtokentype_s", "AuthTokenType_s"], default=""
)
