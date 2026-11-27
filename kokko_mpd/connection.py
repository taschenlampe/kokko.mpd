"""One MPD connection over a socket: dial, greet, send, read replies.

A Connection is used by one thread at a time. The only thing another thread may
do to it is `interrupt()` -- shut the socket down so that a read blocked in
that thread returns with an error -- and `close()` once nobody reads.

Errors: anything that leaves the connection unusable is MPDError (with a
message meant for a person: "connection refused", "timed out waiting for a
reply"); an ACK is ServerRefused and leaves the connection fine.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import dataclass

from .protocol import MPDError, ProtocolError, Reply, ReplyParser, ServerRefused, command_line


@dataclass(frozen=True)
class Target:
    kind: str        # "tcp" or "unix"
    host: str        # host name, or socket path ("\0name" for an abstract socket)
    port: int = 0

    @property
    def label(self) -> str:
        if self.kind == "unix":
            return self.host.replace("\0", "@")
        return "%s:%d" % (self.host, self.port)


def target_from(host, port, env=None) -> tuple:
    """(Target, password-from-env) for the widget's host/port settings.

    An empty host means "where this user's other MPD clients look": $MPD_HOST,
    including its `password@host` form, and $MPD_PORT when no port was given.
    A host starting with `/` or `~` is a unix socket, `@name` an abstract one.
    """
    env = os.environ if env is None else env
    host = str(host or "").strip()
    env_password = ""
    if not host:
        host = str(env.get("MPD_HOST") or "").strip()
        if "@" in host and not host.startswith("@"):
            env_password, _, host = host.partition("@")
        if not port:
            port = env.get("MPD_PORT") or 6600
    if host.startswith("~"):
        host = os.path.expanduser(host)
    if host.startswith("/"):
        return Target("unix", host), env_password
    if host.startswith("@"):
        return Target("unix", "\0" + host[1:]), env_password
    try:
        port = int(port or 6600)
    except (TypeError, ValueError):
        port = 6600
    return Target("tcp", host or "127.0.0.1", port), env_password


def describe_error(exc: BaseException) -> str:
    """"Connection refused" rather than "[Errno 111] Connection refused"."""
    if isinstance(exc, socket.timeout):
        return "timed out"
    return getattr(exc, "strerror", None) or str(exc) or type(exc).__name__


class Connection:
    def __init__(self, target: Target, password: str = ""):
        self.target = target
        self.password = password or ""
        self.sock = None
        self.parser = ReplyParser(expect_greeting=True)
        self.ready = []                  # parsed results not yet handed out
        self.version = ""
        self.in_flight = False           # a command is on the wire, its reply not read
        self.last_used = 0.0             # monotonic time the last reply completed
        self.closed = threading.Event()

    # ------------------------------------------------------------ lifecycle

    def open(self, timeout: float) -> "Connection":
        try:
            if self.target.kind == "unix":
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                sock.connect(self.target.host)
            else:
                sock = socket.create_connection((self.target.host, self.target.port), timeout)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                # request/response: Nagle plus delayed ACK would wait on each other
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError as exc:
            self.closed.set()
            raise MPDError(describe_error(exc)) from exc
        self.sock = sock
        try:
            greeting = self._next()
            if isinstance(greeting, ServerRefused):
                raise ProtocolError("unexpected greeting from server")
            self.version = greeting.pairs[0][1]
            if self.password:
                self.call("password", self.password)
        except ServerRefused as exc:
            self.close()
            raise MPDError(exc.message or str(exc)) from exc
        except BaseException:
            self.close()
            raise
        self.last_used = time.monotonic()
        return self

    def set_timeout(self, seconds):
        if self.sock is not None:
            self.sock.settimeout(seconds)

    def interrupt(self) -> None:
        """Make a blocked read in another thread fail now."""
        self.closed.set()
        sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def close(self) -> None:
        self.closed.set()
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    @property
    def usable(self) -> bool:
        return self.sock is not None and not self.closed.is_set()

    # ---------------------------------------------------------- talking

    def send(self, name: str, *args) -> None:
        """Write one command. UnsafeValue (a CR/LF/NUL argument) before anything is sent."""
        line = command_line(name, *args)
        sock = self.sock
        if sock is None or self.closed.is_set():
            raise MPDError("connection closed")
        try:
            sock.sendall(line)
        except OSError as exc:
            self.closed.set()
            raise MPDError(describe_error(exc)) from exc
        self.in_flight = True

    def read_reply(self) -> Reply:
        """The reply to the command sent last. ServerRefused for an ACK."""
        result = self._next()
        self.in_flight = False
        self.last_used = time.monotonic()
        if isinstance(result, ServerRefused):
            raise result
        return result

    def call(self, name: str, *args) -> Reply:
        self.send(name, *args)
        return self.read_reply()

    def _next(self):
        while not self.ready:
            sock = self.sock      # close() from another thread may clear the attribute
            if sock is None or self.closed.is_set():
                raise MPDError("connection closed")
            try:
                data = sock.recv(65536)
            except socket.timeout as exc:
                self.closed.set()
                raise MPDError("timed out waiting for a reply") from exc
            except OSError as exc:
                self.closed.set()
                raise MPDError(describe_error(exc)) from exc
            if not data:
                self.closed.set()
                raise MPDError("connection closed by server")
            try:
                self.ready.extend(self.parser.feed(data))
            except ProtocolError:
                self.closed.set()
                raise
        return self.ready.pop(0)


def dial(target: Target, password: str, connect_timeout: float, reply_timeout) -> Connection:
    """Open, greet, authenticate; then set the timeout for replies (None = none)."""
    conn = Connection(target, password).open(connect_timeout)
    conn.set_timeout(reply_timeout)
    return conn
