"""The list of albums this player touched -- a cache, not a library.

Losing the file costs a few empty rows on the start screen and nothing else, so
every failure here is swallowed. One entry per album, newest first: the start
screen offers albums, and an album playing five tracks must not fill the list
with itself.
"""

from __future__ import annotations

import json
import os
import threading
import time

RECENT_LIMIT = 20
_lock = threading.Lock()


def cache_home() -> str:
    return os.environ.get("XDG_CACHE_HOME") or os.path.join(
        os.path.expanduser("~"), ".cache")


def cache_dir() -> str:
    return os.path.join(cache_home(), "kokko-mpd")


def recent_file() -> str:
    return os.path.join(cache_dir(), "recent.json")


def load() -> list:
    try:
        with open(recent_file(), "r", encoding="utf-8") as fh:
            rows = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)][:RECENT_LIMIT]


def remember(song: dict) -> None:
    """Put the song's album at the head of the list (temp file + rename)."""
    file = str(song.get("file") or "")
    if not file:
        return
    album = str(song.get("album") or "")
    artist = str(song.get("albumartist") or song.get("artist") or "")
    entry = {"album": album, "albumartist": artist, "file": file, "at": int(time.time())}
    with _lock:
        rows = load()
        if rows and rows[0].get("file") == file and rows[0].get("album") == album:
            return
        keep = []
        for row in rows:
            if album:
                same = (str(row.get("album") or "") == album
                        and str(row.get("albumartist") or "") == artist)
            else:
                same = str(row.get("file") or "") == file
            if not same:
                keep.append(row)
        keep.insert(0, entry)
        path = recent_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(keep[:RECENT_LIMIT], fh, ensure_ascii=False)
            os.replace(tmp, path)
        except OSError:
            pass


def query(conn, request, limit):
    """The `recent` query: answered from the cache, also while MPD is down."""
    return [dict(row, type="recent") for row in load()[:limit]]


def install(bridge) -> None:
    bridge.queries.register("recent", query, local=True)
