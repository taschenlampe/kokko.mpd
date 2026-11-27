#!/usr/bin/env python3
"""Start a bridge for the contract tests, with test timings and a network fence.

    python3 tests/contract/launch.py <bridge-file>

The bridge file is loaded as a module (it has no .py ending, so through
SourceFileLoader) and its `main()` is called. Two things happen first:

* **The fence.** Every socket `connect` in this process is checked: only
  loopback TCP ports other than the real MPD's (6600, and $KOKKO_MPD_FENCE_PORTS)
  and unix sockets below the scratch $HOME are allowed. Anything else -- the
  user's MPD, its unix socket, the internet -- is refused as if nothing were
  listening. This matters: the old bridge dials 127.0.0.1:6600 the moment it
  starts, before the widget's first `config` line arrives, so without the fence a
  test run would talk to the user's real MPD.
* **Tuning.** The timing knobs in $KOKKO_MPD_TUNING (a JSON object, e.g.
  {"HEALTH_INTERVAL": 0.3}) are written onto the module's globals where a global
  of that name exists -- that is how the frozen old bridge, which reads no
  environment, runs with test timings. A bridge that reads its tuning from the
  environment itself sees the same variable.

The contract for a bridge executable is therefore: loadable as a module, and a
`main()` that runs the bridge and returns its exit code.
"""

import importlib.machinery
import importlib.util
import json
import os
import socket
import sys

FORBIDDEN_PORTS = {6600}
FORBIDDEN_PORTS.update(int(p) for p in (os.environ.get("KOKKO_MPD_FENCE_PORTS") or "").split(",") if p)
SCRATCH = os.path.realpath(os.environ.get("HOME", "/nonexistent"))
BLOCKED = []


def allowed(family, address) -> bool:
    if family == socket.AF_UNIX:
        if isinstance(address, bytes):
            address = address.decode("utf-8", "replace")
        if address.startswith("\0"):
            return False                       # abstract sockets: not ours
        path = os.path.realpath(address)
        return path.startswith(SCRATCH + os.sep)
    if family in (socket.AF_INET, socket.AF_INET6):
        host, port = address[0], address[1]
        return host in ("127.0.0.1", "::1") and int(port) not in FORBIDDEN_PORTS
    return False


def install_fence():
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def connect(self, address):
        if not allowed(self.family, address):
            BLOCKED.append(address)
            sys.stderr.write("contract fence: refused connect to %r\n" % (address,))
            raise ConnectionRefusedError(111, "refused by the contract test fence")
        return original(self, address)

    def connect_ex(self, address):
        if not allowed(self.family, address):
            BLOCKED.append(address)
            return 111
        return original_ex(self, address)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


def main() -> int:
    install_fence()
    path = os.path.abspath(sys.argv[1])
    loader = importlib.machinery.SourceFileLoader("kokko_mpd_bridge_under_test", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    loader.exec_module(module)
    tuning = json.loads(os.environ.get("KOKKO_MPD_TUNING") or "{}")
    for name, value in tuning.items():
        if hasattr(module, name):
            setattr(module, name, value)
    return module.main()


if __name__ == "__main__":
    sys.exit(main())
