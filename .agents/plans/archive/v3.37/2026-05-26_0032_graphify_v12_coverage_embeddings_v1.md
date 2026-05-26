---
slug: graphify_v12_coverage_embeddings
title: Graphify v1.2 — Code coverage + Function/Class entity + Embeddings + Mine error fix
created: 2026-05-26T00:32+03:00
owner: hira
target_version: graphify-v1.2
priority: P0
status: gate-1 pending
council_brief: [HERMES, ARIADNE, METIS, TYCHE, ARES, HEPHAESTUS, ZEUS]
related_plans:
  - .agents/plans/archive/v3.36/2026-05-25_2100_general_graphify_hybrid_setup_v1.md
related_briefs:
  - .agents/in_flight/done/2026-05-25_2350_graphify_workflow_integration_vyra.md
  - .agents/in_flight/2026-05-26_0030_graphify_v1_1_report_autogen.md
---

# Graphify v1.2 — Coverage + Embeddings + Mine errors

## 1. Tetikleyici (Why)

v1.0 + v1.1 sonrası Graphify altyapısı **eksik kurulu**. User talimatı: "proje ekibi ve ajanları graphfy hafızasına göre ilerlemeli. amacına uygun yapının eksikliklerini gider. başta böyle eksiksiz kur demiştim ama sallamdın".

Mevcut durum (`vyra.db` denetimi, 2026-05-26 00:30):

| Metrik | Beklenen | Gerçek | Durum |
|--------|----------|--------|-------|
| `app/` Python File entity | 230 | 55 | ❌ %24 coverage |
| Function entity | ~5000+ | **0** | ❌ AST hiç çalışmamış |
| Class entity | ~500+ | **0** | ❌ |
| `defined_in` triple | ~5000+ | 0 | ❌ |
| `imports` triple | ~3000+ | 0 | ❌ predicate destekli değil |
| `calls` triple | ~10000+ | 0 | ❌ predicate destekli değil |
| Embeddings | 705 | **0** | ❌ `lazy:true` hiç tetiklenmedi |
| `mcp__graphify__mine since="all"` | success | errors=3 | ❌ |
| `mcp__graphify__mine since="auto"` | success | errors=2 | ❌ |

**Yansıma**: Subagent'lar `mcp__graphify__search` ile Function/Class arayamadığı için Read'e düşüyor → token erozyonu.

## 2. Hedef (What)

| ID | Bulgu | Hedef | Sorumlu |
|----|-------|-------|---------|
| G1 | code_adapter `app/` altında sadece 55 dosya görüyor (230 var) | Recursive walk + include/exclude düzeltmesi: tüm `.py` taranır | ARIADNE |
| G2 | Function/Class entity = 0 | `_emit_function` çağrılıyor mu? Çalışıyorsa neden 0? Debug + fix → her .py için Function/Class entity üretilmeli | ARIADNE |
| G3 | `defined_in` 0 | G2 düzelince otomatik gelir (sanity assert) | ARIADNE |
| G4 | `imports` + `calls` predicate yok | `code_adapter._process_file` AST walk'a `Import`/`ImportFrom`/`Call` ekle, ontology `predicates.yml`'ye iki yeni predicate ekle (`imports`, `calls`) | ARIADNE |
| G5 | embeddings tablosu 0 satır | `embedding.lazy: true` davranışını araştır; ya `lazy: false` ya da mine sonrası warmup tetikleyici eklemek. Hedef: tüm 705+ entity'nin (G2 sonrası ~5000+) embedding'i üretilsin | HERMES |
| G6 | `mine since="all"` errors=3 | Hata mesajını yakala (MCP wrapper token cap altında kaybediyor), `core/graphify.py mine` fonksiyonunu debug + fix | HEPHAESTUS |
| G7 | KAP 10c coverage assert | `vyrazeus.md` BITIR sweep adımına eşik kontrolü: `File count / .py file count ≥ 0.95`, embedding coverage ≥ %80, aksi halde uyarı | METIS (workflow patch) |
| G8 | `core.cli` veya CLI script: `graphify coverage-report --project vyra` → tablo + threshold pass/fail | Yeni komut (opsiyonel ama önerilir) | HERMES |

## 3. Sorumluluk Matrisi (Disjoint Scope)

