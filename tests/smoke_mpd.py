#!/usr/bin/env python3
"""Rauchtest gegen ein laufendes MPD: startet die Bridge, prueft Antwort, Cover
und den Filterausdruck mit echten Sonderzeichen-Titeln.

    python3 tests/smoke_mpd.py

Bewusst sanft und nur lesend: gefragt werden `status`/`currentsong`/`list album`,
geschrieben wird in einen eigenen Cache (`XDG_CACHE_HOME` umgelenkt), die Queue
bleibt unberuehrt. Kein MPD erreichbar -> uebersprungen, nicht fehlgeschlagen.

Wichtig fuer den Bridge-Teil: stdin muss **offen bleiben**. Wird es sofort
geschlossen, beendet sich die Bridge bei EOF, bevor sie geantwortet hat.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(ROOT, "bin", "mpd-bridge")
HOST, PORT = "127.0.0.1", 6600
META = "+()[]{}*?.'&/"


def load_bridge():
    loader = importlib.machinery.SourceFileLoader("bridge_smoke", BRIDGE)
    spec = importlib.util.spec_from_loader("bridge_smoke", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def raw(command, wait=0.9):
    """One command against MPD, the protocol way (filters stay one argument)."""
    try:
        sock = socket.create_connection((HOST, PORT), 4)
    except OSError:
        return ""
    try:
        sock.recv(64)
        sock.sendall((command + "\n").encode())
        time.sleep(wait)
        sock.setblocking(False)
        data = b""
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
                if b"\nOK\n" in data or data.startswith(b"ACK"):
                    break
        except BlockingIOError:
            pass
        return data.decode("utf-8", "replace")
    finally:
        sock.close()


def reachable():
    try:
        sock = socket.create_connection((HOST, PORT), 3)
        ok = sock.recv(64).startswith(b"OK MPD")
        sock.close()
        return ok
    except OSError:
        return False


def wire(expr):
    """The protocol layer the bridge's quote() applies."""
    return '"' + expr.replace("\\", "\\\\").replace('"', '\\"') + '"'


def values(reply, key):
    return [line[len(key) + 2:] for line in reply.splitlines() if line.startswith(key + ": ")]


def bridge_run(cache, uri):
    script = 'config {"host":"%s","port":%d,"password":""}\n' % (HOST, PORT)
    if uri:
        script += 'art "%s"\n' % uri.replace("\\", "\\\\").replace('"', '\\"')
    proc = subprocess.Popen(["python3", BRIDGE], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env=dict(os.environ, XDG_CACHE_HOME=cache))
    proc.stdin.write(script.encode())
    proc.stdin.flush()
    time.sleep(6)                     # stdin offen halten, sonst EOF-Abbruch
    try:
        proc.stdin.close()
    except OSError:
        pass
    # No communicate() here: stdin was closed by hand, and it would try to flush it
    # again. The output is a handful of lines, so wait-then-read cannot deadlock.
    try:
        proc.wait(timeout=12)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    out = proc.stdout.read()
    err = proc.stderr.read()
    return proc.returncode, out, err


def main():
    if not reachable():
        print("   uebersprungen: kein MPD auf %s:%d" % (HOST, PORT))
        return 0

    failed = 0
    uri = ""
    current = raw("currentsong")
    if values(current, "file"):
        uri = values(current, "file")[0]

    print("=== Bridge starten, Status abfragen%s ===" % (", Cover holen" if uri else ""))
    cache = tempfile.mkdtemp(prefix="mpd-smoke-")
    try:
        code, out, err = bridge_run(cache, uri)
        events = []
        for line in out.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
        kinds = [e.get("event") for e in events if e.get("event")]
        print("   Prozess beendet mit %s | Ereignisse: %s" % (code, ", ".join(kinds) or "keine"))
        if "state" not in kinds:
            print("   FEHLER: kein state-Ereignis -- die Bridge hat nicht geantwortet")
            if err.strip():
                print("   stderr: %s" % err.decode("utf-8", "replace").strip().splitlines()[-1][:140])
            failed = 1
        elif b"Traceback" in err:
            print("   FEHLER: Traceback im stderr")
            failed = 1
        art = [e for e in events if e.get("event") == "art"]
        if uri and art:
            path = art[-1].get("path") or ""
            if path and os.path.isfile(path) and os.path.getsize(path) > 0:
                print("   Cover: %d Bytes (%s)" % (os.path.getsize(path), os.path.basename(path)))
            else:
                print("   Hinweis: art ohne brauchbare Datei (%r)" % path[:60])
        elif uri:
            print("   Hinweis: kein art-Ereignis fuer %r (Lied ohne Cover?)" % uri[:60])
    finally:
        shutil.rmtree(cache, ignore_errors=True)

    print("=== Filterausdruck gegen echte Sonderzeichen-Titel ===")
    module = load_bridge()
    albums = values(raw("list album"), "Album")
    candidates = [a for a in albums if any(ch in a for ch in META)][:6]
    if not candidates:
        print("   uebersprungen: kein Album mit Sonderzeichen in der Bibliothek")
    hits = 0
    for name in candidates:
        expr = module.contains_expression("album", name)
        found = values(raw("list album " + wire(expr)), "Album")
        hit = name in found
        hits += 1 if hit else 0
        print("   %-44s %s" % (name[:44], "getroffen" if hit else "NICHT getroffen"))
    if candidates and hits != len(candidates):
        print("   FEHLER: %d von %d Sonderzeichen-Titeln wurden nicht gefunden" %
              (len(candidates) - hits, len(candidates)))
        failed = 1

    if failed:
        return 1
    print("   ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
