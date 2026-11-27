"""Unit tests for kokko_mpd.protocol, kokko_mpd.filters and kokko_mpd.records.

    python3 -m unittest discover -s tests/unit -t .

No sockets except in `AgainstFakeMPD`, which talks to the fake server on a
loopback port it opens itself.
"""

import os
import socket
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

from kokko_mpd import filters, protocol, records  # noqa: E402
from kokko_mpd.protocol import (ProtocolError, Reply, ReplyParser,  # noqa: E402
                                ServerRefused, UnsafeValue)


def parse_all(data: bytes, chunk: int = None, **kw) -> list:
    parser = ReplyParser(**kw)
    if chunk is None:
        return parser.feed(data)
    out = []
    for i in range(0, len(data), chunk):
        out += parser.feed(data[i:i + chunk])
    return out


class Commands(unittest.TestCase):
    def test_every_argument_is_quoted(self):
        self.assertEqual(protocol.command_line("play", 3), b'play "3"\n')
        self.assertEqual(protocol.command_line("status"), b"status\n")

    def test_quotes_and_backslashes_are_escaped(self):
        self.assertEqual(protocol.command_line("add", 'a "b" \\c'), b'add "a \\"b\\" \\\\c"\n')

    def test_utf8(self):
        self.assertEqual(protocol.command_line("add", "Café"), 'add "Café"\n'.encode())

    def test_a_tab_is_fine(self):
        self.assertEqual(protocol.command_line("add", "a\tb"), b'add "a\tb"\n')

    def test_line_breaks_and_nul_are_refused(self):
        for bad in ("a\nclear", "a\rb", "a\x00b"):
            with self.assertRaises(UnsafeValue):
                protocol.command_line("add", bad)

    def test_the_name_is_checked_not_quoted(self):
        for bad in ("play\nclear", "Play", "", "a b"):
            with self.assertRaises(ValueError):
                protocol.command_line(bad)

    def test_unsafe_value_is_not_a_connection_error(self):
        self.assertFalse(issubclass(UnsafeValue, protocol.MPDError))


class Greeting(unittest.TestCase):
    def test_version(self):
        self.assertEqual(protocol.parse_greeting("OK MPD 0.24.0"), "0.24.0")

    def test_not_mpd(self):
        for line in ("SSH-2.0-OpenSSH", "OK MPD ", "", "ok mpd 0.1"):
            with self.assertRaises(ProtocolError):
                protocol.parse_greeting(line)

    def test_parser_delivers_the_greeting_first(self):
        out = parse_all(b"OK MPD 0.23.5\nvolume: 5\nOK\n", expect_greeting=True)
        self.assertEqual(out[0].pairs, [("OK MPD", "0.23.5")])
        self.assertEqual(out[1].pairs, [("volume", "5")])

    def test_version_compare(self):
        self.assertTrue(protocol.at_least("0.24.0", 0, 24))
        self.assertTrue(protocol.at_least("0.25.1", 0, 24))
        self.assertFalse(protocol.at_least("0.23.15", 0, 24))
        self.assertTrue(protocol.at_least("1.0", 0, 24))
        self.assertFalse(protocol.at_least("", 0, 21))
        self.assertEqual(protocol.version_tuple("0.24.0~git"), (0, 24, 0))


