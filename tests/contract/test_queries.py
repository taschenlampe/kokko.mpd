"""`query` kinds: shapes of the rows, ordering, errors, supersede, paging."""

import json
import os
import time

from harness import ContractCase
from fakempd import library

JAIL = "Thin Lizzy/Jailbreak/01 Jailbreak.flac"
SOUTH = "Thin Lizzy/Jailbreak/02 Southbound.flac"
QUEEN = "ABBA/Arrival/01 Dancing Queen.flac"
PIGS = "Black Sabbath/Paranoid/01 War Pigs.flac"


class Shapes(ContractCase):
    def rows(self, kind, **args):
        ev = self.bridge.ask(kind, **args)
        self.assertIsNotNone(ev, "no result for %s" % kind)
        self.assertNotIn("error", ev, ev.get("error"))
        return ev["rows"]

    def test_result_echoes_id_kind_and_channel(self):
        qid = self.bridge.query("listplaylists", channel="side")
        ev = self.bridge.result(qid)
        self.assertEqual((ev["id"], ev["kind"], ev["channel"]), (qid, "listplaylists", "side"))
        self.assertNotIn("dropped", ev)

    def test_a_result_without_channel_has_an_empty_one(self):
        ev = self.bridge.ask("listplaylists")
        self.assertEqual(ev["channel"], "")

    def test_queue(self):
        self.load_queue([JAIL, QUEEN])
        rows = self.rows("queue")
        self.assertEqual([r["file"] for r in rows], [JAIL, QUEEN])
        self.assertEqual(rows[0]["type"], "file")
        self.assertEqual(rows[1]["pos"], "1")
        self.assertIn("id", rows[0])
        self.assertEqual(rows[0]["title"], "Jailbreak")
        self.assertEqual(rows[0]["duration"], "201.000")

    def test_queue_rows_carry_only_whitelisted_fields(self):
        self.load_queue(["Millie Jackson/Caught Up/01 Rap.flac"])
        row = self.rows("queue")[0]
        self.assertNotIn("label", row)
        allowed = {"type", "file", "id", "pos", "title", "artist", "albumartist", "album",
                   "track", "disc", "date", "genre", "composer", "performer", "name",
                   "time", "duration", "last-modified", "added"}
        self.assertLessEqual(set(row), allowed)

    def test_lsinfo_root_folders_first_then_playlists(self):
        rows = self.rows("lsinfo", path="")
        types = [r["type"] for r in rows]
        self.assertEqual(types, sorted(types, key=lambda t: {"directory": 0, "playlist": 1, "file": 2}[t]))
        dirs = [r["directory"] for r in rows if r["type"] == "directory"]
        self.assertEqual(dirs, sorted(dirs, key=str.lower))
        self.assertIn("road trip", [r.get("playlist") for r in rows])

    def test_lsinfo_folder_sorted_by_name(self):
        rows = self.rows("lsinfo", path="Smashing/Among My Swan")
        self.assertEqual([os.path.basename(r["file"]) for r in rows],
                         ["01 One.flac", "02 Two.flac", "03 Three.flac", "07 Seven.flac"])

    def test_list_values_sorted_case_insensitively(self):
        rows = self.rows("list", tag="artist")
        self.assertTrue(all(r["type"] == "value" for r in rows))
        values = [r["value"] for r in rows]
        self.assertEqual(values, sorted(values, key=str.lower))
        self.assertIn("David Bowie", values)
        self.assertNotIn("", values)

    def test_list_with_filter(self):
        rows = self.rows("list", tag="album", filter=[["artist", "Thin Lizzy"]])
        self.assertEqual([r["value"] for r in rows], ["Jailbreak"])

    def test_list_search_is_case_insensitive_regex(self):
        rows = self.rows("list", tag="artist", search="LIZZY")
        self.assertEqual([r["value"] for r in rows], ["Thin Lizzy"])
        sent = [t for _, t in self.mpd.commands("list")][-1]
        self.assertEqual(sent, ["list", "artist", "(artist =~ '(?i)LIZZY')"])

    def test_list_search_keeps_the_filter(self):
        rows = self.rows("list", tag="album", search="swan", filter=[["artist", "Smashing"]])
        self.assertEqual([r["value"] for r in rows], ["Among My Swan"])
        sent = [t for _, t in self.mpd.commands("list")][-1]
        self.assertEqual(sent[2], "((artist == 'Smashing') AND (album =~ '(?i)swan'))")

    def test_list_search_escapes_regex_characters(self):
        rows = self.rows("list", tag="album", search="#1's + (live)")
        self.assertEqual([r["value"] for r in rows], ["#1's + (live) [x]"])

    def test_find_sort_track_puts_a_discless_file_by_its_number(self):
        rows = self.rows("find", filter=[["album", "Among My Swan"]], sort="track")
        self.assertEqual([r["title"] for r in rows], ["One", "Two", "Seven", "Three"])

    def test_find_sort_date_ascending_with_regex(self):
        rows = self.rows("find", regex=[["date", "^197"]], sort="date")
        dates = [r["date"] for r in rows]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(set(dates), {"1970", "1974", "1976"})

    def test_find_added_since_newest_first(self):
        rows = self.rows("find", added_since="2026-11-01T00:00:00Z", sort="added")
        self.assertEqual([r["file"] for r in rows], [QUEEN])

    def test_find_without_any_condition_answers_nothing(self):
        before = self.mpd.count("find")
        self.assertEqual(self.rows("find"), [])
        self.assertEqual(self.mpd.count("find"), before)

    def test_search_ranks_title_hits_first(self):
        rows = self.rows("search", term="southbound")
        self.assertEqual(rows[0]["file"], SOUTH)
        self.assertEqual((rows[0]["match"], rows[0]["pos"], rows[0]["rank"]), ("title", 0, 0))
        self.assertEqual(rows[1]["match"], "label")
        self.assertEqual(rows[1]["label"], "Southbound")

    def test_search_exact_before_mid_word(self):
        rows = self.rows("search", term="abba")
        self.assertEqual(rows[0]["artist"], "ABBA")
        sabbath = [r for r in rows if r["artist"] == "Black Sabbath"][0]
        self.assertEqual((sabbath["pos"], sabbath["inword"]), (2, "Sabbath"))
        self.assertGreater(sabbath["rank"], rows[0]["rank"])

    def test_search_finds_through_the_folder(self):
        rows = self.rows("search", term="a-ha")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["match"], "file")
        self.assertEqual(rows[0]["inword"], "a-ha")

    def test_search_empty_term_asks_nothing(self):
        before = self.mpd.count("search")
        self.assertEqual(self.rows("search", term="  "), [])
        self.assertEqual(self.mpd.count("search"), before)

    def test_counts(self):
        rows = self.rows("counts", filters=[{"tag": "artist", "value": "Smashing"},
                                            {"tag": "", "value": "x"},
                                            {"tag": "album", "value": "Jailbreak"},
                                            "garbage"])
        self.assertEqual(rows, [4, None, 2, None])

    def test_songinfo_keeps_every_tag(self):
        rows = self.rows("songinfo", file="Millie Jackson/Caught Up/01 Rap.flac")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "Southbound")

    def test_listplaylists_sorted(self):
        rows = self.rows("listplaylists")
        self.assertEqual([r["playlist"] for r in rows], ["favorites", "road trip"])
        self.assertEqual(rows[0]["type"], "playlist")

    def test_playlist(self):
        rows = self.rows("playlist", name="road trip")
        self.assertEqual([r["file"] for r in rows], [JAIL, QUEEN])
        self.assertEqual(rows[0]["artist"], "Thin Lizzy")

    def test_playlist_that_is_not_there_is_an_error(self):
        ev = self.bridge.ask("playlist", name="nope")
        self.assertEqual(ev["rows"], [])
        self.assertIn("No such playlist", ev["error"])

    def test_favorites_are_typed(self):
        rows = self.rows("favorites")
        self.assertEqual([(r["file"], r["type"]) for r in rows], [(PIGS, "favorite")])

    def test_favorites_without_the_playlist_is_an_error(self):
        with self.mpd.lock:
            del self.mpd.playlists["favorites"]
        ev = self.bridge.ask("favorites")
        self.assertEqual(ev["rows"], [])
        self.assertTrue(ev.get("error"))

    def test_recent_remembers_the_album_played(self):
        self.load_queue([JAIL], current=0, state="play")
        self.assertIsNotNone(self.state(3.0, 0, state="play"))
        deadline = time.time() + 2
        rows = []
        while time.time() < deadline and not rows:
            rows = self.rows("recent")
            time.sleep(0.1)
        self.assertEqual(rows[0]["album"], "Jailbreak")
        self.assertEqual(rows[0]["type"], "recent")
        with open(os.path.join(self.home, "cache", "kokko-mpd", "recent.json")) as fh:
            self.assertEqual(json.load(fh)[0]["file"], JAIL)

    def test_unknown_kind_is_an_error(self):
        ev = self.bridge.ask("bogus")
        self.assertEqual(ev["rows"], [])
        self.assertEqual(ev["error"], "unknown query: bogus")

    def test_limit_marks_truncation(self):
        ev = self.bridge.ask("find", filter=[["artist", "Smashing"]], limit=2)
        self.assertEqual(len(ev["rows"]), 2)
        self.assertIs(ev.get("truncated"), True)

    def test_query_connection_raises_binarylimit(self):
        self.rows("listplaylists")
        self.assertIn(["binarylimit", "262144"], [t for _, t in self.mpd.commands("binarylimit")])

    def test_an_ack_keeps_the_query_connection(self):
        self.bridge.ask("playlist", name="nope")
        conns = self.mpd.connections_total
        self.rows("listplaylists")
        self.assertEqual(self.mpd.connections_total, conns)


