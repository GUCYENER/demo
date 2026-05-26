#!/usr/bin/env python
"""VYRA Graphify-Guard hook — PATH-AWARE PreToolUse/PostToolUse enforcer.

Amac
----
Kullanici (2026-05-26 oturumu) eski TTL-bazli "son 10dk Graphify atildi mi"
kontrolunu yetersiz buldu:
  > "okumaya sira gelince okuyorsun bilerek. duzelt hepsini grep readleri
  >  graphiden oku."

Bu nedenle bu hook yeniden tasarlandi:
- Read/Grep'in HEDEFI Graphify entities tablosunda var mi diye bakar.
- Varsa BLOCK + ilgili entity bilgisi ("su mcp__graphify__search/traverse
  cagrisini yap" yonlendirmesi).
- Yoksa ALLOW — Graphify zaten bilmiyor, Read serbest.

Modes
-----
- argv[1] == "pre"  : PreToolUse hook (Grep|Read|Glob)
- argv[1] == "post" : PostToolUse hook (mcp__graphify__*) — sadece history tutar.

Bypass
------
- env GRAPHIFY_GUARD_BYPASS=1   : tek seferlik bypass
- env GRAPHIFY_GUARD_DISABLE=1  : tum guard off (acil durum)
- state.bypass_until > now      : pencere icinde bypass
- whitelist path'leri           : .agents/, .claude/, MEMORY.md, CLAUDE.md,
                                  package.json, alembic.ini, *.toml, dist/,
                                  migrations/versions/, docs/

Graphify DB
-----------
Read-only sorgu: ~/.graphify/instances/vyra.db
- Entity match: properties LIKE '%"path": "<rel>"%' OR name = '<rel>'
- Graphify offline ise (DB yok / erisilemez) FAIL-OPEN (ALLOW + uyari).

Exit codes
----------
0 = allow (stderr -> transcript debug)
2 = block + show stderr to Claude as feedback
"""
from __future__ import annotations

import json
import os
import pathlib
import sqlite3
import sys
import time


HOOK_DIR = pathlib.Path(__file__).resolve().parent
STATE_FILE = HOOK_DIR.parent / "state" / "graphify_lock.json"
GRAPHIFY_DB = pathlib.Path(os.path.expanduser("~/.graphify/instances/vyra.db"))

# Repo root (d:/demo_vyra) — path normalizasyonu icin.
REPO_ROOT = HOOK_DIR.parent.parent.resolve()

WHITELIST_SUBSTRINGS = (
    ".agents/",
    ".claude/",
    "MEMORY.md",
    "CLAUDE.md",
    "package.json",
    "alembic.ini",
    "pyproject.toml",
    "requirements.txt",
    "settings.json",
    "settings.local.json",
    "Gecici_Dosyalar_Sil/",
    "docs/",
    "migrations/versions/",
    "frontend/dist/",
    "node_modules/",
)


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {"last_graphify_ts": 0, "history": [], "bypass_until": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"last_graphify_ts": 0, "history": [], "bypass_until": 0}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _is_whitelisted(target: str) -> bool:
    if not target:
        return False
    norm = target.replace("\\", "/")
    return any(w in norm for w in WHITELIST_SUBSTRINGS)


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}


def _live_log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _to_relative(target: str) -> str | None:
    """Normalize a path to repo-relative (forward slashes). None if not under repo."""
    if not target:
        return None
    try:
        p = pathlib.Path(target)
    except Exception:
        return None
    if p.is_absolute():
        try:
            rel = p.resolve().relative_to(REPO_ROOT)
        except Exception:
            return None
        return rel.as_posix()
    # already relative — normalize slashes
    return target.replace("\\", "/")


