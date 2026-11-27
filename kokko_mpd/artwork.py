"""Covers: from MPD, from the folder beside the song, and the on-disk cache.

MPD hands out only the cover files it knows by name (`cover.*` since 0.24) --
a `folder.jpg` next to the song is invisible to `albumart`, and that is what
most libraries have. The bridge runs on the same machine as the library, so it
reads the usual names itself. Order: `albumart` (a cover *file* beats an
embedded one), the local file, then `readpicture` (whatever is embedded).

The cache is keyed by album, not by song: every track of a release shares one
picture. A cover that is not there is remembered until the next `database`
event, so a library without covers costs one lookup per album, not one per
refresh.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading

from . import recent, radio
from .connection import dial
from .protocol import MPDError, ServerRefused
from .tuning import T

ART_LIMIT = 12 * 1024 * 1024     # a pathological file degrades to "no art"
ART_KEEP = 96                    # files in the cache
PART = ".part"

COVER_PATTERNS = (r"^(cover|front|folder|album|album art|albumart|artwork)$",
                  r"front[ _-]*(cover|art)",
                  r"(cover|artwork|album[ _-]*art)",
                  r"^(case|scan|cd|thumb)$")
COVER_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
COVER_WEAK = ("back", "inside", "inlay", "booklet", "small", "disc", "thumb", "cd")
CACHE_NAME = re.compile(r"^[0-9a-f]{20}\.[a-z]+$")


# ------------------------------------------------------------------- cache

def is_stream(uri: str) -> bool:
    return bool(re.match(r"https?://", uri or "", re.IGNORECASE))


def key_for(song: dict) -> str:
    """Album identity: the folder plus album and album artist."""
    uri = str(song.get("file") or "")
    if is_stream(uri):
        return hashlib.sha1(("stream\n" + uri).encode("utf-8")).hexdigest()[:20]
    directory = uri.rsplit("/", 1)[0] if "/" in uri else ""
    parts = [directory, str(song.get("album") or ""), str(song.get("albumartist") or "")]
    if not directory:
        parts.append(uri)
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()[:20]


def cached(key: str) -> str:
    directory = recent.cache_dir()
    try:
        for name in os.listdir(directory):
            if name.startswith(key + ".") and not name.endswith(PART):
                return os.path.join(directory, name)
    except OSError:
        pass
    return ""


def extension_for(data: bytes, mime: str) -> str:
    if data[:2] == b"\xff\xd8":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    mime = (mime or "").lower()
    for needle, ext in (("jpeg", ".jpg"), ("png", ".png"), ("webp", ".webp"), ("gif", ".gif")):
        if needle in mime:
            return ext
    return ".img"


_seq = 0
_seq_lock = threading.Lock()


def store(key: str, data: bytes, mime: str = "") -> str:
    """Write a fetched picture whole (unique temp name, then rename) and prune."""
    global _seq
    directory = recent.cache_dir()
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, key + extension_for(data, mime))
    with _seq_lock:
        _seq += 1
        seq = _seq
    tmp = "%s.%d.%d%s" % (path, os.getpid(), seq, PART)
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    prune(directory)
    return path


def prune(directory: str) -> None:
    try:
        names = os.listdir(directory)
        entries = [os.path.join(directory, n) for n in names if CACHE_NAME.match(n)]
        if len(entries) <= ART_KEEP:
            return
        entries.sort(key=lambda p: os.path.getmtime(p))
        for path in entries[:len(entries) - ART_KEEP]:
            os.unlink(path)
    except OSError:
        pass


# ------------------------------------------------------------- where it is

def music_directory(root: str) -> str:
    """`musicRoot` from the widget when set, else MPD's own music_directory."""
    if root:
        # Set by the widget: the library as mounted here. A wrong path is the
        # user's answer and is not papered over with mpd.conf.
        return root if os.path.isdir(root) else ""
    config_root = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    for path in (os.path.join(config_root, "mpd", "mpd.conf"),
                 os.path.expanduser("~/.mpdconf"), "/etc/mpd.conf"):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.split("#", 1)[0].strip()
                    if not line.startswith("music_directory"):
                        continue
                    value = line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else ""
                    value = os.path.expanduser(value.strip().strip('"').strip("'"))
                    if value and os.path.isdir(value):
                        return value
                    break
        except OSError:
            continue
    return ""


def local_cover(uri: str, root: str) -> tuple:
    """The best picture sitting beside the song, ranked, largest first."""
    base = music_directory(root)
    if not base or not uri:
        return b"", ""
    root_dir = os.path.realpath(base)
    # The URI comes from the server, so it may not climb out of the library.
    directory = os.path.realpath(os.path.join(root_dir, os.path.dirname(uri)))
    if directory != root_dir and not directory.startswith(root_dir + os.sep):
        return b"", ""
    try:
        names = os.listdir(directory)
    except OSError:
        return b"", ""
    images = []
    for name in names:
        stem, ext = os.path.splitext(name)
        if ext.lower() not in COVER_EXTS:
            continue
        try:
            size = os.path.getsize(os.path.join(directory, name))
        except OSError:
            continue
        images.append((stem.lower(), os.path.join(directory, name), size))
    if not images:
        return b"", ""

    def rank(image):
        stem, _path, size = image
        weak = any(word in stem for word in COVER_WEAK)
        for index, pattern in enumerate(COVER_PATTERNS):
            if re.search(pattern, stem):
                return (index, weak, -size)
        return (len(COVER_PATTERNS), weak, -size)

    for _stem, path, _size in sorted(images, key=rank):
        try:
            with open(path, "rb") as fh:
                data = fh.read(ART_LIMIT + 1)
        except OSError:
            continue
        if 0 < len(data) <= ART_LIMIT:
            return data, ""
    return b"", ""