class Supersede(ContractCase):
    def test_a_replaced_request_is_answered_as_dropped(self):
        self.mpd.delay["find"] = 0.5
        first = self.bridge.query("find", channel="search", filter=[["artist", "ABBA"]])
        time.sleep(0.15)                       # the worker is inside `first`
        middle = self.bridge.query("find", channel="search", filter=[["artist", "Smashing"]])
        last = self.bridge.query("find", channel="search", filter=[["artist", "Thin Lizzy"]])
        ev_last = self.bridge.result(last, 5.0)
        ev_mid = self.bridge.result(middle, 5.0)
        ev_first = self.bridge.result(first, 5.0)
        self.assertEqual([r["file"] for r in ev_last["rows"]], [JAIL, SOUTH])
        self.assertEqual((ev_mid["rows"], ev_mid.get("dropped"), ev_mid.get("error")),
                         ([], True, None))
        self.assertEqual(ev_mid["channel"], "search")
        self.assertFalse(ev_first.get("dropped"))
        sent = [t[1] for _, t in self.mpd.commands("find")]
        self.assertNotIn("(artist == 'Smashing')", sent, "the dropped request reached MPD")

    def test_no_channel_never_supersedes(self):
        self.mpd.delay["find"] = 0.3
        ids = [self.bridge.query("find", filter=[["artist", a]])
               for a in ("ABBA", "Smashing", "Thin Lizzy")]
        evs = [self.bridge.result(i, 5.0) for i in ids]
        self.assertTrue(all(e and not e.get("dropped") and e["rows"] for e in evs))

    def test_different_channels_do_not_supersede_each_other(self):
        self.mpd.delay["find"] = 0.3
        a = self.bridge.query("find", channel="a", filter=[["artist", "ABBA"]])
        time.sleep(0.1)
        b = self.bridge.query("find", channel="b", filter=[["artist", "Smashing"]])
        c = self.bridge.query("find", channel="c", filter=[["artist", "Thin Lizzy"]])
        for qid in (a, b, c):
            self.assertFalse(self.bridge.result(qid, 5.0).get("dropped"))


