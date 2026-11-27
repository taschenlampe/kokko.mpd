"""Browsing the library: folders, tags, filters, search and counts.

Every answer that grows with the library is read in windows of a thousand --
MPD's output buffer is a few megabytes and a reply that does not fit is fatal,
not truncated -- and a sort is done here, on the window's rows, never handed to
the server (a server-side sort would only order the window that already
arrived).
"""

from __future__ import annotations

import re

from . import filters
from .protocol import ServerRefused, at_least
from .records import (SONG_FIELDS, SEARCH_FIELDS, distinct, entry_path, leading_number,
                      records)

PAGE = 1000            # rows per window
COUNT_LIMIT = 120      # filters one `counts` query may ask about

# Which tag a hit matched, best first: what was typed beats a coincidence of the
# pressing. A path hit sits below every tag.
MATCH_RANK = {"title": 0, "artist": 1, "albumartist": 1, "album": 2, "name": 2,
              "genre": 3, "composer": 3, "performer": 3, "date": 3, "label": 4, "comment": 4}
FILE_RANK = 4


# ------------------------------------------------------------------ paging

def pages(conn, limit, fetch, fields=SONG_FIELDS):
    """Rows a window at a time. `fetch(start, end)` runs one page."""
    rows = []
    start = 0
    while start < limit:
        size = min(PAGE, limit - start)
        page = records(fetch(start, start + size), starts=("file",), fields=fields, limit=size)
        rows.extend(page)
        if len(page) < size:
            break
        start += size
    return rows


def filtered(conn, limit, args, fields=SONG_FIELDS):
    """`pages` for find/search/findadd: their window is a trailing `window START:END`."""
    if not at_least(conn.version, 0, 21):
        return records(conn.call(*args).pairs, starts=("file",), fields=fields, limit=limit)
    return pages(conn, limit, lambda a, b: conn.call(*(args + ["window", "%d:%d" % (a, b)])).pairs,
                 fields=fields)


def ranged(conn, limit, args, fields=SONG_FIELDS):
    """`pages` for the commands whose window is the last argument, `START:END`."""
    return pages(conn, limit, lambda a, b: conn.call(*(args + ["%d:%d" % (a, b)])).pairs,
                 fields=fields)


# --------------------------------------------------------------- the kinds

def queue(conn, request, limit):
    return ranged(conn, limit, ["playlistinfo"])


def lsinfo(conn, request, limit):
    rows = records(conn.call("lsinfo", str(request.get("path", "") or "")).pairs,
                   fields=SONG_FIELDS, limit=limit)
    # MPD answers in insertion order, which nobody can predict in a list.
    rows.sort(key=lambda r: (0 if r["type"] == "directory" else (1 if r["type"] == "playlist" else 2),
                             entry_path(r).lower()))
    return rows


def tag_list(conn, request, limit):
    tag = str(request.get("tag") or "album")
    term = str(request.get("search") or "").strip()
    scope = filters.pairs(request.get("filter"))
    if not term:
        rows = distinct(conn.call("list", tag, *filters.conditions(conn.version, scope)).pairs,
                        tag, limit=limit)
        return sorted(rows, key=lambda r: r["value"].lower())
    if not at_least(conn.version, 0, 21):
        rows = distinct(conn.call("list", tag, tag, term).pairs, tag, limit=limit)
        return sorted(rows, key=lambda r: r["value"].lower())
    clauses = [filters.clause(t, "==", v) for t, v in scope] + [filters.icase_contains(tag, term)]
    expression = filters.join_and(clauses)
    try:
        rows = distinct(conn.call("list", tag, expression).pairs, tag, limit=limit)
    except ServerRefused:
        # An MPD built without regex support: an exact-ish hit still beats nothing.
        rows = distinct(conn.call("list", tag, filters.clause(tag, "contains", term)).pairs,
                        tag, limit=limit)
    return sorted(rows, key=lambda r: r["value"].lower())


def find(conn, request, limit):
    args = filters.conditions(conn.version, request.get("filter"), request.get("regex"),
                              request.get("added_since") or "")
    if not args:
        return []                    # no condition would mean the whole library
    rows = filtered(conn, limit, ["find"] + args)
    order = request.get("sort")
    if order == "track":
        # A missing Disc tag is disc one: a single-disc rip has no disc tag at all,
        # and counting it as 0 lifted its track 7 above every `Disc: 1` file.
        rows.sort(key=lambda r: (leading_number(r.get("disc")) or 1,
                                 leading_number(r.get("track")), r.get("file", "")))
    elif order == "date":
        rows.sort(key=lambda r: (str(r.get("date", "")), r.get("file", "")))
    elif order == "added":
        rows.sort(key=lambda r: (str(r.get("added", "")), r.get("file", "")), reverse=True)
    return rows