# ------------------------------------------------------------------ fetching

def fetch_binary(conn, command: str, uri: str) -> tuple:
    """Pull one chunked binary answer in full."""
    data = bytearray()
    mime = ""
    size = None
    while True:
        reply = conn.call(command, uri, len(data))
        if reply.get("size") is not None:
            try:
                size = int(reply.get("size"))
            except ValueError:
                size = None
        if reply.get("type") is not None:
            mime = reply.get("type")
        if not reply.binary:
            break
        data += reply.binary
        if len(data) > ART_LIMIT:
            raise MPDError("album art larger than %d bytes" % ART_LIMIT)
        if size is not None and len(data) >= size:
            break
    return bytes(data), mime


def fetch(conn, uri: str, root: str) -> tuple:
    for command in ("albumart", "readpicture"):
        try:
            data, mime = fetch_binary(conn, command, uri)
        except ServerRefused:
            data, mime = b"", ""
        if command == "albumart":
            if data:
                return data, mime
            data, mime = local_cover(uri, root)
            if data:
                return data, mime
        elif data:
            return data, mime
    return b"", ""


def picture_for(bridge, conn, uri: str, album: str = "", albumartist: str = "") -> str:
    """The cover of any song: the cache first, then one fetch.

    `conn` is the query connection when the caller has one; a stream logo and a
    connection-less caller fall back to a connection of their own.
    """
    key = key_for({"file": uri, "album": album, "albumartist": albumartist})
    path = cached(key)
    if path:
        return path
    data, mime = b"", ""
    if is_stream(uri):
        data, mime = radio.stream_logo(uri)
    elif conn is not None:
        try:
            data, mime = fetch(conn, uri, bridge.music_root or "")
        except (MPDError, ServerRefused):
            data, mime = b"", ""
    else:
        _, target, password = bridge.snapshot()
        own = None
        try:
            own = dial(target, password, T.CONNECT_TIMEOUT, T.CMD_TIMEOUT)
            own.call("binarylimit", T.BINARY_CHUNK)
            data, mime = fetch(own, uri, bridge.music_root or "")
        except (MPDError, ServerRefused):
            data, mime = b"", ""
        finally:
            if own is not None:
                own.close()
    return store(key, data, mime) if data else ""


class Artwork:
    """Announces the current song's cover (`art` events) on its own thread."""

    def __init__(self, bridge):
        self.b = bridge
        self.cv = threading.Condition()
        self.wanted = None
        self.last_song = {}
        self.announced = None      # (uri, path) of the last `art` event
        self.results = {}          # key -> path, "" for "no cover"
        self.root = ""
        self.thread = None

    # --- hooks called by the bridge

    def on_config(self, payload):
        self.root = str(payload.get("musicRoot") or "").strip()

    def on_state(self, status, song):
        recent.remember(song)
        self.last_song = dict(song or {})
        if not self.last_song.get("file"):
            # Nothing playing: no cover to fetch, and the widget should know it
            # before anything else happens (no thread, no race with the next event).
            if self.announced != ("", ""):
                self.announced = ("", "")
                self.b.events.art("", "")
            return
        self.want(self.last_song)

    def on_database(self):
        # The library changed: a cover that was missing may exist now.
        with self.cv:
            self.results.clear()
            song = dict(self.last_song)
        self.want(song)

    def want(self, song):
        with self.cv:
            self.wanted = dict(song)
            self.cv.notify()
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self.loop, name="art", daemon=True)
                self.thread.start()

    # --- the worker

    def loop(self):
        while not self.b.stop.is_set():
            with self.cv:
                while self.wanted is None and not self.b.stop.is_set():
                    self.cv.wait(0.5)
                song, self.wanted = self.wanted, None
            if song is None:
                continue
            try:
                self.cover(song)
            except Exception as exc:      # a cover must never take the bridge down
                import sys
                sys.stderr.write("kokko_mpd: art failed: %r\n" % (exc,))

    def cover(self, song):
        uri = str(song.get("file") or "")
        if not uri:
            if self.announced != ("", ""):   # once, at start and when a stream ends
                self.announced = None      # (uri, path) of the last `art` event
                self.b.events.art("", "")
            return
        gen = self.b.generation
        key = key_for(song)
        with self.cv:
            known = key in self.results
            path = self.results.get(key, "")
        if not known:
            path = self.fetch(song, uri, key)
            with self.cv:
                self.results[key] = path
        if gen != self.b.generation:
            return
        if (uri, path) != self.announced:
            self.announced = (uri, path)
            self.b.events.art(uri, path)

    def fetch(self, song, uri, key) -> str:
        path = cached(key)
        if path:
            return path
        data, mime = b"", ""
        if is_stream(uri):
            data, mime = radio.stream_logo(uri)
        else:
            gen, target, password = self.b.snapshot()
            conn = None
            try:
                conn = dial(target, password, T.CONNECT_TIMEOUT, T.CMD_TIMEOUT)
                conn.call("binarylimit", T.BINARY_CHUNK)
                data, mime = fetch(conn, uri, self.root)
            except (MPDError, ServerRefused):
                data, mime = b"", ""
            finally:
                if conn is not None:
                    conn.close()
        return store(key, data, mime) if data else ""


def install(bridge) -> None:
    art = Artwork(bridge)
    bridge.features.append(art)

    def art_query(conn, request, limit):
        uri = str(request.get("uri") or "")
        if not uri:
            return []
        path = picture_for(bridge, conn, uri, str(request.get("album") or ""),
                           str(request.get("albumartist") or ""))
        return [{"type": "art", "path": path}]

    bridge.queries.register("art", art_query)
