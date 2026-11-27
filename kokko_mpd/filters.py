"""MPD filter expressions, built from the widget's structured conditions.

The widget never sends filter syntax. It sends conditions -- `[tag, value]`
pairs that must match exactly, `[tag, pattern]` pairs for a regular
expression, a term for a case-insensitive substring -- and this module turns
them into the one argument MPD's filter parser reads:

    (artist == 'Thin Lizzy')
    ((artist == 'Thin Lizzy') AND (album =~ '(?i)jail'))

Two layers of quoting stack up. Inside the expression, a value sits in single
quotes with `\\` and `'` escaped (`filter_literal`). The whole expression then
travels as one command argument in double quotes (protocol.quote). Applied in
that order an apostrophe in a band name arrives as one.

Servers older than 0.21 have no expressions; for them `legacy_pairs` gives the
old positional `tag value tag value` form, and anything that form cannot say is
refused rather than silently dropped -- a dropped condition would answer with
the whole library.
"""

from __future__ import annotations

import re

from .protocol import ServerRefused, at_least, safe_text


class FilterUnsupported(ServerRefused):
    """The server is too old for a condition. Reported like an ACK."""

    def __init__(self, message: str):
        super().__init__(0, 0, "", message)


def filter_literal(value) -> str:
    """A value for the inside of `'...'` in a filter expression."""
    text = safe_text(value, "filter value")
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def clause(tag: str, op: str, value) -> str:
    return "(%s %s %s)" % (tag, op, filter_literal(value))


def join_and(clauses: list) -> str:
    """One expression from several; a single clause stays as it is."""
    if not clauses:
        raise ValueError("no clauses")
    if len(clauses) == 1:
        return clauses[0]
    return "(" + " AND ".join(clauses) + ")"


def icase_contains(tag: str, term: str) -> str:
    """A case-insensitive substring test over one tag.

    Written as a regex: MPD's `contains` compares case-sensitively in `list`
    filters, while `=~` with the inline `(?i)` flag does not. The term's regex
    characters are escaped, so a search for "AC/DC (live)" looks for that text.
    """
    return clause(tag, "=~", "(?i)" + re.escape(term))


def any_contains(term: str) -> str:
    return clause("any", "contains", term)


def pairs(conditions) -> list:
    """`[[tag, value], ...]` from untrusted JSON: well-formed pairs with a tag only."""
    out = []
    for item in conditions or []:
        if isinstance(item, (list, tuple)) and len(item) == 2 and str(item[0]):
            out.append((str(item[0]), str(item[1])))
    return out


def conditions(version: str, exact=None, patterns=None, added_since="") -> list:
    """The filter arguments for find/findadd/list/count: [] when there is no condition.

    `exact` and `patterns` are `[tag, value]` lists; `added_since` is MPD's
    timestamp condition (0.24+), which is about when a file entered the library
    rather than any tag.
    """
    exact = pairs(exact)
    patterns = pairs(patterns)
    since = str(added_since or "").strip()
    if since and not at_least(version, 0, 24):
        raise FilterUnsupported("added-since needs MPD 0.24 or newer")
    if not exact and not patterns and not since:
        return []
    if not at_least(version, 0, 21):
        if patterns or since:
            raise FilterUnsupported("regexp filters need MPD 0.21 or newer")
        return legacy_pairs(exact)
    parts = [clause(t, "==", v) for t, v in exact]
    parts += [clause(t, "=~", p) for t, p in patterns]
    if since:
        parts.append("(added-since %s)" % filter_literal(since))
    return [join_and(parts)]


def legacy_pairs(exact) -> list:
    flat = []
    for tag, value in exact:
        flat += [tag, value]
    return flat
