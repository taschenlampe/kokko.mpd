"""A fake MPD server for the bridge contract tests.

It speaks enough of MPD's text protocol for a bridge to connect, read state, park
in `idle`, browse a small in-memory library, change an in-memory queue and fetch
album art -- and it can misbehave on purpose: never greet, drop a connection
after a command, close idle command connections, answer slowly.

Nothing here touches a real MPD, a real library or a real queue. Everything the
server knows is handed to it by the test; everything a client sends is logged,
so a test can assert what went over the wire (`commands()`).

Standard library only. Not a reference implementation of MPD: where the real
server is more permissive or more detailed, this is only as detailed as the
bridge needs, and where it differs knowingly the comment says so.
"""

from __future__ import annotations

import os
import random
import re
import select
import socket
import threading
import time

# MPD spells its keys this way on the wire; the bridge lower-cases them.
WIRE_KEY = {
    "file": "file", "title": "Title", "artist": "Artist", "albumartist": "AlbumArtist",
    "album": "Album", "track": "Track", "disc": "Disc", "date": "Date",
    "genre": "Genre", "composer": "Composer", "performer": "Performer",
    "name": "Name", "label": "Label", "comment": "Comment",
    "musicbrainz_trackid": "MUSICBRAINZ_TRACKID",
    "last-modified": "Last-Modified", "added": "Added",
}
TAGS = ("title", "artist", "albumartist", "album", "track", "disc", "date", "genre",
        "composer", "performer", "name", "label", "comment", "musicbrainz_trackid")

ACK_ARG = 2
ACK_PASSWORD = 3
ACK_PERMISSION = 4
ACK_UNKNOWN = 5
ACK_NO_EXIST = 50


class Ack(Exception):
    def __init__(self, code: int, text: str):
        super().__init__(text)
        self.code = code
        self.text = text


class Drop(Exception):
    """Close the connection without a reply."""


# ------------------------------------------------------------------ parsing

def tokenize(line: str) -> list:
    """Split one command line the way MPD does: words, or "quoted" with escapes."""
    out = []
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c in " \t":
            i += 1
            continue
        if c == '"':
            i += 1
            buf = []
            while i < n and line[i] != '"':
                if line[i] == "\\" and i + 1 < n:
                    i += 1
                buf.append(line[i])
                i += 1
            if i >= n:
                raise Ack(ACK_ARG, "Missing closing '\"'")
            i += 1
            out.append("".join(buf))
            continue
        start = i
        while i < n and line[i] not in " \t":
            if line[i] in "\"'":
                raise Ack(ACK_ARG, "Invalid unquoted character")
            i += 1
        out.append(line[start:i])
    return out


