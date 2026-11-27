"""The widget's plain verbs (`toggle`, `seek 12.5`, ...) and its `cmd` ops.

Each verb becomes one job on the executor. `repeatable` marks the commands that
land in the same place when sent twice (absolute setters, positions, ids) --
only those are re-sent when a reply is lost. `next`/`previous` are repeatable
on purpose: a doubled skip is the smaller evil against a dead button. A scan
(`update`/`rescan`) is not: two scans where one was asked for is a surprise.

Malformed input is ignored without an answer, as the contract says.
"""

from __future__ import annotations

OPTIONS = ("repeat", "random", "single", "consume")


def install(bridge) -> None:
    """Hook for feature modules (phase 4 registers mutations and queries here)."""
    bridge.mutations = {}


def send(bridge, name, *args, repeatable=False):
    bridge.run_job(lambda h: h.call(name, *args, repeatable=repeatable))


def toggle(handle):
    state = handle.call("status", repeatable=True).get("state", "stop")
    if state == "play":
        handle.call("pause", 1, repeatable=True)
    elif state == "pause":
        handle.call("pause", 0, repeatable=True)
    else:
        handle.call("play", repeatable=True)


SIMPLE = {
    "play": ("play",),
    "pause": ("pause", 1),
    "resume": ("pause", 0),
    "stop": ("stop",),
    "next": ("next",),
    "prev": ("previous",),
}


def verb(bridge, name: str, rest: str) -> None:
    if name == "toggle":
        bridge.run_job(toggle)
    elif name in SIMPLE:
        send(bridge, *SIMPLE[name], repeatable=True)
    elif name == "refresh":
        bridge.request_refresh()
    elif name == "seek":
        try:
            send(bridge, "seekcur", "%.3f" % float(rest), repeatable=True)
        except ValueError:
            pass
    elif name == "volume":
        try:
            level = max(0, min(100, int(float(rest))))
        except ValueError:
            return
        send(bridge, "setvol", level, repeatable=True)
    elif name == "setopt":
        option, _, value = rest.partition(" ")
        if option in OPTIONS:
            send(bridge, option, value.strip() or "0", repeatable=True)
    elif name == "play_id":
        try:
            send(bridge, "playid", int(rest), repeatable=True)
        except ValueError:
            pass
    elif name in ("update", "rescan"):
        path = rest.strip()
        send(bridge, name, *([path] if path else []))


def mutate(bridge, payload: dict) -> None:
    op = str(payload.get("op", ""))
    handler = bridge.mutations.get(op)
    if handler is not None:
        handler(bridge, payload)
