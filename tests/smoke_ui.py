#!/usr/bin/env python3
"""Smoke test of the running panel, over the widget's own `state` channel.

Walks all eight tabs and checks what a human would otherwise have to look at:
the tab really switched, the list has rows, the selection sits inside the visible
window, the footer hint still fits (that is the check that caught five truncated
tabs once), and the widget logged no load failure.

    python3 tests/smoke_ui.py

Deliberately interactive but harmless: it opens the panel, presses the digit keys
that switch tabs, reads the state, and closes the panel again -- also when a check
fails (try/finally). It presses no key that changes playback, the queue or a
setting. No plugin installed / no shell reachable -> skipped, not failed.

Everything waits on an observable change instead of sleeping a guessed number of
seconds: the shell needs ten to fifteen seconds to come up on a slow machine, and
a test that reads too early reports a dead widget that is merely young.
"""
import json
import os
import shutil
import subprocess
import sys
import time

PLUGIN_ID = "kokko.mpd"
TABS = 8
SHELL_LOG_DIR = "/usr/share/omarchy/shell"
SETTINGS_ROWS = 20
READY_DEADLINE = 45.0     # how long the widget may take to answer after a restart
CHANGE_DEADLINE = 12.0    # how long one key press may take to show up

FAIL = 0


def step(what):
    print("\n=== %s ===" % what)


def note(what):
    print("   %s" % what)


def bad(what):
    global FAIL
    FAIL = 1
    print("   FAIL: %s" % what)


def have(tool):
    return shutil.which(tool) is not None


def ipc(*args, timeout=20):
    """One call to the plugin's IPC. Returns (rc, stdout)."""
    # No -q: it silences the answer as well, and the answer is the point here.
    cmd = ["omarchy-shell", PLUGIN_ID] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return 124, ""


def read_state(timeout=20):
    rc, out = ipc("state", timeout=timeout)
    if rc != 0 or not out.startswith("{"):
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def wait_for(predicate, deadline=CHANGE_DEADLINE, interval=0.7):
    """Poll the state until the predicate holds. Returns (state, waited_seconds)."""
    start = time.time()
    st = None
    while time.time() - start < deadline:
        st = read_state()
        if st is not None and predicate(st):
            return st, time.time() - start
        time.sleep(interval)
    return st, time.time() - start


def panel(st):
    return (st or {}).get("panel") or {}


