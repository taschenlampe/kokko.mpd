"""MPD's text protocol, without any socket.

Everything here works on bytes and strings only, so it can be tested with
nothing but fixtures: building a command line, reading the greeting, and turning
the server's reply bytes into a `Reply` (or a `ServerRefused` for an ACK). The
`ReplyParser` is incremental -- it is fed whatever a socket read returned, in any
chunk size, and says when a reply is complete -- which is what makes short reads
and binary chunks testable without timing.

The wire format, as far as the bridge uses it:

    greeting   OK MPD <version>\\n
    reply      (<key>: <value>\\n)* OK\\n
    binary     ... binary: <n>\\n <n bytes> \\n ... OK\\n
    refusal    ACK [<code>@<index>] {<command>} <message>\\n
    idle       changed: <subsystem>\\n ... OK\\n
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A single binary chunk larger than this is not a cover, it is a broken or
# hostile peer; the connection is given up rather than the memory.
MAX_BINARY_CHUNK = 12 * 1024 * 1024
# A text line longer than this is treated the same way.
MAX_LINE = 1024 * 1024

GREETING_PREFIX = "OK MPD "


# ------------------------------------------------------------------ errors

class MPDError(Exception):
    """The connection is no longer usable (closed, timed out, out of step)."""


class ProtocolError(MPDError):
    """The peer sent something that is not MPD's protocol."""


class ServerRefused(Exception):
    """An ACK: the server understood the command and refused it.

    Deliberately *not* an MPDError: after an ACK the connection is at a command
    boundary and fine to use. `str()` is the text a person is shown,
    "<command>: <message>" -- the code and index are kept as fields.
    """

    def __init__(self, code: int, index: int, command: str, message: str, raw: str = ""):
        self.code = code
        self.index = index
        self.command = command
        self.message = message
        self.raw = raw
        super().__init__(self.text())

    def text(self) -> str:
        if self.command and self.message:
            return "%s: %s" % (self.command, self.message)
        return self.message or self.raw


class UnsafeValue(ValueError):
    """A value that cannot travel on one command line (CR, LF or NUL in it)."""


# ACK error codes (MPD's ack.h), for callers that branch on them.
ACK_NOT_LIST = 1
ACK_ARG = 2
ACK_PASSWORD = 3
ACK_PERMISSION = 4
ACK_UNKNOWN = 5
ACK_NO_EXIST = 50
ACK_PLAYLIST_MAX = 51
ACK_SYSTEM = 52
ACK_PLAYLIST_LOAD = 53
ACK_UPDATE_ALREADY = 54
ACK_PLAYER_SYNC = 55
ACK_EXIST = 56

_ACK = re.compile(r"^ACK \[(\d+)@(\d+)\] \{([^}]*)\} ?(.*)$")
_FRAMING = re.compile(r"[\x00\r\n]")


def parse_ack(line: str) -> ServerRefused:
    """`ACK [50@0] {load} No such playlist` -> ServerRefused."""
    match = _ACK.match(line)
    if not match:
        body = line[4:].strip() if line.startswith("ACK") else line.strip()
        return ServerRefused(0, 0, "", body, line)
    code, index, command, message = match.groups()
    return ServerRefused(int(code), int(index), command.strip(), message.strip(), line)


# ---------------------------------------------------------------- commands

def safe_text(value, what: str = "value") -> str:
    """`value` as text, refused if it would break the one-line framing."""
    text = str(value)
    hit = _FRAMING.search(text)
    if hit:
        raise UnsafeValue("%s contains a line break or NUL (U+%04X), which MPD cannot carry "
                          "on one command line" % (what, ord(hit.group(0))))
    return text


def quote(value) -> str:
    """One argument in MPD's double quotes, with `\\` and `"` escaped."""
    text = safe_text(value)
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


_COMMAND_NAME = re.compile(r"^[a-z_]+$")


def command_line(name: str, *args) -> bytes:
    """The bytes of one command: name, quoted arguments, newline.

    Every argument is quoted -- also numbers -- which MPD accepts and which keeps
    one rule for everything. The name is checked rather than quoted: it is never
    user data, and a bad one is a programming error.
    """
    if not _COMMAND_NAME.match(name):
        raise ValueError("not a command name: %r" % (name,))
    parts = [name] + [quote(a) for a in args]
    return (" ".join(parts) + "\n").encode("utf-8")


def parse_greeting(line: str) -> str:
    """The server version from `OK MPD 0.24.0`, or ProtocolError."""
    if not line.startswith(GREETING_PREFIX):
        raise ProtocolError("unexpected greeting from server")
    version = line[len(GREETING_PREFIX):].strip()
    if not version:
        raise ProtocolError("greeting without a version")
    return version


