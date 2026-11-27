"""What happens when the server misbehaves: lost replies, hang-ups, wedges."""

import time

from harness import ContractCase, LEGACY, legacy_differs

JAIL = "Thin Lizzy/Jailbreak/01 Jailbreak.flac"
SOUTH = "Thin Lizzy/Jailbreak/02 Southbound.flac"
QUEEN = "ABBA/Arrival/01 Dancing Queen.flac"
PIGS = "Black Sabbath/Paranoid/01 War Pigs.flac"


class LostReplies(ContractCase):
    def setUp(self):
        super().setUp()
        time.sleep(0.2)

    def test_a_mutation_whose_reply_was_lost_is_not_repeated(self):
        self.mpd.drop_after["add"] = 1
        mark = self.bridge.mark()
        self.bridge.cmd("add", uri=JAIL)
        down = self.bridge.wait_event("disconnected", 3.0, mark)
        self.assertIsNotNone(down)
        self.assertIn("not repeated", down["error"])
        self.assertIsNotNone(self.bridge.wait_event("connected", 5.0, mark))
        time.sleep(0.3)
        self.assertEqual(self.mpd.count("add"), 1)
        self.assertEqual(self.queue_files(), [JAIL])

    def test_a_mutation_lost_before_it_ran_is_not_repeated_either(self):
        # the bridge cannot tell this apart from the case above
        self.mpd.drop_before["add"] = 1
        self.bridge.cmd("add", uri=JAIL)
        self.assertIsNotNone(self.bridge.wait_event("disconnected", 3.0))
        time.sleep(0.5)
        self.assertEqual(self.mpd.count("add"), 1)
        self.assertEqual(self.queue_files(), [])

    def test_an_absolute_setter_is_repeated_on_a_fresh_connection(self):
        self.mpd.drop_after["setvol"] = 1
        mark = self.bridge.mark()
        self.bridge.send("volume 61")
        self.assertIsNotNone(self.state(3.0, mark, volume="61"))
        self.assertEqual(self.mpd.count("setvol"), 2)
        self.assertEqual(self.bridge.since(mark, "disconnected"), [])

    def test_next_is_repeated_on_a_lost_reply_deliberately(self):
        self.load_queue([JAIL, SOUTH, QUEEN, PIGS], current=0, state="play")
        self.assertIsNotNone(self.state(3.0, 0, state="play"))
        self.mpd.drop_after["next"] = 1
        self.bridge.send("next")
        self.assertTrue(self.mpd.wait_for(lambda: self.mpd.count("next") == 2, 3.0))
        self.assertEqual(self.mpd.current, 2)   # the documented doubled skip

    def test_findadd_inside_a_callback_is_sent_once(self):
        self.mpd.drop_after["findadd"] = 1
        self.bridge.cmd("findadd", filter=[["artist", "Thin Lizzy"]])
        self.assertIsNotNone(self.bridge.wait_event("disconnected", 3.0))
        time.sleep(0.5)
        self.assertEqual(self.mpd.count("findadd"), 1)
        self.assertEqual(self.queue_files(), [JAIL, SOUTH])

    def test_a_lost_status_reply_is_retried_silently(self):
        mark = self.bridge.mark()
        self.mpd.drop_after["status"] = 1
        self.bridge.send("volume 44")
        self.assertIsNotNone(self.state(3.0, mark, volume="44"))
        self.assertEqual(self.bridge.since(mark, "disconnected"), [])


class ServerHangsUp(ContractCase):
    tuning = {"CMD_IDLE_RENEW": 0.3}

    def test_an_idle_command_connection_is_renewed_before_use(self):
        self.load_queue([JAIL], current=0, state="play")
        self.assertIsNotNone(self.state(3.0, 0, state="play"))
        self.mpd.close_idle_after = 0.5          # MPD's connection_timeout
        time.sleep(1.0)
        mark = self.bridge.mark()
        self.mpd.clear_log()
        self.bridge.send("pause")
        self.assertIsNotNone(self.state(3.0, mark, state="pause"))
        self.assertEqual(self.mpd.count("pause"), 1)
        self.assertEqual(self.bridge.since(mark, "disconnected"), [])

    def test_a_stale_query_connection_is_replaced_quietly(self):
        self.assertIsNotNone(self.bridge.ask("listplaylists"))
        self.mpd.close_idle_after = 0.3
        time.sleep(0.8)
        ev = self.bridge.ask("listplaylists")
        self.assertNotIn("error", ev)
        self.assertEqual(len(ev["rows"]), 2)

    def test_all_connections_killed_reconnects_and_restates(self):
        self.load_queue([JAIL], current=0, state="play")
        self.assertIsNotNone(self.state(3.0, 0, state="play"))
        mark = self.bridge.mark()
        self.mpd.kill_all()
        self.assertIsNotNone(self.bridge.wait_event("disconnected", 3.0, mark))
        self.assertIsNotNone(self.bridge.wait_event("connected", 6.0, mark))
        self.assertIsNotNone(self.state(3.0, mark, state="play"),
                             "the state was not announced again after the reconnect")

    def test_server_gone_answers_queries_with_an_error(self):
        mark = self.bridge.mark()
        self.mpd.stop()
        self.assertIsNotNone(self.bridge.wait_event("disconnected", 3.0, mark))
        ev = self.bridge.ask("listplaylists", 8.0)
        self.assertIsNotNone(ev, "a query hung while the server was gone")
        self.assertEqual(ev["rows"], [])
        self.assertTrue(ev.get("error"))

    def settings_change_during_queries(self):
        self.mpd.delay["find"] = 0.6
        busy = self.bridge.query("find", channel="a", filter=[["artist", "ABBA"]])
        time.sleep(0.15)
        waiting = [self.bridge.query("find", channel=c, filter=[["artist", "Smashing"]])
                   for c in ("b", "c")]
        other = self.make_mpd()
        other.start()
        self.addCleanup(other.stop)
        self.bridge.config(host="127.0.0.1", port=other.port, password="")
        return busy, waiting

    def test_waiting_queries_are_answered_when_the_settings_change(self):
        busy, waiting = self.settings_change_during_queries()
        if LEGACY:
            self.unanswered_ok.add(busy)
        for qid in waiting:
            ev = self.bridge.result(qid, 6.0)
            self.assertIsNotNone(ev, "query %d never answered" % qid)
            self.assertTrue(ev.get("dropped"))

    @legacy_differs("a query in flight during a settings change is never answered")
    def test_the_query_in_flight_is_answered_when_the_settings_change(self):
        busy, _ = self.settings_change_during_queries()
        if LEGACY:
            self.unanswered_ok.add(busy)
        self.assertIsNotNone(self.bridge.result(busy, 6.0), "the running query was never answered")


class Wedge(ContractCase):
    def test_a_silent_daemon_is_announced_once_and_its_recovery_too(self):
        ok = self.bridge.wait_event("health", 3.0, ok=True)
        self.assertIsNotNone(ok)
        self.assertEqual(ok["target"], "127.0.0.1:%d" % self.mpd.port)
        mark = self.bridge.mark()
        self.mpd.wedged = True
        bad = self.bridge.wait_event("health", 6.0, mark, ok=False)
        self.assertIsNotNone(bad, "no health:false while the daemon did not greet")
        self.assertGreaterEqual(bad["fails"], 2)
        self.assertTrue(bad["detail"])
        time.sleep(1.0)
        self.assertEqual(len(self.bridge.since(mark, "health")), 1, "the wedge was announced twice")
        mark = self.bridge.mark()
        self.mpd.wedged = False
        self.assertIsNotNone(self.bridge.wait_event("health", 6.0, mark, ok=True))
