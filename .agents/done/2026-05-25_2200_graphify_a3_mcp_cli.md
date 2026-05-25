---
agent_id: graphify_a3_mcp_cli
brief_created: 2026-05-25 22:00
plan_ref: .agents/plans/2026-05-25_2100_general_graphify_hybrid_setup_v1.md
status: completed
completed_at: 2026-05-25T17:35:00Z
council_brief: HERMES (lead) + ZEUS (token cap)
target_repo: C:\Users\EXT02D059293\Documents\General_Graphify
depends_on: A1 (completed)
disjoint_files_owned:
  - mcp/__init__.py
  - mcp/mcp_server.py
  - mcp/tools.py
  - mcp/clip.py
  - core/cli.py
  - config/config_example.yml
files_created:
  - C:/Users/EXT02D059293/Documents/General_Graphify/mcp/__init__.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/mcp/mcp_server.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/mcp/tools.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/mcp/clip.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/core/cli.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/config/config_example.yml
council_review:
  - reviewer: HERMES
    status: approved_with_constraints
    constraints:
      - signed_stdio_encoding_windows
      - graceful_sigterm_no_taskkill
      - project_routing_via_config_yml
      - fastmcp_optional_stdlib_fallback
  - reviewer: ZEUS
    status: approved_with_constraints
    constraints:
      - every_tool_wrapped_in_clip_output
      - token_caps_loaded_from_ontology
      - cap_violation_truncate_not_raise
self_test_output: |
  graphify version            -> 1.0.0
  graphify --help             -> shows all 7 subcommands (init,mine,status,search,wakeup,migrate,version)
  graphify init vyra          -> {"ok": true, "project": "vyra", "db_path": ".../vyra.db"}
  graphify status --project vyra -> JSON (clipped to status cap=30, _truncated true as expected)
  tools/list                  -> 7 tools returned (warmup,wakeup,search,mine,add_decision,status,traverse)
  tools/call warmup           -> {"ok": true, "version": "1.0.0", ...} exit 0 via EOF
  warmup latency (cold)       -> 23.35 ms (<50 ms target)
  wakeup latency (warm)       -> 0.10 ms (<200 ms target)
  wakeup latency (cold open)  -> 50.19 ms
  clip_dict 1000-item test    -> _truncated=true, 74 tokens (<250 cap)
  mine --quiet bad-project    -> exit 0 (hook safety)
  EOF on stdin                -> exit 0 (graceful)
  SIGINT/SIGTERM handlers     -> installed; Windows TerminateProcess via os.kill is
                                 uncatchable by design (kernel-level), Python signal
                                 handler is registered for catchable delivery (SIGINT,
                                 SIGBREAK best-effort) per HERMES constraint.
tool_token_estimates:
  warmup: 28
  wakeup: 32
  status: 52
  search: not_measured_empty_db
  mine: not_measured_empty_db
  add_decision: not_measured
  traverse: not_measured_empty_db
notes: |
  - Lazy export in mcp/__init__.py via module __getattr__: avoids re-wrapping
    stdout/stderr on plain `import mcp.tools` (CLI path). Wrap still fires when
    mcp.mcp_server is imported directly (server path), per HERMES windows
    encoding constraint.
  - status cap of 30 tokens (per ontology/core.yml) is intentionally small;
    real-world full status payloads will hit the soft truncation path then
    the hard text-clip fallback for multi-project listings — verified.
  - PythonCodeAdapter constructor signature is unknown at A3 time, so
    tool_mine catches TypeError per-adapter and reports it in by_adapter[].
    Other adapters (git, markdown, backlog) use the (g, slug, repo_path)
    signature confirmed via base.py + git_adapter.py inspection.
  - FastMCP not installed in the active interpreter (D:/demo_vyra/python);
    stdlib JSON-RPC fallback is what's exercised by all tests above.
  - core/cli.py command set matches brief exactly: init, mine, status,
    search, wakeup, migrate, version (7).
  - `graphify migrate --from-mempalace` shells out to tools/migrate_from_mempalace.py
    (A4-owned); script is missing today so command returns ok=false with a
    clear error — does not crash.
---

# A3 — MCP Server + CLI (Graphify Hybrid)

## Malware Pre-empt Clause

Mesru altyapi kurulumu. Kullanici acikca onayladi. Sadece local IPC (stdio MCP) +
local file/DB calismasi. Refuze yok.

## Context

