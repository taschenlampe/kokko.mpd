"""The query worker: browsing questions on their own connection and thread.

A `find` over a big library takes long enough to be felt, and must not be felt
on the play button -- so queries never touch the command connection. They run
one at a time on this worker, on a third connection opened by the first query
(a bar that nobody browses holds no extra socket).

Rules (docs/bridge-contract.md, "Queries"):
* every request gets exactly one `result`;
* a waiting request with a channel is skipped once a newer one on the same
  channel arrives, and answered `dropped`;
* a settings change answers everything waiting as `dropped` and the request in
  flight with an error -- nothing is left unanswered;
* a refusal (ACK) is the request's `error`, the connection stays;
* a broken socket gets one more try on a fresh one (MPD hangs up idle
  connections), then the error stands.

Handlers are registered per kind: `handler(conn, request, limit) -> rows`. A
handler flagged `local` gets no connection (radio, recent).
"""

from __future__ import annotations

import threading

from .connection import dial
from .protocol import MPDError, ServerRefused, UnsafeValue
from .tuning import T

ROW_LIMIT = 20000


class QueryError(Exception):
    """A handler's own refusal (e.g. the radio directory is down)."""


class Queries:
    def __init__(self, bridge):
        self.b = bridge
        self.cv = threading.Condition()
        self.pending = []
        self.current = None          # (request, generation) being answered
        self.conn = None
        self.conn_gen = -1
        self.handlers = {}           # kind -> (fn, local)
        self.thread = None

    def register(self, kind: str, fn, local: bool = False):
        self.handlers[kind] = (fn, local)

    # ------------------------------------------------------------ intake

    def submit(self, request: dict) -> None:
        with self.cv:
            self.pending.append(request)
            self.cv.notify()
        self.ensure_worker()

    def ensure_worker(self):
        with self.cv:
            if self.thread is not None and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self.loop, name="queries", daemon=True)
            self.thread.start()

    def drop(self) -> None:
        """Settings changed: answer the waiting, break the one in flight."""
        with self.cv:
            waiting, self.pending = self.pending, []
            conn, self.conn = self.conn, None
        for request in waiting:
            self.b.events.result(request, dropped=True)
        if conn is not None:
            conn.interrupt()

    def shutdown(self):
        with self.cv:
            self.cv.notify_all()
            conn, self.conn = self.conn, None
        if conn is not None:
            conn.interrupt()
            conn.close()

    # ------------------------------------------------------------- worker

    def loop(self):
        b = self.b
        while not b.stop.is_set():
            with self.cv:
                while not self.pending and not b.stop.is_set():
                    self.cv.wait(0.5)
                if b.stop.is_set():
                    return
                request = self.pending.pop(0)
                channel = request.get("channel")
                superseded = bool(channel) and any(
                    r.get("channel") == channel for r in self.pending)
            if superseded:
                b.events.result(request, dropped=True)
                continue
            try:
                self.answer(request)
            except Exception as exc:     # never leave a request unanswered
                b.events.result(request, error="internal error: %r" % (exc,))

    def answer(self, request: dict) -> None:
        b = self.b
        gen = b.generation
        kind = str(request.get("kind", ""))
        try:
            limit = max(1, min(ROW_LIMIT, int(request.get("limit", ROW_LIMIT))))
        except (TypeError, ValueError):
            limit = ROW_LIMIT
        entry = self.handlers.get(kind)
        if entry is None:
            b.events.result(request, error="unknown query: %s" % kind)
            return
        fn, local = entry
        if local:
            try:
                rows = fn(None, request, limit)
            except (QueryError, ValueError) as exc:
                b.events.result(request, error=str(exc))
                return
            self.finish(request, rows, limit)
            return
        error = None
        for attempt in (0, 1):
            conn = None
            try:
                conn = self.connection(gen)
                rows = fn(conn, request, limit)
            except (ServerRefused, UnsafeValue) as exc:
                b.events.result(request, error=str(exc))
                return
            except MPDError as exc:
                error = str(exc) or "connection lost"
                if conn is not None:
                    self.forget(conn)
                if gen != b.generation or b.stop.is_set():
                    error = "settings changed" if gen != b.generation else error
                    break
                continue
            if gen != b.generation:
                error = "settings changed"
                break
            self.finish(request, rows, limit)
            return
        b.events.result(request, error=error)

    def finish(self, request, rows, limit):
        asked = request.get("limit")
        truncated = asked is not None and len(rows) >= limit
        self.b.events.result(request, rows=rows, truncated=truncated)

    def connection(self, gen):
        with self.cv:
            if self.conn is not None and self.conn_gen == gen and self.conn.usable:
                return self.conn
        _, target, password = self.b.snapshot()
        conn = dial(target, password, T.CONNECT_TIMEOUT, T.CMD_TIMEOUT)
        try:
            conn.call("binarylimit", T.BINARY_CHUNK)
        except ServerRefused:
            pass                  # older than 0.22: default chunks, still works
        with self.cv:
            if gen != self.b.generation:
                conn.close()
                raise MPDError("settings changed")
            old, self.conn, self.conn_gen = self.conn, conn, gen
        if old is not None:
            old.close()
        return conn

    def forget(self, conn):
        with self.cv:
            if self.conn is conn:
                self.conn = None
        conn.close()
