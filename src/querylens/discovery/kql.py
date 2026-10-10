"""KQL query builders, string escaping, and query formatting for discovery."""


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
