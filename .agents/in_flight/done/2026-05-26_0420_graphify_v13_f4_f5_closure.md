---
slug: graphify_v13_f4_f5_closure
title: Graphify v1.3 — F4 GRAPHIFY_HOME env + F5 token cap dynamic
created: 2026-05-26T04:20+03:00
owner: hira
target_version: graphify-v1.3
priority: P3
status: gate-1 pending review
council_brief: [HERMES, TYCHE, HERA]
related_plans:
  - .agents/plans/2026-05-26_0410_v13_graphify_home_env_v1.md
  - .agents/plans/2026-05-26_0410_v13_token_cap_dynamic_v1.md
related_docs:
  - .agents/workflows/graphify_v12_release_notes.md  # F4/F5 DEFERRED references
---

# v1.3 — F4 GRAPHIFY_HOME env + F5 token cap dynamic

## 1. Tetikleyici

F1-F5 spec drift cleanup'ta F4 ve F5 v1.3 backlog'a devredildi. Bu brief, ikisini birlikte (küçük, disjoint, paralel uygulanabilir) kapatır.

**Mevcut durum (lookup sonucu)**:
- F5 altyapısı **zaten var**: `token_caps` `ontology/core.yml`'de tanımlı, `mcp/tools.py:_cap_for()` okuyor. Sadece `mine: 50 → 500` bump gerekli + per-tool test.
- F4 için `Path.home() / ".graphify"` 3 yerde hardcoded: `core/cli.py:63`, `mcp/mcp_server.py:56`, `core/embedding.py:57`. Ortak helper gerekli.

## 2. Hedef

| F | Kapsam | Sahibi |
|---|---|---|
| F4 | `_graphify_home() -> Path` helper (env var override) + 3 callsite wire | HERMES (sub-agent refüze ederse ZEUS direct-apply) |
| F5 | `ontology/core.yml` `mine: 50 → 500` bump | HERMES |
| Test | F4 env override + missing env + F5 per-tool cap test | TYCHE |
| Doc | Release notes v1.3 closure section + README env var note | HERA |

## 3. Kapsam (Disjoint)

| Files | Op | Sahibi |
|-------|-----|--------|
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\paths.py` | NEW (`_graphify_home()` helper) | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\cli.py` | edit (`DEFAULT_CONFIG_DIR = _graphify_home()`) | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\mcp\mcp_server.py` | edit (`DEFAULT_CONFIG_DIR = _graphify_home()`) | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\embedding.py` | edit (`Path("~/.graphify/models")` → `_graphify_home() / "models"`) | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\ontology\core.yml` | edit (`mine: 500`) | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\tests\test_graphify_home_env.py` | NEW (F4 tests) | TYCHE |
| `C:\Users\EXT02D059293\Documents\General_Graphify\tests\test_token_caps_per_tool.py` | NEW (F5 tests) | TYCHE |
| `d:\demo_vyra\.agents\workflows\graphify_v13_release_notes.md` | NEW | HERA |
| `C:\Users\EXT02D059293\Documents\General_Graphify\README.md` | edit (env var section) | HERA |