class Paging(ContractCase):
    songs = library.big_library(2500)

    def test_find_is_read_in_windows_of_a_thousand(self):
        ev = self.bridge.ask("find", 10.0, filter=[["artist", "Big Artist"]])
        self.assertEqual(len(ev["rows"]), 2500)
        self.assertEqual(ev["rows"][-1]["title"], "Track 2499")
        windows = [t[-1] for _, t in self.mpd.commands("find")]
        self.assertEqual(windows, ["0:1000", "1000:2000", "2000:3000"])
        self.assertNotIn("truncated", ev)

    def test_queue_is_read_in_ranges(self):
        def fill(m):
            m.queue = []
            m.enqueue(m.songs[:1500])
        self.mpd.external(fill, "playlist")
        ev = self.bridge.ask("queue", 10.0)
        self.assertEqual(len(ev["rows"]), 1500)
        self.assertEqual([t[1:] for _, t in self.mpd.commands("playlistinfo")],
                         [["0:1000"], ["1000:2000"]])


class OldServer(ContractCase):
    version = "0.20.0"

    def test_positional_find_without_window(self):
        ev = self.bridge.ask("find", filter=[["artist", "Thin Lizzy"]])
        self.assertEqual(len(ev["rows"]), 2)
        self.assertEqual([t for _, t in self.mpd.commands("find")][-1],
                         ["find", "artist", "Thin Lizzy"])

    def test_regex_is_refused_not_dropped(self):
        ev = self.bridge.ask("find", regex=[["date", "^197"]])
        self.assertEqual(ev["rows"], [])
        self.assertIn("0.21", ev["error"])

    def test_added_since_needs_0_24(self):
        ev = self.bridge.ask("find", added_since="2026-01-01")
        self.assertIn("0.24", ev["error"])
