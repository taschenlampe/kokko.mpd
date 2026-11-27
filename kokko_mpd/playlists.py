"""Stored playlists and the `favorites` stars, for reading and for changing them.

`favorites` is an ordinary MPD playlist. Starring is `playlistadd`, unstarring
is `playlistdelete` by position -- walked from the end, because every position
before the one being deleted stays valid while the list shrinks.
"""

from __future__ import annotations

from . import filters
from .library import filtered, ranged
from .protocol import ServerRefused, at_least
from .records import SONG_FIELDS, records

FAVORITES = "favorites"
FAVORITE_LIMIT = 500      # songs one album-sized star may touch


# ------------------------------------------------------------------ queries

def listplaylists(conn, request, limit):
    rows = records(conn.call("listplaylists").pairs, starts=("playlist",), limit=limit)
    rows.sort(key=lambda r: r.get("playlist", "").lower())
    return rows


def playlist(conn, request, limit):
    name = str(request.get("name") or "")
    if not name:
        return []
    if at_least(conn.version, 0, 24):
        return ranged(conn, limit, ["listplaylistinfo", name])
    # ranges arrived in 0.24: an older server must send the lot at once
    return records(conn.call("listplaylistinfo", name).pairs, starts=("file",),
                   fields=SONG_FIELDS, limit=limit)


def favorites(conn, request, limit):
    rows = playlist(conn, {"name": FAVORITES, "limit": request.get("limit")}, limit)
    for row in rows:
        row["type"] = "favorite"     # the panel may unstar exactly these rows
    return rows


# ---------------------------------------------------------------- mutations

def uris(conn) -> list:
    """The `favorites` playlist in order; a playlist that is not there is empty."""
    try:
        pairs = conn.call("listplaylistinfo", FAVORITES).pairs
    except ServerRefused:
        return []
    return [value for key, value in pairs if key.lower() == "file"]


def set_favorites(conn, wanted, on: bool) -> None:
    wanted = [u for i, u in enumerate(dict.fromkeys(str(u or "") for u in wanted)) if u]
    if not wanted:
        return
    current = uris(conn)
    if on:
        have = set(current)
        for uri in wanted:
            if uri not in have:
                conn.call("playlistadd", FAVORITES, uri)
                have.add(uri)
        return
    drop = [pos for pos, uri in enumerate(current) if uri in set(wanted)]
    for pos in reversed(drop):
        conn.call("playlistdelete", FAVORITES, pos)


def queue_length(conn) -> int:
    text = conn.call("status", repeatable=True).get("playlistlength", "0")
    try:
        return int(text)
    except ValueError:
        return 0


def append_and_play(conn, uri: str) -> None:
    """Append, then start at the first thing appended (`play <pos>` is idempotent)."""
    start = queue_length(conn)
    conn.call("add", uri)
    if queue_length(conn) > start:
        conn.call("play", start, repeatable=True)


def append_after_current(conn, uri: str) -> None:
    """Append, then move what was appended in behind the playing song."""
    status = conn.call("status", repeatable=True)
    current = status.get("song")
    start = queue_length(conn)
    conn.call("add", uri)
    end = queue_length(conn)
    if end <= start or current is None:
        return
    try:
        target = int(current) + 1
    except ValueError:
        return
    if target < start:
        conn.call("move", "%d:%d" % (start, end), target)


def crop(conn) -> None:
    """Keep only the playing song; nothing playing keeps nothing."""
    status = conn.call("status", repeatable=True)
    current = status.get("song")
    if current is None:
        conn.call("clear")
        return
    position = int(current)
    length = queue_length(conn)
    if length > position + 1:            # tail first: deleting the head renumbers it
        conn.call("delete", "%d:%d" % (position + 1, length))
    if position > 0:
        conn.call("delete", "0:%d" % position)


def find_add(conn, condition, then_play: bool) -> str:
    """Append everything a filter matches. Returns "" or a message for the panel."""
    args = filters.conditions(conn.version, condition)
    if not args:
        return ""
    start = queue_length(conn)
    conn.call("findadd", *args)
    if queue_length(conn) == start:
        # MPD answers OK for nothing matched, and after a database update that is
        # exactly what a stale browser view produces -- silence is the wrong answer.
        return "nothing in the library matches that any more"
    if then_play:
        conn.call("play", start, repeatable=True)
    return ""


def search_add(conn, term: str, tag: str = "") -> str:
    """Append everything a search matches, optionally inside one tag."""
    if at_least(conn.version, 0, 21):
        args = [filters.icase_contains(tag, term) if tag else filters.any_contains(term)]
    else:
        args = [tag, term] if tag else ["any", term]
    start = queue_length(conn)
    conn.call("searchadd", *args)
    if queue_length(conn) == start:
        return "nothing in the library matches “%s”" % term
    return ""


def favorite_filter(conn, condition, on: bool) -> None:
    args = filters.conditions(conn.version, condition)
    if not args:
        return
    rows = filtered(conn, FAVORITE_LIMIT, ["find"] + args, fields=frozenset({"file"}))
    set_favorites(conn, [row.get("file", "") for row in rows], on)


# ---------------------------------------------------------------- wiring

def install(bridge) -> None:
    q = bridge.queries
    q.register("listplaylists", listplaylists)
    q.register("playlist", playlist)
    q.register("favorites", favorites)

    ops = bridge.mutations
    ops["loadplaylist"] = lambda b, p: _one(b, "load", p, "name")
    ops["saveplaylist"] = lambda b, p: _one(b, "save", p, "name")
    ops["rmplaylist"] = lambda b, p: _one(b, "rm", p, "name")
    ops["playlistclear"] = lambda b, p: _one(b, "playlistclear", p, "name")
    ops["renameplaylist"] = lambda b, p: _two(b, "rename", p, "name", "to")
    ops["playlistadd"] = lambda b, p: _two(b, "playlistadd", p, "name", "uri")
    ops["playlistdelete"] = lambda b, p: _two(b, "playlistdelete", p, "name", "pos")
    ops["favorite"] = _favorite
    ops["favoritefilter"] = _favorite_filter


def _one(bridge, command, payload, field):
    value = str(payload.get(field) or "").strip()
    if not value:
        return
    bridge.run_job(lambda h: h.call(command, value))


def _two(bridge, command, payload, first, second):
    a = str(payload.get(first) or "").strip()
    b = payload.get(second)
    if not a or b is None or str(b) == "":
        return
    if isinstance(b, bool):
        return
    bridge.run_job(lambda h: h.call(command, a, b))


def _favorite(bridge, payload):
    uri = str(payload.get("uri") or "")
    if not uri:
        return
    on = bool(payload.get("on", True))
    bridge.run_job(lambda h: set_favorites(h, [uri], on))


def _favorite_filter(bridge, payload):
    condition = payload.get("filter")
    if not condition:
        return
    on = bool(payload.get("on", True))
    bridge.run_job(lambda h: favorite_filter(h, condition, on))
