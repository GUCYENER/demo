#!/usr/bin/env python
"""VYRA — Generate / refresh the OpenAPI contract snapshot (KAP 5).

The snapshot lives at docs/openapi_snapshot.json and is the input to the
oasdiff breaking-change gate (vyrazeus §8 KAP 5). Whenever an endpoint
shape changes, run this script and commit the updated JSON alongside the
endpoint change — that way the diff itself is reviewable.

Usage
-----
From the repo root:

    python scripts/openapi_snapshot.py            # write docs/openapi_snapshot.json
    python scripts/openapi_snapshot.py --check    # exit 1 if on-disk snapshot is stale

CI integration
--------------
The `--check` mode is what the audit job in `.github/workflows/ci.yml`
runs to catch endpoints that were edited without refreshing the snapshot.
For breaking-change detection (additive vs. breaking), the oasdiff tool
takes over — see scripts/oasdiff.sh.

Why a script and not a fixture
------------------------------
FastAPI's `app.openapi()` walks every registered route at startup. We
don't want that cost in CI's hot path on every test, so we cache the
result in a checked-in JSON file and only rebuild on demand.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = REPO_ROOT / "docs" / "openapi_snapshot.json"


def build_openapi() -> dict:
    # Late import keeps the script usable from a thin Python env when only
    # `--check` is needed against an existing snapshot (lint/audit shells).
    sys.path.insert(0, str(REPO_ROOT))
    os.environ.setdefault("VYRA_OPENAPI_SNAPSHOT", "1")
    from app.api.main import app  # noqa: E402
    return app.openapi()


def normalise(spec: dict) -> str:
    # Sort keys + 2-space indent so the diff is line-stable. trailing
    # newline keeps POSIX text-file etiquette and matches what `Write`
    # produces, so the file round-trips cleanly.
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Don't write; exit 1 if the on-disk snapshot is out of sync.",
    )
    args = parser.parse_args()

    current = normalise(build_openapi())

    if args.check:
        if not SNAPSHOT_PATH.exists():
            print(f"[openapi_snapshot] missing: {SNAPSHOT_PATH}", file=sys.stderr)
            return 1
        on_disk = SNAPSHOT_PATH.read_text(encoding="utf-8")
        if on_disk != current:
            print(
                "[openapi_snapshot] STALE — endpoint shape changed but "
                "docs/openapi_snapshot.json was not refreshed.\n"
                "Run: python scripts/openapi_snapshot.py",
                file=sys.stderr,
            )
            return 1
        print("[openapi_snapshot] up to date")
        return 0

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(current, encoding="utf-8")
    print(f"[openapi_snapshot] wrote {SNAPSHOT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
