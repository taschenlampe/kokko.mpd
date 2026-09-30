#!/bin/bash
# Everything that can be checked without a click: syntax, lint, unit tests and
# an optional smoke test against a running MPD.
#
#     tests/run.sh          everything
#     tests/run.sh --fast   without the MPD smoke test (what the hook uses)
#
# Two different kinds of "this did not run", and they must never be confused:
#   * an expected file that is not there is a broken checkout, not a reason to
#     skip -- a suite that can vanish without turning the run red is worse than
#     no suite at all, because "all green" then means nothing.
#   * an optional tool that is not installed may skip its section, but never
#     quietly: it warns and it is named in the summary line, so the result says
#     which sections did NOT run.
set -u
cd "$(dirname "$0")/.." || exit 1
FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

FAIL=0
SKIPPED=()   # optional sections that did not run; printed in the summary line
step() { printf '\n=== %s ===\n' "$1"; }
note() { printf '   %s\n' "$1"; }
bad()  { printf '   FAIL: %s\n' "$1"; FAIL=1; }
warn() { printf '   WARN: %s\n' "$1"; }
# A missing optional tool may skip a section -- but the skip has to be visible
# and it has to show up in the summary, otherwise "all green" hides what never ran.
skip() { warn "$1"; SKIPPED+=("$2"); }
join_skips() { local out="" s; for s in "$@"; do out="${out:+$out, }$s"; done; printf '%s' "$out"; }

step "py_compile (Bridge)"
if [ ! -f bin/mpd-bridge ]; then
  bad "missing file: bin/mpd-bridge"
elif python3 -m py_compile bin/mpd-bridge; then note "ok"; else bad "the bridge does not compile"; fi

step "unit tests (without MPD)"
if [ ! -f tests/test_bridge.py ]; then
  bad "missing test file: tests/test_bridge.py"
elif python3 tests/test_bridge.py; then note "ok"; else bad "unit tests failed"; fi

step "panel and bar state tests (node, no QML engine)"
# One driver per state machine. These files are *expected*: if one of them is
# gone the suite may not quietly shrink -- that fails the run.
run_state_test() {
  local T="$1"
  if [ ! -f "$T" ]; then
    bad "missing test file: $T"
    return 1
  fi
  if ! node "$T" >/dev/null; then
    bad "$T failed"
    node "$T" 2>&1 | tail -8 | sed 's/^/   /'
    return 1
  fi
  return 0
}
STATE_TESTS=(tests/test_panel_state.js tests/test_barwidget_state.js tests/test_media_surfaces.js)
if command -v node >/dev/null 2>&1; then
  # The panel's and the widget's state machines are plain functions over the QML
  # source: these tests pull them out verbatim and drive them in node. They catch
  # the class of bug neither qmllint nor the Python suite can see -- a delayed
  # handler re-deciding against a mode that changed meanwhile, a local filter
  # surviving a view switch, a failed fetch cached as "nothing there", a stale
  # fade timer hiding a card that was just shown again, a last title still shown
  # as current while the daemon is wedged (test_media_surfaces.js).
  STATE_OK=1
  for T in "${STATE_TESTS[@]}"; do
    run_state_test "$T" || STATE_OK=0
  done
  [ "$STATE_OK" -eq 1 ] && note "ok"
else
  # Without node the section cannot run -- but the files still have to be there,
  # and the skip is named in the summary instead of hiding behind "all green".
  for T in "${STATE_TESTS[@]}"; do
    [ -f "$T" ] || bad "missing test file: $T"
  done
  skip "node is not installed -- the panel/bar state tests did NOT run" "node state tests"
fi

step "runner self-check (a missing test file must fail the run)"
# Guards the guard: the check from the section above is run against a file that
# does not exist and has to set FAIL. Silenced on purpose -- it is the exit
# status that matters, not another line of noise. Without this a refactor could
# turn the rule back into a silent skip and nobody would notice until a suite
# had been gone for weeks.
if ( FAIL=0; run_state_test tests/__runner_selfcheck_missing__.js >/dev/null 2>&1; [ "$FAIL" -eq 1 ] ); then
  note "ok (a state test file that is not there fails the run)"
