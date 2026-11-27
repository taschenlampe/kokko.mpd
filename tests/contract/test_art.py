"""Covers: albumart, readpicture, the local file fallback, the cache."""

import hashlib
import os
import time

from harness import ContractCase
from fakempd import library

JAIL = "Thin Lizzy/Jailbreak/01 Jailbreak.flac"
PIGS = "Black Sabbath/Paranoid/01 War Pigs.flac"
INSIDE = "Embedded/Inside/01 Inside.flac"
PLAIN = "Nocover/Plain/01 Plain.flac"


class Art(ContractCase):
    def play(self, uri):
        mark = self.bridge.mark()
        self.load_queue([uri], current=0, state="play")
        return mark

    def art_for(self, uri, mark, timeout=5.0):
        return self.bridge.wait(lambda e: e.get("event") == "art" and e.get("uri") == uri
                                and e.get("path"), timeout, mark)

    def read(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_albumart_lands_in_the_cache(self):
        ev = self.art_for(JAIL, self.play(JAIL))
        self.assertIsNotNone(ev)
        self.assertTrue(ev["path"].startswith(os.path.join(self.home, "cache", "kokko-mpd")))
        self.assertEqual(self.read(ev["path"]), library.COVER_JAILBREAK)
        self.assertTrue(ev["path"].endswith(".png"))

    def test_a_big_cover_comes_in_large_chunks(self):
        ev = self.art_for(PIGS, self.play(PIGS), 8.0)
        data = self.read(ev["path"])
        self.assertEqual(hashlib.sha1(data).hexdigest(),
                         hashlib.sha1(library.COVER_BIG).hexdigest())
        asks = [t for _, t in self.mpd.commands("albumart") if t[1] == PIGS]
        self.assertEqual(len(asks), -(-len(library.COVER_BIG) // 262144))

    def test_embedded_picture_when_there_is_no_cover_file(self):
        ev = self.art_for(INSIDE, self.play(INSIDE))
        self.assertEqual(self.read(ev["path"]), library.PICTURE_EMBEDDED)

    def test_the_same_art_is_not_announced_twice(self):
        mark = self.play(JAIL)
        self.assertIsNotNone(self.art_for(JAIL, mark))
        time.sleep(0.2)
        mark2 = self.bridge.mark()
        self.bridge.send("refresh")
        self.mpd.changed("player")
        self.assertEqual(self.bridge.quiet(0.6, mark2, "art"), [])

    def test_a_missing_cover_is_not_asked_again_until_the_library_changes(self):
        mark = self.play(PLAIN)
        self.assertTrue(self.mpd.wait_for(
            lambda: self.mpd.count("readpicture") >= 1, 3.0))
        time.sleep(0.3)
        for _ in range(3):
            self.bridge.send("refresh")
            self.mpd.changed("player")
            time.sleep(0.15)
        asks = [t for _, t in self.mpd.commands("albumart") if t[1] == PLAIN]
        self.assertEqual(len(asks), 1)
        self.assertIsNone(self.art_for(PLAIN, mark, 0.2))
        self.mpd.changed("database")
        self.assertTrue(self.mpd.wait_for(lambda: len(
            [t for _, t in self.mpd.commands("albumart") if t[1] == PLAIN]) == 2, 3.0))

    def test_art_query_answers_a_path(self):
        ev = self.bridge.ask("art", uri=JAIL, album="Jailbreak", albumartist="Thin Lizzy")
        self.assertEqual(ev["rows"][0]["type"], "art")
        self.assertEqual(self.read(ev["rows"][0]["path"]), library.COVER_JAILBREAK)

    def test_art_query_for_nothing_is_an_empty_path(self):
        ev = self.bridge.ask("art", uri=PLAIN)
        self.assertEqual(ev["rows"], [{"type": "art", "path": ""}])

    def test_art_query_without_uri_is_no_rows(self):
        self.assertEqual(self.bridge.ask("art")["rows"], [])


class LocalCover(ContractCase):
    autoconnect = False

    def setUp(self):
        super().setUp()
        self.music = os.path.join(self.home, "music")
        os.makedirs(os.path.join(self.music, "Nocover", "Plain"))
        with open(os.path.join(self.music, "Nocover", "Plain", "folder.jpg"), "wb") as fh:
            fh.write(library.JPEG)
        os.makedirs(os.path.join(self.home, "outside"))
        with open(os.path.join(self.home, "outside", "folder.jpg"), "wb") as fh:
            fh.write(library.JPEG)

    def test_folder_jpg_from_music_root(self):
        self.connect(musicRoot=self.music)
        mark = self.bridge.mark()
        self.load_queue([PLAIN], current=0, state="play")
        ev = self.bridge.wait(lambda e: e.get("event") == "art" and e.get("path"), 4.0, mark)
        self.assertIsNotNone(ev)
        with open(ev["path"], "rb") as fh:
            self.assertEqual(fh.read(), library.JPEG)

    def test_mpd_conf_music_directory_is_the_default(self):
        os.makedirs(os.path.join(self.home, "config", "mpd"), exist_ok=True)
        with open(os.path.join(self.home, "config", "mpd", "mpd.conf"), "w") as fh:
            fh.write('music_directory "%s"\n' % self.music)
        self.connect()
        mark = self.bridge.mark()
        self.load_queue([PLAIN], current=0, state="play")
        self.assertIsNotNone(self.bridge.wait(
            lambda e: e.get("event") == "art" and e.get("path"), 4.0, mark))

    def test_a_uri_climbing_out_of_the_root_finds_nothing(self):
        self.connect(musicRoot=self.music)
        evil = "../outside/x.flac"
        with self.mpd.lock:
            self.mpd.songs.append(library.song(evil, "x", "x", "x", 1))
        mark = self.bridge.mark()
        self.load_queue([evil], current=0, state="play")
        self.assertTrue(self.mpd.wait_for(lambda: self.mpd.count("readpicture") >= 1, 3.0))
        time.sleep(0.3)
        self.assertEqual([e for e in self.bridge.since(mark, "art") if e.get("path")], [])

    def test_a_root_that_is_not_a_directory_disables_the_fallback(self):
        self.connect(musicRoot=os.path.join(self.home, "nope"))
        mark = self.bridge.mark()
        self.load_queue([PLAIN], current=0, state="play")
        self.assertTrue(self.mpd.wait_for(lambda: self.mpd.count("readpicture") >= 1, 3.0))
        time.sleep(0.3)
        self.assertEqual([e for e in self.bridge.since(mark, "art") if e.get("path")], [])
