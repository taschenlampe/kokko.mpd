#!/usr/bin/env python3
"""Unit tests for bin/mpd-bridge -- no MPD, no shell, no deps.

    python3 tests/test_bridge.py      (or: tests/run.sh)

Stdlib only on purpose: the plugin must be checkable on a machine that has
nothing installed. The bridge is imported by path because it carries no `.py`
suffix (it is a copy of the upstream script, see NOTICE.md).

The last three sections drive the real Bridge methods -- `with_cmd`, `drop`,
`query_worker`, `submit_query`, `manager` -- against a fake transport:
`MPDConn` is subclassed and its `connect()` hands out a recording socket and
file, while `readline`/`send`/`read_response`/`command` stay the production
code. No socket is opened, no MPD is needed, and nothing is installed.
"""
import http.server
import importlib.machinery
import importlib.util
import json
import os
import shutil
import socket
import socketserver
import tempfile
import threading
import time
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "bin", "mpd-bridge")

FAILS = []
CHECKS = 0      # counted so the summary can say "3 of 36" and not "3 of 3"


def load_bridge():
    loader = importlib.machinery.SourceFileLoader("bridge_under_test", BRIDGE)
    spec = importlib.util.spec_from_loader("bridge_under_test", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


B = load_bridge()

# Held so that swapping B.MPDConn for a fake cannot rebind the real class.
REAL_MPDConn = B.MPDConn


# ---------------------------------------------------------------- fake wire
#
# What a lost reply looks like. `readline` raises it after the command was
# already written, which is the case the retry rules are about.
RESET = OSError(104, "Connection reset by peer")


class FakeSock:
    """Records what the bridge writes instead of sending it anywhere.

    `fail_send_at` makes the Nth and every later write raise the way a socket
    that has just been closed does -- the command never reaches the wire. That
    is the failure the retry has to tell apart from a reply that was lost after
    a write that did land.
    """

    def __init__(self, wire, host="", fail_send_at=None):
        self.wire = wire
        self.host = host
        self.closed = False
        self.shut = False
        self.fail_send_at = fail_send_at
        self.sends = 0

    def sendall(self, data):
        self.sends += 1
        if self.closed or (self.fail_send_at is not None
                           and self.sends >= self.fail_send_at):
            raise OSError(9, "Bad file descriptor")
        self.wire.append(data.decode("utf-8", "replace").rstrip("\n"))

    def shutdown(self, how):
        self.shut = True

    def close(self):
        self.closed = True

    def settimeout(self, value):
        pass

    def setsockopt(self, *args):
        pass


class FakeFile:
    """The read side: scripted lines, and a server that then just sits there.

    A script entry that is an exception is raised rather than returned, which
    is how a reply that dies on the way back is written down.
    """

    def __init__(self, script=None, gate=None, block=False):
        self.script = list(script or [])
        self.gate = gate
        self.block = block
        self.reads = 0
        self.entered = threading.Event()
        self.release = threading.Event()

    def readline(self):
        self.reads += 1
        if self.gate is not None and self.reads == 1:
            self.entered.set()
            self.gate.wait(3.0)          # hold this read open, like an idle read
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            return item
        if self.block:
            self.release.wait(3.0)       # an `idle` reply that has not come yet
            return b""                   # ... and then the peer is gone
        return b"OK\n"

    def read(self, count=-1):
        return b""

    def close(self):
        pass


class FakeConn(B.MPDConn):
    """The real MPDConn on a fake transport: `connect()` dials nothing."""

    def __init__(self, target, password="", script=None, gate=None,
                 connect_gate=None, block=False, wire=None, fail_send_at=None):
        # The captured class, not B.MPDConn: that name is the factory by now.
        REAL_MPDConn.__init__(self, target, password)
        self.script = script
        self.gate = gate
        self.connect_gate = connect_gate
        self.block = block
        self.wire = wire if wire is not None else []
        self.fail_send_at = fail_send_at
        self.connecting = False

    def connect(self, timeout=None):
        self.connecting = True
        if self.connect_gate is not None:
            self.connect_gate.wait(3.0)  # a connect that is still in flight
        self.sock = FakeSock(self.wire, self.target[1], self.fail_send_at)
        self.fh = FakeFile(self.script, self.gate, self.block)
        self.version = "0.23.5"
        return self.version


class Wire:
    """Stands in for MPDConn: one FakeConn per call, one shared wire."""

    def __init__(self, plans):
        self.plans = list(plans)
        self.made = []
        self.wire = []

    def __call__(self, target, password=""):
        plan = self.plans.pop(0) if self.plans else {}
        conn = FakeConn(target, password, wire=self.wire, **plan)
        self.made.append(conn)
        return conn


def planted(plans):
    """Swap the bridge's MPDConn for a recording factory: (wire, saved class)."""
    factory = Wire(plans)
    saved = B.MPDConn
    B.MPDConn = factory
    return factory, saved


def stop_bridge(bridge):
    """Let go of the threads a section started, so the next one starts clean."""
    bridge.stop.set()
    bridge.wake.set()
    with bridge.query_cv:
        bridge.query_cv.notify_all()


def wait_for(predicate, seconds=2.0):
    """Poll instead of sleeping a fixed time: a pass should cost no stopwatch."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def connected_cmd(plans, events=None):
    """A bridge holding an already connected fake command connection."""
    factory, saved = planted(plans)
    bridge = B.Bridge()
    sink = events if events is not None else []
    bridge.emit = sink.append
    bridge.refresh_soon = lambda: None      # no background refresh thread
    bridge.request_art = lambda song: None  # no art thread either
    bridge.cmd = factory(bridge.target, bridge.password)
    bridge.cmd.connect()
    bridge.connected = True
    return factory, saved, bridge, sink


def raised_by(fn):
    """The class name of what fn raises, or "" if it returns normally."""
    try:
        fn()
    except BaseException as exc:            # classifying, not handling
        return type(exc).__name__
    return ""


class CannedConn(REAL_MPDConn):
    """A connection that keeps the arguments of every command it is asked.

    `execute_query` builds the argument list; this records it, so a check can
    look at what MPD would have been asked instead of at the quoting on the
    wire. `reject_regex` is a build without the `=~` operator: it refuses a
    regex filter exactly like MPD does, with an ACK.
    """

    def __init__(self, version="0.23.5", pairs=(), reject_regex=False):
        REAL_MPDConn.__init__(self, ("tcp", "127.0.0.1", 6600))
        self.version = version
        self.pairs = list(pairs)
        self.reject_regex = reject_regex
        self.calls = []

    def command(self, name, *args):
        self.calls.append((name, list(args)))
        if self.reject_regex and any("=~" in str(a) for a in args):
            raise B.MPDCommandError("unsupported operator")
        return self.pairs, None


def list_args(version, request, pairs=(), reject_regex=False):
    """The `list` arguments execute_query builds for one request."""
    conn = CannedConn(version, pairs, reject_regex)
    B.Bridge().execute_query(conn, "list", request)
    return conn.calls[-1][1]


def check(name, got, want):
    global CHECKS
    CHECKS += 1
    if got == want:
        print("   ok    %s" % name)
    else:
        FAILS.append(name)
        print("   FAIL  %s\n           expected: %r\n           got:      %r" % (name, want, got))


def jpeg(size):
    """A fake JPEG of an exact byte length, so the pick can be identified by size."""
    head = b"\xff\xd8"
    return head + b"x" * max(0, size - len(head))


def picked(files):
    """Write a library with the given (name, size) files and return the chosen bytes."""
    base = tempfile.mkdtemp(prefix="mpd-cover-")
    album = os.path.join(base, "Album")
    os.makedirs(album)
    for name, size in files:
        with open(os.path.join(album, name), "wb") as handle:
            handle.write(jpeg(size))
    saved = B.music_directory
    B.music_directory = lambda: base
    try:
        data, _mime = B.local_cover("Album/track.mp3")
        return data
    finally:
        B.music_directory = saved
        shutil.rmtree(base, ignore_errors=True)


print("=== cover pick (local_cover) ===")
# The classic names win over everything else, "folder" is the one this library uses.
check("folder.jpg beats the Windows files",
      len(picked([("AlbumArt_{0F838ADF}_Large.jpg", 500), ("folder.jpg", 900)])), 900)
# A front cover has to beat a back cover, even when the back one is the bigger scan.
check("front beats back",
      len(picked([("X - Front Cover.jpg", 400), ("X - Back Cover.jpg", 900)])), 400)
# Nothing but a GUID-named Windows file (the case that motivated the pattern ranking).
check("AlbumArt_{GUID}_Large is found",
      len(picked([("AlbumArt_{0F838ADF-41DB-4F92-9414-C6023070E2EA}_Large.jpg", 700)])), 700)
# Only the wrong side of the booklet: still better than nothing.
check("a lone back cover is still used",
      len(picked([("X - Back Cover.jpg", 600)])), 600)
# "Album Art.jpg" is a classic name, "Album Art Small" is not.
check("Album Art beats Album Art Small",
      len(picked([("Album Art.jpg", 300), ("Album Art Small.jpg", 800)])), 300)
# Within one rank the bigger file wins (the better scan).
check("within a rank the bigger file wins",
      len(picked([("cover.jpg", 200), ("folder.jpg", 800)])), 800)
# No image at all.
check("no image means empty", picked([("track.mp3", 100)]), b"")
# Larger than the plugin's limit: refuse it rather than read a huge file.
check("an oversized image is skipped",
      picked([("folder.jpg", B.ART_LIMIT + 10)]), b"")

print("=== filter expression (contains_expression) ===")
check("category filter with (?i)", B.contains_expression("artist", "iam"), "(artist =~ '(?i)iam')")
# Two escaping layers are visible here and both are needed: `re.escape` doubles the
# metacharacters (the regex layer), `quote_filter_value` doubles the backslashes again
# (the filter's '...' layer). Verified against a live MPD with real album names
# ("#1's International Version", "( O )( O )( O ), cl-018") -- see tests/smoke_mpd.py.
check("special characters are escaped",
      B.contains_expression("album", "AC/DC + live"), "(album =~ '(?i)AC/DC\\\\ \\\\+\\\\ live')")
check("apostrophe in an artist name",
      B.quote_filter_value("O'Brien"), "O\\'Brien")
check("backslash is doubled", B.quote_filter_value("a\\b"), "a\\\\b")

print("=== a list search inside a filter keeps both conditions ===")
# The panel narrows a nested list -- one artist, one genre -- and searches
# inside it, and it sends both in one request (Panel.qml applyCategorySearch:
# { mode: "list", tag: tag, filter: context, search: trimmed }). A list command
# carries one filter, so the narrowing and the term have to be joined by AND.
# Built the other way round, the term alone answered: artist "Little Dragon"
# plus "New" came back with the "New" albums of every artist in the library
# (measured against the real one: 12 rows, Little Dragon's among them).
check("with a filter, the search is narrowed by it",
      list_args("0.23.5", {"tag": "album",
                           "filter": [["artist", "Little Dragon"]],
                           "search": "New"}),
      ["album", "((artist == 'Little Dragon') AND (album =~ '(?i)New'))"])
# Several filter clauses to one term: the same AND, nothing dropped.
check("two filter clauses keep the search too",
      list_args("0.23.5", {"tag": "album",
                           "filter": [["artist", "Little Dragon"], ["genre", "Trip-Hop"]],
                           "search": "New"}),
      ["album", "(((artist == 'Little Dragon') AND (genre == 'Trip-Hop')) AND (album =~ '(?i)New'))"])
# Without a filter the expression is the one it always was.
check("without a filter nothing changes",
      list_args("0.23.5", {"tag": "album", "search": "New"}),
      ["album", "(album =~ '(?i)New')"])
# 0.20 has no filter expressions to join: it keeps the positional spelling,
# exactly as before.
check("a 0.20 server keeps the positional spelling",
      list_args("0.20.3", {"tag": "album",
                           "filter": [["artist", "Little Dragon"]],
                           "search": "New"}),
      ["album", "album", "New"])
# And a build without `=~` still falls back to `contains` rather than failing.
check("a regex-less build still answers",
      list_args("0.23.5", {"tag": "album", "search": "New"}, reject_regex=True),
      ["album", "(album contains 'New')"])

print("=== cache key (art_key) ===")
a = B.art_key({"file": "Rock/X/01.mp3", "album": "X", "albumartist": "Y"})
b = B.art_key({"file": "Rock/X/02.mp3", "album": "X", "albumartist": "Y"})
c = B.art_key({"file": "Rock/Z/01.mp3", "album": "X", "albumartist": "Y"})
check("same album -> same key", a, b)
check("other directory -> other key", a == c, False)
check("the key is 20 characters", len(a), 20)

print("=== image type (extension_for) ===")
check("JPEG detected", B.extension_for(b"\xff\xd8\xff\xe0", ""), ".jpg")
check("PNG detected", B.extension_for(b"\x89PNG\r\n\x1a\n", ""), ".png")
check("WEBP detected", B.extension_for(b"RIFF\x00\x00\x00\x00WEBP", ""), ".webp")
check("falls back to the MIME type", B.extension_for(b"????", "image/png"), ".png")
check("unknown", B.extension_for(b"????", ""), ".img")

print("=== music directory (music_directory) ===")
tmp = tempfile.mkdtemp(prefix="mpd-conf-")
try:
    os.makedirs(os.path.join(tmp, "mpd"))
    music = os.path.join(tmp, "Musik")
    os.makedirs(music)
    with open(os.path.join(tmp, "mpd", "mpd.conf"), "w") as handle:
        handle.write('music_directory    "%s"\n' % music)
    saved_env = os.environ.get("XDG_CONFIG_HOME")
    os.environ["XDG_CONFIG_HOME"] = tmp
    B._MUSIC_DIR = None                     # the module caches its answer
    check("reads music_directory from mpd.conf", B.music_directory(), music)
    if saved_env is None:
        os.environ.pop("XDG_CONFIG_HOME", None)
    else:
        os.environ["XDG_CONFIG_HOME"] = saved_env
    B._MUSIC_DIR = None
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("=== command retry (with_cmd) ===")
# A reply that never comes back is no proof that the command did not run. The
# old rule refused to repeat anything that had reached the wire, and against a
# peer that has just gone away the write *does* reach the wire -- only the read
# learns of it -- so the first press after MPD's idle timeout was swallowed.
# The retry is now scoped to the command and told apart by kind.
#
# A transport command has a defined target, so it is repeated when its reply is
# lost: a doubled `next` is the smaller evil against a press that does nothing.
factory, saved, bridge, events = connected_cmd([{"script": [RESET]},
                                                {"script": [b"OK\n"]}])
try:
    bridge.handle("next")
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

check("a lost reply repeats `next` on a fresh connection",
      factory.wire, ["next", "next"])
check("... building the connection the repeat needs", len(factory.made), 2)
check("... and nothing is reported to the user",
      [e.get("event") for e in events], [])

# Even earlier: an idle command connection is replaced *before* a command is
# sent on it, so the case above is the second line of defence rather than the
# first. This is what makes the first press after a pause land at all.
factory, saved, bridge, events = connected_cmd([{"script": [RESET]},
                                                {"script": [b"OK\n"]}])
dead_sock = bridge.cmd.sock
bridge.cmd.last_used = time.monotonic() - 61   # just past MPD's own 60 s
try:
    bridge.handle("next")
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

check("an idle command connection is replaced before it is used",
      len(factory.made), 2)
check("... so `next` goes out once, on the fresh one", factory.wire, ["next"])
check("... and the dead socket is never written to", dead_sock.sends, 0)
check("... with nothing reported to the user",
      [e.get("event") for e in events], [])

# A failure at the write itself proves nothing ran, so that command is repeated
# on a fresh socket. MPD closes an idle connection after a minute, and the
# first press after that used to be swallowed -- that is what the retry was
# written for.
factory, saved, bridge, events = connected_cmd([{"script": [b"OK\n"]},
                                                {"script": [b"OK\n"]}])
bridge.cmd.sock.closed = True              # the write goes nowhere
try:
    bridge.handle("next")
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

check("a command that never left is retried", factory.wire, ["next"])
check("... on a fresh connection", len(factory.made), 2)

# The other half of the rule, and why the retry may not belong to the callback:
# a mutation whose reply was lost must not be sent again. An extra `add` cannot
# be undone by pressing again.
factory, saved, bridge, events = connected_cmd([{"script": [RESET]}])
try:
    bridge.mutate({"op": "add", "uri": "X/song.mp3"})
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

check("an `add` whose reply was lost is not repeated",
      factory.wire, ["add \"X/song.mp3\""])
check("... no connection is built for a retry that must not happen",
      len(factory.made), 1)
check("... the caller hears a connection error that names the risk",
      [(e.get("event"), "not repeated" in (e.get("error") or ""))
       for e in events], [("disconnected", True)])

# A callback is not one command, and it may not be replayed as a whole: the
# failing write is one command, the ones before it already did their work.
# Measured on the unfixed bridge (write of the second queue read fails):
# `findadd` went out twice and appended the whole artist twice.
factory, saved, bridge, events = connected_cmd([
    {"script": [b"playlistlength: 5\n", b"OK\n", b"OK\n"], "fail_send_at": 3},
    {"script": [b"playlistlength: 6\n", b"OK\n",
                b"OK\n", b"playlistlength: 6\n", b"OK\n"]},
])
try:
    bridge.mutate({"op": "findadd", "filter": [["artist", "X"]]})
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

check("findadd goes out exactly once",
      sum(1 for line in factory.wire if line.startswith("findadd")), 1)
check("... and only the queue read that failed is repeated",
      factory.wire, ["status", "findadd \"(artist == 'X')\"", "status"])

# The same for add_and_play, where the `add` is the mutation at stake.
factory, saved, bridge, events = connected_cmd([
    {"script": [b"playlistlength: 5\n", b"OK\n", b"OK\n"], "fail_send_at": 3},
    {"script": [b"playlistlength: 6\n", b"OK\n", b"OK\n"]},
])
try:
    bridge.mutate({"op": "addplay", "uri": "X/song.mp3"})
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

check("`add` goes out exactly once",
      sum(1 for line in factory.wire if line.startswith("add ")), 1)
check("... and the later `play` still lands on the fresh connection",
      factory.wire[-1], "play \"5\"")

# And a read-only callback keeps the retry unconditionally: a second `status`
# costs a round trip and can change nothing.
factory, saved, bridge, events = connected_cmd([
    {"script": [b"state: pause\n", RESET]},   # status answers, the reply dies
    {"script": [b"state: play\n", b"OK\n", b"file: a.mp3\n", b"OK\n"]},
])
try:
    bridge.refresh_once()
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

check("a read-only callback is still retried",
      [(e.get("event"), (e.get("status") or {}).get("state")) for e in events],
      [("state", "play")])

print("=== a dropped connection and the query worker ===")
# A settings change drops the query socket. That used to close the handles from
# the settings thread while the worker was blocked in a read in its own thread:
# the next read reached for a `None`, raised AttributeError -- which is not an
# MPDError, so nothing in run_query caught it -- and the worker was gone for
# good. Queue, albums, artists, files: every tab stayed unanswered from then on.
gate = threading.Event()
factory, saved = planted([
    {"script": [b"file: a.mp3\n", b"OK\n"], "gate": gate},   # the query connection
    {"script": [RESET]},                                     # its retry fails too
    {"script": [b"file: b.mp3\n", b"OK\n"]},                 # and then a fresh one
])
bridge = B.Bridge()
answers = []
bridge.emit = answers.append
first = factory(bridge.target, bridge.password)
first.connect()
with bridge.query_cv:
    bridge.query_conn = first
try:
    bridge.submit_query({"id": 1, "kind": "queue", "channel": "queue"})
    check("the worker is reading when the settings change arrives",
          wait_for(first.fh.entered.is_set), True)
    bridge.drop("settings changed")
    gate.set()                              # the blocked read comes back
    check("the worker is still there after the drop",
          bool(getattr(bridge, "query_thread", None))
          and wait_for(bridge.query_thread.is_alive), True)
    bridge.submit_query({"id": 2, "kind": "queue", "channel": "queue"})
    check("the query after the drop is answered",
          wait_for(lambda: any(a.get("id") == 2 for a in answers)), True)
    check("... and the one that lost its connection reports an error",
          [(a.get("id"), a.get("rows"), bool(a.get("error")))
           for a in answers if a.get("event") == "result"],
          [(1, [], True), (2, [], False)])
finally:
    gate.set()
    B.MPDConn = saved
    stop_bridge(bridge)

# The same hazard without any threads: the handle a drop takes away is the one
# the reader reaches for next, and that has to come back as a connection error.
nostream = REAL_MPDConn(("tcp", "127.0.0.1", 6600))
nostream.fh = None
nostream.sock = FakeSock([])
check("a read on a connection without a stream is a connection error",
      raised_by(lambda: nostream.readline()), "MPDError")
nosock = REAL_MPDConn(("tcp", "127.0.0.1", 6600))
check("a write on a connection without a socket is a connection error",
      raised_by(lambda: nosock.send("status")), "MPDError")

# And a bridge whose worker is gone -- the state the drop above used to leave it
# in for good. The next request has to start one rather than queue behind a
# thread that will never look at the queue again.
factory, saved = planted([{}])
bridge = B.Bridge()
answers = []
bridge.emit = answers.append
try:
    bridge.submit_query({"id": 7, "kind": "queue", "channel": "queue"})
    check("a request starts a worker when none is running",
          wait_for(lambda: any(a.get("id") == 7 for a in answers)), True)
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

print("=== a connection is announced as the server it is ===")
# Changing host or port while the manager is inside connect() used to publish
# the connection that then came up -- the one to the old server -- under the new
# server's name, so a `next` pressed in that window went to the server the user
# had just left. The window is a whole connect(), which is seconds when the new
# host is the dead one.
gate = threading.Event()
factory, saved = planted([
    {"connect_gate": gate},       # the old host: a command connection in flight
    {"script": []},               # the old host: its idle connection
    {"script": [b"state: play\n", b"OK\n", b"file: B-only.mp3\n", b"OK\n"]},
    {"block": True},              # the new host: an idle connection that waits
])
bridge = B.Bridge()
bridge.target = ("tcp", "10.0.0.1", 6600)
bridge.request_art = lambda song: None
records = []


def measure(payload):
    with bridge.cmd_lock:
        live = bridge.cmd
    records.append({
        "event": payload.get("event"),
        "announced": payload.get("target"),
        "live": B.describe(live.target) if live is not None else None,
    })


bridge.emit = measure
manager = threading.Thread(target=bridge.manager, daemon=True)
manager.start()
try:
    check("the manager was still connecting when the settings changed",
          wait_for(lambda: bool(factory.made) and factory.made[0].connecting), True)
    bridge.apply_config({"host": "10.0.0.2", "port": 6700, "password": ""})
    gate.set()                              # the old connect comes up too late
    wait_for(lambda: any(r["event"] == "connected" for r in records), 3.0)
    time.sleep(0.05)
    announced = [r for r in records if r["event"] == "connected"]
    check("no connection is announced as a server it is not",
          [r for r in announced if r["announced"] != r["live"]], [])
    check("the server the settings name is the one announced",
          [r["announced"] for r in announced], ["10.0.0.2:6700"])
    check("the connection to the host that was left is closed",
          [c.sock is None and c.fh is None for c in factory.made[:2]], [True, True])
finally:
    gate.set()
    for conn in factory.made:
        if conn.fh is not None:
            conn.fh.release.set()
    stop_bridge(bridge)
    manager.join(2.0)
    B.MPDConn = saved

print("=== art cache: finished covers only, and one temp name per writer ===")
# Two defects in the same few lines. (1) `cached_art` matched every name that
# starts with the key, `.part` files included -- with a finished cover and a
# leftover temp file in the directory, 300 of 300 lookups handed out the `.part`.
# (2) Both write paths used `path + ".part"` as their temp name, so two writers
# on one album took the file from each other: the slower one got
# FileNotFoundError, the `except (MPDError, OSError)` turned that into "no
# cover", and the finished cover sat on disk unannounced.


class ArtConn(FakeConn):
    """The fake transport with MPD's binary answer scripted in.

    `albumart` answers the way `fetch_binary` reads it: the size and type lines
    first, then the bytes. Any later call ends the response.
    """

    def __init__(self, blob=b"", target=("tcp", "127.0.0.1", 6600)):
        FakeConn.__init__(self, target)
        self.blob = blob
        self.calls = []

    def command(self, name, *args):
        self.calls.append((name, list(args)))
        if name == "albumart" and self.blob:
            return [("size", str(len(self.blob))), ("type", "image/jpeg")], self.blob
        return [], None


art_cache_root = tempfile.mkdtemp(prefix="mpd-artcache-")
saved_cache_home = os.environ.get("XDG_CACHE_HOME")
os.environ["XDG_CACHE_HOME"] = art_cache_root
cache = B.cache_dir()
try:
    key = B.art_key({"file": "Album/01.mp3", "album": "Album", "albumartist": ""})
    part = os.path.join(cache, key + ".jpg.part")
    with open(part, "wb") as handle:
        handle.write(jpeg(64))
    check("a leftover .part is not a cache hit", B.cached_art(key), "")
    cover = os.path.join(cache, key + ".jpg")
    with open(cover, "wb") as handle:
        handle.write(jpeg(2048))
    check("with both files the finished cover wins", B.cached_art(key), cover)
    check("... however often it is asked",
          [B.cached_art(key) for _ in range(50)], [cover] * 50)

    # The other half: two writers, one album. Each has to write its own temp file
    # -- the one that comes second used to find the file already moved away.
    fresh = B.art_key({"file": "Album/07.mp3", "album": "Seven", "albumartist": ""})
    target = os.path.join(cache, fresh + ".jpg")
    written = []
    real_replace = os.replace

    def record_replace(src, dst):
        written.append((src, dst))
        return real_replace(src, dst)

    saved_conn = B.MPDConn
    os.replace = record_replace
    try:
        # (a) the browsing query: its own connection, on the query worker
        B.Bridge().execute_query(ArtConn(jpeg(4096)), "art",
                                 {"uri": "Album/07.mp3", "album": "Seven"})
        # (b) the art thread of a refresh, writing the same album
        writer = B.Bridge()
        writer.emit = lambda payload: None
        B.MPDConn = lambda target, password="": ArtConn(jpeg(4096))
        writer.art_worker("Album/07.mp3", fresh, writer.generation)
    finally:
        os.replace = real_replace
        B.MPDConn = saved_conn

    check("both writers land on the same finished file",
          [dst for _src, dst in written], [target, target])
    check("... with a temp name of their own",
          len(set(src for src, _dst in written)), 2)
    check("... each a .part beside its target",
          [src.startswith(target + ".") and src.endswith(".part")
           for src, _dst in written], [True, True])
    check("... and no temp file left behind",
          [n for n in os.listdir(cache) if n.endswith(".part")],
          [os.path.basename(part)])
finally:
    shutil.rmtree(art_cache_root, ignore_errors=True)
    if saved_cache_home is None:
        os.environ.pop("XDG_CACHE_HOME", None)
    else:
        os.environ["XDG_CACHE_HOME"] = saved_cache_home

print("=== pruning counts finished covers, not temp files ===")
# A `.part` counted as a cache entry like any other. With two covers and two temp
# files in the directory and ART_CACHE_KEEP at 2, the newest two entries -- the
# temp files -- were kept and both covers were deleted: the prune threw away
# exactly the files the cache exists for.
prune_root = tempfile.mkdtemp(prefix="mpd-prune-")
saved_cache_home = os.environ.get("XDG_CACHE_HOME")
os.environ["XDG_CACHE_HOME"] = prune_root
prune_dir = B.cache_dir()
saved_keep = B.ART_CACHE_KEEP
B.ART_CACHE_KEEP = 2
try:
    covers = [os.path.join(prune_dir, "cover-%d.jpg" % n) for n in range(2)]
    parts = [os.path.join(prune_dir, "cover-%d.jpg.part" % n) for n in range(2)]
    for path in covers + parts:
        with open(path, "wb") as handle:
            handle.write(jpeg(32))
    stamp = time.time()
    for n, path in enumerate(covers):        # the finished covers are the older ones
        os.utime(path, (stamp - 600 - n, stamp - 600 - n))
    for n, path in enumerate(parts):         # the temp files look newer
        os.utime(path, (stamp - n, stamp - n))
    B.prune_cache()
    check("the finished covers survive the prune",
          [os.path.exists(p) for p in covers], [True, True])
    check("... and a temp file of a write in progress too",
          [os.path.exists(p) for p in parts], [True, True])
    # The other direction: a temp file nobody is writing any more is garbage, and
    # since the prune no longer counts `.part` files as entries nothing else would
    # ever collect it.
    stale = os.path.join(prune_dir, "stale.jpg.part")
    with open(stale, "wb") as handle:
        handle.write(jpeg(32))
    os.utime(stale, (stamp - 7200, stamp - 7200))
    B.prune_cache()
    check("a temp file left behind by a dead writer is collected",
          os.path.exists(stale), False)
finally:
    B.ART_CACHE_KEEP = saved_keep
    shutil.rmtree(prune_root, ignore_errors=True)
    if saved_cache_home is None:
        os.environ.pop("XDG_CACHE_HOME", None)
    else:
        os.environ["XDG_CACHE_HOME"] = saved_cache_home

print("=== art: an album without a cover is not fetched again on every refresh ===")
# Measured before the fix: ten plain refreshes were ten connections, each with
# binarylimit/albumart/readpicture -- five volume-wheel steps, ten connections
# and twenty cover commands. `request_art`'s guard was per uri and was cleared
# after the attempt, so a refresh that arrived later started from scratch; an
# album that has no cover on any path (12 of 120 in one sample) did it forever.

ART_STATUS = [b"state: play\n", b"OK\n", b"file: nosuch/01.mp3\n", b"OK\n"]


def art_tries(factory):
    """How often the fake wire was asked for a cover."""
    return sum(1 for line in factory.wire if line.startswith("albumart"))


def art_bridge(plans):
    """A bridge on a connected fake command connection, with the real art path."""
    factory, saved = planted(plans)
    bridge = B.Bridge()
    events = []
    bridge.emit = events.append
    bridge.refresh_soon = lambda: None
    bridge.cmd = factory(bridge.target, bridge.password)
    bridge.cmd.connect()
    bridge.connected = True
    return factory, saved, bridge, events


art_cache_root = tempfile.mkdtemp(prefix="mpd-artrefresh-")
saved_cache_home = os.environ.get("XDG_CACHE_HOME")
os.environ["XDG_CACHE_HOME"] = art_cache_root
try:
    factory, saved, bridge, events = art_bridge([{"script": ART_STATUS * 6}])
    try:
        counts = []
        for _ in range(5):
            bridge.refresh_once()
            # Wait for the cover thread to be done -- that is the state the
            # doubling was measured in (refreshes seconds apart); with the retry
            # left in place the next refresh starts a fresh one.
            wait_for(lambda: bridge.art_uri == "", 2.0)
            counts.append(art_tries(factory))
        check("five refreshes ask MPD for the cover once", art_tries(factory), 1)
        check("... and the first of them did ask", counts[0], 1)
        check("... every one after it did not", counts[1:], [1, 1, 1, 1])
    finally:
        stop_bridge(bridge)
        B.MPDConn = saved
finally:
    shutil.rmtree(art_cache_root, ignore_errors=True)
    if saved_cache_home is None:
        os.environ.pop("XDG_CACHE_HOME", None)
    else:
        os.environ["XDG_CACHE_HOME"] = saved_cache_home

print("=== art: a database change is when a missing cover is looked for again ===")
# The negative answer may not be forever: a rescan can give the album the cover it
# lacked. MPD says so as `changed: database` on the idle connection, and that is
# the one thing that has to clear it. A plain refresh (`changed: player`) must
# not -- that is exactly the retry the cache is there to stop.
gate = threading.Event()
factory, saved = planted([
    {"script": ART_STATUS * 4},
    {"script": [b"changed: database\n", b"OK\n",
                b"changed: player\n", b"OK\n"], "gate": gate, "block": True},
])
bridge = B.Bridge()
seen = []
bridge.emit = seen.append
manager = threading.Thread(target=bridge.manager, daemon=True)
manager.start()
try:
    check("the bridge is parked on its idle read",
          wait_for(lambda: len(factory.made) > 1 and factory.made[1].fh is not None
                   and factory.made[1].fh.entered.is_set(), 3.0), True)
    check("... with the cover thread of the first refresh finished",
          wait_for(lambda: bridge.art_uri == "", 3.0), True)
    check("the first refresh asked for the cover once", art_tries(factory), 1)
    gate.set()                               # MPD reports the library changed
    check("the database change is announced",
          wait_for(lambda: any(e.get("event") == "database" for e in seen), 3.0), True)
    check("... and the cover is looked for again",
          wait_for(lambda: art_tries(factory) == 2, 3.0), True)
    # The refresh that follows is not a database change, so it may not ask again
    # -- and a retry that should not happen needs its moment to show up before it
    # can be counted.
    settled = wait_for(lambda: factory.wire.count("status") >= 3, 3.0)
    time.sleep(0.3)
    check("... once, and not on the plain refresh that follows it",
          settled and art_tries(factory), 2)
finally:
    bridge.stop.set()
    gate.set()
    for conn in factory.made:
        if conn.fh is not None:
            conn.fh.release.set()
    manager.join(2.0)
    B.MPDConn = saved

print("=== radio search: the request that is sent to radio-browser ===")
# A real HTTP server on localhost -- stdlib, in a thread, no network -- that
# writes down what it was asked. The URL is the contract with a public API, so
# it is checked field by field rather than trusted: a term stitched into the
# query string by hand is exactly the bug this catches (a space or an `&` in a
# station name would arrive as two parameters and a truncated search).


def station(name="S", url="http://stream/x", codec="MP3", bitrate=128,
            country="Germany", countrycode="DE", lastcheckok=1, votes=10,
            tags="jazz", homepage=""):
    """One entry shaped like radio-browser's: the fields the search returns."""
    return {"stationuuid": "u-1", "name": name, "url": url, "url_resolved": url,
            "codec": codec, "bitrate": bitrate, "country": country,
            "countrycode": countrycode, "lastcheckok": lastcheckok,
            "votes": votes, "tags": tags, "homepage": homepage, "favicon": ""}


class QuietServer(socketserver.ThreadingTCPServer):
    """A server whose clients may hang up mid-answer, as one of these does."""
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        pass


class FakeRadio:
    """One endpoint on 127.0.0.1 that answers whatever a test tells it to.

    Real sockets and real HTTP, so the fetch runs its real code: urlopen, the
    timeout, the header. `requests` keeps every (path, headers) it was hit
    with, which is how the query string is inspected afterwards.
    """

    def __init__(self, responder):
        self.responder = responder
        self.requests = []
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                owner.requests.append((self.path, dict(self.headers)))
                owner.responder(self)

            def log_message(self, format, *args):
                pass

        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:%d" % self.server.server_address[1]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def radio_reply(payload, status=200):
    """A responder that writes one JSON body."""
    body = json.dumps(payload).encode("utf-8")

    def responder(handler):
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    return responder


def radio_raw(body, status=200):
    """A responder that writes bytes nobody guaranteed are JSON."""
    if not isinstance(body, bytes):
        body = body.encode("utf-8")

    def responder(handler):
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    return responder


def radio_hang(_handler):
    """Take the request and never answer it. The timeout case."""
    time.sleep(6.0)


class RadioPatched:
    """Point the bridge's radio search at a local server for one check."""

    def __init__(self, base, timeout=None, grace=None):
        self.base, self.timeout, self.grace = base, timeout, grace

    def __enter__(self):
        self.saved = (B.RADIO_API, B.RADIO_TIMEOUT, B.RADIO_GRACE)
        B.RADIO_API = self.base
        if self.timeout is not None:
            B.RADIO_TIMEOUT = self.timeout
        if self.grace is not None:
            B.RADIO_GRACE = self.grace
        return self

    def __exit__(self, *exc):
        B.RADIO_API, B.RADIO_TIMEOUT, B.RADIO_GRACE = self.saved


# The endpoint is the one the task names, and it is https without a key.
check("the real endpoint",
      (B.RADIO_API + B.RADIO_PATH), "https://all.api.radio-browser.info/json/stations/search")
# No country and no tag means neither parameter is sent -- an empty filter is
# not the same as one that matches nothing.
plain = urllib.parse.parse_qs(urllib.parse.urlsplit(B.radio_url("laut.fm")).query)
check("country and tag are left out when they are empty",
      ("countrycode" in plain, "tag" in plain), (False, False))

with FakeRadio(radio_reply([station(name="Swiss Groove")])) as srv:
    with RadioPatched(srv.base, timeout=2.0):
        rows = B.Bridge().radio_search({"search": "swiss groove & more", "limit": 7,
                                        "country": "CH", "tag": "jazz"})
    path, headers = srv.requests[0]
    query = urllib.parse.urlsplit(path).query
    sent = urllib.parse.parse_qs(query)
    check("the search term arrives whole, ampersand and all",
          sent.get("name"), ["swiss groove & more"])
    check("the term is escaped in the query string, not stitched in",
          ("swiss groove & more" in path, "%26" in query), (False, True))
    check("hidebroken, the order and the limit are asked for",
          (sent.get("hidebroken"), sent.get("order"), sent.get("reverse"),
           sent.get("limit")),
          (["true"], ["votes"], ["true"], ["7"]))
    check("country and tag narrow it",
          (sent.get("countrycode"), sent.get("tag")), (["CH"], ["jazz"]))
    check("the search path is the API's",
          urllib.parse.urlsplit(path).path, "/json/stations/search")
    # radio-browser asks callers to identify themselves rather than arrive as a
    # nameless client, and a default urllib agent gets refused outright.
    check("a User-Agent names the plugin",
          headers.get("User-Agent"), B.RADIO_UA)
    check("... with a contact in it",
          "github.com/taschenlampe/kokko.mpd" in (headers.get("User-Agent") or ""), True)
    check("the answer comes back as a row", [r["name"] for r in rows], ["Swiss Groove"])

with FakeRadio(radio_reply([station()])) as srv:
    with RadioPatched(srv.base, timeout=2.0):
        B.Bridge().radio_search({"search": "   "})
    check("an empty search asks the directory nothing", srv.requests, [])

# A country or a tag on its own *is* a question: that is how the panel browses
# the directory ("which German stations are there", "which jazz stations"). One
# name is enough for the directory to answer, and an empty `name=` next to it
# would narrow nothing -- it would read as "station names containing nothing".
with FakeRadio(radio_reply([station(name="Deutschlandfunk")])) as srv:
    with RadioPatched(srv.base, timeout=2.0):
        rows = B.Bridge().radio_search({"search": "", "country": "DE"})
    # `urlsplit` on nothing would be a crash rather than a failure: a bridge that
    # never asks is exactly what this pair of checks is about, so the missing
    # request has to read as a failed check with the count in it.
    sent = (urllib.parse.parse_qs(urllib.parse.urlsplit(srv.requests[0][0]).query)
            if srv.requests else {})
    check("browsing a country asks for the country and sends no name",
          ("name" in sent, sent.get("countrycode"), len(srv.requests)),
          (False, ["DE"], 1))
    check("... and the answer is still a station row",
          [r["name"] for r in rows], ["Deutschlandfunk"])

with FakeRadio(radio_reply([station(name="Jazz Radio")])) as srv:
    with RadioPatched(srv.base, timeout=2.0):
        rows = B.Bridge().radio_search({"search": "", "tag": "jazz"})
    sent = (urllib.parse.parse_qs(urllib.parse.urlsplit(srv.requests[0][0]).query)
            if srv.requests else {})
    check("browsing a tag asks for the tag and sends no name",
          ("name" in sent, sent.get("tag"), len(srv.requests)), (False, ["jazz"], 1))
    check("... and that answer too", [r["name"] for r in rows], ["Jazz Radio"])

with FakeRadio(radio_reply([station()])) as srv:
    with RadioPatched(srv.base, timeout=2.0):
        B.Bridge().radio_search({"search": "", "country": "", "tag": ""})
    check("a browse with nothing at all still asks nothing", srv.requests, [])

print("=== radio search: only stations that can play ===")
# What the directory sends and what a row is allowed to be. `lastcheckok` is
# radio-browser's own verdict on whether the stream worked the last time it
# tried it; a station it has marked broken is a row that does not play, and a
# search result is the wrong place to find that out. An entry whose URL never
# resolved has nothing to hand a player at all.
answer = [
    station(name="Good One", url="http://a/1"),
    station(name="Broken One", url="http://a/2", lastcheckok=0),
    station(name="No Stream", url="", lastcheckok=1),
    station(name="Also Good", url="http://a/3", bitrate="192"),
    station(name="Checked As String", url="http://a/4", lastcheckok="1"),
]
rows = B.radio_stations(json.dumps(answer).encode(), 50)
check("checked stations with a resolved stream, and nothing else",
      [r["name"] for r in rows], ["Good One", "Also Good", "Checked As String"])
check("a row carries what the panel draws",
      sorted(rows[0]),
      ["bitrate", "codec", "country", "countrycode", "homepage",
       "lastcheckok", "name", "tags", "url_resolved", "votes"])
check("the fields keep their values",
      (rows[0]["url_resolved"], rows[0]["codec"], rows[0]["country"],
       rows[0]["lastcheckok"]),
      ("http://a/1", "MP3", "Germany", 1))
check("a bitrate the API sent as a string is still a number",
      rows[1]["bitrate"], 192)
check("the limit caps the rows", len(B.radio_stations(json.dumps(answer).encode(), 2)), 2)

print("=== radio search: an answer that is not an answer ===")
# Never a traceback and never a hang: each of these is the error reply the
# other queries give, and the bridge lives on.
check("a body that is not JSON is a radio error",
      raised_by(lambda: B.radio_stations(b"<html>503 Service Unavailable</html>")), "RadioError")
check("an empty body is a radio error",
      raised_by(lambda: B.radio_stations(b"")), "RadioError")
check("an object instead of a list is a radio error",
      raised_by(lambda: B.radio_stations(b'{"error":"no stations"}')), "RadioError")
check("an empty list is simply no stations",
      B.radio_stations(b"[]", 50), [])

for label, responder in (
        ("a 503", radio_raw(b"nope", 503)),
        ("HTML where JSON belongs", radio_raw(b"<html>no</html>")),
):
    with FakeRadio(responder) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            check("%s comes back as a radio error" % label,
                  raised_by(lambda: B.Bridge().radio_search({"search": "laut.fm"})),
                  "RadioError")

print("=== radio search: a directory that never answers ===")
# The reason this op is written the way it is. MPD once hung a read and took
# the whole bridge with it; a public HTTP directory is the same hazard with a
# worse socket, so the fetch is cut off and answered as an error, and the
# worker is free again for the next question.
with FakeRadio(radio_hang) as srv:
    # The MPD connection the queue query afterwards needs: the first reply is
    # `binarylimit`'s OK, then the playlist's one entry.
    factory, saved = planted([{"script": [b"OK\n", b"file: a.mp3\n", b"OK\n"]}])
    bridge = B.Bridge()
    answers = []
    bridge.emit = answers.append
    try:
        with RadioPatched(srv.base, timeout=0.3, grace=0.2):
            bridge.submit_query({"id": 1, "kind": "radio_search",
                                 "channel": "radio", "search": "laut.fm"})
            check("the hung request is still answered",
                  wait_for(lambda: any(a.get("id") == 1 for a in answers), 5.0), True)
        check("... with an error and no rows",
              [(a.get("rows"), bool(a.get("error")))
               for a in answers if a.get("id") == 1],
              [([], True)])
        # The whole point: the bridge is still there, and an ordinary MPD query
        # submitted after the hang gets its answer.
        bridge.submit_query({"id": 2, "kind": "queue", "channel": "queue"})
        check("... and an MPD query after it is answered too",
              wait_for(lambda: any(a.get("id") == 2 for a in answers), 5.0), True)
        check("... with the queue it asked for",
              [a["rows"][0]["file"] for a in answers if a.get("id") == 2], ["a.mp3"])
    finally:
        B.MPDConn = saved
        stop_bridge(bridge)

# The socket timeout cannot end every hang: urlopen covers the connect and the
# reads, but name resolution runs in C and ignores it, so a resolver that has
# gone away parks the call for as long as *its* timeout. The watchdog thread on
# top is the ceiling that catches that one -- simulated here by a fetch that
# never returns at all.
with RadioPatched("http://127.0.0.1:1", timeout=0.2, grace=0.2):
    saved_open = B.urlopen_body
    B.urlopen_body = lambda url, timeout: threading.Event().wait()
    try:
        started = time.time()
        kind = raised_by(lambda: B.Bridge().radio_search({"search": "laut.fm"}))
        took = time.time() - started
    finally:
        B.urlopen_body = saved_open
check("a fetch that ignores its own timeout is cut off", kind, "RadioError")
check("... at the hard ceiling rather than never", took < 1.5, True)

print("=== radio search: it never touches MPD ===")
# A radio lookup is a query against somebody else's catalogue. No MPD
# connection is opened for it and no command is sent: not a play, not an add,
# nothing that could change the queue.
with FakeRadio(radio_reply([station()])) as srv:
    factory, saved = planted([])
    bridge = B.Bridge()
    answers = []
    bridge.emit = answers.append
    try:
        with RadioPatched(srv.base, timeout=2.0):
            bridge.submit_query({"id": 3, "kind": "radio_search",
                                 "channel": "radio", "search": "laut.fm"})
            check("the radio answer arrives as a result event",
                  wait_for(lambda: any(a.get("id") == 3 for a in answers), 3.0), True)
        check("... carrying the radio kind and its channel",
              [(a.get("kind"), a.get("channel"), len(a.get("rows") or []))
               for a in answers if a.get("id") == 3],
              [("radio_search", "radio", 1)])
        check("... and MPD was never connected to or asked anything",
              (factory.made, factory.wire), ([], []))
    finally:
        B.MPDConn = saved
        stop_bridge(bridge)

print("=== stream logos: a running station is resolved to its favicon ===")
# The bridge already speaks radio-browser for the search box. The same
# directory answers `GET /json/stations/byurl?url=<stream-url>` with the station
# record for a stream address, and that record carries `favicon`. Issue #56:
# the running stream is resolved through it, the logo is fetched into the one
# art cache, and the local path is announced like any other cover -- the glyph
# stays only while there is no logo.
#
# Four rules come straight from the live directory and are checked here:
#   * about a fifth of the `favicon` URLs are dead -> that is "no logo", not an
#     error the surface could show;
#   * measured logos run to 400 KB -> anything past the ceiling is dropped;
#   * some URLs answer with an HTML error page -> only `image/*` is an image;
#   * the lookup is cached per stream URL, so a state change does not ask again.
#
# The section is skipped when the bridge has none of this: against the unfixed
# file it reports the absence as a failed check instead of dying before the
# first one -- the same shape case 12 uses over BarWidget.qml.


def bridge_has_stream_logos():
    return all(hasattr(B, name) for name in (
        "radio_byurl_url", "radio_favicon_candidates", "favicon_for", "stream_art",
        "RADIO_BYURL_PATH", "RADIO_FAVICON_MAX"))


def png_logo(size):
    """A fake PNG of an exact byte length, so the ceiling can be aimed at."""
    head = b"\x89PNG\r\n\x1a\n"
    return head + b"x" * max(0, size - len(head))


def stream_responders(favicon_rel, image=b"", image_type="image/png",
                      favicon_status=200):
    """The directory's two answers: the byurl record and the logo itself.

    The favicon URL is built from the request's own Host header, so the record
    points back at this fake server whichever port it landed on.
    """
    def responder(handler):
        base = "http://" + handler.headers["Host"]
        if handler.path.startswith("/json/stations/byurl"):
            body = json.dumps([{
                "stationuuid": "u-1", "name": "Groove Salad",
                "url": "", "url_resolved": "", "lastcheckok": 1,
                "favicon": (base + favicon_rel) if favicon_rel else "",
            }]).encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        handler.send_response(favicon_status)
        handler.send_header("Content-Type", image_type)
        handler.send_header("Content-Length", str(len(image)))
        handler.end_headers()
        handler.wfile.write(image)
    return responder


if not bridge_has_stream_logos():
    check("the bridge resolves a running stream's station logo", False, True)
else:
    STREAM_URL = "https://ice5.somafm.com/groovesalad-128-aac"

    check("the byurl endpoint is the directory's",
          B.RADIO_API + B.RADIO_BYURL_PATH,
          "https://all.api.radio-browser.info/json/stations/byurl")
    check("the stream address is one whole parameter",
          urllib.parse.parse_qs(urllib.parse.urlsplit(
              B.radio_byurl_url("http://s/x?a=1&b=2")).query).get("url"),
          ["http://s/x?a=1&b=2"])
    check("the size ceiling is 512 KB", B.RADIO_FAVICON_MAX, 512 * 1024)

    # The usable half of a byurl answer: the logo URL, or nothing.
    check("the station's favicon is read from the record",
          B.radio_favicon_candidates(json.dumps([{
              "favicon": "http://logo/x.png", "lastcheckok": 1}]).encode()),
          ["http://logo/x.png"])
    check("a record without a favicon is no logo",
          B.radio_favicon_candidates(json.dumps([{"favicon": ""}]).encode()), [])
    check("an answer that is not a station list is a radio error",
          raised_by(lambda: B.radio_favicon_candidates(b'{"error":"nope"}')), "RadioError")

    # The lookup is cached: the running station does not re-ask the directory on
    # every state change.
    with FakeRadio(stream_responders("/logo.png", png_logo(200))) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            first = B.favicon_for(STREAM_URL)
            second = B.favicon_for(STREAM_URL)
        asked = [p for p, _h in srv.requests
                 if p.startswith("/json/stations/byurl")]
        check("the station record is found once", first, srv.base + "/logo.png")
        check("the lookup is cached -- the directory is asked once",
              len(asked), 1)
        check("... and the second call answers from memory", second, first)

    # A valid image lands as data plus an image mime.
    with FakeRadio(stream_responders("/logo.png", png_logo(200))) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            data, mime = B.stream_art(STREAM_URL)
        check("a valid logo comes back whole",
              (data, mime), (png_logo(200), "image/png"))

    # A dead favicon URL -- about a fifth of the measured ones -- is no logo; it
    # is not an error the surface could show.
    with FakeRadio(stream_responders("/dead.png", b"", favicon_status=404)) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            check("a dead favicon URL is no logo, not an error",
                  B.stream_art(STREAM_URL), (b"", ""))

    # Past the ceiling the bytes are dropped rather than cached.
    with FakeRadio(stream_responders("/big.png",
                                     png_logo(B.RADIO_FAVICON_MAX + 4096))) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            check("a logo past the size ceiling is dropped",
                  B.stream_art(STREAM_URL), (b"", ""))

    # HTML where an image belongs is not an image.
    with FakeRadio(stream_responders("/page", b"<html>not found</html>",
                                     image_type="text/html")) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            check("HTML where an image belongs is dropped",
                  B.stream_art(STREAM_URL), (b"", ""))

    # The whole path: the worker announces the running stream's logo as a path
    # in the one art cache.
    stream_cache = tempfile.mkdtemp(prefix="mpd-streamart-")
    saved_cache_home = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = stream_cache
    try:
        with FakeRadio(stream_responders("/logo.png", png_logo(4096))) as srv:
            with RadioPatched(srv.base, timeout=2.0):
                B._favicon_cache.clear()
                bridge = B.Bridge()
                events = []
                bridge.emit = events.append
                song = {"file": STREAM_URL, "name": "Groove Salad"}
                bridge.art_worker(STREAM_URL, B.art_key(song),
                                  bridge.generation)
        art = [e for e in events if e.get("event") == "art"]
        path = str(art[0].get("path") or "") if art else ""
        check("the running stream announces a logo path", bool(path), True)
        check("... written into the one art cache",
              os.path.dirname(path), B.cache_dir())
        bytes_on_disk = b""
        if path and os.path.exists(path):
            with open(path, "rb") as handle:
                bytes_on_disk = handle.read()
        check("... carrying the logo's own bytes", bytes_on_disk, png_logo(4096))
        check("... and the surface is told it is an image",
              str(art[0].get("mime", "") if art else "").startswith("image/"), True)
    finally:
        shutil.rmtree(stream_cache, ignore_errors=True)
        if saved_cache_home is None:
            os.environ.pop("XDG_CACHE_HOME", None)
        else:
            os.environ["XDG_CACHE_HOME"] = saved_cache_home

    # Only the running station is resolved. A row in the radio tab is browsed
    # through the `art` query, and that one must not reach the directory at all.
    with FakeRadio(stream_responders("/logo.png", png_logo(64))) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            rows = B.Bridge().execute_query(CannedConn(), "art",
                                            {"uri": STREAM_URL})
        check("browsing a stream row never resolves a logo",
              (srv.requests, rows), ([], [{"type": "art", "path": ""}]))

print("=== stream logos: the fallback walks a chain of candidates ===")
# Issue #56 resolved a stream to *one* favicon -- the first record that carried
# one. The live directory disproved that: for a single stream address it returns
# several records, and the first favicon is not the good one. Measured on
# streaming.smartradio.ch:9502, the first record's favicon (jazzgumboradio's
# favicon.ico) answers 404 while its second (a 30 KB PNG) answers 200. So the
# resolution becomes a candidate chain: every non-empty `favicon` in answer
# order, deduplicated, then each record's homepage /favicon.ico; the first
# candidate that is an image wins. The loop is capped so a directory with dozens
# of matching records cannot fire dozens of fetches, and every candidate failing
# is simply "no logo" -- never an error the surface could show.
#
# The section is skipped when the bridge has none of this, and reports the
# absence as one failed check instead of dying before the first one -- the same
# shape the section above uses.


def bridge_has_candidate_chain():
    return all(hasattr(B, name) for name in (
        "radio_favicon_candidates", "favicon_candidates_for",
        "homepage_favicon", "RADIO_ART_CANDIDATES"))


def chain_responder(build_records, files):
    """The directory's answer plus every candidate URL on the same server.

    `build_records(base)` returns the byurl records for the request's own Host,
    so a favicon or a homepage points back at this fake server whichever port it
    landed on. `files` maps a path to (status, content_type, body); a path not in
    it is a 404 HTML page, the way a dead favicon answers.
    """
    def responder(handler):
        base = "http://" + handler.headers["Host"]
        if handler.path.startswith("/json/stations/byurl"):
            body = json.dumps(build_records(base)).encode("utf-8")
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.send_header("Content-Length", str(len(body)))
            handler.end_headers()
            handler.wfile.write(body)
            return
        path = urllib.parse.urlsplit(handler.path).path
        status, image_type, image = files.get(
            path, (404, "text/html", b"<html>not found</html>"))
        handler.send_response(status)
        handler.send_header("Content-Type", image_type)
        handler.send_header("Content-Length", str(len(image)))
        handler.end_headers()
        handler.wfile.write(image)
    return responder


def candidate_paths(srv):
    """The paths the fake server was asked for, directory requests aside."""
    return [urllib.parse.urlsplit(p).path for p, _h in srv.requests
            if not p.startswith("/json/stations/byurl")]


if not bridge_has_candidate_chain():
    check("the logo fallback tries a chain of candidates", False, True)
else:
    CHAIN_URL = "https://streaming.smartradio.ch:9502/stream"

    check("the per-stream fetch cap is a small number",
          B.RADIO_ART_CANDIDATES, 4)

    # The reader itself: favicons first, in answer order, deduplicated, then
    # each record's homepage /favicon.ico -- and a homepage with no scheme or
    # host is not a candidate at all.
    check("every record's favicon is a candidate, in order",
          B.radio_favicon_candidates(json.dumps([
              {"favicon": "http://a/1.png"},
              {"favicon": "http://a/2.png"},
          ]).encode()),
          ["http://a/1.png", "http://a/2.png"])
    check("a repeated favicon is one candidate",
          B.radio_favicon_candidates(json.dumps([
              {"favicon": "http://a/same.png"},
              {"favicon": "http://a/same.png"},
          ]).encode()),
          ["http://a/same.png"])
    check("a missing favicon falls back to the homepage's /favicon.ico",
          B.radio_favicon_candidates(json.dumps([
              {"favicon": "", "homepage": "http://radio.example/show"},
          ]).encode()),
          ["http://radio.example/favicon.ico"])
    check("favicons come before homepage fallbacks",
          B.radio_favicon_candidates(json.dumps([
              {"favicon": "http://a/x.png", "homepage": "http://radio.example/"},
          ]).encode()),
          ["http://a/x.png", "http://radio.example/favicon.ico"])
    check("a broken homepage is skipped, not turned into a request",
          [B.homepage_favicon(v) for v in ("", "n/a", "www.example.com")],
          ["", "", ""])
    check("an answer that is not a station list is a radio error",
          raised_by(lambda: B.radio_favicon_candidates(b'{"error":"nope"}')),
          "RadioError")

    # 1) The live jazzgumboradio case: the first record's favicon is dead, the
    #    second record's is a good image -- the second one's bytes come back.
    files = {"/dead.png": (404, "text/html", b"<html>gone</html>"),
             "/good.png": (200, "image/png", png_logo(30699))}
    with FakeRadio(chain_responder(
            lambda base: [
                {"favicon": base + "/dead.png"},
                {"favicon": base + "/good.png"},
            ], files)) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            data, mime = B.stream_art(CHAIN_URL)
        check("a dead first favicon does not hide the second record's logo",
              (data, mime), (png_logo(30699), "image/png"))
        check("... both candidates were actually tried",
              candidate_paths(srv), ["/dead.png", "/good.png"])

    # 2) A record with no favicon but a homepage: <host>/favicon.ico is the
    #    candidate that answers.
    files = {"/favicon.ico": (200, "image/x-icon", png_logo(512))}
    with FakeRadio(chain_responder(
            lambda base: [{"favicon": "", "homepage": base + "/show"}],
            files)) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            data, mime = B.stream_art(CHAIN_URL)
        check("a station without a favicon is rescued by its homepage",
              (data, mime), (png_logo(512), "image/x-icon"))
        check("... through the homepage's /favicon.ico",
              candidate_paths(srv), ["/favicon.ico"])

    # 3) Every candidate dead: no logo, and no exception either.
    files = {"/a.png": (404, "text/html", b"<html>no</html>")}
    with FakeRadio(chain_responder(
            lambda base: [{"favicon": base + "/a.png", "homepage": ""}],
            files)) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            check("all candidates dead is simply no logo",
                  B.stream_art(CHAIN_URL), (b"", ""))

    # 4) The cap holds: eight dead candidates must cost at most
    #    RADIO_ART_CANDIDATES fetches. The candidate fetches are the calls to
    #    the (real) fetch the test intercepts and counts.
    files = {"/dead%d.png" % n: (404, "text/html", b"no") for n in range(8)}
    with FakeRadio(chain_responder(
            lambda base: [{"favicon": base + "/dead%d.png" % n}
                          for n in range(8)], files)) as srv:
        calls = []
        real_fetch = B.fetch_remote

        def counting_fetch(url, timeout, accept="image/*"):
            calls.append(url)
            return real_fetch(url, timeout, accept)

        B.fetch_remote = counting_fetch
        try:
            with RadioPatched(srv.base, timeout=2.0):
                B._favicon_cache.clear()
                check("a directory with many dead records is still no logo",
                      B.stream_art(CHAIN_URL), (b"", ""))
        finally:
            B.fetch_remote = real_fetch
        check("... and the fetch loop stops at the cap",
              len(calls), B.RADIO_ART_CANDIDATES)

    # 5) Dedupe reaches the wire: the same URL twice in the chain is fetched once.
    files = {"/same.png": (200, "image/png", png_logo(64))}
    with FakeRadio(chain_responder(
            lambda base: [{"favicon": base + "/same.png"},
                          {"favicon": base + "/same.png"}],
            files)) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            data, mime = B.stream_art(CHAIN_URL)
        hits = [p for p in candidate_paths(srv) if p == "/same.png"]
        check("a repeated candidate is fetched once",
              (len(hits), data == png_logo(64)), (1, True))

    # 6) The candidate list is asked once per stream. A definitively empty
    #    answer is remembered; a directory that could not be reached is not.
    with FakeRadio(chain_responder(lambda base: [], {})) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            first = B.favicon_candidates_for(CHAIN_URL)
            second = B.favicon_candidates_for(CHAIN_URL)
        asked = [p for p, _h in srv.requests
                 if p.startswith("/json/stations/byurl")]
        check("an empty answer is remembered as no candidates",
              (first, second), ([], []))
        check("... and asked once, not once per refresh", len(asked), 1)

    B._favicon_cache.clear()
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    dead_port = closed.getsockname()[1]
    closed.close()
    with RadioPatched("http://127.0.0.1:%d" % dead_port, timeout=0.3, grace=0.2):
        unreachable = B.favicon_candidates_for(CHAIN_URL)
    check("a directory that could not be reached is not remembered",
          (unreachable, CHAIN_URL in B._favicon_cache), ([], False))

    # 7) A broken homepage on a record with a dead favicon is skipped, and the
    #    whole thing still ends as "no logo" rather than a crash.
    with FakeRadio(chain_responder(
            lambda base: [{"favicon": base + "/gone.png",
                           "homepage": "n/a"},
                          {"favicon": "", "homepage": ""}],
            {"/gone.png": (410, "text/html", b"<html>gone</html>")})) as srv:
        with RadioPatched(srv.base, timeout=2.0):
            B._favicon_cache.clear()
            check("a broken homepage neither crashes nor fetches",
                  B.stream_art(CHAIN_URL), (b"", ""))

print("=== health: the daemon stops greeting ===")
# A wedged MPD accepts the connection and then says nothing -- the state that
# made the bar keep showing a stale title as if it were current. The decision
# (two misses, one announcement per change) needs no socket; the probe is then
# run against a real silent socket, a refused port and a transport that greets.

class SilentMPD(socketserver.BaseRequestHandler):
    """Accepts and never sends the banner. What a wedged MPD looks like."""

    def handle(self):
        time.sleep(5.0)          # outlive the probe's own timeout


bridge = B.Bridge()
events = []
bridge.emit = events.append

bridge.health_tick(False, "no banner")
check("one miss is not a verdict", events, [])

bridge.health_tick(False, "no banner")
check("two misses in a row announce the wedge once",
      [(e.get("event"), e.get("ok"), e.get("detail")) for e in events],
      [("health", False, "no banner")])

bridge.health_tick(False, "no banner")
check("... and not again while it stays silent", len(events), 1)

bridge.health_tick(True, "0.24.0")
check("the greeting coming back is announced too",
      [(e.get("event"), e.get("ok")) for e in events],
      [("health", False), ("health", True)])

bridge.health_tick(True, "0.24.0")
check("... once, not on every probe", len(events), 2)

bridge.health_tick(False, "no banner")
bridge.health_tick(True, "0.24.0")
check("a single miss after a recovery is not announced",
      [e.get("ok") for e in events], [False, True])
stop_bridge(bridge)

# The probe, against a socket that really never greets.
quiet = QuietServer(("127.0.0.1", 0), SilentMPD)
threading.Thread(target=quiet.serve_forever, daemon=True).start()
try:
    bridge = B.Bridge()
    bridge.target = ("tcp", "127.0.0.1", quiet.server_address[1])
    ok, detail = bridge.probe_health()
    check("a socket that never greets is a failed probe", (ok, detail != ""), (False, True))
    check("... and the reason is the timeout, not a crash", detail, "timed out")
finally:
    quiet.shutdown()
    quiet.server_close()

# Nothing listening at all: MPD is not running, which is a different sentence.
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
closed_port = sock.getsockname()[1]
sock.close()
bridge = B.Bridge()
bridge.target = ("tcp", "127.0.0.1", closed_port)
ok, detail = bridge.probe_health()
check("a refused connection is a failed probe too", (ok, detail != ""), (False, True))

# And the healthy case, over the fake transport: one connection of its own.
factory, saved = planted([{}])
try:
    bridge = B.Bridge()
    check("a greeting that arrives is a healthy probe",
          bridge.probe_health(), (True, "0.23.5"))
    check("... on a connection the probe opens and closes itself",
          len(factory.made), 1)
finally:
    B.MPDConn = saved

print()
if FAILS:
    print("   %d of %d checks failed: %s" % (
        len(FAILS), CHECKS, ", ".join(FAILS)))
    raise SystemExit(1)
print("   all checks passed")
