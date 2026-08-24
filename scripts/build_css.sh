#!/usr/bin/env bash
# Rebuilds printme/static/css/output.css from printme/static/src/input.css
# using the Tailwind standalone CLI (tailwindcss-linux-x64, repo root -
# not committed, not on the internet dependency path: this is a dev-time
# build step only, the compiled output.css is what actually ships).
#
# Linux/macOS companion to build_css.ps1, for dev-container/non-Windows
# sessions.
#
# Usage: scripts/build_css.sh [--watch]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAILWIND="$REPO_ROOT/tailwindcss-linux-x64"
INPUT="$REPO_ROOT/printme/static/src/input.css"
OUTPUT="$REPO_ROOT/printme/static/css/output.css"

if [ ! -x "$TAILWIND" ]; then
  echo "tailwindcss-linux-x64 not found (or not executable) at $TAILWIND - download the" >&2
  echo "standalone CLI from https://github.com/tailwindlabs/tailwindcss/releases and" >&2
  echo "place it at the repo root, then chmod +x it." >&2
  exit 1
fi

args=(-i "$INPUT" -o "$OUTPUT")
if [ "${1:-}" = "--watch" ]; then
  args+=(--watch)
fi

"$TAILWIND" "${args[@]}"
