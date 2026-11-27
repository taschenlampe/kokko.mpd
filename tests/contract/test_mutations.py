"""`cmd` ops: queue and stored playlists -- always the FAKE server's."""

import time

from harness import ContractCase

JAIL = "Thin Lizzy/Jailbreak/01 Jailbreak.flac"
SOUTH = "Thin Lizzy/Jailbreak/02 Southbound.flac"
QUEEN = "ABBA/Arrival/01 Dancing Queen.flac"
PIGS = "Black Sabbath/Paranoid/01 War Pigs.flac"
TAKE = "a-ha/Hunting High and Low/01 Take On Me.flac"


class Mutations(ContractCase):
    def setUp(self):
        super().setUp()
        time.sleep(0.2)
        self.mpd.clear_log()

    def until(self, predicate, timeout=2.0):
        self.assertTrue(self.mpd.wait_for(predicate, timeout))

    def names(self):
        return [t[0] for _, t in self.mpd.commands() if t[0] not in ("status", "currentsong", "idle", "noidle", "binarylimit", "albumart", "readpicture")]

    def test_add(self):
        self.bridge.cmd("add", uri=JAIL)
        self.until(lambda: self.queue_files() == [JAIL])

    def test_add_a_directory(self):
        self.bridge.cmd("add", uri="Thin Lizzy/Jailbreak")
        self.until(lambda: self.queue_files() == [JAIL, SOUTH])

    def test_addplay_plays_the_first_appended(self):
        self.load_queue([QUEEN])
        self.bridge.cmd("addplay", uri="Thin Lizzy/Jailbreak")
        self.until(lambda: self.mpd.state == "play")
        self.assertEqual(self.mpd.current, 1)
        self.assertEqual([t for _, t in self.mpd.commands("play")], [["play", "1"]])

    def test_insert_lands_behind_the_playing_song(self):
        self.load_queue([QUEEN, PIGS, TAKE], current=0, state="play")
        self.bridge.cmd("insert", uri=JAIL)
        self.until(lambda: self.queue_files() == [QUEEN, JAIL, PIGS, TAKE])
        self.assertEqual([t for _, t in self.mpd.commands("move")], [["move", "3:4", "1"]])

    def test_remove_move_clear(self):
        self.load_queue([QUEEN, PIGS, TAKE])
        with self.mpd.lock:
            pid = self.mpd.queue[1]["id"]
        self.bridge.cmd("remove", id=pid)
        self.until(lambda: self.queue_files() == [QUEEN, TAKE])
        self.bridge.cmd("move", **{"from": 1, "to": 0})
        self.until(lambda: self.queue_files() == [TAKE, QUEEN])
        self.bridge.cmd("clear")
        self.until(lambda: self.queue_files() == [])

    def test_playid_and_playpos(self):
        self.load_queue([QUEEN, PIGS, TAKE])
        with self.mpd.lock:
            tid = self.mpd.queue[2]["id"]
        self.bridge.cmd("playid", id=tid)
        self.until(lambda: self.mpd.current == 2 and self.mpd.state == "play")
        self.bridge.cmd("playpos", pos=1)
        self.until(lambda: self.mpd.current == 1)

    def test_shuffle_sends_shuffle(self):
        self.load_queue([QUEEN, PIGS, TAKE])
        self.bridge.cmd("shuffle")
        self.until(lambda: self.mpd.count("shuffle") == 1)

    def test_crop_keeps_only_the_playing_song_tail_first(self):
        self.load_queue([QUEEN, PIGS, TAKE, JAIL], current=1, state="play")
        self.bridge.cmd("crop")
        self.until(lambda: self.queue_files() == [PIGS])
        self.assertEqual([t for _, t in self.mpd.commands("delete")],
                         [["delete", "2:4"], ["delete", "0:1"]])

    def test_crop_with_nothing_playing_clears(self):
        self.load_queue([QUEEN, PIGS])
        self.bridge.cmd("crop")
        self.until(lambda: self.queue_files() == [])

    def test_stored_playlist_ops(self):
        self.load_queue([QUEEN])
        self.bridge.cmd("loadplaylist", name="road trip")
        self.until(lambda: self.queue_files() == [QUEEN, JAIL, QUEEN])
        self.bridge.cmd("saveplaylist", name="saved one")
        self.until(lambda: "saved one" in self.mpd.playlists)
        self.bridge.cmd("renameplaylist", name="saved one", to="renamed")
        self.until(lambda: "renamed" in self.mpd.playlists and "saved one" not in self.mpd.playlists)
        self.bridge.cmd("playlistadd", name="renamed", uri=PIGS)
        self.until(lambda: self.mpd.playlists["renamed"][-1] == PIGS)
        self.bridge.cmd("playlistdelete", name="renamed", pos=0)
        self.until(lambda: self.mpd.playlists["renamed"] == [JAIL, QUEEN, PIGS])
        self.bridge.cmd("playlistclear", name="renamed")
        self.until(lambda: self.mpd.playlists["renamed"] == [])
        self.bridge.cmd("rmplaylist", name="renamed")
        self.until(lambda: "renamed" not in self.mpd.playlists)

    def test_findadd_is_one_command_with_one_filter(self):
        self.bridge.cmd("findadd", filter=[["artist", "Thin Lizzy"]])
        self.until(lambda: self.queue_files() == [JAIL, SOUTH])
        self.assertEqual([t for _, t in self.mpd.commands("findadd")],
                         [["findadd", "(artist == 'Thin Lizzy')"]])

    def test_findadd_two_conditions_are_joined_with_and(self):
        self.bridge.cmd("findadd", filter=[["artist", "Thin Lizzy"], ["title", "Southbound"]])
        self.until(lambda: self.queue_files() == [SOUTH])
        self.assertEqual(self.mpd.commands("findadd")[0][1][1],
                         "((artist == 'Thin Lizzy') AND (title == 'Southbound'))")

    def test_findadd_carries_quotes_and_metacharacters(self):
        self.bridge.cmd("findadd", filter=[["album", "#1's + (live) [x]"], ["artist", 'Kid\'s "Band"']])
        self.until(lambda: self.queue_files() == ["Weird/#1's/01 ( O )( O ).flac"])

    def test_findplay_plays_what_it_added(self):
        self.load_queue([QUEEN])
        self.bridge.cmd("findplay", filter=[["album", "Jailbreak"]])
        self.until(lambda: self.mpd.state == "play" and self.mpd.current == 1)

    def test_findadd_without_a_match_says_so(self):
        mark = self.bridge.mark()
        self.bridge.cmd("findadd", filter=[["artist", "Nobody"]])
        ev = self.bridge.wait_event("ack", 2.0, mark)
        self.assertIsNotNone(ev)
        self.assertEqual(ev["error"], "nothing in the library matches that any more")

    def test_searchadd(self):
        self.bridge.cmd("searchadd", term="sabbath")
        self.until(lambda: self.queue_files() == [PIGS])
        self.assertEqual(self.mpd.commands("searchadd")[0][1][1], "(any contains 'sabbath')")

    def test_searchadd_in_one_category(self):
        self.bridge.cmd("searchadd", term="paranoid", tag="album")
        self.until(lambda: self.queue_files() == [PIGS])
        self.assertEqual(self.mpd.commands("searchadd")[0][1][1], "(album =~ '(?i)paranoid')")

    def test_searchadd_without_a_match_says_so(self):
        mark = self.bridge.mark()
        self.bridge.cmd("searchadd", term="zzzz")
        ev = self.bridge.wait_event("ack", 2.0, mark)
        self.assertEqual(ev["error"], "nothing in the library matches \u201czzzz\u201d")

    def test_favorite_on_twice_is_one_row_and_off_removes_it(self):
        self.bridge.cmd("favorite", uri=JAIL, on=True)
        self.until(lambda: JAIL in self.mpd.playlists["favorites"])
        self.bridge.cmd("favorite", uri=JAIL, on=True)
        time.sleep(0.4)
        self.assertEqual(self.mpd.playlists["favorites"].count(JAIL), 1)
        self.bridge.cmd("favorite", uri=JAIL, on=False)
        self.until(lambda: self.mpd.playlists["favorites"] == [PIGS])

    def test_favorite_creates_the_playlist(self):
        with self.mpd.lock:
            del self.mpd.playlists["favorites"]
        self.bridge.cmd("favorite", uri=QUEEN)
        self.until(lambda: self.mpd.playlists.get("favorites") == [QUEEN])

    def test_favoritefilter_stars_a_whole_album(self):
        self.bridge.cmd("favoritefilter", filter=[["album", "Jailbreak"]], on=True)
        self.until(lambda: self.mpd.playlists["favorites"] == [PIGS, JAIL, SOUTH])
        self.bridge.cmd("favoritefilter", filter=[["album", "Jailbreak"]], on=False)
        self.until(lambda: self.mpd.playlists["favorites"] == [PIGS])

    def test_an_ack_is_reported_and_the_connection_stays(self):
        mark = self.bridge.mark()
        self.bridge.cmd("loadplaylist", name="does not exist")
        ev = self.bridge.wait_event("ack", 2.0, mark)
        self.assertIsNotNone(ev)
        self.assertIn("No such playlist", ev["error"])
        self.assertEqual(self.bridge.since(mark, "disconnected"), [])
        self.bridge.cmd("add", uri=JAIL)
        self.until(lambda: self.queue_files() == [JAIL])

    def test_unknown_op_and_missing_fields_send_nothing(self):
        for payload in ({"op": "explode"}, {"op": "add"}, {"op": "addplay", "uri": ""},
                        {"op": "loadplaylist"}, {"op": "playlistadd", "name": "x"},
                        {"op": "playlistdelete", "name": "x"}, {"op": "favorite"},
                        {"op": "favoritefilter"}, {"op": "searchadd", "term": "  "}):
            self.bridge.cmd(**payload)
        time.sleep(0.5)
        self.assertEqual(self.names(), [])

    def test_a_line_break_in_a_value_is_refused_not_sent(self):
        mark = self.bridge.mark()
        self.bridge.cmd("add", uri="evil\nclear")
        ev = self.bridge.wait_event("ack", 2.0, mark)
        self.assertIsNotNone(ev)
        self.assertNotIn("add", self.names())
        self.assertNotIn("clear", self.names())
