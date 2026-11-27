"""The bridge process: stdin lines in, JSON events out.

Phase 2 placeholder -- the protocol layer exists, the connection and state
layers come in phase 3. Until then this reads stdin to EOF and exits 0, so the
entry point and the launcher can be exercised, and says on stderr that it is
not a bridge yet.
"""

import sys


def main() -> int:
    sys.stderr.write("kokko_mpd: not implemented yet (phase 2: protocol layer only)\n")
    sys.stderr.flush()
    for _line in sys.stdin:
        pass
    return 0
