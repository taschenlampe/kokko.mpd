"""The queue: what the panel's buttons and drags do to it.

Each op is one job on the executor. The ones that name a position or an id are
repeatable -- replaying them lands on the same song -- while `add` is not: a
repeated append after a lost reply would double the album.
"""

from __future__ import annotations

from .playlists import append_after_current, append_and_play, crop, find_add, queue_length, search_add


def _int(payload, key, default=None):
    value = payload.get(key, default)
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _uri(payload):
    return str(payload.get("uri") or "").strip()


def _name(payload):
    return str(payload.get("name") or "").strip()


def install(bridge) -> None:
    ops = bridge.mutations
    ops["playid"] = _playid
    ops["playpos"] = _playpos
    ops["add"] = lambda b, p: _send(b, "add", _uri(p))
    ops["addplay"] = lambda b, p: _job(b, append_and_play, _uri(p))
    ops["insert"] = lambda b, p: _job(b, append_after_current, _uri(p))
    ops["remove"] = _remove
    ops["move"] = _move
    ops["clear"] = lambda b, p: b.run_job(lambda h: h.call("clear"))
    ops["shuffle"] = lambda b, p: b.run_job(lambda h: h.call("shuffle"))
    ops["crop"] = lambda b, p: b.run_job(lambda h: crop(h))
    ops["findadd"] = lambda b, p: _add_by(b, p, play=False)
    ops["findplay"] = lambda b, p: _add_by(b, p, play=True)
    ops["searchadd"] = _searchadd


def _send(bridge, command, value):
    if not value:
        return
    bridge.run_job(lambda h: h.call(command, value))


def _job(bridge, fn, value):
    if not value:
        return
    bridge.run_job(lambda h: fn(h, value))


def _playid(bridge, payload):
    song = _int(payload, "id")
    if song is None:
        return
    bridge.run_job(lambda h: h.call("playid", song, repeatable=True))


def _playpos(bridge, payload):
    pos = _int(payload, "pos")
    if pos is None:
        return
    bridge.run_job(lambda h: h.call("play", pos, repeatable=True))


def _remove(bridge, payload):
    song = _int(payload, "id")
    if song is None:
        return
    bridge.run_job(lambda h: h.call("deleteid", song, repeatable=True))


def _move(bridge, payload):
    start, end = _int(payload, "from"), _int(payload, "to")
    if start is None or end is None:
        return
    bridge.run_job(lambda h: h.call("move", start, end, repeatable=True))


def _add_by(bridge, payload, play):
    condition = payload.get("filter")
    if not condition:
        return

    def job(h):
        message = find_add(h, condition, play)
        if message:
            bridge.events.ack(message)
    bridge.run_job(job)


def _searchadd(bridge, payload):
    term = str(payload.get("term") or "").strip()
    tag = str(payload.get("tag") or "").strip()
    if not term:
        return

    def job(h):
        message = search_add(h, term, tag)
        if message:
            bridge.events.ack(message)
    bridge.run_job(job)
