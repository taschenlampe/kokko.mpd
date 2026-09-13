#!/bin/bash
# Git kann Hooks nicht versionieren, also zeigt dieser Aufruf den Klon auf
# .githooks/ (einmal pro Klon noetig).
set -eu
cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
chmod +x .githooks/* tests/*.sh tests/*.py 2>/dev/null || true
echo "core.hooksPath = $(git config --get core.hooksPath)"
echo "aktive Hooks:   $(ls .githooks | tr '\n' ' ')"