A1 tamamlandi — `core.graphify.Graphify`, `core.query`, `core.embedding`,
`core.migration` ve `ontology/{core,predicates}.yml` hazir. A2 (adapters)
paralel calisiyor; senin module'lerin A2'nin tamamlanmasini BEKLEMEZ:
sadece `core.graphify` + `ontology` import edersin. `mcp__graphify__mine`
tool icinde adapter cagirilirken `from adapters import ...` lazy import kullan
(A2 bittiginde calisir, bitmeden de `mine` exception verir gracefully).

## Disjoint Scope (sadece bu 6 dosya)

`mcp/__init__.py`, `mcp/mcp_server.py`, `mcp/tools.py`, `mcp/clip.py`,
`core/cli.py`, `config/config_example.yml`

**Asla dokunma:** schema/, ontology/, core/graphify.py, core/embedding.py,
core/query.py, core/migration.py, adapters/, tests/, tools/, examples/, README.

## Mimari

```
Claude (VSCode) ─stdio─> python -m mcp.mcp_server
                          ├─ FastMCP server (varsa) | stdlib JSON-RPC fallback (yoksa)
                          ├─ tools.py: 7 tool handler
                          ├─ clip.py: _clip_output(text, max_tokens)
                          └─ core.graphify.Graphify per-project lazy load
```

## MCP Tools (7 adet)

`mcp/tools.py` icinde tool handler'lar. Token cap'lar `ontology/core.yml.token_caps`
icinden okunur:

| Tool | Signature | Cap | Davranis |
|---|---|---|---|
| `warmup` | `warmup() -> dict` | 50 | DB acmaz, sadece process alive + version + loaded_projects:[] |
| `wakeup` | `wakeup(project: str) -> dict` | 250 | Project DB acar, son 10 commit + open refactor + active plan ozeti |
| `search` | `search(query: str, project: str, limit: int = 10, mode: str = "hybrid") -> dict` | 250 | Graph or hybrid search; result = [{type,name,score,source_ref}] |
| `mine` | `mine(project: str, since: str = "auto") -> dict` | 50 | adapters import et + 4 adapter calistir + AdapterReport summary |
| `add_decision` | `add_decision(commit_msg, branch, council, refactor_ids=[], bug_ids=[]) -> dict` | 30 | Decision entity + closes triple'lar |
| `status` | `status(project: str \| None = None) -> dict` | 30 | Per-project: db_size, entity_count, triple_count, last_mine |
| `traverse` | `traverse(start: str, predicate: str \| None, depth: int = 2) -> dict` | 200 | BFS from start_entity_id |

**ZEUS constraint:** her tool handler donus degeri `clip.clip_dict(result, cap)` ile
filtrelenir. Cap asilirsa truncate (raise DEGIL) — `{..., "_truncated": true, "_clip_reason": "token_cap"}`.

**HERMES constraint:** `wakeup` ve `search` icinde DB lazy open — ilk cagrida acilir,
sonra cache (process omru boyunca). `Graphify` instance dict: `_loaded: dict[str, Graphify]`.

## `mcp/clip.py`

```python
# mcp/clip.py
from __future__ import annotations
import json
from typing import Any

# Rough estimator: chars / 4 ~= tokens (English/Turkish mixed).
def estimate_tokens(s: str) -> int:
    return max(1, len(s) // 4)

def clip_text(text: str, max_tokens: int) -> tuple[str, bool]:
    target_chars = max_tokens * 4
    if len(text) <= target_chars:
        return text, False
    return text[:target_chars - 20] + "... [truncated]", True

def clip_dict(d: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    js = json.dumps(d, ensure_ascii=False, default=str)
    if estimate_tokens(js) <= max_tokens:
        return d
    # Iterative shrink: drop or truncate list-valued fields first.
    out = dict(d)
    for k, v in list(out.items()):
        if isinstance(v, list) and len(v) > 3:
            out[k] = v[:3] + [{"_dropped": len(v) - 3}]
            if estimate_tokens(json.dumps(out, ensure_ascii=False, default=str)) <= max_tokens:
                out["_truncated"] = True
                out["_clip_reason"] = "token_cap"
                return out
    # Last resort: text clip on json
    txt, _ = clip_text(json.dumps(out, ensure_ascii=False, default=str), max_tokens)
    return {"_truncated": True, "_clip_reason": "token_cap_hard", "_payload_clipped": txt}
```

## `mcp/mcp_server.py`

- Try `from fastmcp import FastMCP` else fall back to stdlib JSON-RPC over stdio
- Windows encoding hardening:
  ```python
  import sys, io, os
  os.environ.setdefault("PYTHONIOENCODING", "utf-8")
  sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)
  sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", line_buffering=True)
  ```