def version_tuple(version: str) -> tuple:
    """`0.24.0` -> (0, 24, 0); unparsable parts count as 0."""
    out = []
    for part in (version or "").split("."):
        digits = re.match(r"\d+", part)
        out.append(int(digits.group(0)) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def at_least(version: str, major: int, minor: int) -> bool:
    return version_tuple(version)[:2] >= (major, minor)


# ----------------------------------------------------------------- replies

@dataclass
class Reply:
    """One complete answer: the key/value pairs in order, and binary if any.

    Keys keep the server's spelling here; folding them is the caller's choice.
    `binary` is None when the reply had no binary section.
    """
    pairs: list = field(default_factory=list)
    binary: bytes | None = None

    def get(self, key: str, default=None):
        low = key.lower()
        for k, v in self.pairs:
            if k.lower() == low:
                return v
        return default

    def values(self, key: str) -> list:
        low = key.lower()
        return [v for k, v in self.pairs if k.lower() == low]


_MORE = object()   # _step: the buffer holds no complete line
_NEXT = object()   # _step: a line was consumed, no reply finished yet


class ReplyParser:
    """Incremental reader of replies.

    `feed(data)` takes bytes as they arrive and returns a list of finished
    results, each a Reply or a ServerRefused, in order. Bytes after a finished
    reply stay buffered for the next one. A violation of the framing raises
    ProtocolError; the parser is unusable after that, like the connection.

    `expect_greeting=True` makes the first line the greeting, delivered as a
    one-pair Reply (("OK MPD", version)) -- so a connection can use the same
    parser from the first byte on.
    """

    def __init__(self, expect_greeting: bool = False, max_binary: int = MAX_BINARY_CHUNK):
        self.buf = bytearray()
        self.pairs = []
        self.binary = None
        self.need = None          # bytes still owed by a binary section (+1 for its newline)
        self.chunk = bytearray()
        self.greeting = expect_greeting
        self.max_binary = max_binary
        self.broken = False

    def feed(self, data: bytes) -> list:
        if self.broken:
            raise ProtocolError("parser used after a protocol error")
        self.buf.extend(data)
        out = []
        try:
            while True:
                result = self._step()
                if result is _MORE:
                    break
                if result is not _NEXT:
                    out.append(result)
        except ProtocolError:
            self.broken = True
            raise
        return out

    @property
    def idle(self) -> bool:
        """Nothing half-read: the stream is at a reply boundary."""
        return not self.buf and not self.pairs and self.need is None and self.binary is None

    def _step(self):
        if self.need is not None:
            take = min(self.need, len(self.buf))
            self.chunk.extend(self.buf[:take])
            del self.buf[:take]
            self.need -= take
            if self.need:
                return _MORE
            if not self.chunk.endswith(b"\n"):
                raise ProtocolError("binary chunk not followed by a newline")
            self.binary = bytes(self.chunk[:-1])
            self.chunk = bytearray()
            self.need = None
        end = self.buf.find(b"\n")
        if end < 0:
            if len(self.buf) > MAX_LINE:
                raise ProtocolError("line longer than %d bytes" % MAX_LINE)
            return _MORE
        raw = bytes(self.buf[:end])
        del self.buf[:end + 1]
        line = raw.decode("utf-8", "replace")
        if self.greeting:
            self.greeting = False
            return Reply([("OK MPD", parse_greeting(line))])
        if line == "OK":
            reply = Reply(self.pairs, self.binary)
            self.pairs, self.binary = [], None
            return reply
        if line.startswith("ACK "):
            # MPD sends an ACK instead of a reply, never after part of one
            # (command lists aside, which this bridge does not use).
            self.pairs, self.binary = [], None
            return parse_ack(line)
        key, sep, value = line.partition(": ")
        if not sep:
            raise ProtocolError("not a key/value line: %r" % line[:80])
        if key == "binary":
            try:
                count = int(value)
            except ValueError:
                raise ProtocolError("malformed binary chunk length")
            if count < 0 or count > self.max_binary:
                raise ProtocolError("refusing a %d byte binary chunk" % count)
            if self.binary is not None:
                raise ProtocolError("two binary sections in one reply")
            self.pairs.append((key, value))
            self.need = count + 1
            self.chunk = bytearray()
            return _NEXT
        self.pairs.append((key, value))
        return _NEXT


def changed_subsystems(reply: Reply) -> list:
    """The subsystems an `idle` reply names, in order."""
    return reply.values("changed")