def search(conn, request, limit):
    term = str(request.get("term") or "").strip()
    if not term:
        return []
    if at_least(conn.version, 0, 21):
        args = [filters.any_contains(term)]
    else:
        args = ["any", term]
    return rank(filtered(conn, limit, ["search"] + args, fields=SEARCH_FIELDS), term)


def counts(conn, request, limit):
    """One number per filter -- how many songs appending that filter would add."""
    items = request.get("filters")
    if not isinstance(items, list):
        return []
    out = []
    for item in items[:COUNT_LIMIT]:
        if not isinstance(item, dict):
            out.append(None)
            continue
        tag = str(item.get("tag") or "").strip()
        value = str(item.get("value") or "")
        if not tag or not value:
            out.append(None)
            continue
        try:
            pairs = conn.call("count", tag, value).pairs
        except ServerRefused:
            out.append(None)          # this filter is refused; the others still count
            continue
        found = None
        for key, text in pairs:
            if key.lower() == "songs":
                found = int(text) if text.isdigit() else None
        out.append(found)
    return out


def songinfo(conn, request, limit):
    """One song with every tag MPD sends -- this row is read by a person."""
    uri = str(request.get("file") or "")
    if not uri:
        return []
    args = filters.conditions(conn.version, [["file", uri]])
    return records(conn.call("find", *args).pairs, starts=("file",), fields=None, limit=1)


# -------------------------------------------------------------- ranking

def rank(rows, term):
    """Sort a search answer by where it matched and say where that was.

    `any contains` is a substring test over every tag, so "abba" is found in
    "Sabbath" and a label hit can bury the title match. Each row leaves with
    `match`, `pos` (0 whole value, 1 word start, 2 inside a word), `rank`
    (pos*10 + tag rank) and `inword` (the word the term sits in). A row that
    matched only a tag this answer does not carry (a MusicBrainz id) is dropped:
    nobody searches for a UUID. The path counts -- below every tag -- because a
    folder named "a-ha" is how an artist tagged "a‐ha" is still found.
    """
    needle = term.casefold()
    kept = []
    for row in rows:
        best, best_pos = "", 9
        for tag, place in MATCH_RANK.items():
            value = str(row.get(tag) or "").casefold()
            at = value.find(needle)
            if at < 0:
                continue
            pos = 0 if value == needle else (1 if at == 0 or not value[at - 1].isalnum() else 2)
            if best == "" or (pos, place) < (best_pos, MATCH_RANK[best]):
                best, best_pos = tag, pos
        if best == "":
            path = str(row.get("file") or "")
            at = path.casefold().find(needle)
            if at < 0:
                continue
            best = "file"
            best_pos = 1 if at == 0 or not path.casefold()[at - 1].isalnum() else 2
        row["match"] = best
        row["pos"] = best_pos
        row["rank"] = best_pos * 10 + (FILE_RANK if best == "file" else MATCH_RANK[best])
        row["inword"] = (path_segment(str(row.get("file") or ""), needle) if best == "file"
                         else word_around(str(row.get(best) or ""), needle))
        kept.append(row)
    kept.sort(key=lambda r: r["rank"])
    return kept


def word_around(value: str, needle: str) -> str:
    low = value.lower()
    at = low.find(needle)
    if at < 0:
        return ""
    left, right = at, at + len(needle)
    while left > 0 and low[left - 1].isalnum():
        left -= 1
    while right < len(low) and low[right].isalnum():
        right += 1
    return value[left:right]


def path_segment(value: str, needle: str) -> str:
    low = value.casefold()
    at = low.find(needle)
    if at < 0:
        return ""
    start = low.rfind("/", 0, at) + 1
    end = low.find("/", at)
    return value[start:len(low) if end < 0 else end]


def install(bridge) -> None:
    queries = bridge.queries
    queries.register("queue", queue)
    queries.register("lsinfo", lsinfo)
    queries.register("list", tag_list)
    queries.register("find", find)
    queries.register("search", search)
    queries.register("counts", counts)
    queries.register("songinfo", songinfo)
