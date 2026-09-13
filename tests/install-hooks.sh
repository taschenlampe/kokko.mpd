#!/bin/bash
# Git cannot version hooks, so this points the clone at .githooks/ (needed
# once per clone).
set -eu
cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
chmod +x .githooks/* tests/*.sh tests/*.py 2>/dev/null || true
echo "core.hooksPath = $(git config --get core.hooksPath)"
echo "aktive Hooks:   $(ls .githooks | tr '\n' ' ')"
