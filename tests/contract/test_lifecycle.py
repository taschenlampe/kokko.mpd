"""Start, connect, reconnect, settings changes, shutdown."""

import os
import socket
import subprocess
import time

from harness import ContractCase, legacy_differs
from fakempd.server import FakeMPD


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Startup(ContractCase):
    def test_connected_names_version_and_target(self):
        ev = self.bridge.since(0, "connected")[-1]
        self.assertEqual(ev["version"], "0.24.0")
        self.assertEqual(ev["target"], "127.0.0.1:%d" % self.mpd.port)

    @legacy_differs("dials 127.0.0.1:6600 at start, before the widget's config arrives")
    def test_nothing_is_dialled_before_the_first_config(self):
        refused = [l for l in self.bridge.stderr if l.startswith("contract fence:")]
        self.assertEqual(refused, [], "the bridge connected somewhere before it was told where")

    def test_first_state_follows_connected(self):
        names = [e["event"] for e in self.bridge.since(0) if e["event"] in ("connected", "state")]
        self.assertEqual(names[:2], ["connected", "state"])
        state = self.bridge.since(0, "state")[0]
        self.assertEqual(state["status"]["state"], "stop")
        self.assertEqual(state["song"], {})

    def test_no_song_announces_empty_art(self):
        ev = self.bridge.wait_event("art", 2.0)
        self.assertIsNotNone(ev)
        self.assertEqual((ev["uri"], ev["path"]), ("", ""))

    def test_two_connections_idle_and_command(self):
        # cmd + idle; the query connection opens on the first query only
        self.assertTrue(self.mpd.wait_for(lambda: len(self.mpd.live_clients()) >= 2, 2.0))
        self.assertTrue(self.mpd.wait_for(lambda: any(
            c.idling for c in self.mpd.live_clients()), 2.0), "nobody parked in idle")

    def test_idle_names_the_subsystems(self):
        self.assertTrue(self.mpd.wait_for(lambda: self.mpd.commands("idle"), 2.0))
        idles = self.mpd.commands("idle")
        self.assertEqual(set(idles[0][1][1:]),
                         {"player", "mixer", "options", "playlist", "update", "database"})

    def test_same_config_twice_does_not_reconnect(self):
        mark = self.bridge.mark()
        self.bridge.config(host="127.0.0.1", port=self.mpd.port, password="")
        self.assertEqual(self.bridge.quiet(0.6, mark, "connected"), [])
        self.assertEqual(self.bridge.since(mark, "disconnected"), [])

    def test_quit_exits_cleanly(self):
        self.bridge.send("quit")
        self.assertEqual(self.bridge.proc.wait(5), 0)

    def test_garbage_is_ignored(self):
        mark = self.bridge.mark()
        for line in ("nonsense", "", "   ", "cmd {broken", "cmd [1,2]", "query [1]",
                     "query {bad", "seek abc", "volume loud", "setopt", "setopt bogus 1",
                     "play_id x", "config {broken"):
            self.bridge.send(line)
        time.sleep(0.4)
        self.assertEqual([e["event"] for e in self.bridge.since(mark)
                          if e["event"] not in ("health",)], [])
        self.assertIsNone(self.bridge.proc.poll(), "the bridge died on garbage")
        self.assertIsNotNone(self.bridge.ask("listplaylists"))
        self.assertEqual(self.mpd.count("setvol") + self.mpd.count("seekcur"), 0)


class SettingsChange(ContractCase):
    def test_new_server_is_announced_and_used(self):
        other = self.make_mpd(version="0.23.5")
        other.start()
        self.addCleanup(other.stop)
        mark = self.bridge.mark()
        self.bridge.config(host="127.0.0.1", port=other.port, password="")
        down = self.bridge.wait_event("disconnected", 3.0, mark)
        self.assertIsNotNone(down)
        up = self.bridge.wait_event("connected", 5.0, mark)
        self.assertEqual(up["target"], "127.0.0.1:%d" % other.port)
        self.assertEqual(up["version"], "0.23.5")
        self.bridge.send("next")
        self.assertTrue(other.wait_for(lambda: other.count("next") == 1, 3.0))
        self.assertEqual(self.mpd.count("next"), 0, "a command went to the old server")
        self.assertTrue(self.mpd.wait_for(lambda: not self.mpd.live_clients(), 3.0),
                        "connections to the old server were left open")


class Unreachable(ContractCase):
    autoconnect = False

    def test_disconnected_then_connected_when_server_appears(self):
        port = free_port()
        self.bridge.config(host="127.0.0.1", port=port, password="")
        down = self.bridge.wait_event("disconnected", 3.0)
        self.assertIsNotNone(down)
        self.assertIn("retryIn", down)
        self.assertTrue(down.get("error"))
        late = self.make_mpd()
        late.fixed_port = port
        late.start()
        self.addCleanup(late.stop)
        self.assertIsNotNone(self.bridge.wait_event("connected", 10.0))


class Password(ContractCase):
    password = "s3cret"

    def test_password_is_sent_first(self):
        first = {}
        for cid, tokens in self.mpd.commands():
            first.setdefault(cid, tokens)
        for tokens in first.values():
            self.assertEqual(tokens, ["password", "s3cret"])
        state = self.bridge.since(0, "state")[0]
        self.assertIn("volume", state["status"])


class WrongPassword(ContractCase):
    password = "s3cret"
    autoconnect = False

    def test_wrong_password_is_a_disconnect_with_reason(self):
        self.bridge.config(host="127.0.0.1", port=self.mpd.port, password="nope")
        down = self.bridge.wait_event("disconnected", 3.0)
        self.assertIsNotNone(down)
        self.assertIn("password", down["error"])
        self.assertEqual(self.bridge.since(0, "connected"), [])


class EnvironmentHost(ContractCase):
    password = "pw"
    autoconnect = False

    def bridge_env(self):
        return {"MPD_HOST": "pw@127.0.0.1", "MPD_PORT": str(self.mpd.port)}

    def test_empty_host_means_mpd_host(self):
        self.bridge.config(host="", password="")
        up = self.bridge.wait_event("connected", 5.0)
        self.assertIsNotNone(up, self.bridge.stderr)
        self.assertEqual(up["target"], "127.0.0.1:%d" % self.mpd.port)


class UnixSocket(ContractCase):
    autoconnect = False

    def test_a_path_is_a_unix_socket(self):
        path = os.path.join(self.home, "mpd.sock")
        sock_mpd = self.make_mpd(unix_path=path)
        sock_mpd.start()
        self.addCleanup(sock_mpd.stop)
        self.bridge.config(host=path, port=6600, password="")
        up = self.bridge.wait_event("connected", 5.0)
        self.assertIsNotNone(up)
        self.assertEqual(up["target"], path)