def _graphify_lookup(rel_path: str) -> list[dict] | None:
    """Return matching entities in Graphify DB. None if DB unavailable (fail-open).

    Match strategy:
      1) File entity where name = rel_path (exact)
      2) Function entity where properties.file = rel_path (any function in file)
    """
    if not GRAPHIFY_DB.exists():
        return None
    try:
        uri = f"file:{GRAPHIFY_DB.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=2.0)
        con.row_factory = sqlite3.Row
    except Exception:
        return None

    matches: list[dict] = []
    try:
        # 1) File entity exact match by name
        for r in con.execute(
            "SELECT id, name, type FROM entities "
            "WHERE type='File' AND name = ? LIMIT 3",
            (rel_path,),
        ):
            matches.append({"id": r["id"], "name": r["name"], "type": r["type"]})

        # 2) Function entities whose properties.file = rel_path
        like_pat = f'%"file": "{rel_path}"%'
        for r in con.execute(
            "SELECT id, name, type FROM entities "
            "WHERE type='Function' AND properties LIKE ? LIMIT 5",
            (like_pat,),
        ):
            matches.append({"id": r["id"], "name": r["name"], "type": r["type"]})
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return matches


def _block_message(
    tool_name: str, target: str, rel: str, matches: list[dict]
) -> str:
    lines = [
        "===================================================================",
        "[graphify-guard] BLOCKED — hedef Graphify'da indekslenmis",
        f"  Tool          : {tool_name}",
        f"  Target        : {target!r}",
        f"  Relative      : {rel}",
        "  Kural         : Bu dosya Graphify'da var. Once Graphify'dan oku.",
        "",
        "  Graphify entity'leri (ilk 5):",
    ]
    for m in matches[:5]:
        lines.append(f"    - [{m['type']}] {m['name']}  (id={m['id'][:8]})")
    lines += [
        "",
        "  Cozum:",
        "    mcp__graphify__search(query='<konu>', project='vyra', limit=5)",
        f"    mcp__graphify__traverse(start='{matches[0]['name']}', "
        "project='vyra', depth=2)",
        "",
        "  Acil bypass (gercekten gerekirse):",
        "    1) Bu cagrida env GRAPHIFY_GUARD_BYPASS=1",
        "    2) .agents/state/graphify_lock.json -> bypass_until = <epoch>",
        "    3) Tum guard'i kapat: env GRAPHIFY_GUARD_DISABLE=1",
        "===================================================================",
    ]
    return "\n".join(lines)


def main() -> int:
    if os.environ.get("GRAPHIFY_GUARD_DISABLE") == "1":
        return 0

    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    payload = _read_payload()
    tool_name = payload.get("tool_name", "?")
    tool_input = payload.get("tool_input", {}) or {}
    now = int(time.time())
    state = _load_state()

    if mode == "post":
        state["last_graphify_ts"] = now
        history = state.get("history") or []
        history.append({"ts": now, "tool": tool_name})
        state["history"] = history[-50:]
        _save_state(state)
        _live_log(
            f"[graphify-guard] FRESH ({tool_name}) — history yenilendi @ {now}"
        )
        return 0

    # PRE — Read / Grep / Glob
    target = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("pattern")
        or ""
    )

    # 1) Whitelist
    if _is_whitelisted(str(target)):
        _live_log(f"[graphify-guard] WHITELIST ({tool_name}) {target!r}")
        return 0

    # 2) Bypass kontrolleri
    bypass_until = int(state.get("bypass_until") or 0)
    if bypass_until and now < bypass_until:
        _live_log(
            f"[graphify-guard] BYPASS_WINDOW ({tool_name}) {target!r} "
            f"— {bypass_until - now}s kaldi"
        )
        return 0
    if os.environ.get("GRAPHIFY_GUARD_BYPASS") == "1":
        _live_log(f"[graphify-guard] ENV_BYPASS ({tool_name}) {target!r}")
        return 0

    # 3) Path-aware lookup
    rel = _to_relative(str(target))
    if rel is None:
        # Pattern-only Grep veya repo-disi path: lookup yapamiyoruz, ALLOW.
        _live_log(
            f"[graphify-guard] NO_PATH ({tool_name}) {target!r} — repo-disi/pattern, allow"
        )
        return 0

    matches = _graphify_lookup(rel)
    if matches is None:
        # Graphify offline → fail-open
        _live_log(
            f"[graphify-guard] GRAPHIFY_OFFLINE ({tool_name}) {rel} — fail-open ALLOW"
        )
        return 0

    if not matches:
        _live_log(
            f"[graphify-guard] MISS ({tool_name}) {rel} — Graphify'da yok, ALLOW"
        )
        return 0

    # Match var → BLOCK
    _live_log(_block_message(tool_name, str(target), rel, matches))
    return 2


if __name__ == "__main__":
    sys.exit(main())
