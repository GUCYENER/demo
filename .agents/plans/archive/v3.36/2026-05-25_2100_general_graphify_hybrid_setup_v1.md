---
plan_id: general_graphify_hybrid_setup
created: 2026-05-25
branch: hira
status: in_progress
approved_at: 2026-05-25
approved_by: user
decisions_applied:
  Q1: A1 dispatch immediately, no extra review checkpoint
  Q2: SLO green OR v3.40.0 calendar cap (whichever first)
  Q3: patch sequence after vyra → cosmos_mobile → cosmos → mahsul_mezati
version_target: v3.37.0
council_mod: 3
council_lead: MNEMOSYNE + ARIADNE
council_members: [MNEMOSYNE, ARIADNE, HERMES, ARES, TYCHE, NIKE, HERA, CRAZYMEMPLC, ZEUS]
hebe_gate_required: false
target_dir: C:\Users\EXT02D059293\Documents\General_Graphify
data_dir: C:\Users\EXT02D059293\.graphify
mcp_name: graphify
deliverable_type: cross-project infrastructure
---

# General_Graphify — Hibrit Graph + Vector Memory MCP Kurulumu

## 1. Context

VYRA + Cosmos_Mobile + COSMOS + Mahsul_Mezati projelerinde mevcut MemPalace MCP
(`~/.mempalace/`, 270 MB ChromaDB) aşağıdaki failure modlarını gösteriyor:

- ChromaDB thread leak → `taskkill /F /T` fallback gerekli (mcp_servers.py:59-68)
- MINE_TIMEOUT 300 s → 600 s'ye çıkartılmak zorunda kalındı (büyük wing)
- WAKEUP_TIMEOUT 120 s — ONNX cold-start şişiyor
- Windows UnicodeEncodeError önlemleri zorunlu (4 ayrı env var)
- Subprocess + thread spawn her tool çağrısında
- Token bütçesi gevşek (~700 tk wakeup, ~500 tk search)

Kullanıcı kararı: hibrit (graph-first + opsiyonel embedding) yapı kurulacak,
**her projede** BAŞLA + BİTİR akışlarına entegre edilecek, **anlık** kod
farkındalığı + **token tasarrufu** sağlanacak.

## 2. Goals

1. `Documents/General_Graphify/` altında reusable, proje-agnostik graph memory iskeleti
2. `~/.graphify/instances/<project>.db` per-project izole SQLite store
3. MCP server (`mcp__graphify__*`) — MemPalace ile paralel çalışır
4. 4 proje BAŞLA/BİTİR workflow'larına entegrasyon (vyra önce, diğerleri patch ile)
5. Git post-commit hook ile anlık incremental sync
6. Lossless migrasyon MemPalace → Graphify (drawer → Memory entity)
7. MNEMOSYNE + ARIADNE greenlight şartları karşılanmış olarak teslim

## 3. Non-Goals

- MemPalace'ı silme (30 gün paralel kalır — SLO yeşilse sonra devre dışı)
- Çapraz-proje sorgu CLI'ı (v1'de design var, implementation v2'ye ertelendi)
- Web UI (CLI + MCP yeter)
- Graphviz/Mermaid auto-render (sadece export, render manuel)

## 4. Decisions Locked

| # | Karar | Detay | Konsey |
|---|---|---|---|
| 1 | DB konumu | `~/.graphify/instances/<slug>.db` | ARIADNE |
| 2 | Migrasyon | Otomatik lossless — drawer → Memory entity | MNEMOSYNE |
| 3 | Embedding | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, lazy | MNEMOSYNE + ARIADNE |
| 4 | Vector backend | `sqlite-vec` (varsa) + numpy fallback (yoksa) | ARIADNE |
| 5 | İki MCP paralel | 30 gün | MNEMOSYNE |
| 6 | Test stratejisi | TYCHE + ARES brief → pytest subagent | TYCHE |
| 7 | Real-time sync | Git post-commit hook + BAŞLA freshness gate (2 katman) | HERMES |
| 8 | Token cap | ontology.yml içinde per-tool cap | ZEUS |
| 9 | Workflow patch | vyra ilk, sonra 3 proje aynı patch | HERA |