Graphify kaynak kodu konumu: `C:\Users\EXT02D059293\Documents\General_Graphify\`

| Subagent | Files | Op |
|----------|-------|-----|
| ARIADNE-CODE | `adapters/code_adapter.py` (G1+G2+G3+G4 — TEK AGENT shared file) | edit |
| ARIADNE-CODE | `ontology/predicates.yml` | edit (imports, calls predicate ekle) |
| HERMES-EMBED | `core/graphify.py` mine sonu hook (G5) + `core/embedding.py` | edit |
| HEPHAESTUS-MINE | `core/graphify.py` `mine()` since=all branch (G6) + debug logging | edit |
| METIS-WORKFLOW | `d:\demo_vyra\.agents\workflows\vyrazeus.md` KAP 10c | edit |
| TYCHE+ARES | `tests/unit/test_code_adapter_coverage.py`, `tests/unit/test_imports_calls.py`, `tests/integration/test_mine_since_all.py`, `tests/integration/test_embedding_lazy.py` | create |
| ZEUS | 2-gate review | — |

**Yasak**: vyra repo'sundaki app/, frontend/, tests/ ellenmez. Bu plan vyra projesi değil, **Graphify altyapısı** plan'ı.

## 4. Sıralama (Wave A paralel)

Disjoint file scope sayesinde 4 paralel agent:
- **Wave A** (paralel): ARIADNE-CODE, HERMES-EMBED, HEPHAESTUS-MINE, METIS-WORKFLOW
- **Wave B** (sequential, A bitince): TYCHE+ARES test brief
- **Wave C**: Full re-mine + coverage assert + Decision

## 5. Acceptance Criteria

- [ ] `app/` File entity count ≥ %95 of `.py` count (230 → ≥219)
- [ ] Function entity count > 1000
- [ ] Class entity count > 100
- [ ] `defined_in` triple count > 1000
- [ ] `imports` + `calls` predicate aktif, count > 500 her biri
- [ ] Embedding rows > %80 of total entity count
- [ ] `mcp__graphify__mine(since="auto")` errors=0
- [ ] `mcp__graphify__mine(since="all")` errors=0
- [ ] KAP 10c workflow assert mevcut
- [ ] `mcp__graphify__search(query="_load_source", project="vyra")` Function entity döner (smoke)

## 6. 2-Gate Council Plan

**KAPI 1** (yazım sonrası): HERMES + ARIADNE + HEPHAESTUS + METIS + TYCHE masa.

**KAPI 2** (spec-vs-output):

| Spec | Verifikasyon | Karar |
|------|--------------|-------|
| G1 coverage ≥ %95 | SQL count | — |
| G2 Function>1000 | SQL count | — |
| G3 defined_in>1000 | SQL count | — |
| G4 imports+calls predicate aktif | SQL distinct predicate | — |
| G5 embedding ≥ %80 | SQL count(embeddings)/count(entities) | — |
| G6 mine errors=0 | MCP call check | — |
| G7 KAP 10c | grep workflow file | — |
| Tests PASS | pytest | — |

## 7. Risk

- **R-G2**: AST walk yapılıyor ama 0 Function — kök neden olası: `add_entity` schema validation reddediyor olabilir veya `code_adapter` adapter list'ten düşürülmüş. ARIADNE önce **5 dakika** debug yapmalı (gerçek bir mine çalıştır + log).
- **R-G5**: `lazy:true` sentence-transformers modeli initial download'unu erteliyor olabilir. İlk warmup ~150MB indirme + ~5 dakika encode (705 entity için).
- **R-G6**: `since="all"` muhtemelen MCP wrapper token cap'i ile detayı yutuyor — direct `python -m core.cli mine --project vyra --since all` çalıştırarak stderr'ı yakala.

## 8. Bağımlılık

- Graphify v1.1 (report autogen brief `2026-05-26_0030`) **paralel** ilerleyebilir — disjoint scope.
- Vyra projesi v3.37.0 BITIR (commit `628705c`) ✅ tamam.

## 9. Açık Sorular

1. **Embedding model boyutu**: paraphrase-multilingual-MiniLM-L12-v2 ~470MB (download). Onay? Default kabul.
2. **`imports`/`calls` triple emisyon kapsamı**: tüm `Call` node'larını mı yoksa sadece top-level + class method'ları mı? Default: tüm Call node'lar (filter sonra).
3. **Coverage threshold**: %95 sıkı mı? Default: %95 (bazı `__init__.py`, generated dosyalar düşebilir).
4. **CLI komut `graphify coverage-report`**: bu sprint mi v1.3 mü? Default: bu sprint, basit tablo.

Cevap beklerim → KAPI 1 → 4 paralel agent dispatch.
