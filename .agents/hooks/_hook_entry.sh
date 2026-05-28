#!/usr/bin/env bash
# VYRA Graphify-Guard hook entry — delegates to graphify_guard.py.
#
# Wired from .claude/settings.json:
#   PreToolUse  (Grep|Read|Glob)        → this script "pre"
#   PostToolUse (mcp__graphify__.*)     → this script "post"
#
# Reads JSON payload on stdin (forwarded as-is to the Python guard),
# resolves a working Python interpreter, exits with the guard's exit code
# (0 = allow, 2 = block, other = fail-open with stderr to transcript).
#
# Resolution order for the Python interpreter:
#   1. $VYRA_PYTHON env (explicit override — useful in CI / sandboxes)
#   2. repo-local Windows venv (./python/Scripts/python.exe) — works from WSL via /mnt path
#   3. python3 in PATH
#   4. python  in PATH
# If none is found we fail-open (exit 0) so the harness never wedges
# because of a broken interpreter; the Python guard itself also fails open
# whenever the Graphify DB is missing.
set -u

MODE="${1:-pre}"
HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD="${HOOK_DIR}/graphify_guard.py"

if [[ ! -f "$GUARD" ]]; then
  echo "[graphify-guard] guard script missing: $GUARD — fail-open ALLOW" >&2
  exit 0
fi

is_wsl() {
  [[ -r /proc/version ]] && grep -qiE 'microsoft|wsl' /proc/version
}

resolve_python() {
  if [[ -n "${VYRA_PYTHON:-}" ]] && command -v "$VYRA_PYTHON" >/dev/null 2>&1; then
    printf '%s\n' "$VYRA_PYTHON"; return 0
  fi
  # Under WSL, prefer Linux-native python3 — the repo-local python.exe is
  # a Windows-native binary and mangles POSIX `/mnt/...` paths.
  if is_wsl && command -v python3 >/dev/null 2>&1; then
    command -v python3; return 0
  fi
  local repo_root local_py
  repo_root="$(cd "$HOOK_DIR/../.." && pwd)"
  local_py="$repo_root/python/Scripts/python.exe"
  if [[ -x "$local_py" ]]; then
    printf '%s\n' "$local_py"; return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3; return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python; return 0
  fi
  return 1
}

PY="$(resolve_python)" || {
  echo "[graphify-guard] no python interpreter found — fail-open ALLOW" >&2
  exit 0
}

exec "$PY" "$GUARD" "$MODE"