## 5. Architecture Summary

```
Claude (VSCode) ─stdio─> graphify mcp_server.py (FastMCP, single process)
                          ├─ core.graphify        (CRUD + query + traverse)
                          ├─ core.embedding       (lazy ONNX load)
                          ├─ core.query           (DSL + builders)
                          ├─ core.migration       (schema versioning)
                          └─ adapters             (git/markdown/backlog/code)
                                  │
                                  ▼
                          ~/.graphify/
                          ├─ instances/<proj>.db  (entities + triples + vec)
                          ├─ config.yml           (project → db map)
                          ├─ models/              (ONNX, opt)
                          └─ migrations/<NN>.sql
```

## 6. Directory Layout

```
C:\Users\EXT02D059293\Documents\General_Graphify\
├── README.md                       # quickstart + design doc
├── pyproject.toml                  # pip install -e . — exposes `graphify` CLI
├── requirements.txt
├── .gitignore
├── schema/
│   ├── 001_entities.sql
│   ├── 002_triples.sql
│   ├── 003_embeddings.sql
│   └── 004_indexes_views.sql
├── ontology/
│   ├── core.yml
│   ├── predicates.yml
│   └── README.md
├── core/
│   ├── __init__.py
│   ├── graphify.py
│   ├── embedding.py
│   ├── query.py
│   ├── migration.py
│   └── cli.py
├── adapters/
│   ├── __init__.py
│   ├── git_adapter.py
│   ├── markdown_adapter.py
│   ├── backlog_adapter.py
│   ├── code_adapter.py
│   └── conversation_adapter.py
├── mcp/
│   ├── mcp_server.py
│   └── tools.py
├── instances/                      # gitignored
│   └── .gitkeep
├── tools/
│   ├── visualize.py
│   ├── migrate_from_mempalace.py
│   ├── benchmark.py
│   └── install_git_hook.py
├── tests/
│   ├── test_graphify_core.py
│   ├── test_query.py
│   ├── test_adapters.py
│   ├── test_mcp_tools.py
│   └── test_migration.py
└── examples/
    ├── usage.md
    ├── basla_bitir_integration.md
    └── ontology_extension.md
```

## 7. Subagent Dispatch Matrix (disjoint files)

| Agent | Brief | Files Owned | Council Brief |
|---|---|---|---|
| **A1 — Schema & Core** | `.agents/in_flight/2026-05-25_2110_graphify_a1_schema_core.md` | `schema/*.sql`, `core/graphify.py`, `core/migration.py`, `core/query.py`, `core/embedding.py`, `ontology/*.yml` | ARIADNE lead + HERMES + NIKE (perf) |
| **A2 — Adapters** | `.agents/in_flight/2026-05-25_2110_graphify_a2_adapters.md` | `adapters/*.py` (5 dosya) | HERMES + ARIADNE |
| **A3 — MCP & CLI** | `.agents/in_flight/2026-05-25_2110_graphify_a3_mcp_cli.md` | `mcp/mcp_server.py`, `mcp/tools.py`, `core/cli.py` | HERMES + ZEUS (token cap) |
| **A4 — Tooling** | `.agents/in_flight/2026-05-25_2110_graphify_a4_tooling.md` | `tools/migrate_from_mempalace.py`, `tools/visualize.py`, `tools/benchmark.py`, `tools/install_git_hook.py` | MNEMOSYNE (migrasyon) + NIKE (benchmark) |
| **A5 — Tests** | `.agents/in_flight/2026-05-25_2110_graphify_a5_tests.md` | `tests/*.py` | TYCHE lead + ARES |
| **A6 — Docs** | `.agents/in_flight/2026-05-25_2110_graphify_a6_docs.md` | `README.md`, `examples/*.md`, `pyproject.toml`, `requirements.txt`, `.gitignore` | HERA |

