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
import importlib.machinery
import importlib.util
import os
import shutil
import tempfile
import threading
import time

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

print()
if FAILS:
    print("   %d of %d checks failed: %s" % (
        len(FAILS), CHECKS, ", ".join(FAILS)))
    raise SystemExit(1)
print("   all checks passed")
