---
slug: graphify_f1_f5_spec_drift_cleanup
title: F1-F5 spec drift formal cleanup — brief revize + ARIADNE schema note
created: 2026-05-26T03:45+03:00
owner: hira
target_version: graphify-v1.2.3 (docs-only)
priority: P3
status: gate-1 pending review
council_brief: [ARES, HERA, ARIADNE]
related_briefs:
  - .agents/in_flight/done/2026-05-26_0145_graphify_v12_tyche_ares_tests.md
  - .agents/in_flight/done/2026-05-26_0210_graphify_v12_wave_c_risk_mitigation.md
related_docs:
  - .agents/workflows/graphify_v12_release_notes.md  # §"Bilinen uyumsuzluklar (spec drift — ARES F1-F5)"
---

# F1-F5 Spec Drift — Formal Cleanup (docs-only, no code)

## 1. Tetikleyici

Wave B test yazımı sırasında ARES, brief spec ile gerçek Graphify implementation arasında 5 noktada drift tespit etti (F1-F5). Wave B'de "tests assert impl, spec revize sayılır" politikası uygulandı; release notes §"Bilinen uyumsuzluklar" bu durumu rapor etti ama **kaynak brief'ler güncellenmedi**.

Bu mini-sprint, drift'leri formal kapatır:
- Eski brief'lerde "F1-F5 — RESOLVED (impl baseline)" bloğu
- Release notes §"Bilinen uyumsuzluklar" → §"Resolved spec drifts" rename
- Yeni v1.3 backlog item: F4 (`GRAPHIFY_HOME` env) + F5 (token cap dynamic) actionable hale getir

**Kod değişikliği YOK**. Sadece doc + brief revize.

## 2. Hedef

| F | Spec drift | Mevcut durum | Resolution kaynağı |
|---|---|---|---|
| F1 | `tool_mine` result keys: brief'te `entities_added`/`triples_added`, impl `entities_created`/`triples_created` | Tests impl key'lerini assert ediyor | Spec impl'i takip etsin (release notes §"Resolved spec drifts" altında dokümante) |
| F2 | CLI JSON keys: brief `coverage/passed`, impl `ratio_embedded/ok` | Tests impl key'lerini assert ediyor | Aynı: spec impl'i takip et |
| F3 | CLI empty project exit: brief 1, impl 1 (DB var, 0 entity) veya 2 (DB yok) | Tests impl ayrımını saygılı | Spec impl'in ayrımını adopt et (1 = empty, 2 = missing DB) |
| F4 | `GRAPHIFY_HOME` env var YOK, sadece `Path.home()` | v1.3 backlog | Brief açık (`HOME` env override için ayrı backlog item) |
| F5 | `tool_mine` 50-token cap clipping | v1.3 backlog | Dynamic cap (mine 500+, search 50) için ayrı backlog item |

## 3. Kapsam (Disjoint)

