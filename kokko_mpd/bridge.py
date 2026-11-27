"""The bridge process: the widget's lines in, JSON events out.

Threads:
    main        reads stdin, dispatches; never blocks on MPD
    commands    the Executor -- owns the command connection (session.py)
    manager     connection rounds and the idle loop (state.py)
    health      the greeting probe (state.py)
    queries     browsing questions on their own connection (queries.py)

Shared state is small and guarded by `lock`: where to connect (target,
password, generation) and whether `connected` has been announced. The
generation is bumped by every effective settings change; every thread compares
the generation it started with before it announces anything.
"""

from __future__ import annotations

import json
import signal
import sys
import threading

from . import artwork, commands, library, playlists, queue_ops, radio, recent
from .connection import Target, target_from
from .events import Events
from .protocol import ServerRefused, UnsafeValue
from .queries import Queries
from .session import CommandSession, Executor, NotConnected, SessionFailed
from .state import Health, Manager, read_state


class Bridge:
    def __init__(self, stdout=None):
        self.stop = threading.Event()
        self.events = Events(stdout, on_broken=self.stop.set)
        self.lock = threading.RLock()
        self.target = Target("tcp", "127.0.0.1", 6600)
        self.password = ""
        self.generation = 0
        self.configured = threading.Event()
        self.connected = False
        self.idle_conn = None
        self.wake = threading.Event()
        self.last_state = None
        self.music_root = None            # None: never configured; "" means mpd.conf
        self.session = CommandSession(self)
        self.executor = Executor()
        self.queries = Queries(self)
        self.health = Health(self)
        self.features = []                # objects with optional on_state/on_database/on_config
        commands.install(self)
        # Feature slices: each registers its query kinds and `cmd` ops, and the
        # ones with a hook on state/database/config append themselves to `features`.
        for module in (library, playlists, queue_ops, artwork, radio, recent):
            module.install(self)

    # ------------------------------------------------------------ link state

    def snapshot(self):
        with self.lock:
            return self.generation, self.target, self.password

    def apply_config(self, payload: dict) -> None:
        root = payload.get("musicRoot", "")
        self.music_root = str(root or "").strip()
        for feature in self.features:
            hook = getattr(feature, "on_config", None)
            if hook:
                hook(payload)
        target, env_password = target_from(payload.get("host", ""), payload.get("port"))
        password = str(payload.get("password", "") or "") or env_password
        with self.lock:
            if (self.configured.is_set() and target == self.target
                    and password == self.password and self.connected):
                return
            self.target, self.password = target, password
            self.generation += 1
            self.configured.set()
        self.drop("settings changed")
        self.wake.set()

    def publish(self, gen, cmd, idle) -> bool:
        """A round came up. Announce it -- unless it belongs to an old generation."""
        with self.lock:
            if gen != self.generation or self.stop.is_set():
                return False
            self.idle_conn = idle
            self.connected = True
            label = self.target.label
        self.executor.submit(lambda: self._attach(cmd, gen))
        self.events.connected(cmd.version, label)
        self.request_refresh()
        return True

    def _attach(self, cmd, gen):
        if gen != self.generation:
            cmd.close()
            return
        self.session.attach(cmd, gen)
        self.last_state = None

    def drop(self, reason: str) -> None:
        """Tear the round down; the manager starts the next one."""
        with self.lock:
            was, self.connected = self.connected, False
            idle, self.idle_conn = self.idle_conn, None
        if idle is not None:
            idle.interrupt()
        conn = self.session.conn
        if conn is not None:
            conn.interrupt()          # break a read the executor may be in
        self.executor.submit(self.session.detach)
        self.queries.drop()
        self.last_state = None
        if was:
            self.events.disconnected(reason)

    def lost(self, gen, reason: str) -> None:
        if gen == self.generation:
            self.drop(reason)

    def library_changed(self):
        for feature in self.features:
            hook = getattr(feature, "on_database", None)
            if hook:
                hook()
        self.events.database()

    # ------------------------------------------------------------ commands

    def run_job(self, job, read_only=False, refresh=True):
        """Queue `job(handle)` on the executor; report what goes wrong."""
        def run():
            try:
                self.session.run(job, read_only)
            except NotConnected:
                return
            except (ServerRefused, UnsafeValue) as exc:
                self.events.ack(str(exc))
            except SessionFailed as exc:
                self.drop(str(exc))
                return
            if refresh:
                self.request_refresh()
        self.executor.submit(run)

    def request_refresh(self):
        self.executor.submit_refresh(self._refresh)

    def _refresh(self):
        try:
            status, song = self.session.run(read_state, read_only=True)
        except NotConnected:
            return
        except (ServerRefused, UnsafeValue) as exc:
            self.events.ack(str(exc))
            return
        except SessionFailed as exc:
            self.drop(str(exc))
            return
        state = (status, song)
        if state != self.last_state:
            self.last_state = state
            self.events.state(status, song)
        for feature in self.features:
            hook = getattr(feature, "on_state", None)
            if hook:
                hook(status, song)

    # --------------------------------------------------------------- stdin

    def handle(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        verb, _, rest = line.partition(" ")
        rest = rest.strip()
        if verb == "quit":
            self.stop.set()
            return
        if verb in ("config", "cmd", "query"):
            try:
                payload = json.loads(rest or "{}")
            except ValueError:
                return
            if not isinstance(payload, dict):
                return
            if verb == "config":
                self.apply_config(payload)
            elif verb == "cmd":
                commands.mutate(self, payload)
            else:
                self.queries.submit(payload)
            return
        commands.verb(self, verb, rest)

    def run(self, stdin=None) -> int:
        stdin = stdin if stdin is not None else sys.stdin
        self.executor.start()
        threading.Thread(target=Manager(self).run, name="manager", daemon=True).start()
        threading.Thread(target=self.health.run, name="health", daemon=True).start()
        self.queries.ensure_worker()
        try:
            while not self.stop.is_set():
                line = stdin.readline()
                if not line:
                    break
                self.handle(line)
        except KeyboardInterrupt:
            pass
        self.shutdown()
        return 0

    def shutdown(self):
        self.stop.set()
        with self.lock:
            self.generation += 1
        self.wake.set()
        self.drop("shutting down")
        self.queries.shutdown()
        self.executor.stop()
        self.executor.thread.join(2.0)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    def on_term(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, on_term)
    except ValueError:
        pass                          # not the main thread (embedded in a test)
    try:
        return Bridge().run()
    except BrokenPipeError:
        return 0