def main():
    step("shell reachable?")
    if not have("omarchy-shell"):
        note("skipped: omarchy-shell is not on this machine")
        return 0

    # `tab <name>` opens the panel as a side effect: the least invasive way in
    # (no click, no playback, no setting).
    opened = False
    try:
        rc, _ = ipc("tab", "settings")
        if rc != 0:
            note("skipped: the plugin does not answer (installed and enabled?)")
            return 0

        st, waited = wait_for(lambda s: s.get("panelOpen") is True, deadline=READY_DEADLINE)
        if st is None or not st.get("panelOpen"):
            bad("the widget did not open a panel within %.0f s (still starting? then re-run)" % READY_DEADLINE)
            return 1
        opened = True
        note("panel open after %.1f s" % waited)
        if not st.get("connected"):
            note("note: MPD is not connected -- the lists may be legitimately empty")
        note("connected=%s  volume=%s  state=%s  look=%s" % (
            st.get("connected"), st.get("volume"), st.get("state"), st.get("look")))

        step("walk all %d tabs" % TABS)
        seen = []
        for n in range(1, TABS + 1):
            before = str(panel(read_state()).get("tab") or "")
            rc, _ = ipc("key", str(n))
            if rc != 0:
                bad("key %d was not accepted" % n)
                continue

            # Two things have to settle before the state is worth judging: the tab
            # switch itself, and -- on the queue, where the selection is the playing
            # track -- the list scrolling that row into view. Measured: that scroll
            # finishes a moment after the tab is already there, so demanding it in
            # the same breath was a false alarm of this test.
            def settled(s):
                p = panel(s)
                if str(p.get("tab") or "") == before:
                    return False
                rows = p.get("rows") or 0
                if not rows:
                    return True
                vis = p.get("visible") or {}
                if vis.get("first") is None:
                    return True
                return vis["first"] <= (p.get("sel") or 0) <= vis["last"]

            st, waited = wait_for(settled, deadline=CHANGE_DEADLINE)
            p = panel(st)
            tab = str(p.get("tab") or "")
            if tab == before:
                bad("key %d did not switch the tab (still %r after %.1f s)" % (n, tab, waited))
            rows = p.get("rows")
            sel = p.get("sel")
            vis = p.get("visible") or {}
            hint = str(p.get("hint") or "")
            trunc = p.get("hintTruncated")

            seen.append(tab)
            note("%d  %-10s Zeilen %-6s Auswahl %-4s sichtbar %s-%s  %s" % (
                n, tab, rows, sel, vis.get("first"), vis.get("last"),
                "Hinweis gekuerzt!" if trunc else ""))

            if not tab:
                bad("tab %d: no name reported" % n)
            if not p.get("frameTitle"):
                bad("tab %s: no frame title" % tab)
            if rows is None:
                bad("tab %s: no row count" % tab)
            if trunc:
                bad("tab %s: the footer hint is cut off" % tab)
            if not hint:
                bad("tab %s: the footer hint is empty" % tab)
            if rows:
                if not (0 <= (sel or 0) < rows):
                    bad("tab %s: selection %s outside 0..%s" % (tab, sel, rows - 1))
                if vis.get("first") is not None and not (vis["first"] <= (sel or 0) <= vis["last"]):
                    bad("tab %s: selection %s is not in the visible window %s-%s" % (
                        tab, sel, vis.get("first"), vis.get("last")))
                if not (vis.get("h") or 0) > 0:
                    bad("tab %s: the list has no room (h=%s)" % (tab, vis.get("h")))

        if len(set(seen)) != TABS:
            bad("%d tabs answered, but the names repeat: %s" % (TABS, ", ".join(seen)))
        else:
            note("all %d answered, names distinct" % TABS)

        step("settings tab: grouping, and the footer that must not be cut")
        rc, _ = ipc("key", "8")
        st, waited = wait_for(lambda s: str(panel(s).get("tab")) == "settings")
        p = panel(st)
        if str(p.get("tab")) != "settings":
            bad("key 8 did not land on the settings tab")
        else:
            rows = p.get("rows")
            peek = p.get("peek") or []
            sel = p.get("sel")
            note("Zeilen %s, Auswahl %s, Hinweis gekuerzt: %s" % (rows, sel, p.get("hintTruncated")))
            note("die ersten: %s" % ", ".join(peek))
            if rows != SETTINGS_ROWS:
                bad("expected %d rows (6 headers + 14 settings), got %s" % (SETTINGS_ROWS, rows))
            if sel != 1:
                bad("the selection should skip the first header and land on row 1, got %s" % sel)
            if not peek or not peek[0].startswith("header|"):
                bad("the first row is not a header")
            if any(z.endswith("|") for z in peek):
                bad("a row has an empty title: %s" % peek)

        step("regressions in the log?")
        if have("qs") and os.path.isdir(SHELL_LOG_DIR):
            try:
                r = subprocess.run(["qs", "log", "-p", SHELL_LOG_DIR], capture_output=True, text=True, timeout=30)
                hits = [l for l in (r.stdout or "").splitlines() if "kokko.mpd failed" in l]
                if hits:
                    for h in hits[-3:]:
                        print("   %s" % h.strip()[:150])
                    bad("%d load failure(s) for the widget in the log" % len(hits))
                else:
                    note("ok -- no 'kokko.mpd failed' in the log")
            except subprocess.TimeoutExpired:
                note("skipped: qs log did not answer")
        else:
            note("skipped: no qs log here (other machine?)")

    finally:
        if opened:
            ipc("close")
            st, waited = wait_for(lambda s: s.get("panelOpen") is False, deadline=CHANGE_DEADLINE)
            if st is not None and st.get("panelOpen"):
                bad("the panel is still open after the test")
            else:
                note("panel closed again (%.1f s)" % waited)

    return FAIL


if __name__ == "__main__":
    print("   Smoke test of the panel -- it opens the panel for a few seconds.")
    sys.exit(main())
