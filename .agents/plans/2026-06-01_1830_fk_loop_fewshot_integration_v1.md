---
plan_id: fk_loop_fewshot_integration
created: 2026-06-01
branch: hira
status: in_progress
version_target: v3.44.0
council_mod: 3
hebe_gate_required: false
---

# FK Loop → Few-Shot Entegrasyonu + Tip-Farkında Çok-Dialect Template Motoru

## Context (Neden?)
FK Loop (`fk_synthetic_generator`) gerçek-veriyle doğrulanmış (execute + row_count>0) JOIN/aggregate
örnekleri üretip `learned_db_queries`'e (source='synthetic') yazıyor. Ama bunlar **yalnız cache-hit'e**
yarıyor (generic sorular, düşük eşleşme) — LLM few-shot prompt'una GİRMİYOR. Asıl değer (LLM SQL üretim
doğruluğu) burada hapsolmuş. Ayrıca anlamsız inferred FK'ler (partman/extension) gürültü + başarısız
deneme üretiyor (görselde 2 hata + 16 boş). Kullanıcı: few-shot entegrasyonu + db-türüne göre daha çok
fonksiyon istiyor.

## Mevcut Durum (Explore bulguları — kanıtlı)
- `fk_synthetic_generator._fetch_relationships` (satır 95-130): `ds_db_relationships` okuyor, **schema
  dışlama YOK**, **confidence/is_inferred filtresi YOK** → partman FK'leri render+execute ediliyor.
- Sistem-şema dışlama SSOT'suz dağınık (`pg_catalog/information_schema/pg_toast`; **partman/extension YOK**).
- `few_shot_examples` (mig 014): **`origin`/`is_active` kolonu YOK** → sentetik ayırt/ağırlıklama yapılamıyor.
- `few_shot_selector` (satır 70-74): cold-start — usage_count=0 → priority=0 (sentetik dezavantajlı).
- `few_shot_auto_populator` (gerçek user) + `synthetic_db_query_pairs` (LLM-pair, admin) zaten few_shot'a
  yazıyor; FK Loop YAZMIYOR.
- Template'ler: G1 (LOOKUP_JOIN, AGGREGATE_COUNT) + G3 (CHAIN_JOIN/LATERAL/CTE/STRING_AGG/WINDOW/TIME_SERIES/
  JUNCTION) — G3 **PG-only ve base loop'ta kullanılmıyor**.

## Faz/Gate Haritası (öncelik sırası)

### P0 — Gürültü Temizliği (Konsey: HEPHAESTUS + ORACLE + ARES) [PREREQUISITE]
- SSOT `_EXCLUDED_SCHEMAS` sabiti (system + extension: pg_catalog, information_schema, pg_toast, partman,
  pglogical, cron, repack, ...). `_fetch_relationships` SELECT'ine `from_schema/to_schema NOT IN (...)`.
- Confidence filtresi: declared FK (is_inferred=FALSE) VEYA `confidence_score >= 0.85` (param ile esnek).
  `is_inferred` SELECT'e eklenir.
- Hata şeffaflığı: başarısız denemenin GERÇEK DB hatası `ds_synthetic_query_runs.error_message`'a yazılsın
  (generic "beklenmeyen hata" yerine sınıflandırılmış: permission/type/timeout). UI /synthetic-failures'da göster.
- **Verify:** partman kaynağında re-run → 0 partman denemesi; başarısız=0/anlamlı; failures'da gerçek sebep.

### P1 — Few-Shot Entegrasyonu (Konsey: METIS + PROMETHEUS + HEPHAESTUS)
- **Migration 051:** `few_shot_examples` + `origin VARCHAR(16) DEFAULT 'user'` + `is_active BOOLEAN DEFAULT TRUE`
  (+ schema.py SSOT). Mevcut insert'ler default 'user' alır.
- **Terfi:** `fk_synthetic_generator` başarılı örneği learned_db_queries'e yazarken few_shot_examples'a da
  terfi etsin (`origin='synthetic_fk'`), mevcut 3-katman dedup (sql_hash/cosine/Jaccard) ile. Ortak helper
  (`few_shot_selector.upsert_example` veya auto_populator dedup) — kod tekrarı yok.
