#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
  echo "tmux-remote-sessions: python3 is required" >&2
  exit 1
fi

exec python3 "$SCRIPT_DIR/generate_bindings.py" install