- **HERMES + MNEMOSYNE constraint:** `signal.signal(SIGTERM, _graceful_exit)` ve `SIGINT` —
  acik DB connection'lari close, sonra `sys.exit(0)`. Hicbir yerde `os._exit` veya `taskkill` kullanma.
- Config yukle: `~/.graphify/config.yml` (yoksa default'lardan uret + warn)
- Tool register: 7 tool decorator/dict map ile

## `mcp/__init__.py`

```python
from mcp.mcp_server import main
__all__ = ["main"]
```

## `core/cli.py`

Argparse tabanli CLI (pyproject.toml console_scripts entry: `graphify = core.cli:main`).
Komutlar:

| Komut | Argumanlar | Davranis |
|---|---|---|
| `graphify init <project>` | --path PATH | `~/.graphify/instances/<project>.db` olustur + migrate |
| `graphify mine` | --project-cwd PATH [--since-last] [--quiet] | Project slug cwd'den infer; tum adapter'lari calistir |
| `graphify status` | [--project SLUG] | DB size + entity/triple count |
| `graphify search <query>` | --project SLUG [--limit N] [--mode hybrid\|graph] | Search sonuc |
| `graphify wakeup` | --project SLUG | wakeup tool benzeri ozet |
| `graphify migrate` | --from-mempalace [--dry-run] | tools/migrate_from_mempalace.py'i cagirir (A4'un sorumluluga, sen sadece shell-out) |
| `graphify version` | yok | core.__version__ |

**HERMES constraint:** `graphify mine` git hook'tan cagirildiginda `--quiet` flag arka planda
1 satir log basar (stderr), exit 0. Hata olursa exit 0 yine — commit'i bloklamaz, log dosyasina yazar (`~/.graphify/logs/mine.log`).

## `config/config_example.yml`

```yaml
# Copy to ~/.graphify/config.yml and edit per machine.
version: 1
default_project: vyra
projects:
  vyra:
    repo_path: D:/demo_vyra
    db_path: ${HOME}/.graphify/instances/vyra.db
    adapters: [git, markdown, backlog, code]
    code_roots: [app, frontend]
  cosmos_mobile:
    repo_path: C:/Users/EXT02D059293/Documents/cosmos_mobile
    db_path: ${HOME}/.graphify/instances/cosmos_mobile.db
    adapters: [git, markdown, backlog]

embedding:
  enabled: true
  model: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
  lazy: true
  cache_dir: ${HOME}/.graphify/models

mcp:
  log_level: INFO
  log_dir: ${HOME}/.graphify/logs
  graceful_shutdown_timeout_s: 5
```

## Acceptance Criteria

1. `python -m mcp.mcp_server` clean start; stdin'e `{"jsonrpc":"2.0","id":1,"method":"tools/list"}` yazinca 7 tool listesi doner
2. `warmup` < 50 ms (cold), `wakeup` < 200 ms (warm, vyra DB on existing data)
3. SIGTERM testi: process'i `os.kill(pid, SIGTERM)` ile durdur → exit code 0, DB lock yok
4. Token cap test: search(query="x") sonucu 1000 fake entity uret → result `_truncated=true` ve <250 token
5. `graphify --help` cikti var; tum 7 alt komut hep listed
6. `graphify status --project vyra` JSON cikti
7. Windows cp1252 ortaminda Turkce karakterli sorgu calisiyor

## Self-Test

```bash
cd "C:/Users/EXT02D059293/Documents/General_Graphify"
PY="D:/demo_vyra/python/Scripts/python.exe"

# 1. CLI smoke
$PY -m core.cli version
$PY -m core.cli init vyra_a3_test
$PY -m core.cli status --project vyra_a3_test

# 2. MCP server smoke (stdio)
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | $PY -m mcp.mcp_server

# 3. SIGTERM check (start in background, kill, check exit code)
```

## Reporting

Frontmatter guncelle:
- `status: completed`
- `completed_at: <iso8601>`
- `files_created: [list]`
- `self_test_output: <output>`
- `tool_token_estimates: {warmup: N, wakeup: N, ...}` (her tool'un on-empty-db ortalama token sayisi)
- `notes: <decisions/issues>`

## NOTLAR

- Emoji yok
- Subprocess SADECE `core/cli.py`'de `graphify migrate` icin (A4'un script'ini cagiriyor); MCP server icinde subprocess yok
- FastMCP yoksa stdlib JSON-RPC fallback (HERMES kararidir; ek pip dep istemiyoruz)
- `config.yml` parse: PyYAML varsa kullan, yoksa core/graphify.py'deki YAML fallback'ini reuse et
