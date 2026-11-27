"""Test harness: one bridge process, one fake MPD, one scratch home.

A test case gets a fake MPD (`self.mpd`) serving the made-up library and a
bridge (`self.bridge`) running as a child process with its stdin/stdout -- the
same pipes the widget uses. The bridge's HOME, XDG_CACHE_HOME and
XDG_CONFIG_HOME point into a temporary directory, MPD_HOST/MPD_PORT are unset,
so nothing the user owns is read or written.

Every test ends with the same invariant check: each query sent got exactly one
`result`, and the bridge exits with 0 when its stdin closes.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from fakempd import library  # noqa: E402
from fakempd.server import FakeMPD  # noqa: E402

DEFAULT_BRIDGE = os.path.join(ROOT, "bin", "mpd-bridge")
LAUNCH = os.path.join(HERE, "launch.py")

# Fast timings for the knobs both bridges must honour (see docs/bridge-contract.md).
TUNING = {
    "HEALTH_INTERVAL": 0.3,
    "HEALTH_TIMEOUT": 0.3,
    "CMD_IDLE_RENEW": 45.0,
    "CMD_TIMEOUT": 2.0,
    "MIN_ROUND_ALIVE": 0.5,
    # Nothing leaves this machine: the public radio directory is replaced by a
    # port nothing listens on, unless a test points it at its own fake.
    "RADIO_API": "http://127.0.0.1:9",
    "RADIO_TIMEOUT": 2.0,
    "RADIO_GRACE": 0.5,
}


def bridge_path() -> str:
    return os.path.abspath(os.environ.get("CONTRACT_BRIDGE") or DEFAULT_BRIDGE)


# The frozen old bridge, or a copy of it (run.py --legacy): its known
# differences are expected failures instead of failures.
LEGACY = (bridge_path() == os.path.abspath(DEFAULT_BRIDGE)
          or os.environ.get("CONTRACT_LEGACY") == "1")


def legacy_differs(reason):
    """A rule the new bridge must keep and the frozen old one is known to break.

    Against bin/mpd-bridge the test is an expected failure (and says so in the
    run); against any other bridge it is an ordinary test.
    """
    def wrap(fn):
        if LEGACY:
            fn = unittest.expectedFailure(fn)
        fn.legacy_reason = reason
        return fn
    return wrap


class BridgeProcess:
    def __init__(self, path, home, tuning=None, env_extra=None):
        env = {k: v for k, v in os.environ.items() if k not in ("MPD_HOST", "MPD_PORT")}
        env.update({
            "HOME": home,
            "XDG_CACHE_HOME": os.path.join(home, "cache"),
            "XDG_CONFIG_HOME": os.path.join(home, "config"),
            "XDG_STATE_HOME": os.path.join(home, "state"),
            "KOKKO_MPD_TUNING": json.dumps(tuning or {}),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        env.update(env_extra or {})
        self.proc = subprocess.Popen(
            [sys.executable, LAUNCH, path], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, cwd=home)
        self.events = []
        self.raw = []
        self.stderr = []
        self.cv = threading.Condition()
        self.sent_ids = []
        self.next_id = 1
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read_out(self):
        for line in self.proc.stdout:
            text = line.decode("utf-8")
            with self.cv:
                self.raw.append(text)
                try:
                    ev = json.loads(text)
                except ValueError:
                    ev = {"event": "__unparseable__", "line": text}
                ev["_t"] = time.monotonic()
                self.events.append(ev)
                self.cv.notify_all()

    def _read_err(self):
        for line in self.proc.stderr:
            self.stderr.append(line.decode("utf-8", "replace"))

    # --- talking

    def send(self, line: str):
        self.proc.stdin.write((line + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def config(self, **values):
        self.send("config " + json.dumps(values))

    def cmd(self, op, **args):
        payload = {"op": op}
        payload.update(args)
        self.send("cmd " + json.dumps(payload))

    def query(self, kind, channel="", **args):
        qid = self.next_id
        self.next_id += 1
        payload = {"id": qid, "kind": kind}
        payload.update(args)
        if channel:
            payload["channel"] = channel
        self.sent_ids.append(qid)
        self.send("query " + json.dumps(payload))
        return qid

    # --- listening

    def mark(self) -> int:
        with self.cv:
            return len(self.events)

    def since(self, mark=0, name=None):
        with self.cv:
            evs = self.events[mark:]
        return [e for e in evs if name is None or e.get("event") == name]

    def wait(self, predicate, timeout=5.0, mark=0):
        """The first event from `mark` on that satisfies `predicate`, or None."""
        deadline = time.monotonic() + timeout
        with self.cv:
            while True:
                for ev in self.events[mark:]:
                    if predicate(ev):
                        return ev
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self.cv.wait(left)

    def wait_event(self, name, timeout=5.0, mark=0, **fields):
        return self.wait(lambda e: e.get("event") == name and all(
            e.get(k) == v for k, v in fields.items()), timeout, mark)

    def result(self, qid, timeout=5.0):
        return self.wait(lambda e: e.get("event") == "result" and e.get("id") == qid, timeout)

    def ask(self, kind, timeout=5.0, **args):
        """Send one query and return its result event."""
        return self.result(self.query(kind, **args), timeout)

    def quiet(self, seconds, mark=None, name=None):
        """The events of `name` that arrived during the next `seconds`."""
        start = self.mark() if mark is None else mark
        time.sleep(seconds)
        return self.since(start, name)

    def close(self, timeout=5.0):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            return None


class ContractCase(unittest.TestCase):
    """Base class: a fake MPD, a bridge, a scratch home."""

    songs = None              # None -> library.SONGS
    version = "0.24.0"
    password = None
    tuning = {}
    autoconnect = True

    def setUp(self):
        # ids a legacy_differs test knows the old bridge leaves unanswered
        self.unanswered_ok = set()
        self.home = tempfile.mkdtemp(prefix="kmpd-contract-")
        os.makedirs(os.path.join(self.home, "config"), exist_ok=True)
        self.mpd = self.make_mpd()
        self.mpd.start()
        tuning = dict(TUNING)
        tuning.update(self.tuning)
        self.bridge = BridgeProcess(bridge_path(), self.home, tuning, self.bridge_env())
        self.addCleanup(self.cleanup)
        if self.autoconnect:
            self.connect()

    def make_mpd(self, **kw):
        songs = library.SONGS if self.songs is None else self.songs
        args = dict(songs=songs, version=self.version, password=self.password,
                    covers=library.COVERS, pictures=library.PICTURES,
                    playlists=library.PLAYLISTS)
        args.update(kw)
        return FakeMPD(**args)

    def bridge_env(self):
        return {}

    def connect(self, mpd=None, **extra):
        mpd = mpd or self.mpd
        mark = self.bridge.mark()
        values = {"host": "127.0.0.1", "port": mpd.port, "password": self.password or ""}
        values.update(extra)
        self.bridge.config(**values)
        ev = self.bridge.wait_event("connected", 5.0, mark)
        self.assertIsNotNone(ev, "no `connected` after config; stderr: %s" % self.bridge.stderr)
        state = self.bridge.wait_event("state", 5.0, mark)
        self.assertIsNotNone(state, "no `state` after connecting")
        return ev

    def state(self, timeout=3.0, mark=0, **status):
        """The latest-arriving state whose status has these values."""
        return self.bridge.wait(lambda e: e.get("event") == "state" and all(
            e["status"].get(k) == v for k, v in status.items()), timeout, mark)

    def queue_files(self):
        with self.mpd.lock:
            return [s["file"] for s in self.mpd.queue]

    def load_queue(self, files, current=None, state="stop"):
        """Put songs into the FAKE server's queue, as another client would."""
        def change(m):
            m.queue = []
            m.enqueue([m.find_song(f) for f in files])
            m.current = current
            m.state = state
        self.mpd.external(change, "playlist", "player")

    def cleanup(self):
        try:
            self.check_every_query_answered()
        finally:
            code = self.bridge.close()
            self.mpd.stop()
            shutil.rmtree(self.home, ignore_errors=True)
        self.assertEqual(code, 0, "bridge did not exit cleanly on EOF; stderr: %s"
                         % "".join(self.bridge.stderr[-20:]))
        bad = self.bridge.since(0, "__unparseable__")
        self.assertEqual(bad, [], "stdout carried a line that is not JSON")
        fenced = [l for l in self.bridge.stderr if l.startswith("contract fence:")
                  and not (LEGACY and "('127.0.0.1', 6600)" in l)]
        self.assertEqual(fenced, [], "the bridge tried to leave the test sandbox")

    def check_every_query_answered(self, timeout=8.0):
        deadline = time.monotonic() + timeout
        while True:
            results = self.bridge.since(0, "result")
            counts = {}
            for r in results:
                counts[r.get("id")] = counts.get(r.get("id"), 0) + 1
            missing = [i for i in self.bridge.sent_ids
                       if counts.get(i, 0) == 0 and i not in self.unanswered_ok]
            if not missing or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        doubled = [i for i, n in counts.items() if n > 1]
        self.assertEqual(missing, [], "queries never answered: %s" % missing)
        self.assertEqual(doubled, [], "queries answered twice: %s" % doubled)
