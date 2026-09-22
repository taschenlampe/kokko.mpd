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
    """Records what the bridge writes instead of sending it anywhere."""

    def __init__(self, wire, host=""):
        self.wire = wire
        self.host = host
        self.closed = False
        self.shut = False

    def sendall(self, data):
        if self.closed:
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
                 connect_gate=None, block=False, wire=None):
        # The captured class, not B.MPDConn: that name is the factory by now.
        REAL_MPDConn.__init__(self, target, password)
        self.script = script
        self.gate = gate
        self.connect_gate = connect_gate
        self.block = block
        self.wire = wire if wire is not None else []
        self.connecting = False

    def connect(self, timeout=None):
        self.connecting = True
        if self.connect_gate is not None:
            self.connect_gate.wait(3.0)  # a connect that is still in flight
        self.sock = FakeSock(self.wire, self.target[1])
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
# old retry ran the whole callback again, so `next` was written twice and
# skipped a song, `add` appended the same file again, and a toggle that reads
# the state, flips it and is asked to flip it again ended where it started --
# the button looked dead.
factory, saved, bridge, events = connected_cmd([{"script": [RESET]},
                                                {"script": [b"OK\n"]}])
try:
    bridge.handle("next")
finally:
    B.MPDConn = saved
    stop_bridge(bridge)

check("a lost reply does not put `next` on the wire twice", factory.wire, ["next"])
check("... and does not build a connection it may not use", len(factory.made), 1)
check("... the caller hears a connection error instead",
      [e.get("event") for e in events], ["disconnected"])

# The other half of the rule: a failure at the write itself proves nothing ran,
# so the retry the docstring promises still happens. MPD closes an idle
# connection after a minute, and the first press after that used to be
# swallowed -- that is what the retry was written for.
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

print()
if FAILS:
    print("   %d of %d checks failed: %s" % (
        len(FAILS), CHECKS, ", ".join(FAILS)))
    raise SystemExit(1)
print("   all checks passed")
