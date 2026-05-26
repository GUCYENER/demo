---
project: vyra
graphify_version: 1.0
schema_version: 4
ontology_version: 1.0
generated_at: 2026-05-25T23:48+03:00
db_path: C:\Users\EXT02D059293\.graphify\instances\vyra.db
db_size_mb: 1.15
last_git_mark: 8891f714084f35d4bd2a0960cdadcb3f484b0c8d
last_md_mark: 2026-05-25T18:48:21+00:00
---

# Graphify VYRA — Yapı Raporu

Bu rapor, [`d:\demo_vyra\.agents\reports\graphify.htm`](graphify.htm) ile birlikte okunur. HTML görsel; bu MD özet + metrikler.

## 1. Genel Durum

| Metrik | Değer | Cap / Hedef |
|--------|-------|-------------|
| entities | **676** | (soft cap yok) |
| triples | **1453** | entity başına ≤ 500 (pruning v1.1) |
| DB boyutu | **1.15 MB** | < 100 MB soft cap |
| schema_version | 4 | forward-only migration |
| ontology_version | 1.0 | core.yml |
| last_git_mark | `8891f71` | son commit indexed |
| last_md_mark | 2026-05-25T18:48 UTC | markdown adapter çıktısı |

## 2. Entity Dağılımı

| Type | Count | Açıklama |
|------|------:|----------|
| File | 345 | git tracked files (Markov/JS/CSS/Python) |
| Commit | 100 | git log adapter ile mined |
| Plan | 92 | `.agents/plans/` markdown adapter |
| Decision | 86 | commit msg → Decision entity (council='git_inferred') |
| BenchProbe | 30 | Faz 4 benchmark golden queries |
| Person | 9 | git author (reviewed_by) |
| Project | 1 | VYRA root (Project entity) |
| **TOPLAM** | **663** | (+13 yeni Graphify v1 commit'inden) |

> Mine sonrası **+13 entity, +26 triple** — Graphify v1 commit'i (8891f71) ve dokunduğu 12 dosya.

## 3. Predicate Dağılımı

| Predicate | Count | Domain → Range |
|-----------|------:|----------------|
| refactors | 662 | Commit → File |
| lives_in | 345 | File → Project |
| belongs_to | 278 | Function/Plan/Decision → File |
| has_status | 92 | Plan → str |
| related_to | 24 | Plan ↔ Plan (cross-link) |
| has_version_target | 17 | Plan → str (vX.Y.Z) |
| reviewed_by | 9 | Commit → Person |
| **TOPLAM** | **1427** | (+26 yeni → 1453) |

## 4. En Son Aktivite

| # | Entity | Type | Note |
|---|--------|------|------|
| 1 | `8891f71` | Commit | Son commit: Graphify v1 + workflow integration |
| 2 | `feat:8891f71` | Decision | Auto-derived Decision (council='git_inferred') |
| 3 | `2026-05-25_2350_graphify_workflow_integration_vyra.md` | Plan | Faz 6 brief done/ |
| 4 | `2026-05-25_2359_graphify_workflow_integration_sisters.md` | Plan | Faz 7 brief done/ |
| 5 | `2026-05-25_2100_general_graphify_hybrid_setup_v1.md` | Plan | Ana plan |

## 5. Sağlık & Sınırlar

- **Pruning policy** (v1.1): entity başına soft cap 500 edge. Şu an en yüksek edge'li entity için durum görmek istersen `graphify_traverse(start="vyra", depth=1)` çağır.
- **Token caps** (per MCP tool): warmup 50 / wakeup 700 / search 1500 / mine 800 / status 200 / add_decision 200 / traverse 1000
- **Predicate whitelist** enforced — `add_triple` validation policy = `warn` (v1 bootstrap)
- **Cross-instance query**: v2 deferred (federated query API + materialized union — [ontology/README.md](../../C:/Users/EXT02D059293/Documents/General_Graphify/ontology/README.md))

## 6. Workflow Entegrasyonu

| Dosya | Branch | Durum |
|-------|--------|-------|
| `.agents/workflows/vyrazeus.md` | hira | Patched +51 satır (5 patch + KAP 10c) |
| `D:\COSMOS\.claude\commands\zeus.md` | — | Patched +36 satır (ADIM 0b/10c) |
| `D:\Cosmos_Mobile\.agents\workflows\mobilzeus.md` | — | Patched +29 satır (3 patch) |
| `D:\Mahsul Mezati\.claude\commands\zeus.md` | — | Patched +33 satır (ADIM 0b/10c) |

VYRA commit: `8891f71` (hira). Sister repos uncommitted (kullanıcı kararı bekleniyor).

## 7. Benchmark (Real VYRA, p95)

| Metric | p95 | Target | Margin |
|--------|----:|-------:|-------:|
| graphify_wakeup | 0.326 ms | < 3000 ms | **9000×** |
| graph search | 0.691 ms | < 10 ms | 14× |
| hybrid search | 0.502 ms | < 200 ms | 400× |
| disk | 1.2 MB | < 10 MB | 8× |

> Faz 4 benchmark çıktısı — 5 iter, real DB. MAP@3=0.0 (golden query refinement v1.1).

## 8. Komutlar

```bash
# DB durumu
python -m core.cli status --project vyra

# Son commit'i mine et
python -m core.cli mine --project vyra

# Mermaid graph üret (genel)
python "C:/Users/EXT02D059293/Documents/General_Graphify/tools/visualize.py" \
  --project vyra --format mermaid --max-nodes 80 \
  --output d:/demo_vyra/.agents/reports/graphify.mmd

# Bir entity'den BFS
python "C:/Users/EXT02D059293/Documents/General_Graphify/tools/visualize.py" \
  --project vyra --focus-entity "2026-05-25_2100_general_graphify_hybrid_setup_v1.md" \
  --depth 2 --format mermaid \
  --output d:/demo_vyra/.agents/reports/graphify_plan_focus.mmd
```

## 9. Bilinen Boşluklar / TODO

- [ ] Pruning automation (v1.1): `tools/prune.py` scheduled job
- [ ] MAP@3 = 0 — golden queries gerçek entity isimleriyle eşleşmiyor; refinement v1.1
- [ ] Cross-instance federated query API (v2)
- [ ] Identity reconciliation: Person canonical name/email cross-link (v2)
