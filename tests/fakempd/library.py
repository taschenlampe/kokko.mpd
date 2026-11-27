"""The library the fake MPD serves: small, deterministic, made up.

Each song exists to exercise something the bridge must get right: several
artist tags on one song, a title with filter metacharacters, an album whose one
file lacks a Disc tag, a label hit that must rank below a title hit, a mid-word
hit, a folder-only hit, a song without any cover.
"""

import struct
import zlib


def png(width=4, height=4, rgb=(200, 30, 30), pad=0):
    """A valid PNG. `pad` adds a text chunk so the file gets big (chunking tests)."""
    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    if pad:
        out += chunk(b"tEXt", b"pad\x00" + b"x" * pad)
    out += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return out


JPEG = (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xd9")


def song(file, title, artist, album, track, **extra):
    s = {"file": file, "title": title, "artist": artist, "album": album,
         "albumartist": extra.pop("albumartist", artist), "track": str(track),
         "date": extra.pop("date", "2001"), "genre": extra.pop("genre", "Rock"),
         "duration": extra.pop("duration", 200 + track),
         "added": extra.pop("added", "2026-01-01T00:00:00Z"),
         "last-modified": extra.pop("last_modified", "2025-12-01T00:00:00Z")}
    s.update(extra)
    return s


SONGS = [
    song("Thin Lizzy/Jailbreak/01 Jailbreak.flac", "Jailbreak", "Thin Lizzy", "Jailbreak", 1,
         date="1976", disc="1"),
    song("Thin Lizzy/Jailbreak/02 Southbound.flac", "Southbound", "Thin Lizzy", "Jailbreak", 2,
         date="1976", disc="1"),
    song("Millie Jackson/Caught Up/01 Rap.flac", "(If Loving You Is Wrong) I Don't Want to Be Right",
         "Millie Jackson", "Caught Up", 1, date="1974", genre="Soul", label="Southbound"),
    song("Black Sabbath/Paranoid/01 War Pigs.flac", "War Pigs", "Black Sabbath", "Paranoid", 1,
         date="1970", genre="Metal"),
    song("ABBA/Arrival/01 Dancing Queen.flac", "Dancing Queen", "ABBA", "Arrival", 1,
         date="1976", genre="Pop", added="2026-11-20T10:00:00Z"),
    song("a-ha/Hunting High and Low/01 Take On Me.flac", "Take On Me", "a\u2010ha",
         "Hunting High and Low", 1, date="1985", genre="Pop"),
    # several artists on one song: MPD sends two Artist lines
    song("Various/Duets/01 Under Pressure.flac", "Under Pressure", ["Queen", "David Bowie"],
         "Duets", 1, albumartist="Various Artists", date="1981"),
    # metacharacters a filter has to carry
    song("Weird/#1's/01 ( O )( O ).flac", "( O )( O )( O ), cl-018", "Kid's \"Band\"",
         "#1's + (live) [x]", 1, date="2020"),
    # an album whose 7th track has no Disc tag: it must sort by track, not first
    song("Smashing/Among My Swan/07 Seven.flac", "Seven", "Smashing", "Among My Swan", 7,
         date="1996"),
    song("Smashing/Among My Swan/01 One.flac", "One", "Smashing", "Among My Swan", 1,
         date="1996", disc="1"),
    song("Smashing/Among My Swan/02 Two.flac", "Two", "Smashing", "Among My Swan", 2,
         date="1996", disc="1"),
    song("Smashing/Among My Swan/03 Three.flac", "Three", "Smashing", "Among My Swan", 3,
         date="1996", disc="2"),
    # no cover anywhere: albumart ACKs, readpicture is empty, no local file
    song("Nocover/Plain/01 Plain.flac", "Plain", "Nocover", "Plain", 1, date="2010"),
    # only an embedded picture
    song("Embedded/Inside/01 Inside.flac", "Inside", "Embedded", "Inside", 1, date="2011"),
    # unicode in every field
    song("Ümlaut/Größe/01 Café.flac", "Café Ünïcödé ♫", "Björk", "Größe", 1, date="2003",
         genre="Électro"),
]

COVER_JAILBREAK = png(8, 8, (10, 120, 200))
COVER_BIG = png(64, 64, (90, 90, 90), pad=600_000)   # > 2 chunks of 262144
PICTURE_EMBEDDED = png(4, 4, (0, 200, 0))

COVERS = {
    "Thin Lizzy/Jailbreak": (COVER_JAILBREAK, ""),
    "Black Sabbath/Paranoid": (COVER_BIG, ""),
}
PICTURES = {
    "Embedded/Inside/01 Inside.flac": (PICTURE_EMBEDDED, "image/png"),
}

PLAYLISTS = {
    "road trip": ["Thin Lizzy/Jailbreak/01 Jailbreak.flac",
                  "ABBA/Arrival/01 Dancing Queen.flac"],
    "favorites": ["Black Sabbath/Paranoid/01 War Pigs.flac"],
}

STREAM = "http://radio.invalid/stream.mp3"


def big_library(n=2500):
    """Enough songs to need several windows of 1000."""
    return [song("Big/Album %03d/%04d Track.flac" % (i // 20, i), "Track %04d" % i,
                 "Big Artist", "Album %03d" % (i // 20), i % 20 + 1) for i in range(n)]
