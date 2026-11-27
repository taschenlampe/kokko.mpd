"""The command connection and the one thread that uses it.

Every transport button, every queue change and every status read goes through
`Executor`: a single worker thread with a FIFO of jobs. That gives the ordering
guarantee for free -- MPD sees commands in the order the widget sent them -- and
means the command socket is never shared between threads, so it needs no lock.

`CommandSession` holds the socket and the retry policy, which is per command,
never per job: a job like "append an album, then play it" sends several
commands, and running the job again would repeat the ones that already worked.

    write failed            nothing reached MPD -> same command on a fresh socket
    reply lost, repeatable  the command lands in the same place again -> resend
    reply lost, otherwise   given up; the error says "sent, reply lost -- not repeated"

A read-only job (status + currentsong) is the one exception: it may be run again
whole on a fresh socket, because it cannot change anything.
"""

from __future__ import annotations

import queue
import threading
import time

from .connection import Connection, dial
from .protocol import MPDError
from .tuning import T


class NotConnected(Exception):
    """No command connection right now: the job is dropped quietly."""


class SessionFailed(Exception):
    """The command connection is gone; str() is the message for `disconnected`."""


class LostReply(MPDError):
    def __init__(self, cause: MPDError):
        super().__init__(str(cause))
        self.cause = cause


class Handle:
    """What a job sees: `call()` one command at a time, and the server version."""

    def __init__(self, session: "CommandSession"):
        self.session = session
        self.repeated = False

    @property
    def version(self) -> str:
        conn = self.session.conn
        return conn.version if conn is not None else ""

    def call(self, name: str, *args, repeatable: bool = False):
        return self.session.call(self, name, args, repeatable)


class CommandSession:
    def __init__(self, link):
        self.link = link          # .target .password .generation (the bridge)
        self.conn: Connection | None = None
        self.generation = -1

    # --- owned connection

    def attach(self, conn: Connection, generation: int) -> None:
        self.detach()
        self.conn = conn
        self.generation = generation

    def detach(self) -> None:
        conn, self.conn = self.conn, None
        if conn is not None:
            conn.close()

    def redial(self) -> Connection:
        if self.generation != self.link.generation:
            raise MPDError("settings changed")
        fresh = dial(self.link.target, self.link.password, T.CONNECT_TIMEOUT, T.CMD_TIMEOUT)
        old, self.conn = self.conn, fresh
        if old is not None:
            old.close()
        return fresh

    def ready_conn(self) -> Connection:
        conn = self.conn
        if conn is None or self.generation != self.link.generation:
            raise NotConnected()
        # MPD hangs up on a command connection unused for connection_timeout, and a
        # write to that socket still succeeds -- so replace it before it is used.
        if not conn.in_flight and time.monotonic() - conn.last_used > T.CMD_IDLE_RENEW:
            try:
                conn = self.redial()
            except MPDError:
                pass          # keep the old one; its own failure path still applies
        return conn

    # --- one command

    def call(self, handle: Handle, name: str, args, repeatable: bool):
        conn = self.ready_conn()
        try:
            conn.send(name, *args)
        except MPDError:
            conn = self.redial()          # nothing went out: a copy of nothing
            handle.repeated = True
            conn.send(name, *args)
        try:
            return conn.read_reply()
        except MPDError as exc:
            if not repeatable:
                raise LostReply(exc)
        conn = self.redial()
        handle.repeated = True
        conn.send(name, *args)
        return conn.read_reply()

    # --- one job

    def run(self, job, read_only: bool = False):
        """Run `job(handle)`. ServerRefused/UnsafeValue pass through untouched."""
        handle = Handle(self)
        try:
            return job(handle)
        except LostReply as exc:
            self.detach()
            if handle.repeated:
                raise SessionFailed(str(exc.cause))
            raise SessionFailed("%s (sent, reply lost -- not repeated)" % exc.cause)
        except MPDError as exc:
            if read_only and self.generation == self.link.generation:
                try:
                    self.redial()
                    return job(Handle(self))
                except MPDError as again:
                    exc = again
            self.detach()
            raise SessionFailed(str(exc) or "connection lost")


class Executor:
    """The single thread that owns the command session.

    `submit(fn)` queues a job; `fn()` runs on the executor thread. `refresh` is
    coalesced: asking while one is queued adds nothing.
    """

    def __init__(self, name="commands"):
        self.jobs = queue.Queue()
        self.refresh_queued = threading.Event()
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self._loop, name=name, daemon=True)

    def start(self):
        self.thread.start()

    def submit(self, fn) -> None:
        if not self.stopped.is_set():
            self.jobs.put(fn)

    def submit_refresh(self, fn) -> None:
        if self.refresh_queued.is_set():
            return
        self.refresh_queued.set()

        def run():
            self.refresh_queued.clear()
            fn()
        self.submit(run)

    def stop(self) -> None:
        self.stopped.set()
        self.jobs.put(None)

    def _loop(self):
        while True:
            fn = self.jobs.get()
            if fn is None or self.stopped.is_set():
                return
            try:
                fn()
            except Exception as exc:  # a job must never take the executor down
                import sys
                sys.stderr.write("kokko_mpd: job failed: %r\n" % (exc,))
