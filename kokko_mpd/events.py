"""Everything the bridge says to the widget, in one place.

One JSON object per line on stdout. Each event of docs/bridge-contract.md has
one method here, so the shapes live in a single file.
"""

from __future__ import annotations

import json
import sys
import threading


class Events:
    def __init__(self, stream=None, on_broken=None):
        self.stream = stream if stream is not None else sys.stdout
        self.lock = threading.Lock()
        self.on_broken = on_broken
        self.broken = False

    def emit(self, payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False) + "\n"
        with self.lock:
            if self.broken:
                return
            try:
                self.stream.write(line)
                self.stream.flush()
            except (BrokenPipeError, OSError, ValueError):
                # the widget is gone (closed pipe / closed stream): nobody to talk to
                self.broken = True
                if self.on_broken:
                    self.on_broken()

    # --- the events

    def connected(self, version: str, target: str):
        self.emit({"event": "connected", "version": version, "target": target})

    def disconnected(self, error: str, target: str = None, retry_in: float = None):
        payload = {"event": "disconnected", "error": error}
        if target is not None:
            payload["target"] = target
        if retry_in is not None:
            payload["retryIn"] = retry_in
        self.emit(payload)

    def state(self, status: dict, song: dict):
        self.emit({"event": "state", "status": status, "song": song})

    def art(self, uri: str, path: str, mime: str = ""):
        self.emit({"event": "art", "uri": uri, "path": path, "mime": mime})

    def database(self):
        self.emit({"event": "database"})

    def health(self, ok: bool, detail: str, target: str, fails: int = None):
        payload = {"event": "health", "ok": ok, "detail": detail, "target": target}
        if fails is not None:
            payload["fails"] = fails
        self.emit(payload)

    def ack(self, error: str):
        self.emit({"event": "ack", "error": error})

    def result(self, request: dict, rows=None, error: str = None,
               truncated: bool = False, dropped: bool = False):
        payload = {"event": "result", "id": request.get("id"),
                   "kind": str(request.get("kind", "")),
                   "channel": request.get("channel", "") or "",
                   "rows": rows if rows is not None else []}
        if error:
            payload["error"] = error
        if truncated:
            payload["truncated"] = True
        if dropped:
            payload["dropped"] = True
        self.emit(payload)