**Disjoint kapsam doğrulandı:** Hiç iki ajan aynı dosyaya dokunmuyor.
A1 → A2/A3'in import edebileceği API'yi önce yayınlar (interface contract A1'in brief'inde).

**Dispatch sırası:**
1. **Önce A1** (tek başına — diğerleri A1'in interface'ine bağımlı)
2. A1 tamam → A2 + A3 + A4 + A6 **paralel** dispatch
3. Hepsi tamam → A5 (test, son çünkü tam kod gerek)

## 8. MNEMOSYNE Greenlight Şartları

- [ ] `tools/benchmark.py` — 20 sabit sorgu, MemPalace vs Graphify MAP@3 karşılaştırması; %85 altı çıkarsa embedding model değiştir
- [ ] `tools/migrate_from_mempalace.py` — lossless, source metadata korunur, dry-run modu
- [ ] MemPalace MCP 30 gün paralel (kaldırma sadece SLO 7 gün yeşil sonrası)
- [ ] MCP server SIGTERM handler graceful exit (taskkill fallback yok)

## 9. ARIADNE Greenlight Şartları

- [ ] Ontology versiyonlama: `ontology/core.yml` üst düzey `version: 1.0` — per-instance `ontology_version` kolonu
- [ ] Triple pruning policy dokümante — entity başına soft cap 500 edge, eski/düşük conf arşiv
- [ ] Schema migration: `core/migration.py` idempotent, `001..0NN` sıralı, geri-alınabilir
- [ ] Predicate whitelist: `predicates.yml` — whitelist dışı tetik error/warn
- [ ] Cross-instance query design notu var (implementation v2)

## 10. SaaS-grade SLO Targets

| Metrik | MemPalace mevcut | Graphify hedef | Ölçüm yeri |
|---|---|---|---|
| BAŞLA wakeup latency p95 | 5-30 s | <3 s | benchmark.py |
| BİTİR mine incremental p95 | 30 s - 10 dk | <5 s | benchmark.py |
| Search p95 (graph) | n/a | <10 ms | benchmark.py |
| Search p95 (hybrid) | 0.5-2 s | <200 ms | benchmark.py |
| Cold-start error rate | ~%5-10 | <%0.1 | logs |
| Disk per project | 50-100 MB | <10 MB | du -sh |
| Token budget — wakeup | ~700 | <250 | tool output len |
| Token budget — search | ~500 | <250 | tool output len |

**SLO 7 gün yeşil kalmazsa:** MemPalace devre dışı bırakılmaz, Graphify v2 plan açılır.

## 11. Workflow Integration (BAŞLA + BİTİR)

### BAŞLA patch (vyrazeus.md + 3 sister workflow)

```
1. Servisler kontrol (mevcut)
2. ⚡ GRAPHIFY WAKEUP (YENİ — MemPalace freshness gate öncesi):
   - mcp__graphify__warmup()                    [<50 ms]
   - mcp__graphify__wakeup(project="vyra")      [<200 ms, ~250 tk]
   - Stale gate: last_indexed_commit ≠ HEAD ise:
     • mcp__graphify__mine(since="HEAD~10")     [<500 ms]
3. MemPalace warmup/wakeup (fallback — paralel 30 gün)
4. Git status (mevcut)
5. Proje durumu (mevcut, ama refactor backlog Graphify entity'den okunur)
6. In-flight kontrolü (mevcut)
7. Plan housekeeping (mevcut, completed plan → Graphify Decision triple)
8. Refactor priority gate (Graphify entity üzerinden — disk scan değil)
9. Oturum hazır raporu
```

### BİTİR patch