| Files | Op | Sahibi |
|-------|-----|--------|
| `d:\demo_vyra\.agents\in_flight\done\2026-05-26_0145_graphify_v12_tyche_ares_tests.md` | edit (F1-F5 RESOLVED bloğu ekle) | ARES |
| `d:\demo_vyra\.agents\workflows\graphify_v12_release_notes.md` | edit (§ rename + içerik düzelt) | HERA |
| `d:\demo_vyra\.agents\in_flight\` | create 2 yeni v1.3 brief skeleton | ARIADNE |

**Yasak**: Graphify pkg dosyalarına dokunma (`General_Graphify/*`), kod değişikliği yapma, mevcut commit'leri amend etme.

## 4. Spec

### ARES — eski brief revize
`2026-05-26_0145_graphify_v12_tyche_ares_tests.md` (in_flight/done/) sonuna ekle:

```markdown
---

## F1-F5 Spec Drift — RESOLVED (post-Wave C, 2026-05-26)

Wave B test yazımı sırasında tespit edilen 5 spec drift, "tests assert impl"
politikası ile resolve edildi. Bu brief'in spec'i artık impl baseline'a göre revize sayılır:

- **F1 RESOLVED**: `tool_mine` result keys `entities_created`/`triples_created`
  (NOT `entities_added`/`triples_added`).
- **F2 RESOLVED**: CLI JSON keys `ratio_embedded`/`ok` (NOT `coverage`/`passed`).
- **F3 RESOLVED**: CLI exit codes — `1` = empty project (DB var, 0 entity below
  threshold), `2` = missing DB.
- **F4 DEFERRED → v1.3**: `GRAPHIFY_HOME` env var support. Backlog brief:
  `2026-05-26_0345_v13_graphify_home_env.md` (skeleton).
- **F5 DEFERRED → v1.3**: `tool_mine` token cap dynamic (mine 500+, search 50).
  Backlog brief: `2026-05-26_0345_v13_token_cap_dynamic.md` (skeleton).

Source: `.agents/workflows/graphify_v12_release_notes.md` §"Resolved spec drifts".
```

### HERA — release notes revize
`.agents/workflows/graphify_v12_release_notes.md` §"Bilinen uyumsuzluklar (spec drift — ARES F1-F5)" başlığını şu şekilde değiştir:

- **Yeni başlık**: "Resolved spec drifts (ARES F1-F5)"
- Açıklama bloğu güncelle: "Wave B'de tespit edilen 5 drift, Wave C+D döneminde resolve edildi (F1-F3 impl baseline adopt; F4-F5 v1.3 backlog)."
- F1-F3 satırlarına "**RESOLVED — impl baseline**" işareti ekle
- F4-F5 satırlarına "**DEFERRED → v1.3 (brief: ...)**" işareti ekle

### ARIADNE — v1.3 backlog brief skeleton'ları
2 yeni dosya oluştur (in_flight'a değil, henüz dispatch edilmiyor — sadece backlog):

**`d:\demo_vyra\.agents\plans\v1.3_graphify_home_env.md`**:
```markdown
---
slug: v13_graphify_home_env
title: GRAPHIFY_HOME env var support (F4 closure)
created: 2026-05-26
target_version: graphify-v1.3
priority: P3 (backlog)
status: backlog
---

# v1.3 — GRAPHIFY_HOME env var

## Sorun
Şu an `Graphify.__init__` ve CLI yalnızca `Path.home() / ".graphify"`
kullanıyor; CI/test/multi-user senaryolarında override gerekli.

## Tasarım
- `GRAPHIFY_HOME` env var varsa onu kullan, yoksa fallback `Path.home() / ".graphify"`
- `core/graphify.py` + `core/cli.py` ortak helper: `def _graphify_home() -> Path`
- Test: env override + missing env davranışları

## Acceptance
- `GRAPHIFY_HOME=/tmp/gx python -m core.cli status` → DB path `/tmp/gx/instances/*.db`
- Suite: 187+ PASS
```

**`d:\demo_vyra\.agents\plans\v1.3_token_cap_dynamic.md`**:
```markdown
---
slug: v13_token_cap_dynamic
title: tool_mine/search token cap dynamic per-tool (F5 closure)
created: 2026-05-26
target_version: graphify-v1.3
priority: P3 (backlog)
status: backlog
---

# v1.3 — Dynamic token cap per MCP tool

## Sorun
Şu an `_cap_for(...)` tüm tool'lar için 50 default; geniş projelerde
`tool_mine` sonuçları clip ediliyor (production scenario).

## Tasarım
- Config: `mcp.token_caps: {mine: 500, search: 50, traverse: 100}`
- `_cap_for(registry, slug, tool, default)` config'i okusun
- ProjectRegistry'de eksik anahtarlar için default fallback

## Acceptance
- `tool_mine` 500-token cap'e kadar genişler
- `tool_search` 50 (mevcut) korunur
- Suite: 187+ PASS, yeni test_token_caps_per_tool
```

## 5. Acceptance

- [ ] ARES: eski brief'te F1-F5 RESOLVED bloğu görünüyor
- [ ] HERA: release notes §"Resolved spec drifts" rename ve içerik düzeltildi
- [ ] ARIADNE: 2 yeni v1.3 backlog brief skeleton mevcut (`plans/` altında)
- [ ] Kod değişikliği YOK (Graphify pkg dokunulmamış)
- [ ] Vyra repo: 3 doküman touch + 2 yeni skeleton commit'lendi

## 6. Rules

- **Graphify-first lookup zorunlu DEĞİL** (sadece doc/brief, kod referansı yok)
- **Mine-after-fix**: KAPI-2 sonrası mine + add_decision (docs counts as state change)
- **Disjoint scope**: ARES kendi brief'i, HERA release notes, ARIADNE plans/
- **Commit**: ZEUS final integration (vyra repo, Graphify pkg dokunulmamış)
- **HERMES YOK**: bu sprint docs-only, kod sahibi yok

## 7. Çıktı raporu

1. ARES: brief diff özet (eklenen blok ≤30 satır)
2. HERA: §rename + içerik güncelleme diff özet
3. ARIADNE: 2 yeni skeleton dosyanın yolu + first-30-line preview
4. KAPI-2 onay sonrası ZEUS commit hazırlar