else
  bad "a missing state test file was swallowed again -- the suite could vanish unnoticed"
fi

step "qmllint (QML syntax)"
# Vanilla qmllint only finds Omarchy's modules through a directory trick:
# qs.Ui/qs.Commons as Ui/Commons under one include path.
QS=${TMPDIR:-/tmp}/qslint
mkdir -p "$QS/qs"
if [ -d /usr/share/omarchy/shell/Ui ]; then
  ln -sfn /usr/share/omarchy/shell/Ui "$QS/qs/Ui"
  ln -sfn /usr/share/omarchy/shell/Commons "$QS/qs/Commons"
fi
if [ -x /usr/lib/qt6/bin/qmllint ] && [ -d /usr/share/omarchy/shell/Ui ]; then
  OUT=$(/usr/lib/qt6/bin/qmllint -I "$QS" ./*.qml 2>&1)
  HITS=$(printf '%s\n' "$OUT" | grep -icE "error|\[syntax\]")
  if [ "$HITS" -gt 0 ]; then
    printf '%s\n' "$OUT" | grep -iE "error|\[syntax\]" | head -10 | sed 's/^/   /'
    bad "$HITS qmllint finding(s) -- a syntax error makes the widget vanish without a word"
  else
    note "ok (import warnings about qs.* are normal)"
  fi
else
  skip "qmllint or the Omarchy modules are missing (other machine?) -- the QML syntax was NOT checked" "qmllint"
fi

step "omarchy plugin validate"
if command -v omarchy >/dev/null 2>&1; then
  # Read the output *as well as* the exit code: on its own the code is reliable
  # (measured: rc=1 for a manifest without `kinds`, rc=0 for a good one), but the
  # text catches failures that arrive without one.
  # Beware when measuring this by hand: `$?` after a *pipeline* is the status of
  # the last element -- `validate | head | sed; echo $?` always shows 0. That is
  # exactly how this was mis-diagnosed once; use PIPESTATUS[0] or no pipeline.
  OUT=$(omarchy plugin validate . 2>&1); RC=$?
  if printf '%s' "$OUT" | grep -qiE 'invalid|missing|error|not a plugin|failed'; then
    printf '%s\n' "$OUT" | head -5 | sed 's/^/   /'
    bad "validate reported a problem (exit code was $RC -- it is 0 even for a broken manifest)"
  elif [ "$RC" -ne 0 ]; then
    printf '%s\n' "$OUT" | head -5 | sed 's/^/   /'
    bad "validate exited with $RC"
  else
    note "ok"
  fi
else
  skip "the omarchy CLI is not present here -- the plugin manifest was NOT validated" "omarchy plugin validate"
fi

if [ "$FAST" -eq 0 ]; then
  step "smoke test against MPD (optional, read-only)"
  if [ ! -f tests/smoke_mpd.py ]; then
    bad "missing test file: tests/smoke_mpd.py"
  else
    # Captured instead of streamed, so the "no MPD here" skip inside the script
    # can be told apart from a real run: it exits 0 either way, and that skip has
    # to show up in the summary as well.
    OUT=$(python3 tests/smoke_mpd.py 2>&1); RC=$?
    printf '%s\n' "$OUT"
    if [ "$RC" -ne 0 ]; then
      bad "smoke test failed"
    elif printf '%s' "$OUT" | grep -q '^   skipped: no MPD'; then
      skip "no MPD reachable -- the smoke test did NOT run" "MPD smoke test"
    else
      note "ok"
    fi
  fi
fi

printf '\n'
if [ "$FAIL" -ne 0 ]; then
  echo "FAILED"
elif [ "${#SKIPPED[@]}" -gt 0 ]; then
  echo "all green (skipped: $(join_skips "${SKIPPED[@]}"))"
else
  echo "all green"
fi
exit "$FAIL"