class FilterParser:
    """MPD's filter expressions, the subset the bridge sends.

    (TAG == 'v'), (TAG != 'v'), (TAG contains 'v'), (TAG starts_with 'v'),
    (TAG =~ 'v'), (TAG !~ 'v'), (base 'v'), (added-since 'v'), (!EXPR),
    (EXPR AND EXPR ...). `any` is every tag plus the file path.
    """

    OPS = ("==", "!=", "=~", "!~", "contains", "starts_with")

    def __init__(self, text: str, fold: bool):
        self.s = text
        self.i = 0
        self.fold = fold  # search/searchadd compare case-insensitively

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] == " ":
            self.i += 1

    def expect(self, ch):
        self.ws()
        if not self.s.startswith(ch, self.i):
            raise Ack(ACK_ARG, "Expected '%s'" % ch)
        self.i += len(ch)

    def word(self):
        self.ws()
        m = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*").match(self.s, self.i)
        if not m:
            raise Ack(ACK_ARG, "Word expected")
        self.i = m.end()
        return m.group(0)

    def value(self):
        self.ws()
        if self.i >= len(self.s) or self.s[self.i] not in "'\"":
            raise Ack(ACK_ARG, "Quoted string expected")
        q = self.s[self.i]
        self.i += 1
        buf = []
        while self.i < len(self.s) and self.s[self.i] != q:
            if self.s[self.i] == "\\" and self.i + 1 < len(self.s):
                self.i += 1
            buf.append(self.s[self.i])
            self.i += 1
        if self.i >= len(self.s):
            raise Ack(ACK_ARG, "Closing quote expected")
        self.i += 1
        return "".join(buf)

    def parse(self):
        pred = self.expr()
        self.ws()
        if self.i != len(self.s):
            raise Ack(ACK_ARG, "Unparsed garbage after expression")
        return pred

    def expr(self):
        self.expect("(")
        self.ws()
        if self.s.startswith("!", self.i) and not self.s.startswith("!=", self.i):
            self.i += 1
            inner = self.expr()
            self.expect(")")
            return lambda song: not inner(song)
        if self.s.startswith("(", self.i):
            parts = [self.expr()]
            while True:
                self.ws()
                if self.s.startswith("AND", self.i):
                    self.i += 3
                    parts.append(self.expr())
                    continue
                break
            self.expect(")")
            return lambda song: all(p(song) for p in parts)
        tag = self.word()
        low = tag.lower()
        if low == "base":
            base = self.value().rstrip("/")
            self.expect(")")
            return lambda song: song["file"].startswith(base + "/")
        if low in ("added-since", "modified-since"):
            since = self.value()
            self.expect(")")
            key = "added" if low == "added-since" else "last-modified"
            return lambda song: str(song.get(key, "")) >= since
        self.ws()
        op = None
        for cand in self.OPS:
            if self.s.startswith(cand, self.i):
                op = cand
                self.i += len(cand)
                break
        if op is None:
            raise Ack(ACK_ARG, "Unknown filter operator")
        val = self.value()
        self.expect(")")
        if low not in TAGS and low not in ("any", "file"):
            raise Ack(ACK_ARG, "Unknown filter type: %s" % tag)
        return self.compare(low, op, val)

    def compare(self, tag, op, val):
        fold = self.fold
        rx = None
        if op in ("=~", "!~"):
            try:
                rx = re.compile(val, re.IGNORECASE if fold else 0)
            except re.error:
                raise Ack(ACK_ARG, "Invalid regular expression")

        def values(song):
            if tag == "any":
                vals = []
                for t in TAGS:
                    vals.extend(as_list(song.get(t)))
                vals.append(song["file"])
                return vals
            return as_list(song.get(tag))

        def one(v):
            a, b = (v.lower(), val.lower()) if fold else (v, val)
            if op == "==":
                return a == b
            if op == "!=":
                return a != b
            if op == "contains":
                return b in a
            if op == "starts_with":
                return a.startswith(b)
            if op == "=~":
                return bool(rx.search(v))
            if op == "!~":
                return not rx.search(v)
            return False

        if op in ("!=", "!~"):
            return lambda song: all(one(v) for v in values(song)) if values(song) else True
        return lambda song: any(one(v) for v in values(song))


def as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def parse_filter(args: list, fold: bool):
    """Filter arguments of find/search/list/count, in either spelling."""
    if not args:
        return lambda song: True
    if len(args) == 1 and args[0].startswith("("):
        return FilterParser(args[0], fold).parse()
    if len(args) % 2:
        raise Ack(ACK_ARG, "Incorrect number of filter arguments")
    preds = []
    for tag, val in zip(args[0::2], args[1::2]):
        preds.append(FilterParser("", fold).compare(tag.lower(), "contains" if fold else "==", val))
    return lambda song: all(p(song) for p in preds)


def parse_range(text: str, length: int) -> tuple:
    m = re.fullmatch(r"(\d+)(?::(\d*))?", text or "")
    if not m:
        raise Ack(ACK_ARG, "Bad range")
    start = int(m.group(1))
    if m.group(2) is None:
        end = start + 1
    elif m.group(2) == "":
        end = length
    else:
        end = int(m.group(2))
    return start, end


# ------------------------------------------------------------------- server

