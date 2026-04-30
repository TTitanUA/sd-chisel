#!/usr/bin/env bash
# Run backend (uvicorn) and frontend (Vite) in parallel with merged stdout.
# Each line is prefixed with [be]/[fe]. Ctrl+C stops both.
# Implementation lives in dev.mjs (cross-platform).
set -e
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec node "$script_dir/dev.mjs" "$@"
