"""Property-based and unit tests for KQL string-literal escaping and injection defense.

Verifies that escape_kql_string correctly neutralizes escape characters, quotes,
and control characters across arbitrary unicode input permutations via Hypothesis.
"""

from hypothesis import given
from hypothesis import strategies as st

from querylens.discovery.kql import escape_kql_string


def test_escape_kql_string_plain() -> None:
    """Verify standard alphanumeric strings remain intact."""
    assert escape_kql_string("my-account-123") == "my-account-123"


def test_escape_kql_string_quotes_and_slashes() -> None:
    """Verify quotes and backslashes are properly escaped."""
    assert escape_kql_string('account"with"quotes') == r"account\"with\"quotes"
    assert escape_kql_string(r"account\with\slashes") == r"account\\with\\slashes"
    assert escape_kql_string(r"complex\"quote") == r"complex\\\"quote"


def test_escape_kql_string_control_characters() -> None:
    """Verify newlines, tabs, and carriage returns are escaped."""
    assert escape_kql_string("line1\nline2") == r"line1\nline2"
    assert escape_kql_string("col1\tcol2") == r"col1\tcol2"
    assert escape_kql_string("line1\r\nline2") == r"line1\r\nline2"


@given(st.text())
def test_escape_kql_string_property(text: str) -> None:
    """Property test verifying no unescaped quotes or raw control characters exist.

    In a valid KQL string literal, any double-quote must be preceded by an odd number
    of backslashes so it cannot prematurely close the literal.
    """
    escaped = escape_kql_string(text)

    # Raw newlines, carriage returns, or null bytes must not be present unescaped
    assert "\n" not in escaped
    assert "\r" not in escaped
    assert "\0" not in escaped

    # Scan for double quotes and verify they are escaped
    for i, char in enumerate(escaped):
        if char == '"':
            # Count preceding backslashes
            backslash_count = 0
            j = i - 1
            while j >= 0 and escaped[j] == "\\":
                backslash_count += 1
                j -= 1
            # An odd number of backslashes means the quote itself is escaped
            assert backslash_count % 2 == 1, f"Unescaped quote at index {i} in {escaped!r}"