- **Selector:** sentetik için taban-priority (cold-start cezasını kır) + gerçeğe göre hafif düşük ağırlık
  (`SYNTHETIC_WEIGHT`); prompt başına sentetik **cap** (max 1-2, gerçeği kovmasın). `origin` kolonuyla.
- **Verify:** FK Loop sonrası few_shot_examples'ta origin='synthetic_fk' kayıtlar; FK-tablolarına dair soruda
  select_few_shots sentetiği seçer (signature match); gerçek örnek varsa onu öncelikler; token cap aşılmaz.

### P2 — Tip-Farkında + Çok-Dialect Template Motoru (Konsey: ORACLE + POSEIDON + METIS)
- **Tip-farkındalık:** template seçimi enrichment `semantic_type` (amount/date/status) + kolon tipiyle —
  SUM/AVG→sayısal kolon, TIME-BUCKET→tarih kolonu. Kör FK işleme YOK (partman TEXT↔TEXT engellenir).
- **Yeni template'ler:** AGGREGATE_STATS (SUM/AVG/MIN/MAX), EXISTS/ANTI-JOIN (orphan/kapsam), TIME-BUCKETED
  (date_trunc+FK), DISTINCT-COUNT. + mevcut G3 (CHAIN_JOIN, LATERAL_TOP_K, WINDOW) base loop'a dahil.
- **Çok-dialect:** her template 4 dialect (PG/Oracle/MSSQL/MySQL) — LIMIT/FETCH FIRST/TOP, date fonksiyonları
  (date_trunc vs TRUNC vs DATEPART vs DATE_FORMAT), STRING_AGG vs LISTAGG vs STRING_AGG vs GROUP_CONCAT.
- **Verify:** her template her dialekte syntax-geçerli üretir; tip-uygun kolon seçer; 4 dialect smoke.

### P3 — Ops (Konsey: NIKE + TYCHE)
- Hata sınıflandırma + metrik (cache-hit oranı, few-shot kullanım, sentetik başarı trendi).
- Keşif/drift sonrası otomatik FK Loop tetik (schedule); job tracker Redis (multi-worker).

## Critical Files
- `app/services/db_learning/fk_synthetic_generator.py` (_fetch_relationships, generate_for_source, terfi)
- `app/services/db_learning/synthetic_templates.py` (template render — tip-farkında + dialect)
- `app/services/rag/few_shot_selector.py` (upsert_example, select_few_shots ağırlık)
- `app/services/db_learning/few_shot_auto_populator.py` (dedup reuse)
- `migrations/versions/051_*.py` (few_shot_examples origin/is_active) + `app/core/schema.py`
- `app/api/routes/db_learning_api.py` (synthetic-failures error transparency)

## Yeniden Kullanılacak Mevcut Fonksiyonlar
- `synthetic_db_query_pairs.py` 3-katman dedup (sql_hash/cosine/Jaccard) — terfi'de reuse.
- `learned_queries_service._embed_question` — embedding.
- `synthetic_templates._quote_identifier/_limit_clause` — dialect quoting (G2 PG-only → genişlet).
- `incremental_schema_integrator` schema exclusion deseni — SSOT'a çek.

## Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Sentetik few-shot gerçeği kovar | Orta | LLM kalite düşer | prompt cap + düşük ağırlık (P1) |
| Anlamsız template (tip uyumsuz) | Yüksek (partman) | başarısız+gürültü | tip-farkındalık (P2) + schema filtre (P0) |
| Migration drift (origin kolonu) | Düşük | eski insert'ler | DEFAULT 'user' + schema.py SSOT |
| Çok-dialect syntax hatası | Orta | execute fail | dialect başına smoke (P2 verify) |

## Verification (uçtan-uca)
- P0: partman re-run → 0 partman; failures gerçek sebep.
- P1: FK Loop → few_shot origin='synthetic_fk'; FK-soruda select_few_shots sentetik seçer; cap korunur.
- P2: 4 dialect × yeni template smoke; tip-uygun kolon.
- pytest (mevcut few_shot/synthetic testleri) yeşil + yeni testler.

## Out-of-scope (sonraki faz)
- few-shot admin onay UI (şimdilik auto-active + düşük ağırlık).
- learned_db_queries cache TTL/pruning revizyonu.
