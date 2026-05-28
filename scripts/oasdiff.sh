#!/usr/bin/env bash
# VYRA — OpenAPI breaking-change gate wrapper (KAP 5).
#
# Generates a fresh snapshot in /tmp and compares it against the
# checked-in docs/openapi_snapshot.json using oasdiff. Exits 1 if any
# breaking change is detected (oasdiff's own --fail-on ERR).
#
# Bootstrap state (v3.39.0): oasdiff is a Go binary released by Tufin
# at https://github.com/oasdiff/oasdiff. CI installs it via the official
# action; locally either install the binary or run via Docker:
#
#   docker run --rm -v "$PWD":/repo tufin/oasdiff \
#       breaking /repo/docs/openapi_snapshot.json /repo/.tmp/openapi_new.json
#
# This wrapper picks the binary if it's on PATH, falls back to the
# Docker invocation otherwise, and surfaces oasdiff's own exit code.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT="${REPO_ROOT}/docs/openapi_snapshot.json"
WORK_DIR="${REPO_ROOT}/.tmp"
NEW_SPEC="${WORK_DIR}/openapi_new.json"

mkdir -p "$WORK_DIR"

if [[ ! -f "$SNAPSHOT" ]]; then
  echo "[oasdiff] base snapshot missing: $SNAPSHOT" >&2
  echo "[oasdiff] run scripts/openapi_snapshot.py first" >&2
  exit 1
fi

# Pick a Python interpreter the same way the graphify guard does so this
# wrapper works from WSL and native Windows Git Bash alike.
PY="${VYRA_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if command -v python3 >/dev/null 2>&1; then PY="$(command -v python3)";
  elif command -v python >/dev/null 2>&1; then PY="$(command -v python)";
  else
    echo "[oasdiff] no python interpreter found" >&2
    exit 2
  fi
fi

# Generate a fresh spec on the side; the snapshot itself is untouched.
"$PY" - <<'PY' > "$NEW_SPEC"
import json, os, sys
sys.path.insert(0, os.environ["REPO_ROOT"])
os.environ.setdefault("VYRA_OPENAPI_SNAPSHOT", "1")
from app.api.main import app
print(json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False))
PY

run_oasdiff() {
  if command -v oasdiff >/dev/null 2>&1; then
    oasdiff breaking "$SNAPSHOT" "$NEW_SPEC" --fail-on ERR
    return $?
  fi
  if command -v docker >/dev/null 2>&1; then
    docker run --rm \
      -v "$SNAPSHOT":/base.json:ro \
      -v "$NEW_SPEC":/head.json:ro \
      tufin/oasdiff breaking /base.json /head.json --fail-on ERR
    return $?
  fi
  echo "[oasdiff] neither oasdiff nor docker is installed" >&2
  echo "[oasdiff] install: https://github.com/oasdiff/oasdiff#installation" >&2
  return 3
}

REPO_ROOT="$REPO_ROOT" run_oasdiff
rc=$?
if [[ $rc -ne 0 ]]; then
  echo "[oasdiff] breaking changes detected (exit=$rc)" >&2
  echo "[oasdiff] either move to /v2 namespace or document a >=1 minor deprecation" >&2
fi
exit $rc