class Replies(unittest.TestCase):
    def test_plain_reply(self):
        [r] = parse_all(b"volume: 50\nstate: play\nOK\n")
        self.assertEqual(r.pairs, [("volume", "50"), ("state", "play")])
        self.assertIsNone(r.binary)
        self.assertEqual(r.get("STATE"), "play")

    def test_empty_reply(self):
        [r] = parse_all(b"OK\n")
        self.assertEqual((r.pairs, r.binary), ([], None))

    def test_value_with_colon_space_inside(self):
        [r] = parse_all(b"Title: Re: Re: Hello\nOK\n")
        self.assertEqual(r.pairs, [("Title", "Re: Re: Hello")])

    def test_empty_value(self):
        [r] = parse_all(b"Album: \nOK\n")
        self.assertEqual(r.pairs, [("Album", "")])

    def test_repeated_keys_keep_their_order(self):
        [r] = parse_all(b"Artist: A\nArtist: B\nOK\n")
        self.assertEqual(r.values("artist"), ["A", "B"])

    def test_two_replies_in_one_read(self):
        out = parse_all(b"a: 1\nOK\nb: 2\nOK\n")
        self.assertEqual([r.pairs for r in out], [[("a", "1")], [("b", "2")]])

    def test_any_chunking_gives_the_same_replies(self):
        data = b"OK MPD 0.24.0\nfile: x\nTitle: \xc3\xa9\nOK\nACK [50@0] {load} No such playlist\nOK\n"
        whole = parse_all(data, expect_greeting=True)
        for size in (1, 2, 3, 7, 64):
            pieces = parse_all(data, chunk=size, expect_greeting=True)
            self.assertEqual([type(x) for x in pieces], [type(x) for x in whole], size)
            self.assertEqual(pieces[1].pairs, whole[1].pairs)
            self.assertEqual(pieces[1].pairs[1], ("Title", "é"))

    def test_incomplete_reply_waits(self):
        parser = ReplyParser()
        self.assertEqual(parser.feed(b"volume: 5\nst"), [])
        self.assertFalse(parser.idle)
        [r] = parser.feed(b"ate: stop\nOK\n")
        self.assertEqual(r.get("state"), "stop")
        self.assertTrue(parser.idle)

    def test_garbage_line_is_a_protocol_error(self):
        with self.assertRaises(ProtocolError):
            parse_all(b"this is not mpd\n")

    def test_broken_parser_stays_broken(self):
        parser = ReplyParser()
        with self.assertRaises(ProtocolError):
            parser.feed(b"nope\n")
        with self.assertRaises(ProtocolError):
            parser.feed(b"OK\n")

    def test_overlong_line(self):
        with self.assertRaises(ProtocolError):
            parse_all(b"x" * (protocol.MAX_LINE + 10))

    def test_idle_reply(self):
        [r] = parse_all(b"changed: player\nchanged: mixer\nOK\n")
        self.assertEqual(protocol.changed_subsystems(r), ["player", "mixer"])


class Acks(unittest.TestCase):
    def test_ack_fields_and_text(self):
        [e] = parse_all(b"ACK [50@0] {load} No such playlist\n")
        self.assertIsInstance(e, ServerRefused)
        self.assertEqual((e.code, e.index, e.command, e.message),
                         (50, 0, "load", "No such playlist"))
        self.assertEqual(str(e), "load: No such playlist")

    def test_ack_without_command(self):
        [e] = parse_all(b"ACK [5@0] {} unknown command \"x\"\n")
        self.assertEqual(str(e), 'unknown command "x"')

    def test_odd_ack_is_kept_verbatim(self):
        e = protocol.parse_ack("ACK something odd")
        self.assertEqual(str(e), "something odd")

    def test_ack_is_not_a_connection_error(self):
        self.assertFalse(issubclass(ServerRefused, protocol.MPDError))

    def test_reply_after_an_ack_parses(self):
        out = parse_all(b"ACK [2@0] {play} Bad song index\nvolume: 1\nOK\n")
        self.assertIsInstance(out[0], ServerRefused)
        self.assertEqual(out[1].pairs, [("volume", "1")])


