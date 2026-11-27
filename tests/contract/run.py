#!/usr/bin/env python3
"""Run the bridge contract tests.

    python3 tests/contract/run.py                   # bin/mpd-bridge
    python3 tests/contract/run.py --bridge <file>   # another bridge executable
    python3 tests/contract/run.py -k health         # only tests matching a pattern

Every test drives the bridge as a child process against the fake MPD in
tests/fakempd -- never against a real server.
"""

import argparse
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", help="bridge executable (default: bin/mpd-bridge)")
    parser.add_argument("-k", dest="pattern", action="append", help="only tests matching")
    parser.add_argument("--legacy", action="store_true",
                        help="the bridge is a copy of bin/mpd-bridge: its known differences are expected")
    parser.add_argument("-v", dest="verbose", action="store_true")
    opts = parser.parse_args()
    if opts.bridge:
        os.environ["CONTRACT_BRIDGE"] = os.path.abspath(opts.bridge)
    if opts.legacy:
        os.environ["CONTRACT_LEGACY"] = "1"
    sys.path.insert(0, HERE)
    loader = unittest.TestLoader()
    if opts.pattern:
        loader.testNamePatterns = ["*%s*" % p for p in opts.pattern]
    suite = loader.discover(HERE, pattern="test_*.py", top_level_dir=HERE)
    print("bridge under test: %s" % (os.environ.get("CONTRACT_BRIDGE") or "bin/mpd-bridge"))
    result = unittest.TextTestRunner(verbosity=2 if opts.verbose else 1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
