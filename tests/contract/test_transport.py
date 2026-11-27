"""The transport verbs: what goes over the wire for each."""

import time

from harness import ContractCase

FILES = ["Thin Lizzy/Jailbreak/01 Jailbreak.flac", "Thin Lizzy/Jailbreak/02 Southbound.flac",
         "ABBA/Arrival/01 Dancing Queen.flac"]


class Transport(ContractCase):
    def setUp(self):
        super().setUp()
        self.load_queue(FILES, current=0, state="play")
        self.assertIsNotNone(self.state(3.0, 0, state="play"))
        time.sleep(0.2)
        self.mpd.clear_log()

    def sent(self, line, name, timeout=2.0):
        self.bridge.send(line)
        ok = self.mpd.wait_for(lambda: self.mpd.commands(name), timeout)
        self.assertTrue(ok, "%r sent no %s" % (line, name))
        return [t for _, t in self.mpd.commands(name)]

    def test_toggle_pauses_resumes_and_starts(self):
        self.assertEqual(self.sent("toggle", "pause"), [["pause", "1"]])
        self.assertIsNotNone(self.state(2.0, 0, state="pause"))
        self.mpd.clear_log()
        self.assertEqual(self.sent("toggle", "pause"), [["pause", "0"]])
        self.bridge.send("stop")
        self.assertIsNotNone(self.state(2.0, self.bridge.mark() - 1, state="stop")
                             or self.state(2.0, 0, state="stop"))
        self.mpd.clear_log()
        self.assertEqual(self.sent("toggle", "play"), [["play"]])

    def test_simple_verbs(self):
        cases = [("play", ["play"]), ("pause", ["pause", "1"]), ("resume", ["pause", "0"]),
                 ("next", ["next"]), ("prev", ["previous"]), ("stop", ["stop"])]
        for line, wire in cases:
            self.mpd.clear_log()
            got = self.sent(line, wire[0])
            self.assertEqual(got, [wire], line)

    def test_seek_is_absolute_with_three_decimals(self):
        self.assertEqual(self.sent("seek 12.5", "seekcur"), [["seekcur", "12.500"]])

    def test_volume_is_clamped(self):
        self.assertEqual(self.sent("volume 150", "setvol"), [["setvol", "100"]])
        self.mpd.clear_log()
        self.assertEqual(self.sent("volume -3", "setvol"), [["setvol", "0"]])
        self.mpd.clear_log()
        self.assertEqual(self.sent("volume 42.7", "setvol"), [["setvol", "42"]])

    def test_setopt_sends_the_option_itself(self):
        for name in ("repeat", "random", "single", "consume"):
            self.mpd.clear_log()
            self.assertEqual(self.sent("setopt %s 1" % name, name), [[name, "1"]])
        self.mpd.clear_log()
        self.assertEqual(self.sent("setopt single oneshot", "single"), [["single", "oneshot"]])

    def test_setopt_without_value_sends_zero(self):
        self.assertEqual(self.sent("setopt random", "random"), [["random", "0"]])

    def test_play_id(self):
        with self.mpd.lock:
            sid = self.mpd.queue[2]["id"]
        self.assertEqual(self.sent("play_id %d" % sid, "playid"), [["playid", str(sid)]])

    def test_update_and_rescan(self):
        self.assertEqual(self.sent("update", "update"), [["update"]])
        self.assertEqual(self.sent("rescan ABBA", "rescan"), [["rescan", "ABBA"]])

    def test_a_command_is_followed_by_a_state_push(self):
        mark = self.bridge.mark()
        self.bridge.send("volume 33")
        self.assertIsNotNone(self.state(1.5, mark, volume="33"))
