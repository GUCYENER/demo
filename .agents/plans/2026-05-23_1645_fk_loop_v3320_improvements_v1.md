---
plan_id: fk_loop_v3320_improvements
created: 2026-05-23
branch: hira
status: in_progress
version_target: v3.32.0
council_mod: 3
hebe_gate_required: true
---

# FK Loop İyileştirmeleri — v3.32.0

## Context (Neden bu değişiklik?)

Kullanıcı `DB Öğrenme Loop — ORACLE-LOCAL-TEST` ekranında "FK sürecini incele, tüm FK'ler atlanmadan join'ler doğru üretiliyor mu, 2. tıklama nasıl çalışıyor, çoklama olmamalı, gelişim alanları" diye sorguladı. İnceleme sonucu UNIQ garantileri sağlam (2. tıklama temiz idempotent ✅) ama kapsam ve doğruluk problemleri tespit edildi:

1. **Composite FK kırık (P0):** Multi-column FK'lerin her kolonu ayrı satır olarak `ds_db_relationships`'ta tutuluyor, render template'leri tek-column varsayıyor → Cartesian product riski.
2. **`row_count > 0` enforcement yok (P0):** Docstring söz veriyor ama kod boş sonuçları da öğreniyor; cache şişmesi.
3. **Junction (N:M) template'i FK Loop'tan çağrılmıyor (P1):** `is_junction=TRUE` flag mevcut ama loop bunu okumuyor.
4. **Declared + Inferred FK dedupe yok (P1):** Aynı (from→to) için 2 satır varsa hedef DB'de 2× execute.
5. **Failure circuit breaker yok (P2):** Kalıcı hata her tıklamada yeniden denenir.
6. **Self-ref soru metni mantıksız (P2):** "X tablosundaki kayıtların ilgili X bilgilerini göster".
7. **Cardinality-aware template seçimi yok (P2):** 1:1, 1:N, N:1 ayırt edilmeden her FK'ye aynı 2 template uygulanıyor.
8. **Frontend progress feedback sığ (P2):** Summary objesi `total_fks/success/skipped/failed_*` içeriyor ama UI'da progress bar yok.
9. **Bonus (kullanıcı eklemesi):** `oracle_local_test/docker-compose.yml` VSCode YAML linter uyarıları.

## Mevcut Durum (Explore bulguları)

