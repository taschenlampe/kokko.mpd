"""Unit tests for the phase-3 pieces that have logic without sockets:
target resolution, tuning overrides, the health verdict, the executor."""

import os
import sys
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from kokko_mpd import tuning  # noqa: E402
from kokko_mpd.connection import Target, target_from  # noqa: E402
from kokko_mpd.session import Executor  # noqa: E402
from kokko_mpd.state import Health  # noqa: E402


class Targets(unittest.TestCase):
    def test_tcp_default(self):
        self.assertEqual(target_from("", None, env={}), (Target("tcp", "127.0.0.1", 6600), ""))

    def test_explicit_host_ignores_env(self):
        t, pw = target_from("nas", 6601, env={"MPD_HOST": "pw@other", "MPD_PORT": "1"})
        self.assertEqual((t, pw), (Target("tcp", "nas", 6601), ""))

    def test_env_host_with_password_and_port(self):
        t, pw = target_from("", 0, env={"MPD_HOST": "secret@box", "MPD_PORT": "6700"})
        self.assertEqual((t, pw), (Target("tcp", "box", 6700), "secret"))

    def test_unix_and_abstract(self):
        self.assertEqual(target_from("/run/mpd.sock", 1, env={})[0], Target("unix", "/run/mpd.sock"))
        t = target_from("@mpd", 1, env={})[0]
        self.assertEqual((t.host, t.label), ("\0mpd", "@mpd"))

    def test_bad_port(self):
        self.assertEqual(target_from("h", "x", env={})[0].port, 6600)

    def test_label(self):
        self.assertEqual(Target("tcp", "127.0.0.1", 6600).label, "127.0.0.1:6600")


class TuningOverrides(unittest.TestCase):
    def test_known_names_with_the_right_type(self):
        t = tuning.Tuning({"HEALTH_INTERVAL": 2, "HEALTH_FAILS": 5, "RADIO_API": "http://x"})
        self.assertEqual((t.HEALTH_INTERVAL, t.HEALTH_FAILS, t.RADIO_API), (2.0, 5, "http://x"))
        self.assertIsInstance(t.HEALTH_INTERVAL, float)

    def test_unknown_and_wrong_types_are_ignored(self):
        t = tuning.Tuning({"NOPE": 1, "HEALTH_FAILS": "many", "CMD_TIMEOUT": None, "_x": 1})
        self.assertEqual((t.HEALTH_FAILS, t.CMD_TIMEOUT), (2, 10.0))
        self.assertFalse(hasattr(t, "NOPE"))


class FakeEvents:
    def __init__(self):
        self.seen = []

    def health(self, ok, detail, target, fails=None):
        self.seen.append((ok, fails))


class HealthVerdict(unittest.TestCase):
    def setUp(self):
        self.bridge = type("B", (), {})()
        self.bridge.events = FakeEvents()
        self.h = Health(self.bridge)

    def test_first_good_probe_is_announced_once(self):
        self.h.tick(True, "0.24", "t")
        self.h.tick(True, "0.24", "t")
        self.assertEqual(self.bridge.events.seen, [(True, None)])

    def test_one_miss_is_no_verdict_two_are(self):
        self.h.tick(True, "", "t")
        self.h.tick(False, "timed out", "t")
        self.assertEqual(self.bridge.events.seen, [(True, None)])
        self.h.tick(False, "timed out", "t")
        self.h.tick(False, "timed out", "t")
        self.assertEqual(self.bridge.events.seen, [(True, None), (False, 2)])
        self.h.tick(True, "", "t")
        self.assertEqual(self.bridge.events.seen[-1], (True, None))

    def test_a_miss_between_goods_resets(self):
        self.h.tick(False, "", "t")
        self.h.tick(True, "", "t")
        self.h.tick(False, "", "t")
        self.assertEqual(self.bridge.events.seen, [(True, None)])


class ExecutorOrder(unittest.TestCase):
    def test_jobs_run_in_order_on_one_thread(self):
        ex = Executor()
        ex.start()
        seen, threads = [], set()
        done = threading.Event()
        for i in range(50):
            ex.submit(lambda i=i: (seen.append(i), threads.add(threading.get_ident())))
        ex.submit(done.set)
        self.assertTrue(done.wait(2))
        ex.stop()
        self.assertEqual(seen, list(range(50)))
        self.assertEqual(len(threads), 1)

    def test_refresh_is_coalesced(self):
        ex = Executor()
        gate = threading.Event()
        count = []
        ex.submit(gate.wait)
        ex.start()
        for _ in range(10):
            ex.submit_refresh(lambda: count.append(1))
        gate.set()
        done = threading.Event()
        ex.submit(done.set)
        self.assertTrue(done.wait(2))
        ex.stop()
        self.assertEqual(len(count), 1)

    def test_a_failing_job_does_not_stop_it(self):
        ex = Executor()
        ex.start()
        done = threading.Event()
        old = sys.stderr
        sys.stderr = open(os.devnull, "w")
        try:
            ex.submit(lambda: 1 / 0)
            ex.submit(done.set)
            self.assertTrue(done.wait(2))
        finally:
            sys.stderr.close()
            sys.stderr = old
            ex.stop()


if __name__ == "__main__":
    unittest.main()
