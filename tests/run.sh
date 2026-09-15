#!/bin/bash
# Everything that can be checked without a click: syntax, lint, unit tests and
# an optional smoke test against a running MPD.
#
#     tests/run.sh          everything
#     tests/run.sh --fast   without the MPD smoke test (what the hook uses)
set -u
cd "$(dirname "$0")/.." || exit 1
FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

FAIL=0
step() { printf '\n=== %s ===\n' "$1"; }
note() { printf '   %s\n' "$1"; }
bad()  { printf '   FAIL: %s\n' "$1"; FAIL=1; }

step "py_compile (Bridge)"
if python3 -m py_compile bin/mpd-bridge; then note "ok"; else bad "the bridge does not compile"; fi

step "unit tests (without MPD)"
if python3 tests/test_bridge.py; then note "ok"; else bad "unit tests failed"; fi

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
  note "skipped: qmllint or the Omarchy modules are missing (other machine?)"
fi

step "consistency (manifest, panel keys against the schema, escapes)"
if python3 tests/check_consistency.py; then note "ok"; else bad "consistency checks failed"; fi

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
  note "skipped: the omarchy CLI is not present here"
fi

if [ "$FAST" -eq 0 ]; then
  step "smoke test against MPD (optional, read-only)"
  if python3 tests/smoke_mpd.py; then note "ok"; else bad "smoke test failed"; fi

  # Opens the panel for a moment, so it does not belong in --fast (the hook): a
  # panel that flashes open on every commit is worse than the check is worth.
  step "UI smoke test (walks all tabs, needs the running shell)"
  if command -v omarchy-shell >/dev/null 2>&1; then
    if python3 tests/smoke_ui.py; then note "ok"; else bad "the panel smoke test failed"; fi
  else
    note "skipped: no omarchy-shell here (other machine?)"
  fi
fi

printf '\n'
if [ "$FAIL" -eq 0 ]; then echo "all green"; else echo "FAILED"; fi
exit "$FAIL"
