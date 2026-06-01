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

### P1 — Few-Shot Entegrasyonu (Konsey: METIS + PROMETHEUS + HEPHAESTUS) — ✅ TAMAM (v3.44.0)
- ✅ **Migration 051:** `few_shot_examples.origin VARCHAR(16) DEFAULT 'user'` + `is_active BOOLEAN DEFAULT TRUE`
  (+idx_few_shot_origin/active, idempotent). Mevcut insert'ler default 'user' alır.
- ✅ **Terfi:** `fk_synthetic_generator._promote_to_few_shot` → `few_shot_auto_populator.promote_synthetic`.
  **Kod tekrarı YOK** (code-review REUSE bulgusu): mevcut `_find_duplicate` (L1 normalize + L2 cosine≥0.92),
  `_embed_question` (canonical embedding), `build_schema_signature`, `_insert_new` (vector/array) yeniden
  kullanıldı. Yalnız `learned_db_queries` status='inserted' iken çağrılır; populator dedup'ı farklı FK/kind'in
  aynı sorusunu bump'a indirir (tablo şişmez). origin insert-sonrası `_set_origin` ile işaretlenir.
- ✅ **Selector** (`select_few_shots`): `origin` SELECT + `is_active=TRUE` filtre + cold-start floor
  (`SYNTHETIC_PRIORITY_FLOOR=0.30`) + hafif düşük ağırlık (`SYNTHETIC_WEIGHT=0.85`) + cap
  (`MAX_SYNTHETIC_IN_TOPK=1`, havuz tükenirse fallback doldurur). `_has_origin_columns` yalnız-pozitif cache.
- ✅ **code-review medium (7 angle × verify):** REUSE mimari fix (ilk taslak upsert_example'ı genişletiyordu →
  revert), intent çift-ceza fix (`intent=None`), `_has_origin_columns` kalıcı-False kilidi, `_picked` id()→DB id.
  Sahte-cursor smoke: cap/floor/weight/graceful 4 senaryo yeşil.
- **Verify (canlı, bekliyor):** FK Loop sonrası few_shot_examples'ta origin='synthetic_fk' kayıtlar; FK-tablo
  sorusunda select_few_shots sentetiği seçer; gerçek örnek varsa onu öncelikler; token cap aşılmaz.

### P2 — Tip-Farkında + Çok-Dialect Template Motoru (Konsey: ORACLE + POSEIDON + METIS)

**P2a — ✅ TAMAM (v3.45.0):**
- ✅ **Yeni modül `synthetic_dialect.py`:** `classify_data_type` (numeric/temporal/text/boolean/other,
  4-dialect) + dialect SQL helper'ları (`string_agg` LISTAGG/GROUP_CONCAT/STRING_AGG, `to_day_expr`,
  `current_date_expr`; sep injection-safe).
- ✅ **2 yeni per-FK template (4-dialect):** AGGREGATE_STATS (numeric ölçü COUNT/SUM/AVG/MIN/MAX per
  parent, INNER JOIN deterministik) + EXISTS_ANTI_JOIN (orphan parent, NOT EXISTS + ORDER BY pk).
- ✅ **Tip-keşfi:** `_load_table_columns` (columns_json + is_pk) + `_pick_numeric_measure` (FK/PK/keyish/
  patolojik-ad eler, temiz ölçü yoksa skip → `skipped_no_column`). Default kinds 2→4; 1:1'de yalnız LOOKUP.
- ✅ **code-review:** TR kolon adı over-filter fix (unicode-toleranslı `_safe_measure_name`), is_pk-farkında
  ölçü (anlamsız SUM(id) önlenir), INNER JOIN NULL-sıra, anti-join determinizm, classify bit/varbit. 4
  dialect × composite smoke yeşil.

**P2b — bekliyor:**
- **Mevcut PG-hardcoded template'leri 4-dialect + gerçek kolon:** STRING_AGG_DETAILS (LISTAGG/GROUP_CONCAT
  via `synthetic_dialect.string_agg` + text kolon keşfi), WINDOW_RUNNING_TOTAL (numeric+temporal kolon,
  window fn standart), TIME_SERIES_GENERATE (4-dialect takvim — GENERATE_SERIES/CONNECT BY/recursive CTE
  veya PG-gate). Bu template'ler şu an `d="postgresql"` hardcode → non-PG'de patlıyor + kolon TAHMİN ediyor.
- **Altitude (code-review notu):** col_ctx tip-gate'i generator if-chain + render ValueError'da İKİ yerde —
  P2b'de "kind→gerekli col_ctx anahtarları" tablosuyla genelleştir (yeni tip-bağımlı kind tek yerde tanımlansın).
- **DISTINCT-COUNT / TIME-BUCKETED** (opsiyonel, ek değer).
- **Verify:** her template her dialekte syntax-geçerli; tip-uygun kolon; 4 dialect smoke.

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
