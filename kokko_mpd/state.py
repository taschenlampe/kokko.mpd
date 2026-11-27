"""Connection rounds, idle push, status reads and the greeting probe.

`Manager` runs one *round* at a time: dial the command and the idle
connection, announce `connected`, then park in `idle` until MPD says something
changed (-> refresh) or the connection breaks (-> `disconnected`, backoff, next
round). A settings change bumps the bridge's generation; whatever a round
dialled for an older generation is closed and never announced.

`Health` is independent of both: every HEALTH_INTERVAL it opens one more short
connection and waits HEALTH_TIMEOUT for the greeting. A daemon that accepts and
never greets (the documented wedge) looks perfectly connected otherwise.
"""

from __future__ import annotations

import time

from .connection import dial
from .protocol import MPDError, changed_subsystems
from .records import record
from .tuning import T

IDLE_SUBSYSTEMS = ("player", "mixer", "options", "playlist", "update", "database")


class Manager:
    def __init__(self, bridge):
        self.b = bridge

    def run(self):
        b = self.b
        backoff = T.BACKOFF_FIRST
        # Nothing is dialled before the widget has said where to.
        while not b.stop.is_set() and not b.configured.is_set():
            b.wake.wait(0.2)
        while not b.stop.is_set():
            gen, target, password = b.snapshot()
            b.wake.clear()
            cmd = idle = None
            try:
                cmd = dial(target, password, T.CONNECT_TIMEOUT, T.CMD_TIMEOUT)
                idle = dial(target, password, T.CONNECT_TIMEOUT, None)
            except MPDError as exc:
                for conn in (cmd, idle):
                    if conn is not None:
                        conn.close()
                if gen != b.generation:
                    backoff = T.BACKOFF_FIRST
                    continue
                b.events.disconnected(str(exc), target.label, backoff)
                b.wake.wait(backoff)
                backoff = T.BACKOFF_FIRST if gen != b.generation else min(T.BACKOFF_MAX, backoff * 2)
                continue
            if not b.publish(gen, cmd, idle):
                cmd.close()
                idle.close()
                backoff = T.BACKOFF_FIRST
                continue
            alive_since = time.monotonic()
            reason = self.idle_loop(gen, idle)
            idle.close()
            if gen != b.generation:
                backoff = T.BACKOFF_FIRST
                continue
            b.lost(gen, reason)
            if time.monotonic() - alive_since < T.MIN_ROUND_ALIVE:
                backoff = min(T.BACKOFF_MAX, backoff * 2)
                b.wake.wait(backoff)
            else:
                backoff = T.BACKOFF_FIRST

    def idle_loop(self, gen, idle) -> str:
        b = self.b
        try:
            while not b.stop.is_set() and gen == b.generation:
                idle.send("idle", *IDLE_SUBSYSTEMS)
                reply = idle.read_reply()
                if gen != b.generation:
                    break
                changed = changed_subsystems(reply)
                if "database" in changed:
                    b.library_changed()
                b.request_refresh()
        except MPDError as exc:
            return str(exc) or "connection lost"
        return "connection lost"


def read_state(handle) -> tuple:
    """(status, song) from one round trip each, keys folded."""
    status = record(handle.call("status", repeatable=True).pairs)
    song = record(handle.call("currentsong", repeatable=True).pairs)
    return status, song


class Health:
    def __init__(self, bridge):
        self.b = bridge
        self.ok = None
        self.fails = 0

    def tick(self, ok: bool, detail: str, target: str) -> None:
        """One probe result folded into the announced verdict (no I/O, testable)."""
        if ok:
            self.fails = 0
            if self.ok is not True:
                self.ok = True
                self.b.events.health(True, detail, target)
            return
        self.fails += 1
        if self.fails >= T.HEALTH_FAILS and self.ok is not False:
            self.ok = False
            self.b.events.health(False, detail, target, self.fails)

    def probe(self, target, password) -> tuple:
        try:
            conn = dial(target, password, T.HEALTH_TIMEOUT, T.HEALTH_TIMEOUT)
        except MPDError as exc:
            return False, str(exc) or "no greeting"
        version = conn.version
        conn.close()
        return True, version

    def run(self):
        b = self.b
        while not b.stop.is_set() and not b.configured.is_set():
            b.stop.wait(0.2)
        while not b.stop.is_set():
            gen, target, password = b.snapshot()
            try:
                ok, detail = self.probe(target, password)
            except Exception as exc:          # the guard must survive a bad probe
                ok, detail = False, str(exc)
            if gen == b.generation:
                self.tick(ok, detail, target.label)
            if b.stop.wait(T.HEALTH_INTERVAL):
                return
