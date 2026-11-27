"""The numbers that decide how patient the bridge is.

Defaults are the production values. The contract tests set
$KOKKO_MPD_TUNING to a JSON object (e.g. {"HEALTH_INTERVAL": 0.3}) to run the
same code with test timings; unknown names in it are ignored, values of the
wrong type are ignored too (the default stays).
"""

from __future__ import annotations

import json
import os


class Tuning:
    CONNECT_TIMEOUT = 5.0      # dialling + greeting
    CMD_TIMEOUT = 10.0         # one reply on the command / query connection
    CMD_IDLE_RENEW = 45.0      # replace the command socket after this long unused
    MIN_ROUND_ALIVE = 5.0      # a round shorter than this counts as a failed connect
    BACKOFF_FIRST = 1.0
    BACKOFF_MAX = 15.0
    REFRESH_MIN_GAP = 0.1      # between two status reads of one burst
    HEALTH_INTERVAL = 20.0     # greeting probe period
    HEALTH_TIMEOUT = 3.0       # how long the probe waits for the greeting
    HEALTH_FAILS = 2           # misses in a row before "not answering"
    BINARY_CHUNK = 256 * 1024  # binarylimit asked for on query/art connections
    RADIO_API = "https://all.api.radio-browser.info"
    RADIO_TIMEOUT = 8.0
    RADIO_GRACE = 2.0

    def __init__(self, overrides: dict | None = None):
        for name, value in (overrides or {}).items():
            default = getattr(type(self), name, None)
            if default is None or name.startswith("_"):
                continue
            if isinstance(default, bool) or not isinstance(value, type(default)):
                if not (isinstance(default, float) and isinstance(value, int)):
                    continue
            setattr(self, name, type(default)(value))


def from_environment() -> Tuning:
    try:
        overrides = json.loads(os.environ.get("KOKKO_MPD_TUNING") or "{}")
    except ValueError:
        overrides = {}
    return Tuning(overrides if isinstance(overrides, dict) else {})


T = from_environment()