class Binary(unittest.TestCase):
    def frame(self, payload, extra=b"", size=None):
        size = len(payload) if size is None else size
        return (b"size: %d\ntype: image/png\nbinary: %d\n" % (size, len(payload))
                + payload + b"\n" + extra + b"OK\n")

    def test_binary_reply(self):
        payload = bytes(range(256)) * 4
        [r] = parse_all(self.frame(payload))
        self.assertEqual(r.binary, payload)
        self.assertEqual(r.get("size"), "1024")
        self.assertEqual(r.get("type"), "image/png")

    def test_binary_containing_ok_and_newlines(self):
        payload = b"\nOK\nACK [1@0] {} x\nbinary: 5\n"
        [r] = parse_all(self.frame(payload))
        self.assertEqual(r.binary, payload)

    def test_binary_in_one_byte_reads(self):
        payload = os.urandom(3000)
        [r] = parse_all(self.frame(payload), chunk=1)
        self.assertEqual(r.binary, payload)

    def test_zero_length_chunk(self):
        [r] = parse_all(b"size: 10\nbinary: 0\n\nOK\n")
        self.assertEqual(r.binary, b"")

    def test_missing_newline_after_chunk(self):
        with self.assertRaises(ProtocolError):
            parse_all(b"binary: 3\nabcXOK\n")

    def test_bad_lengths(self):
        for line in (b"binary: x\n", b"binary: -1\n"):
            with self.assertRaises(ProtocolError):
                parse_all(line)
        with self.assertRaises(ProtocolError):
            parse_all(b"binary: 100\n", max_binary=99)

    def test_two_binary_sections(self):
        with self.assertRaises(ProtocolError):
            parse_all(b"binary: 1\na\nbinary: 1\nb\nOK\n")

    def test_lines_after_the_binary(self):
        [r] = parse_all(self.frame(b"abc", extra=b"note: after\n"))
        self.assertEqual(r.binary, b"abc")
        self.assertEqual(r.get("note"), "after")


class Filters(unittest.TestCase):
    V = "0.24.0"

    def test_exact(self):
        self.assertEqual(filters.conditions(self.V, [["artist", "Thin Lizzy"]]),
                         ["(artist == 'Thin Lizzy')"])

    def test_and(self):
        self.assertEqual(filters.conditions(self.V, [["artist", "A"], ["album", "B"]]),
                         ["((artist == 'A') AND (album == 'B'))"])

    def test_regex_and_added_since(self):
        self.assertEqual(filters.conditions(self.V, [], [["date", "^19"]], "2026-01-01"),
                         ["((date =~ '^19') AND (added-since '2026-01-01'))"])

    def test_no_condition(self):
        self.assertEqual(filters.conditions(self.V, [], [], ""), [])
        self.assertEqual(filters.conditions(self.V, None), [])

    def test_malformed_pairs_are_ignored(self):
        self.assertEqual(filters.conditions(self.V, [["", "x"], ["a"], "zz", 5, ["t", "v"]]),
                         ["(t == 'v')"])

    def test_apostrophe_and_backslash(self):
        self.assertEqual(filters.filter_literal("Kid's \\ \"Band\""), "'Kid\\'s \\\\ \"Band\"'")

    def test_both_layers_round_trip_through_the_fake_parser(self):
        from fakempd.server import FilterParser, tokenize
        value = "Kid's \\ \"Band\" #1 (live) [x]"
        expr = filters.conditions(self.V, [["artist", value]])[0]
        line = protocol.command_line("find", expr).decode().rstrip("\n")
        argument = tokenize(line)[1]
        self.assertTrue(FilterParser(argument, False).parse()({"file": "f", "artist": value}))

    def test_icase_contains_escapes_regex(self):
        self.assertEqual(filters.icase_contains("album", "a+b (c)"),
                         "(album =~ '(?i)a\\\\+b\\\\ \\\\(c\\\\)')")

    def test_old_server_positional(self):
        self.assertEqual(filters.conditions("0.20.0", [["artist", "A"], ["album", "B"]]),
                         ["artist", "A", "album", "B"])

    def test_old_server_refuses_what_it_cannot_say(self):
        with self.assertRaises(filters.FilterUnsupported) as cm:
            filters.conditions("0.20.0", [], [["date", "^19"]])
        self.assertIn("0.21", str(cm.exception))
        with self.assertRaises(filters.FilterUnsupported) as cm:
            filters.conditions("0.23.0", [], [], "2026-01-01")
        self.assertIn("0.24", str(cm.exception))

    def test_unsupported_is_reported_like_an_ack(self):
        self.assertTrue(issubclass(filters.FilterUnsupported, ServerRefused))

    def test_line_break_in_a_filter_value(self):
        with self.assertRaises(UnsafeValue):
            filters.conditions(self.V, [["artist", "a\nb"]])


