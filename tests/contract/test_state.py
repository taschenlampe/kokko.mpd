"""State arrives by idle push, deduplicated, in MPD's own (lower-cased) keys."""

import time

from harness import ContractCase

JAIL = "Thin Lizzy/Jailbreak/01 Jailbreak.flac"
SOUTH = "Thin Lizzy/Jailbreak/02 Southbound.flac"
DUET = "Various/Duets/01 Under Pressure.flac"


class IdlePush(ContractCase):
    def test_another_client_playing_is_pushed_without_asking(self):
        mark = self.bridge.mark()
        self.load_queue([JAIL, SOUTH], current=0, state="play")
        ev = self.state(3.0, mark, state="play")
        self.assertIsNotNone(ev, "no state push after an external change")
        self.assertEqual(ev["song"]["file"], JAIL)
        self.assertEqual(ev["song"]["title"], "Jailbreak")
        self.assertEqual(ev["status"]["playlistlength"], "2")

    def test_keys_are_lower_case(self):
        mark = self.bridge.mark()
        self.load_queue([JAIL], current=0, state="play")
        ev = self.state(3.0, mark, state="play")
        for key in list(ev["status"]) + list(ev["song"]):
            self.assertEqual(key, key.lower())
        self.assertEqual(ev["song"]["albumartist"], "Thin Lizzy")
        self.assertEqual(ev["song"]["last-modified"], "2025-12-01T00:00:00Z")

    def test_repeated_tags_are_joined(self):
        mark = self.bridge.mark()
        self.load_queue([DUET], current=0, state="play")
        ev = self.state(3.0, mark, state="play")
        self.assertEqual(ev["song"]["artist"], "Queen, David Bowie")

    def test_an_unchanged_state_is_not_announced_again(self):
        self.load_queue([JAIL], current=0, state="pause")
        self.assertIsNotNone(self.state(3.0, 0, state="pause"))
        time.sleep(0.3)
        mark = self.bridge.mark()
        self.bridge.send("refresh")
        self.bridge.send("refresh")
        self.mpd.changed("mixer")          # an idle wake that changes nothing
        self.assertEqual(self.bridge.quiet(0.6, mark, "state"), [])

    def test_refresh_after_a_real_change_is_announced(self):
        mark = self.bridge.mark()
        with self.mpd.lock:
            self.mpd.volume = 77          # changed behind the bridge's back, no idle
        self.bridge.send("refresh")
        ev = self.state(2.0, mark, volume="77")
        self.assertIsNotNone(ev)

    def test_database_change_is_its_own_event(self):
        mark = self.bridge.mark()
        self.mpd.changed("database")
        self.assertIsNotNone(self.bridge.wait_event("database", 2.0, mark))

    def test_a_scan_ends_in_a_database_event(self):
        mark = self.bridge.mark()
        self.bridge.send("update Thin Lizzy")
        self.assertIsNotNone(self.bridge.wait_event("database", 3.0, mark))
        self.assertEqual(self.mpd.commands("update")[-1][1], ["update", "Thin Lizzy"])

    def test_stored_playlist_changes_do_not_wake_the_bridge(self):
        # documented gap: `stored_playlist` is not in the idle set
        time.sleep(0.2)
        mark = self.bridge.mark()
        before = self.mpd.count("status")
        self.mpd.changed("stored_playlist")
        time.sleep(0.4)
        self.assertEqual(self.mpd.count("status"), before)
        self.assertEqual(self.bridge.since(mark, "state"), [])

    def test_unicode_survives(self):
        mark = self.bridge.mark()
        self.load_queue(["Ümlaut/Größe/01 Café.flac"], current=0, state="play")
        ev = self.state(3.0, mark, state="play")
        self.assertEqual(ev["song"]["title"], "Café Ünïcödé ♫")
        self.assertEqual(ev["song"]["artist"], "Björk")