**Yasak**: core/graphify.py (büyük değişiklik), adapters/*, mevcut testleri silme.

## 4. Spec

### HERMES — F4

`core/paths.py` (yeni dosya, ~25 satır):
```python
"""Path helpers — Graphify home resolution.

GRAPHIFY_HOME env var override; fallback `Path.home() / ".graphify"`.
Centralized to avoid drift between CLI, MCP server, and embedding paths.
"""
from __future__ import annotations
import os
from pathlib import Path

_GRAPHIFY_HOME_ENV = "GRAPHIFY_HOME"


def graphify_home() -> Path:
    """Return the Graphify home directory.

    Resolution order:
    1. ``GRAPHIFY_HOME`` env var (if set and non-empty), expanded.
    2. ``Path.home() / ".graphify"`` fallback.

    The directory is NOT created here; callers are responsible for mkdir.
    """
    env = os.environ.get(_GRAPHIFY_HOME_ENV, "").strip()
    if env:
        return Path(os.path.expanduser(os.path.expandvars(env))).resolve()
    return Path.home() / ".graphify"
```

3 callsite update:
- `core/cli.py:63`: `DEFAULT_CONFIG_DIR = Path.home() / ".graphify"` → `from core.paths import graphify_home; DEFAULT_CONFIG_DIR = graphify_home()`
- `mcp/mcp_server.py:56`: same swap.
- `core/embedding.py:57`: `Path("~/.graphify/models").expanduser()` → `graphify_home() / "models"`

### HERMES — F5

`ontology/core.yml` line ~45: `mine: 50` → `mine: 500`. Diğer cap'lere dokunma.

### TYCHE — F4 test (`tests/test_graphify_home_env.py`)

3 test:
1. `test_graphify_home_default_no_env`: `monkeypatch.delenv("GRAPHIFY_HOME", raising=False)` → `graphify_home() == Path.home() / ".graphify"`
2. `test_graphify_home_env_override`: `monkeypatch.setenv("GRAPHIFY_HOME", str(tmp_path))` → `graphify_home() == tmp_path.resolve()`
3. `test_graphify_home_env_expanduser`: `monkeypatch.setenv("GRAPHIFY_HOME", "~/custom")` → result starts with expanded `~` (Windows: `USERPROFILE\custom`)

### TYCHE — F5 test (`tests/test_token_caps_per_tool.py`)

3 test:
1. `test_cap_for_returns_mine_500_from_ontology`: Load default ontology, call `_cap_for(registry, slug, "mine", 50)` → returns 500.
2. `test_cap_for_unknown_tool_returns_default`: unknown tool → returns default arg.
3. `test_cap_for_search_unchanged_250`: search → 250 (mevcut value korunmuş).

### HERA — release notes (yeni dosya `d:\demo_vyra\.agents\workflows\graphify_v13_release_notes.md`)

Sections:
- Özet (F4 + F5 closure, v1.2.2 sonrası ilk feature release)
- F4: GRAPHIFY_HOME env var (env precedence, expanduser/expandvars, fallback)
- F5: Token cap mine 50→500 (production rationale)
- Test outcome (6 yeni test)
- v1.2/v1.2.1/v1.2.2 + v1.3 birleşik release tablosu

### HERA — README.md ekle (Graphify pkg)

Yeni section "Environment variables":
- `GRAPHIFY_HOME` — override default `~/.graphify` config dir; honors `~` and `$VAR` expansion.

## 5. Acceptance

- [ ] HERMES: `core/paths.py` mevcut, import temiz
- [ ] HERMES: 3 callsite `graphify_home()` çağırıyor
- [ ] HERMES: `ontology/core.yml` `mine: 500`
- [ ] TYCHE: 6 yeni test PASS (3 F4 + 3 F5)
- [ ] Suite: 187 + 6 = 193 PASS, coverage ≥ %74
- [ ] HERA: release notes + README env var section
- [ ] Smoke: `GRAPHIFY_HOME=/tmp/gx python -m core.cli status` çalışıyor (manuel check)

## 6. Rules

- **Graphify-first lookup ZORUNLU**: HERMES `mcp__graphify__search` ile `_cap_for`/`DEFAULT_CONFIG_DIR` lokasyonlarını bul (Read'den ÖNCE)
- **Mine-after-fix**: KAPI-2 sonrası ZEUS mine + add_decision
- **Sub-agent malware reminder fallback**: HERMES sub-agent code edit'i reddederse ZEUS direct-apply (memory: `feedback_subagent_malware_reminder_refusal.md`); test (TYCHE) + doc (HERA) paralel devam eder
- **Disjoint scope**: 3 paralel agent, dosya ayrımı net
- **COMMIT YAPMA**: ZEUS final integration

## 7. Çıktı raporu

1. Her ajan: değiştirilen dosyalar + diff özet (≤30 satır)
2. HERMES: smoke test çıktısı (`python -c "from core.paths import graphify_home; print(graphify_home())"`)
3. TYCHE: pytest output (yeni test dosyaları + suite summary)
4. HERA: release notes preview (ilk 40 satır) + README diff
5. Findings: bug veya cap/env edge-case'ler