class Client:
    def __init__(self, server, sock, cid):
        self.server = server
        self.sock = sock
        self.cid = cid
        self.binarylimit = 8192
        self.authed = server.password is None
        self.pending = set()      # idle subsystems changed since this client last asked
        self.idling = False
        self.last_active = time.monotonic()
        self.buf = b""
        self.closed = False

    # --- I/O

    def write(self, data: bytes):
        try:
            self.sock.sendall(data)
        except OSError:
            self.closed = True

    def lines(self, pairs):
        out = []
        for k, v in pairs:
            out.append(("%s: %s\n" % (k, v)).encode("utf-8"))
        return b"".join(out)

    def readline(self, timeout=None):
        while b"\n" not in self.buf:
            if self.closed:
                return None
            if timeout is not None:
                r, _, _ = select.select([self.sock], [], [], timeout)
                if not r:
                    return ""
            try:
                chunk = self.sock.recv(65536)
            except OSError:
                return None
            if not chunk:
                return None
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("utf-8", "replace")

    def close(self):
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class FakeMPD:
    """One fake server. `start()` returns the port (or the socket path)."""

    def __init__(self, songs=None, version="0.24.0", password=None, covers=None,
                 pictures=None, playlists=None, unix_path=None):
        self.version = version
        self.password = password
        self.unix_path = unix_path
        self.lock = threading.RLock()
        self.cv = threading.Condition(self.lock)
        self.songs = [dict(s) for s in (songs or [])]
        self.covers = dict(covers or {})      # directory -> (bytes, mime) for albumart
        self.pictures = dict(pictures or {})  # file -> (bytes, mime) for readpicture
        self.playlists = {k: list(v) for k, v in (playlists or {}).items()}
        self.queue = []          # list of song dicts with "id"
        self.next_id = 1
        self.current = None      # queue index
        self.state = "stop"
        self.elapsed = 0.0
        self.volume = 50
        self.options = {"repeat": "0", "random": "0", "single": "0", "consume": "0"}
        self.playlist_version = 1
        self.updating = 0
        self.log = []            # (client id, tokens)
        self.clients = []
        self.cid = 0
        self.stopped = threading.Event()
        # fault injection
        self.wedged = False                # accept, never greet
        self.drop_after = {}               # command -> n: execute, then drop without reply (n times)
        self.drop_before = {}              # command -> n: drop on receipt, do not execute
        self.delay = {}                    # command -> seconds before the reply
        self.close_idle_after = None       # seconds: MPD's connection_timeout (not for idle)
        self.ack_on = {}                   # command -> text: refuse with ACK
        self.connections_total = 0

    # --- lifecycle

    def start(self):
        if self.unix_path:
            self.lsock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.lsock.bind(self.unix_path)
            self.address = self.unix_path
        else:
            self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.lsock.bind(("127.0.0.1", getattr(self, "fixed_port", 0)))
            self.address = self.lsock.getsockname()[1]
        self.lsock.listen(32)
        self.stopped.clear()
        threading.Thread(target=self.accept_loop, daemon=True).start()
        threading.Thread(target=self.reaper, daemon=True).start()
        return self.address

    @property
    def port(self):
        return self.address

    def stop(self):
        self.stopped.set()
        try:
            self.lsock.close()
        except OSError:
            pass
        self.kill_all()
        if self.unix_path and os.path.exists(self.unix_path):
            os.unlink(self.unix_path)

    def kill_all(self):
        with self.lock:
            clients = list(self.clients)
        for c in clients:
            c.close()
        with self.cv:
            self.cv.notify_all()

    def accept_loop(self):
        while not self.stopped.is_set():
            try:
                sock, _ = self.lsock.accept()
            except OSError:
                return
            with self.lock:
                self.cid += 1
                self.connections_total += 1
                client = Client(self, sock, self.cid)
                self.clients.append(client)
            threading.Thread(target=self.serve, args=(client,), daemon=True).start()

    def reaper(self):
        """MPD's connection_timeout: an idle non-`idle` connection is hung up on."""
        while not self.stopped.wait(0.05):
            limit = self.close_idle_after
            if limit is None:
                continue
            now = time.monotonic()
            with self.lock:
                stale = [c for c in self.clients
                         if not c.idling and now - c.last_active > limit]
            for c in stale:
                c.close()

    def live_clients(self):
        with self.lock:
            return [c for c in self.clients if not c.closed]

    # --- what a test asks

    def commands(self, name=None):
        with self.lock:
            entries = list(self.log)
        if name is None:
            return entries
        return [e for e in entries if e[1] and e[1][0] == name]

    def count(self, name):
        return len(self.commands(name))

    def clear_log(self):
        with self.lock:
            self.log = []

    def wait_for(self, predicate, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    # --- "another client" changes things

    def changed(self, *subsystems):
        with self.cv:
            for c in self.clients:
                c.pending.update(subsystems)
            self.cv.notify_all()

    def external(self, fn, *subsystems):
        with self.lock:
            fn(self)
        self.changed(*subsystems)

    # --- the connection

    def serve(self, client):
        # The documented wedge: the socket is accepted and nothing is said until
        # the daemon is released (SIGCONT) -- then the greeting comes late.
        while self.wedged and not client.closed and not self.stopped.is_set():
            time.sleep(0.05)
        if client.closed or self.stopped.is_set():
            client.close()
            self.forget(client)
            return
        client.write(("OK MPD %s\n" % self.version).encode())
        try:
            while not client.closed and not self.stopped.is_set():
                line = client.readline()
                if line is None:
                    break
                client.last_active = time.monotonic()
                self.dispatch(client, line)
                client.last_active = time.monotonic()
        except Drop:
            pass
        finally:
            client.close()
            self.forget(client)

    def forget(self, client):
        with self.lock:
            if client in self.clients:
                self.clients.remove(client)

    def dispatch(self, client, line):
        try:
            tokens = tokenize(line)
        except Ack as exc:
            client.write(("ACK [%d@0] {} %s\n" % (exc.code, exc.text)).encode())
            return
        if not tokens:
            client.write(b"ACK [5@0] {} No command given\n")
            return
        name = tokens[0]
        with self.lock:
            self.log.append((client.cid, tokens))
            before = self.drop_before.get(name, 0)
            if before:
                self.drop_before[name] = before - 1
        if before:
            raise Drop()
        if name in self.delay:
            time.sleep(self.delay[name])
        if name == "idle":
            self.do_idle(client, tokens[1:])
            return
        if name == "noidle":
            return  # outside idle MPD ignores it
        if name == "close":
            raise Drop()
        try:
            if name in self.ack_on:
                raise Ack(ACK_UNKNOWN, self.ack_on[name])
            if not client.authed and name not in ("password", "ping", "close"):
                raise Ack(ACK_PERMISSION, "you don't have permission for \"%s\"" % name)
            handler = getattr(self, "cmd_" + name.replace("-", "_"), None)
            if handler is None:
                raise Ack(ACK_UNKNOWN, "unknown command \"%s\"" % name)
            with self.lock:
                body = handler(client, tokens[1:])
        except Ack as exc:
            client.write(("ACK [%d@0] {%s} %s\n" % (exc.code, name, exc.text)).encode())
            return
        with self.lock:
            after = self.drop_after.get(name, 0)
            if after:
                self.drop_after[name] = after - 1
        if after:
            raise Drop()  # executed, but the reply never leaves
        client.write((body or b"") + b"OK\n")

    def do_idle(self, client, wanted):
        wanted = set(wanted) or {"database", "update", "stored_playlist", "playlist",
                                 "player", "mixer", "output", "options", "sticker",
                                 "subscription", "message", "partition", "neighbor",
                                 "mount"}
        client.idling = True
        try:
            while not client.closed and not self.stopped.is_set():
                with self.cv:
                    hit = client.pending & wanted
                    if hit:
                        client.pending -= hit
                        client.write(client.lines(("changed", s) for s in sorted(hit)) + b"OK\n")
                        return
                line = client.readline(timeout=0.05)
                if line is None:
                    client.closed = True
                    return
                if line == "":
                    with self.cv:
                        if not (client.pending & wanted):
                            self.cv.wait(0.05)
                    continue
                with self.lock:
                    self.log.append((client.cid, tokenize(line)))
                if line.strip() == "noidle":
                    with self.cv:
                        hit = client.pending & wanted
                        client.pending -= hit
                    client.write(client.lines(("changed", s) for s in sorted(hit)) + b"OK\n")
                    return
                # anything else during idle is a protocol violation; MPD closes
                client.closed = True
                return
        finally:
            client.idling = False
            client.last_active = time.monotonic()

    # ------------------------------------------------------------ helpers

    def song_pairs(self, song, extra=()):
        pairs = [("file", song["file"])]
        for key in ("last-modified", "added"):
            if song.get(key):
                pairs.append((WIRE_KEY[key], song[key]))
        for tag in TAGS:
            for v in as_list(song.get(tag)):
                pairs.append((WIRE_KEY.get(tag, tag), v))
        if song.get("duration") is not None:
            pairs.append(("Time", str(int(float(song["duration"])))))
            pairs.append(("duration", "%.3f" % float(song["duration"])))
        pairs.extend(extra)
        return pairs

    def queue_pairs(self, index):
        song = self.queue[index]
        return self.song_pairs(song, (("Pos", str(index)), ("Id", str(song["id"]))))

    def find_song(self, uri):
        for s in self.songs:
            if s["file"] == uri:
                return s
        return None

    def resolve(self, uri):
        """`add` takes a file, a directory, or a stream URL."""
        if re.match(r"^[a-z][a-z0-9+.-]*://", uri):
            return [{"file": uri}]
        song = self.find_song(uri)
        if song:
            return [song]
        prefix = uri.rstrip("/") + "/"
        hits = [s for s in self.songs if s["file"].startswith(prefix) or uri == ""]
        if not hits:
            raise Ack(ACK_NO_EXIST, "No such directory")
        return sorted(hits, key=lambda s: s["file"])

    def enqueue(self, songs, at=None):
        added = []
        for s in songs:
            entry = dict(s)
            entry["id"] = self.next_id
            self.next_id += 1
            added.append(entry)
        if at is None:
            self.queue.extend(added)
        else:
            self.queue[at:at] = added
        self.queue_changed()
        return added

    def queue_changed(self):
        self.playlist_version += 1
        self.changed("playlist")

    def window(self, args):
        if len(args) >= 2 and args[-2] == "window":
            return args[:-2], args[-1]
        return args, None

    def apply_window(self, rows, window):
        if window is None:
            return rows
        start, end = parse_range(window, len(rows))
        return rows[start:end]

    def matching(self, args, fold):
        return [s for s in self.songs if parse_filter(args, fold)(s)]

    # ----------------------------------------------------------- commands

    def cmd_ping(self, c, a):
        return b""

    def cmd_password(self, c, a):
        if self.password is None or (a and a[0] == self.password):
            c.authed = True
            return b""
        raise Ack(ACK_PASSWORD, "incorrect password")

    def cmd_binarylimit(self, c, a):
        size = int(a[0])
        if size < 64:
            raise Ack(ACK_ARG, "Value too small")
        c.binarylimit = size
        return b""

    def cmd_status(self, c, a):
        pairs = [("volume", str(self.volume))]
        for k in ("repeat", "random", "single", "consume"):
            pairs.append((k, self.options[k]))
        pairs += [("partition", "default"), ("playlist", str(self.playlist_version)),
                  ("playlistlength", str(len(self.queue))), ("mixrampdb", "0"),
                  ("state", self.state)]
        if self.current is not None and self.current < len(self.queue):
            song = self.queue[self.current]
            pairs += [("song", str(self.current)), ("songid", str(song["id"]))]
            if self.current + 1 < len(self.queue):
                nxt = self.queue[self.current + 1]
                pairs += [("nextsong", str(self.current + 1)), ("nextsongid", str(nxt["id"]))]
            if self.state != "stop":
                dur = float(song.get("duration") or 0)
                pairs += [("time", "%d:%d" % (int(self.elapsed), int(dur))),
                          ("elapsed", "%.3f" % self.elapsed),
                          ("duration", "%.3f" % dur), ("bitrate", "320"),
                          ("audio", "44100:16:2")]
        if self.updating:
            pairs.append(("updating_db", str(self.updating)))
        return c.lines(pairs)

    def cmd_currentsong(self, c, a):
        if self.current is None or self.current >= len(self.queue):
            return b""
        return c.lines(self.queue_pairs(self.current))

    # transport
    def set_player(self, state):
        self.state = state
        self.changed("player")

    def cmd_play(self, c, a):
        if a:
            pos = int(a[0])
            if pos < 0 or pos >= len(self.queue):
                raise Ack(ACK_ARG, "Bad song index")
            self.current = pos
            self.elapsed = 0.0
        elif self.current is None:
            if not self.queue:
                return b""
            self.current = 0
        self.set_player("play")
        return b""

    def cmd_playid(self, c, a):
        sid = int(a[0]) if a else None
        for i, s in enumerate(self.queue):
            if s["id"] == sid:
                self.current = i
                self.elapsed = 0.0
                self.set_player("play")
                return b""
        raise Ack(ACK_NO_EXIST, "No such song")

    def cmd_pause(self, c, a):
        if self.state == "stop":
            return b""
        if a:
            self.set_player("pause" if a[0] == "1" else "play")
        else:
            self.set_player("play" if self.state == "pause" else "pause")
        return b""

    def cmd_stop(self, c, a):
        self.set_player("stop")
        return b""

    def cmd_next(self, c, a):
        if self.current is None:
            return b""
        if self.current + 1 < len(self.queue):
            self.current += 1
            self.elapsed = 0.0
        else:
            self.current = None
            self.state = "stop"
        self.changed("player")
        return b""

    def cmd_previous(self, c, a):
        if self.current is None:
            return b""
        self.current = max(0, self.current - 1)
        self.elapsed = 0.0
        self.changed("player")
        return b""

    def cmd_seekcur(self, c, a):
        self.elapsed = float(a[0])
        self.changed("player")
        return b""

    def cmd_setvol(self, c, a):
        v = int(a[0])
        if v < 0 or v > 100:
            raise Ack(ACK_ARG, "Invalid volume value")
        self.volume = v
        self.changed("mixer")
        return b""

    def set_option(self, name, a):
        if not a or a[0] not in ("0", "1", "oneshot"):
            raise Ack(ACK_ARG, "Boolean (0/1) expected")
        self.options[name] = a[0]
        self.changed("options")
        return b""

    def cmd_repeat(self, c, a):
        return self.set_option("repeat", a)

    def cmd_random(self, c, a):
        return self.set_option("random", a)

    def cmd_single(self, c, a):
        return self.set_option("single", a)

    def cmd_consume(self, c, a):
        return self.set_option("consume", a)

    def cmd_update(self, c, a):
        self.updating += 1
        job = self.updating
        self.changed("update")

        def finish():
            time.sleep(0.2)
            with self.lock:
                self.updating = 0
            self.changed("update", "database")
        threading.Thread(target=finish, daemon=True).start()
        return c.lines([("updating_db", str(job))])

    cmd_rescan = cmd_update

    # queue
    def cmd_playlistinfo(self, c, a):
        rng = range(len(self.queue))
        if a:
            start, end = parse_range(a[0], len(self.queue))
            rng = range(start, min(end, len(self.queue)))
        out = b""
        for i in rng:
            out += c.lines(self.queue_pairs(i))
        return out

    def cmd_add(self, c, a):
        if not a:
            raise Ack(ACK_ARG, "wrong number of arguments for \"add\"")
        at = int(a[1]) if len(a) > 1 else None
        self.enqueue(self.resolve(a[0]), at)
        return b""

    def cmd_addid(self, c, a):
        added = self.enqueue(self.resolve(a[0])[:1])
        return c.lines([("Id", str(added[0]["id"]))])

    def remove_at(self, indexes):
        for i in sorted(indexes, reverse=True):
            del self.queue[i]
            if self.current is not None:
                if i == self.current:
                    self.current = None
                    self.state = "stop"
                    self.changed("player")
                elif i < self.current:
                    self.current -= 1
        self.queue_changed()

    def cmd_deleteid(self, c, a):
        sid = int(a[0])
        for i, s in enumerate(self.queue):
            if s["id"] == sid:
                self.remove_at([i])
                return b""
        raise Ack(ACK_NO_EXIST, "No such song")

    def cmd_delete(self, c, a):
        start, end = parse_range(a[0], len(self.queue))
        if start >= len(self.queue):
            raise Ack(ACK_ARG, "Bad song index")
        self.remove_at(list(range(start, min(end, len(self.queue)))))
        return b""

    def cmd_move(self, c, a):
        start, end = parse_range(a[0], len(self.queue))
        to = int(a[1])
        playing = self.queue[self.current]["id"] if self.current is not None else None
        block = self.queue[start:end]
        del self.queue[start:end]
        self.queue[to:to] = block
        if playing is not None:
            self.current = [s["id"] for s in self.queue].index(playing)
        self.queue_changed()
        return b""

    def cmd_clear(self, c, a):
        self.queue = []
        self.current = None
        if self.state != "stop":
            self.state = "stop"
            self.changed("player")
        self.queue_changed()
        return b""

    def cmd_shuffle(self, c, a):
        playing = self.queue[self.current]["id"] if self.current is not None else None
        random.Random(1).shuffle(self.queue)
        if playing is not None:
            self.current = [s["id"] for s in self.queue].index(playing)
        self.queue_changed()
        return b""

    # stored playlists
    def stored(self, name):
        if name not in self.playlists:
            raise Ack(ACK_NO_EXIST, "No such playlist")
        return self.playlists[name]

    def stored_changed(self):
        self.changed("stored_playlist")

    def cmd_listplaylists(self, c, a):
        out = []
        for name in self.playlists:
            out += [("playlist", name), ("Last-Modified", "2026-01-01T00:00:00Z")]
        return c.lines(out)

    def cmd_listplaylistinfo(self, c, a):
        uris = self.stored(a[0])
        rng = range(len(uris))
        if len(a) > 1:
            if self.version < "0.24":
                raise Ack(ACK_ARG, "too many arguments for \"listplaylistinfo\"")
            start, end = parse_range(a[1], len(uris))
            rng = range(start, min(end, len(uris)))
        out = b""
        for i in rng:
            song = self.find_song(uris[i]) or {"file": uris[i]}
            out += c.lines(self.song_pairs(song))
        return out

    def cmd_load(self, c, a):
        self.enqueue([self.find_song(u) or {"file": u} for u in self.stored(a[0])])
        return b""

    def cmd_save(self, c, a):
        if a[0] in self.playlists:
            raise Ack(ACK_NO_EXIST, "Playlist already exists")
        self.playlists[a[0]] = [s["file"] for s in self.queue]
        self.stored_changed()
        return b""

    def cmd_rm(self, c, a):
        self.stored(a[0])
        del self.playlists[a[0]]
        self.stored_changed()
        return b""

    def cmd_rename(self, c, a):
        self.stored(a[0])
        if a[1] in self.playlists:
            raise Ack(ACK_NO_EXIST, "Playlist already exists")
        self.playlists[a[1]] = self.playlists.pop(a[0])
        self.stored_changed()
        return b""

    def cmd_playlistadd(self, c, a):
        uris = [s["file"] for s in self.resolve(a[1])]
        self.playlists.setdefault(a[0], []).extend(uris)
        self.stored_changed()
        return b""

    def cmd_playlistdelete(self, c, a):
        uris = self.stored(a[0])
        pos = int(a[1])
        if pos < 0 or pos >= len(uris):
            raise Ack(ACK_ARG, "Bad song index")
        del uris[pos]
        self.stored_changed()
        return b""

    def cmd_playlistclear(self, c, a):
        self.playlists[a[0]] = []
        self.stored_changed()
        return b""

    # library
    def cmd_lsinfo(self, c, a):
        path = (a[0] if a else "").strip("/")
        prefix = path + "/" if path else ""
        dirs, files = [], []
        for s in self.songs:
            if not s["file"].startswith(prefix):
                continue
            rest = s["file"][len(prefix):]
            if "/" in rest:
                d = prefix + rest.split("/", 1)[0]
                if d not in dirs:
                    dirs.append(d)
            else:
                files.append(s)
        if path and not dirs and not files:
            raise Ack(ACK_NO_EXIST, "No such directory")
        out = b""
        for d in dirs:
            out += c.lines([("directory", d), ("Last-Modified", "2026-01-01T00:00:00Z")])
        for s in files:
            out += c.lines(self.song_pairs(s))
        if not path:
            for name in self.playlists:
                out += c.lines([("playlist", name)])
        return out

    def cmd_list(self, c, a):
        if not a:
            raise Ack(ACK_ARG, "too few arguments for \"list\"")
        tag = a[0].lower()
        rest = a[1:]
        if rest and rest[-2:-1] == ["group"]:
            rest = rest[:-2]
        if tag not in TAGS and tag != "file":
            raise Ack(ACK_ARG, "Unknown tag type: %s" % a[0])
        if len(rest) == 1 and not rest[0].startswith("("):
            # `list album <artist>`: the ancient positional spelling
            rest = ["artist", rest[0]]
        songs = self.matching(rest, fold=False)
        seen = []
        for s in songs:
            vals = as_list(s.get(tag)) or [""]
            for v in vals:
                if v not in seen:
                    seen.append(v)
        return c.lines((WIRE_KEY.get(tag, tag), v) for v in seen)

    def cmd_find(self, c, a):
        args, window = self.window(a)
        rows = self.apply_window(self.matching(args, fold=False), window)
        return b"".join(c.lines(self.song_pairs(s)) for s in rows)

    def cmd_search(self, c, a):
        args, window = self.window(a)
        rows = self.apply_window(self.matching(args, fold=True), window)
        return b"".join(c.lines(self.song_pairs(s)) for s in rows)

    def cmd_findadd(self, c, a):
        hits = self.matching(a, fold=False)
        if hits:
            self.enqueue(hits)
        return b""

    def cmd_searchadd(self, c, a):
        hits = self.matching(a, fold=True)
        if hits:
            self.enqueue(hits)
        return b""

    def cmd_count(self, c, a):
        hits = self.matching(a, fold=False)
        total = sum(float(s.get("duration") or 0) for s in hits)
        return c.lines([("songs", str(len(hits))), ("playtime", str(int(total)))])

    # binary
    def binary(self, c, data, mime, offset, with_size=True):
        chunk = data[offset:offset + c.binarylimit]
        head = []
        if with_size:
            head.append(("size", str(len(data))))
        if mime:
            head.append(("type", mime))
        head.append(("binary", str(len(chunk))))
        return c.lines(head) + chunk + b"\n"

    def cmd_albumart(self, c, a):
        uri, offset = a[0], int(a[1])
        directory = os.path.dirname(uri)
        if directory not in self.covers:
            raise Ack(ACK_NO_EXIST, "No file exists")
        data, _mime = self.covers[directory]
        return self.binary(c, data, "", offset)

    def cmd_readpicture(self, c, a):
        uri, offset = a[0], int(a[1])
        if uri not in self.pictures:
            return b""   # MPD answers a plain OK when the file has no picture
        data, mime = self.pictures[uri]
        return self.binary(c, data, mime, offset)