```
1. Quality gates (mevcut)
2. ⚡ GRAPHIFY DECISION RECORD (YENİ):
   - mcp__graphify__add_decision(
       commit_msg, branch,
       council_signatures, refactor_ids_closed, bug_ids_fixed
     )                                          [<10 ms]
3. git commit + push (mevcut)
4. ⚡ GRAPHIFY MINE (YENİ — git push sonrası):
   - mcp__graphify__mine(since=last_indexed)    [<5 s]
   - Spot-check: search(last_commit_sha) — bulunmalı
5. MemPalace mine_project (paralel 30 gün)
6. CRAZYMEMPLC + MNEMOSYNE doğrulaması
```

### Git post-commit hook (per project, idempotent)

```bash
#!/bin/sh
# .git/hooks/post-commit (created by tools/install_git_hook.py)
graphify mine --project-cwd "$PWD" --since-last --quiet &
```

Background, async — commit hızını yavaşlatmaz.

## 12. Risks

| # | Risk | Etki | Mitigation |
|---|---|---|---|
| R1 | sqlite-vec Windows wheel yok/bozuk | hybrid search çalışmaz | numpy fallback hazır (`embedding.py` iki backend) |
| R2 | sentence-transformers download fail | embed yüklenemez | Offline model bundle önerisi `tools/download_model.py` |
| R3 | Migrasyon ChromaDB lock | mevcut MemPalace bozulabilir | Migrasyon SADECE read-only chroma open + dry-run default |
| R4 | Disjoint kapsam ihlali | iki agent aynı dosya | Brief'lerde explicit file list + ZEUS preview before commit |
| R5 | Token cap bypass | output şişer | `_clip_output(max_tokens)` her tool wrapper'da zorunlu |
| R6 | Git hook bozulması | commit fail | Hook `set -e` YOK + arka plan `&` + 5 s timeout |

## 13. Rollout

1. **Faz 0 — Plan onayı** (şu an)
2. **Faz 1 — A1 dispatch** (Schema & Core) — interface kontrat
3. **Faz 2 — A2/A3/A4/A6 paralel dispatch** (Adapters/MCP/Tools/Docs)
4. **Faz 3 — A5 dispatch** (Tests, TYCHE+ARES brief)
5. **Faz 4 — Benchmark + Konsey greenlight** (MNEMOSYNE + ARIADNE imza)
6. **Faz 5 — vyra MCP kayıt** (`claude mcp add graphify`) + migrasyon dry-run + smoke
7. **Faz 6 — vyrazeus.md patch** (ayrı küçük commit) — 1 hafta gözlem
8. **Faz 7 — 3 sister workflow patch** (cosmos_mobile, cosmos, mahsul_mezati)
9. **Faz 8 — 30 gün paralel SLO izleme** — yeşilse MemPalace MCP devre dışı

## 14. Acceptance Criteria

- [ ] 6 subagent brief'leri done/ altında
- [ ] tests/ pytest yeşil (>%85 coverage hedef)
- [ ] benchmark.py — Graphify SLO 8 metriğin 7'sinde target altında
- [ ] MNEMOSYNE + ARIADNE imza şartlarının tamamı checked
- [ ] `claude mcp list` çıktısında `graphify: ✓ Connected`
- [ ] vyra BAŞLA: `🟢 GRAPHIFY` satırı oturum hazır raporunda görünüyor
- [ ] vyra BİTİR: graphify_mine spot-check yeşil
- [ ] migrate_from_mempalace.py dry-run: 270 MB chroma → ~5000 Memory entity (estimate) lossless rapor
- [ ] Kullanıcı son onayı

## 15. Open Questions for User

(Şu an açık kalan tek soru — onay sonrası dispatch başlar)

**Q1:** Plan onaylanırsa A1 dispatch hemen başlasın mı, yoksa Faz 1 öncesi
ek bir review noktası ister misiniz?

**Q2:** MemPalace 30 günlük paralel periyot — SLO yeşil olmasa bile takvim
tetiği var mı (örn. v3.40.0'da review)? Yoksa sadece SLO yeşilse devre dışı?

**Q3:** Diğer 3 projeye patch sırası — vyra'dan sonra (cosmos_mobile, cosmos,
mahsul_mezati) hangisinden başlanmalı?