class Records(unittest.TestCase):
    def test_record_folds_and_joins(self):
        r = records.record([("Artist", "Queen"), ("Artist", "David Bowie"), ("Title", "x"),
                            ("Artist", "Queen")])
        self.assertEqual(r, {"artist": "Queen, David Bowie", "title": "x"})

    def test_records_split_on_start_keys(self):
        pairs = [("directory", "A"), ("Last-Modified", "t"), ("file", "A/1"), ("Title", "one"),
                 ("Label", "L"), ("playlist", "p")]
        rows = records.records(pairs, fields=records.SONG_FIELDS)
        self.assertEqual(rows, [{"type": "directory", "directory": "A", "last-modified": "t"},
                                {"type": "file", "file": "A/1", "title": "one"},
                                {"type": "playlist", "playlist": "p"}])

    def test_pairs_before_the_first_record_are_skipped(self):
        self.assertEqual(records.records([("size", "3"), ("file", "x")]),
                         [{"type": "file", "file": "x"}])

    def test_limit(self):
        pairs = [("file", str(i)) for i in range(10)]
        self.assertEqual(len(records.records(pairs, limit=3)), 3)

    def test_distinct_drops_blanks(self):
        rows = records.distinct([("Album", "B"), ("Album", ""), ("Album", "a")], "album")
        self.assertEqual(rows, [{"type": "value", "value": "B"}, {"type": "value", "value": "a"}])

    def test_leading_number(self):
        for value, n in (("4", 4), ("4/12", 4), (" 07 ", 7), ("", 0), (None, 0), ("x", 0)):
            self.assertEqual(records.leading_number(value), n, value)

    def test_entry_path(self):
        self.assertEqual(records.entry_path({"type": "directory", "directory": "A"}), "A")


class AgainstFakeMPD(unittest.TestCase):
    """The parser reading a real socket: greeting, chunked cover, ACK."""

    def setUp(self):
        from fakempd import library
        from fakempd.server import FakeMPD
        self.library = library
        self.mpd = FakeMPD(songs=library.SONGS, covers=library.COVERS)
        self.port = self.mpd.start()
        self.addCleanup(self.mpd.stop)
        self.sock = socket.create_connection(("127.0.0.1", self.port), 2)
        self.addCleanup(self.sock.close)
        self.parser = ReplyParser(expect_greeting=True)
        self.pending = []

    def next_result(self):
        while not self.pending:
            data = self.sock.recv(4096)
            self.assertTrue(data, "server closed")
            self.pending += self.parser.feed(data)
        return self.pending.pop(0)

    def ask(self, name, *args):
        self.sock.sendall(protocol.command_line(name, *args))
        return self.next_result()

    def test_session(self):
        self.assertEqual(self.next_result().pairs, [("OK MPD", "0.24.0")])
        self.assertEqual(self.ask("binarylimit", 262144).pairs, [])
        uri = "Black Sabbath/Paranoid/01 War Pigs.flac"
        data = b""
        while True:
            r = self.ask("albumart", uri, len(data))
            data += r.binary
            if len(data) >= int(r.get("size")):
                break
        self.assertEqual(data, self.library.COVER_BIG)
        e = self.ask("albumart", "Nocover/Plain/01 Plain.flac", 0)
        self.assertIsInstance(e, ServerRefused)
        self.assertEqual(e.code, protocol.ACK_NO_EXIST)
        self.assertEqual(self.ask("status").get("state"), "stop")
        self.assertTrue(self.parser.idle)


if __name__ == "__main__":
    unittest.main()
