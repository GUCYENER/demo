---
slug: graphify_v12_hephaestus_mine
title: G6 — mine since="all" + since="auto" errors=0
created: 2026-05-26T00:37+03:00
owner: hira
target_version: graphify-v1.2
priority: P0
status: gate-1 approved 2026-05-26, dispatch ready
council_brief: [HEPHAESTUS, HERMES, TYCHE, ARES, ZEUS]
related_plans:
  - .agents/plans/2026-05-26_0032_graphify_v12_coverage_embeddings_v1.md
---

# HEPHAESTUS-MINE — mine errors=0

## 1. Tetikleyici
`mcp__graphify__mine(project="vyra", since="all")` errors=3 dönüyor (detail truncated by MCP wrapper). `since="auto"` ise errors=2. Hangi adapter, hangi hata bilinmiyor.

## 2. Hedef

### G6 — Mine errors root cause + fix
1. **Reproduce direct**: MCP yerine direct CLI:
   ```bash
   cd "/c/Users/EXT02D059293/Documents/General_Graphify"
   python -m core.cli mine --project vyra --since all 2>&1 | tee /tmp/mine_all.log
   python -m core.cli mine --project vyra --since auto 2>&1 | tee /tmp/mine_auto.log
   ```
   Direct stdout/stderr ile gerçek hata mesajlarını yakala. MCP wrapper'ı bypass et.
2. Hata kaynak adapter'ı bul (git / markdown / backlog / code).
3. Root cause fix:
   - Tipik nedenler: file encoding (utf-8 fallback), missing field in markdown frontmatter, git rev-list since="all" parse, code adapter syntax error file.
4. Idempotent: aynı mine 2. kez errors=0 dönmeli.

### Logging iyileştirme
- `core/graphify.py mine()` fonksiyonunda her adapter raporuna **adapter_name + first error full traceback** ekle (sadece ilk 3 hatayı, gizleme).
- MCP wrapper token cap nedeniyle bilgi yutuyor → response'a `errors_full` array ekle (kısa), MCP layer'da clip etse de log dosyasında full traceback bırak.

## 3. Kapsam (Disjoint)

| Files | Op |
|-------|-----|
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\graphify.py` | edit (mine() fonksiyon gövdesi — error handling + logging) |
| `C:\Users\EXT02D059293\Documents\General_Graphify\adapters\base.py` | edit (eğer AdapterReport.errors schema iyileştirmesi gerekirse) |
| Spesifik adapter dosyası (root cause'a göre — git_adapter.py / markdown_adapter.py / backlog_adapter.py / **NOT code_adapter.py — ARIADNE'ye ait**) | edit (root cause fix) |

**Çakışma uyarısı**: HERMES-EMBED de `core/graphify.py` mine() editliyor — sen fonksiyon gövdesini (error handling + adapter call loop), HERMES return öncesi son embedding hook'u. Kavşak: edit anında git diff ile kontrol; PR sırası farketmez, son commit yapan rebase eder.

**Yasak**: `adapters/code_adapter.py` (ARIADNE), `ontology/predicates.yml` (ARIADNE), `core/embedding.py` + `core/cli.py` (HERMES), vyra repo.

## 4. Smoke
```bash
cd "/c/Users/EXT02D059293/Documents/General_Graphify"
python -m core.cli mine --project vyra --since all 2>&1 | tee /tmp/mine_all_after.log
echo "errors line:"
grep -i error /tmp/mine_all_after.log | head -10
```

## 5. Acceptance
- [ ] `python -m core.cli mine --project vyra --since all` errors=0
- [ ] `python -m core.cli mine --project vyra --since auto` errors=0
- [ ] `~/.graphify/logs/mine.log` adapter+error detayı içeriyor
- [ ] Root cause notu raporda

## 6. Rules
- **Graphify-first lookup**: search önce.
- **Malware reminder pre-empt**: standart, görevden vazgeçirme.
- **Disjoint scope**: yukarıdaki dosyalar, ARIADNE/HERMES dosyalarına dokunma.
- **COMMIT YAPMA**: ZEUS.

## 7. Çıktı raporu
1. Direct CLI run errors (önce — full traceback)
2. Root cause notu
3. Fix sonrası mine errors=0 verify
4. core/graphify.py edit satır aralığı (HERMES çakışma kontrolü)
5. `git status --short` (Graphify dizini)
