"""radio_search: an HTTP directory, never MPD."""

import http.server
import json
import threading
import time
import urllib.parse

from harness import ContractCase


def station(name="Swiss Groove", **kw):
    s = {"name": name, "url_resolved": "http://stream.invalid/%s" % name.replace(" ", ""),
         "codec": "MP3", "bitrate": "128", "country": "Switzerland", "countrycode": "CH",
         "lastcheckok": 1, "votes": 42, "tags": "jazz", "homepage": "http://example.invalid/",
         "favicon": "", "url": "http://x.invalid/"}
    s.update(kw)
    return s


class Directory(http.server.ThreadingHTTPServer):
    daemon_threads = True


class RadioCase(ContractCase):
    body = json.dumps([station(), station("Broken", lastcheckok=0),
                       station("NoStream", url_resolved=""),
                       station("Ftp", url_resolved="ftp://x.invalid/s"),
                       station("Deutschlandfunk", bitrate=64)]).encode()
    status = 200

    def setUp(self):
        self.requests = []
        case = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                case.requests.append((self.path, dict(self.headers)))
                self.send_response(case.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(case.body)

            def log_message(self, *a):
                pass

        self.http = Directory(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.tuning = dict(self.tuning, RADIO_API="http://127.0.0.1:%d" % self.http.server_address[1])
        super().setUp()
        self.addCleanup(self.http.shutdown)


class Radio(RadioCase):
    def test_only_playable_stations_become_rows(self):
        ev = self.bridge.ask("radio_search", channel="radio", search="groove")
        self.assertNotIn("error", ev)
        self.assertEqual([r["name"] for r in ev["rows"]], ["Swiss Groove", "Deutschlandfunk"])
        row = ev["rows"][0]
        self.assertEqual(set(row), {"name", "url_resolved", "codec", "bitrate", "country",
                                    "countrycode", "lastcheckok", "votes", "tags", "homepage"})
        self.assertEqual(row["bitrate"], 128)
        self.assertEqual(ev["channel"], "radio")

    def test_the_request(self):
        self.bridge.ask("radio_search", search="rock & roll", country="DE", tag="jazz", limit=5)
        path, headers = self.requests[-1]
        url = urllib.parse.urlparse(path)
        self.assertEqual(url.path, "/json/stations/search")
        q = dict(urllib.parse.parse_qsl(url.query))
        self.assertEqual(q, {"name": "rock & roll", "limit": "5", "hidebroken": "true",
                             "order": "votes", "reverse": "true", "countrycode": "DE",
                             "tag": "jazz"})
        self.assertIn("kokko.mpd", headers.get("User-Agent", ""))

    def test_nothing_to_ask_asks_nothing(self):
        ev = self.bridge.ask("radio_search", search=" ")
        self.assertEqual(ev["rows"], [])
        self.assertEqual(self.requests, [])

    def test_it_never_touches_mpd(self):
        time.sleep(0.2)
        conns = self.mpd.connections_total
        self.mpd.clear_log()
        self.bridge.ask("radio_search", search="groove")
        self.assertEqual(self.mpd.connections_total, conns)
        self.assertEqual([t for _, t in self.mpd.commands() if t[0] not in ("idle",)], [])


class RadioDown(RadioCase):
    status = 503

    def test_a_broken_directory_is_an_error_not_a_broken_mpd(self):
        mark = self.bridge.mark()
        ev = self.bridge.ask("radio_search", search="groove")
        self.assertEqual(ev["rows"], [])
        self.assertTrue(ev["error"])
        self.assertEqual(self.bridge.since(mark, "disconnected"), [])
        self.assertNotIn("error", self.bridge.ask("listplaylists"))


class RadioGarbage(RadioCase):
    body = b"<html>nope</html>"

    def test_not_json_is_an_error(self):
        ev = self.bridge.ask("radio_search", search="groove")
        self.assertIn("not JSON", ev["error"])
