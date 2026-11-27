"""Turning MPD's flat key/value replies into the rows the widget reads.

MPD answers `status` as one record and `playlistinfo`/`lsinfo`/`find` as a flat
stream in which a new `file:` (or `directory:`/`playlist:`) line starts the next
record. Keys are folded to lower case (the widget reads `albumartist`, never
`AlbumArtist`), and a key that repeats inside one record -- two Artist lines on a
duet -- is joined with ", " instead of keeping only the last.
"""

from __future__ import annotations

# What a song row carries. MPD volunteers more (sticker counts, audio format,
# MusicBrainz ids), and a row may be one of twenty thousand on a line.
SONG_FIELDS = frozenset((
    "file", "id", "pos", "title", "artist", "albumartist", "album", "track", "disc",
    "date", "genre", "composer", "performer", "name", "time", "duration",
    "last-modified", "added",
))
# A search answer also says why it matched on the two tags that surprise people.
SEARCH_FIELDS = SONG_FIELDS | {"label", "comment"}

RECORD_STARTS = ("file", "directory", "playlist")
JOIN = ", "


def put(record: dict, key: str, value: str) -> None:
    """Set `key`, or append `value` to it if the record already has another value."""
    old = record.get(key)
    if old is None:
        record[key] = value
    elif value not in old.split(JOIN):
        record[key] = old + JOIN + value


def record(pairs) -> dict:
    """A single-record reply (`status`, `currentsong`) as a dict."""
    out = {}
    for key, value in pairs:
        put(out, key.lower(), value)
    return out


def records(pairs, starts=RECORD_STARTS, fields=None, limit=None) -> list:
    """A multi-record reply as a list of dicts with a `type` naming the start key.

    `fields` (a set of lower-case keys) keeps only those; None keeps everything.
    Pairs before the first start key belong to no record and are skipped.
    """
    rows = []
    current = None
    for key, value in pairs:
        low = key.lower()
        if low in starts:
            if limit is not None and len(rows) >= limit:
                break
            current = {"type": low, low: value}
            rows.append(current)
        elif current is not None and (fields is None or low in fields):
            put(current, low, value)
    return rows


def distinct(pairs, tag: str, limit=None) -> list:
    """A `list <tag>` reply as `{"type": "value", "value": ...}` rows, without blanks.

    An empty value is "every song without this tag": real, but nothing a
    person can browse into or tell apart in a list.
    """
    low = tag.lower()
    rows = []
    for key, value in pairs:
        if key.lower() == low and value != "":
            if limit is not None and len(rows) >= limit:
                break
            rows.append({"type": "value", "value": value})
    return rows


def entry_path(row: dict) -> str:
    """The path a record is addressed by, whichever kind it is."""
    return row.get(row.get("type", ""), "")


def leading_number(value) -> int:
    """`4`, `4/12` -> 4; missing or unparsable -> 0."""
    text = str(value or "").split("/", 1)[0].strip()
    digits = ""
    for ch in text:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else 0
