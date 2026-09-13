#!/bin/bash
# Alles, was sich ohne Klick pruefen laesst: Syntax, Lint, Unit-Tests und ein
# optionaler Rauchtest gegen ein laufendes MPD.
#
#     tests/run.sh          alles
#     tests/run.sh --fast   ohne MPD-Rauchtest (fuer den pre-commit-Hook)
set -u
cd "$(dirname "$0")/.." || exit 1
FAST=0
[ "${1:-}" = "--fast" ] && FAST=1

FAIL=0
step() { printf '\n=== %s ===\n' "$1"; }
note() { printf '   %s\n' "$1"; }
bad()  { printf '   FEHLER: %s\n' "$1"; FAIL=1; }

step "py_compile (Bridge)"
if python3 -m py_compile bin/mpd-bridge; then note "ok"; else bad "die Bridge laesst sich nicht uebersetzen"; fi

step "Unit-Tests (ohne MPD)"
if python3 tests/test_bridge.py; then note "ok"; else bad "Unit-Tests fehlgeschlagen"; fi

step "qmllint (QML-Syntax)"
# Vanilla-qmllint findet Omarchys Module nur ueber einen Verzeichnis-Trick:
# qs.Ui/qs.Commons als Ui/Commons unter einem Include-Pfad.
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
    bad "$HITS qmllint-Befund(e) -- ein Syntaxfehler laesst das Widget wortlos verschwinden"
  else
    note "ok (Import-Warnungen zu qs.* sind normal)"
  fi
else
  note "uebersprungen: qmllint oder die Omarchy-Module fehlen (andere Maschine?)"
fi

step "omarchy plugin validate"
if command -v omarchy >/dev/null 2>&1; then
  if omarchy plugin validate . >/dev/null 2>&1; then note "ok"; else bad "validate meldet ein Problem"; fi
else
  note "uebersprungen: die omarchy-CLI gibt es hier nicht"
fi

if [ "$FAST" -eq 0 ]; then
  step "Rauchtest gegen MPD (optional, nur lesend)"
  if python3 tests/smoke_mpd.py; then note "ok"; else bad "Rauchtest fehlgeschlagen"; fi
fi

printf '\n'
if [ "$FAIL" -eq 0 ]; then echo "alles gruen"; else echo "FEHLGESCHLAGEN"; fi
exit "$FAIL"