- [app/services/db_learning/fk_synthetic_generator.py](app/services/db_learning/fk_synthetic_generator.py): `_fetch_relationships` (88-119) tek-satır okuma; `generate_for_source` (225-427) per-FK × per-kind döngü; `_already_succeeded` (123-139) yalnız `success=TRUE` kontrolü.
- [app/services/db_learning/synthetic_templates.py](app/services/db_learning/synthetic_templates.py): `Relationship` dataclass tek-column kolon string; `render_lookup_join`/`render_aggregate_count` tek-column ON clause.
- [app/services/ds_learning_service.py](app/services/ds_learning_service.py): Oracle (886-918), MSSQL (610-637), PG (~408-468 multi-column kısmı dahil), MySQL FK introspect — `constraint_name` yazılıyor ama `fk_position` yok; multi-column FK için her kolon ayrı INSERT.
- [app/api/routes/db_learning_api.py](app/api/routes/db_learning_api.py): `/generate-synthetic-queries`, `/synthetic-status`, `/synthetic-failures` endpoint'leri çalışıyor; summary objesi UI'a dönüyor.
- [frontend/assets/js/modules/ds_learning_module.js#L1620-L1735](frontend/assets/js/modules/ds_learning_module.js): `openDbLearningLoop` + `triggerSyntheticGeneration` + `_startStatusPolling` mevcut; progress UI yok.
- [migrations/versions/003_ds_discovery_tables.py:57-69](migrations/versions/003_ds_discovery_tables.py#L57-L69): `ds_db_relationships` schema — `fk_position` yok.
- [oracle_local_test/docker-compose.yml](oracle_local_test/docker-compose.yml): top-level `cpus`/`mem_limit`/`memswap_limit` + `deploy.resources.limits` duplicate (bilinçli, ama VSCode YAML schema şikayet edebilir).

## Faz/Gate Haritası

| Gate | Konu | Disjoint Dosya Kapsamı | Ajan |
|------|------|------------------------|------|
| G1   | Backend Core — composite FK gruplama, dedupe, circuit breaker, row_count enforcement, cardinality-aware, junction integration, self-ref question | `app/services/db_learning/fk_synthetic_generator.py`, `app/services/db_learning/synthetic_templates.py`, `app/services/ds_learning_service.py`, `migrations/versions/038_v3320_fk_position.py` (YENİ) | Ajan-A |
| G2   | Frontend — progress bar + failure modal UX | `frontend/assets/js/modules/ds_learning_module.js`, opsiyonel `frontend/assets/css/modules/_db_loop.css` | Ajan-B |
| G3   | Tests — composite, dedupe, junction, circuit breaker | `tests/test_fk_loop_improvements.py` (YENİ) | Ajan-C |
| G4   | Docker compose VSCode YAML uyarıları | `oracle_local_test/docker-compose.yml` | Ajan-D |
| G5   | Council Gate (HERMES + ARES + TYCHE + HEPHAESTUS + HEBE) — her ajan output'una uygulanır | (ZEUS doğrudan) | ZEUS |
| G6   | Commit + Code Review | (ZEUS doğrudan) | ZEUS |

## Critical Files to Modify / Create

**Modify:**
- `app/services/db_learning/fk_synthetic_generator.py` (G1)
- `app/services/db_learning/synthetic_templates.py` (G1)
- `app/services/ds_learning_service.py` (G1 — Oracle/PG/MSSQL/MySQL FK introspect'e position eklemek)
- `frontend/assets/js/modules/ds_learning_module.js` (G2)
- `oracle_local_test/docker-compose.yml` (G4)

**Create:**
- `migrations/versions/038_v3320_fk_position.py` (G1)
- `tests/test_fk_loop_improvements.py` (G3)

## Yeniden Kullanılacak Mevcut Fonksiyonlar

- `synthetic_templates.render_junction_n2m` (G1 — junction wiring için zaten hazır)
- `cardinality_analyzer.analyze_relationships` çıktısındaki `cardinality_from/to`, `is_junction` (G1)
- `dedupe_service.sql_hash` (mevcut UNIQ koruma)
- `frontend.showToast` + `.vyra-empty-state` + `_tooltip.css` (HEBE pattern)

## Risk Özeti

| Risk | Olasılık | Etki | Mitigasyon |
|------|----------|------|------------|
| Composite FK gruplama eski single-FK row'larında regression | Orta | Orta | Backfill migration `fk_position=1` default; `_fetch_relationships` constraint_name yoksa fallback `id` ile tek-satır olarak grupla |
| `ds_synthetic_query_runs` UNIQUE eski composite çoklu satırları boşlukta bırakır | Düşük | Düşük | Eski audit satırları DELETE edilmez; yeni run sadece canonical `relationship_id`'ye yazar |
| Junction false-positive (cardinality_analyzer yanlış işaretlemiş) → garip N:M sorgu | Düşük | Düşük | JUNCTION_N2M sadece `is_junction=TRUE AND confidence_score >= 0.7` |
| Migration backfill PG window function PG12 öncesi farklı davranabilir | Çok düşük | Düşük | `ROW_NUMBER() OVER` SQL standart, PG10+ destekli |
| Frontend progress bar polling overhead | Düşük | Düşük | Mevcut 1.5s poll korunur, sadece UI render değişir |

## Verification

```bash
# Migration test
D:\demo_vyra\python\Scripts\python.exe -m alembic upgrade head
D:\demo_vyra\python\Scripts\python.exe -m alembic downgrade -1
D:\demo_vyra\python\Scripts\python.exe -m alembic upgrade head

# Unit tests
D:\demo_vyra\python\Scripts\python.exe -m pytest tests/test_fk_loop_improvements.py -v
D:\demo_vyra\python\Scripts\python.exe -m pytest tests/test_synthetic_db_query_pairs.py tests/test_fk_inference_service.py -q  # regression

# Smoke (manuel)
# 1. ORACLE-LOCAL-TEST üzerinde "Sentetik SQL Üret (FK Loop)" tıkla
# 2. Progress bar görünüyor mu?
# 3. Bitince tekrar tıkla → "tümü atlandı" durumu mantıklı görünüyor mu?
# 4. Composite FK olan tablo varsa (mevcut sample DB'de yoksa script ile ekle) → multi-column ON clause oluşmuş mu?
```

## Out-of-scope (sonraki faza)

- Chain (3+ hop) join'lerin FK Loop'a entegrasyonu — `fk_graph_resolver` orchestrator wiring (ayrı plan)
- LLM-bazlı soru üretimi (sentetik template question_tr'yi LLM ile zenginleştirme)
- Failure log retention/archival
- `cpus`/`mem_limit` legacy top-level vs `deploy.resources` Compose spec resmi dönüş (Docker yön değiştirene kadar bekle)

## Faz Tamamlanma İzleri

- [ ] G1: Backend Core (Ajan-A)
- [ ] G2: Frontend Progress (Ajan-B)
- [ ] G3: Tests (Ajan-C)
- [ ] G4: Docker Compose (Ajan-D)
- [ ] G5: Council Gate her ajan
- [ ] G6: Commit + Code Review
