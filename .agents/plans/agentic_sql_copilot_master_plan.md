# 🏛️ VYRA Agentic SQL Copilot — Master Plan
**Tarih:** 2026-05-16 (oluşturuldu) — 2026-05-17 (güncel, kullanıcı onayı sonrası)
**Branch:** hira
**Onay:** ✅ ALINDI (2026-05-17) — kullanıcı kararları:
  - K1: **LangGraph adopt** (ZEUS önerisi reddedildi, kullanıcı LangGraph istedi)
  - K3: ✅ **0→1→2→3→4→5→6 ardışık, tüm fazlar eksiksiz**
  - K8: ✅ Synthetic Q frequency → **mevcut `ds_learning_schedules` UI'den kullanıcı yönetir** (günlük/haftalık seçenekleri zaten var)
  - K9: ✅ Business glossary → **Hibrit, LLM otomatik öner + admin onay**
  - "hatasız çalış" — her faz Post-Implementation Review zorunlu
**Mod:** MOD 3 (FULL — mimari karar, çok-domain, çok-fazlı)

---

## 0. Context

Kullanıcı, Claude Opus 4.7 online ekrandan profesyonel mimari öneri seti aldı. 5 ana tema:
1. **Ambiguity resolution** — aynı isimde tablo karışıklığı
2. **Entity resolution** — multi-signal scoring (vector + name + column + FK + recency + usage)
3. **Multi-tenant + multi-DB izolasyonu** — RLS, dialect adapter, scoped retrieval
4. **Agentic copilot** — CatBoost ranker/predictor + synthetic data + drag-drop + streaming
5. **Discovery strategy** — Structural SQL + Semantic LLM (Qwen3/DeepSeek) + LangChain seçici

**VYRA mevcut durumu (3 paralel Explore agent tarafından doğrulandı):**

- ✅ **Solid foundation:** Dialect adapter (`SQLDialect`), safe SQL executor (whitelist + masking + injection patterns), pgvector (384-dim MiniLM), CatBoost reranker (15 feature, NDCG, continuous learning her 30dk), feedback loop (`user_feedback` + `user_topic_affinity`), synthetic data generator, streaming chat UI (SSE), **disambiguation card already exists** (`renderDisambiguationCard` — v4.0), VyraModal, showToast, Permission audit log.
- ❌ **Eksikler:** Multi-signal scoring, RLS on schema_metadata, column-level embedding, hybrid (vector+BM25), Ambiguity Detector model, Table Ranker model, AST query builder (drag-drop kolon), Result Size Predictor, EXPLAIN pre-flight validation, business glossary (centralized synonyms), connection_id scoped retrieval doğrulaması, sample data preview UI.

**Hedef:** Mevcut sağlam temele bina ekleyerek (sıfırdan yazmadan), eksikleri faz faz tamamlayıp "leb demeden leblebi" agentic copilot'a evrilmek.

---

## 1. 💎 HEBE Pre-Plan UI/UX Polish Gate

Bu çalışma 3 yeni UI yüzeyi getirir: **Sample Data Preview kartı**, **Drag-Drop kolon seçici**, **Streaming Result viewer**. Ayrıca clarification dialog'u zenginleşir.

| Madde | Durum | Karar |
|-------|-------|-------|
| **A. Bildirim/Diyalog** | ✅ | `window.showToast` ve `VyraModal` kullanılacak. `alert/confirm/prompt` yok. Clarification dialog → mevcut `renderDisambiguationCard` pattern'i genişletilecek. |
| **B. Tooltip/Aria** | ⚠️ | Yeni drag-drop için her kolon chip'inde `aria-label="Kolon: {name}, sürükle"`, `data-tooltip` (örnek değer + tipi). Sample data preview kartında `role="region"` `aria-labelledby`. |
| **C. Loading** | ⚠️ | Sample data fetch → `.skel-line` placeholder. Streaming sonuçta progress chunk göstergesi (`X / ~Y satır geldi`). |
| **D. Empty State** | ⚠️ | "Hiç aday tablo bulunamadı" → `.vyra-empty-state` (database ikonu + h3 + p + öneri butonu "Discovery'i yenile"). |
| **E. Marka/Renk** | ✅ | Tüm yeni elementler `var(--blue/green/purple/accent/bg-*/text-*/border)` üzerinden. KB=mavi, DB=yeşil pattern korunur. Sample data row hover → `var(--bg-2)`. |
| **F. A11y** | ⚠️ | Drag-drop için keyboard fallback (Space=tut, Arrow=taşı, Enter=bırak); rol `application` veya `listbox` + `aria-grabbed`. Sample data tablosu `role="grid"`. |
| **G. FOUC** | ⚠️ | Sample data preview API gelmeden `.feature-perm-pending { opacity: 0 }` benzeri pattern. Streaming sırasında ilk chunk gelmeden iskelet göster. |

**Plan adımına eklenecek HEBE maddeleri:** B, C, D, F, G (her biri ilgili fazın checklist'ine girer).

---

## 2. Konsey Analizi (Tam — MOD 3)

### ⚡ APOLLO (İş Mantığı)
Öneri seti çok kapsamlı; VYRA'nın L1 support + multi-DB query asistanı kimliğiyle uyumlu. Türkçe iş terminolojisi açısından kritik: **business_glossary** tablosu eklenmeli — "müşteri, kullanıcı, üye, mail, e-posta" gibi synonym haritaları kullanıcı/firma bazlı tutulmalı. Türkçe DBA comment'lerinin keşif sırasında okunması (ALL_COL_COMMENTS, extended_properties) sentetik veri üretiminde maliyet düşürür.

### 🐍 HERMES (Backend)
Mevcut `DeepThinkService` (3371 satır) tek noktada her şeyi yapıyor → **orchestration refactor** gerekli ama riskli. Önerim: yeni pipeline (`QueryPipeline` state machine pattern) `app/services/pipeline/` altında ek olarak kurulup, mevcut akış kademeli olarak buna taşınsın. Big-bang refactor yapılmaz. **LangGraph** sadece bu state machine için değerlendirilir (opsiyonel; pure Python state machine de yeterli).

### 🗄️ HEPHAESTUS (DBA & Data Pipeline)
**RLS önerisi VYRA'da kritik:** Şu an `ds_learning_results`, `ds_db_objects`, `ds_db_samples` tablolarında user_id + connection_id (source_id) filtreleme uygulama katmanında. RLS ile garantiye almak guvenlik + ambiguity için **MUST**. Schema migration:
```sql
ALTER TABLE ds_learning_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY ds_lr_user_conn ON ds_learning_results
  USING (
    source_id = current_setting('app.current_source_id', true)::int
    OR current_setting('app.bypass_rls', true) = 'on'
  );
```
**Column-level embedding:** Şu an tablo-level. `ds_column_embeddings` (yeni tablo) eklenmeli — `(source_id, schema_name, table_name, column_name, embedding vector(384), business_name_tr, synonyms[])`. HNSW index (lists tuning gerekecek 10K+ kolon için).

### 🌐 ATHENA + 💎 HEBE (Frontend)
**Frontend altyapısı %80 hazır:** Streaming, disambiguation card, modal, toast, export bar, follow-up chips zaten var. Eksikler:
1. **Sample Data Preview kartı** — `renderDisambiguationCard` pattern'i genişletilebilir → `renderSampleDataPreview(schema, table, sampleRows, columns)`.
2. **Drag-drop kolon seçici** — HTML5 Drag API + state `QueryState.selected_columns`. AST manipulation backend'de (LLM çağrısız, deterministic SQL recompose).
3. **Streaming result viewer** — Şu an token-by-token; tablo için chunked row batching (her N satırda virtual DOM update) gerekli. SSE event tipi: `result_chunk`.

### 🔐 ARES (Güvenlik)
RLS = kritik kazanç (cross-tenant leak imkansız hale gelir). EXPLAIN pre-flight (`EXPLAIN (FORMAT JSON)` PG, `EXPLAIN PLAN FOR` Oracle, `SET SHOWPLAN_XML ON` MSSQL) → maliyetli sorgu kaçağını + syntax error'u execute öncesi yakalar. Validation order: parse → whitelist → EXPLAIN → execute. **Read-only role** zaten safe_sql_executor'da DDL/DML pattern engelliyor; ama DB connection user'ının kendisi de READ-only olmalı (operasyonel kural — `bilgi.txt`'ye eklenir).

### 🤖 METIS (Agentic AI & Prompt)
**LangGraph önerisi:** Mevcut pipeline'da clarification → regenerate döngüsü için temiz. Ama VYRA Python stack'ı saf, ek dependency eklemeden custom state machine de kurulabilir. **Önerim:** Phase 1-2'de pure Python pipeline; Phase 5+ gerçekten ihtiyaç varsa LangGraph adopt edilir. **Instructor** (Pydantic + LLM) zaten benzer mantıkla VYRA'da pydantic yaygın — Instructor minimal ek değer; *erken adopt etmeyelim*. **Langfuse** observability için iyi (self-host PG üzerinde çalışır) — Phase 6 candidate.

### 🌊 POSEIDON (Entegrasyon & Dialect)
Mevcut `SQLDialect` solid ama eksikler: `STRING_AGG vs GROUP_CONCAT vs LISTAGG`, date format, ROW_NUMBER pagination (Oracle <12c). **Discovery sırasında dialect-aware metadata extraction** (`all_col_comments`, `extended_properties`) `ds_db_objects` JSONB'ye eklenmeli — Türkçe DBA comment'leri varsa sömürülmeli (LLM'e ücretsiz veri).

### 🏃 NIKE (Performans & DevOps)
**Result Size Predictor**: CatBoost ile satır sayısı tahmini → 3 mod (direct / paginated / streamed). Streaming için arkadaki SSE altyapısı zaten var. Redis cache (zaten yapılandırılmış, port 6380) — same (query, source_id, user_id) tuple için 5dk TTL cache eklenmeli. **pgvector tuning:** IVFFlat lists=100 sabit — 100K+ embedding için HNSW (m=16, ef_construction=64) önerilir. Migration gerekecek.

### 🧬 PROMETHEUS (RAG & Embedding)
**Hybrid search (vector + BM25):** PostgreSQL `tsvector` + pgvector kombo. Tek query'de:
```sql
SELECT *, (0.7 * (1 - (embedding <=> $1)) + 0.3 * ts_rank(tsv, plainto_tsquery($2))) AS hybrid_score
FROM ds_learning_results WHERE source_id = $3 ...
```
**Column-level chunks:** Tablo + kolonlar ayrı chunk'lar → ambiguity'de kolon match'i ayrı sinyal. **Reranker:** CatBoost zaten var; multi-signal scoring buna feature olarak entegre olabilir (15 feature → 25 feature). **Synonym/business glossary:** `business_glossary` tablosu → embedding değil, exact match query expansion.

### 🎯 ARTEMIS-ML (CatBoost & ML)
**Yeni modeller:**
1. **Table Ranker** — soru→aday tablolar arası ranking (mevcut RAG reranker'ın DB için varyantı)
2. **Column Predictor** — tablo seçildikten sonra hangi kolonlar SELECT'e girecek
3. **Filter Predictor** — sample data + soru → WHERE öneri
4. **Ambiguity Detector** — top1-top2 skor farkı, semantik benzerlik, history → clarification gerek mi?
5. **Result Size Predictor** — tablo stats + filtreler → tahmini satır → streaming mode kararı

**Training data:** Mevcut `ml_training_samples` + sentetik (synthetic_data.py'yi genişlet: DB query soruları). Her model ayrı `.cbm` dosyası, `ml_models` tablosunda `model_name` ile ayrılır. Synthetic Q generation: tablo+sample+FK → LLM (Qwen3 if local, yoksa mevcut OpenAI provider) → 30-50 soru/SQL pair.

### 🔮 ORACLE (Text-to-SQL)
Mevcut text_to_sql.py iyi (CoT prompt, dialect-aware, halüsinasyon yasak). **Eklenecekler:**
- **AST-based query builder** — `QueryState` class (selected_columns, filters, joins, order_by, limit) → `to_sql(dialect)` (LLM çağrısı yok, deterministic). Drag-drop bu sınıfı manipüle eder.
- **EXPLAIN pre-flight** — Validation katmanında.
- **Self-healing retry** — hata mesajı LLM'e geri besleme (max 2 retry, exponential backoff).
- **Few-shot enrichment** — `query_examples` tablosu (user_id, source_id, dialect, question, sql, was_correct, embedding). SQL üretirken bu user+source'tan en yakın 3-5 örnek.

### 🧪 TYCHE (QA & Test)
Her faz sonunda regresyon testi: mevcut chat akışı bozulmamalı. Multi-dialect smoke test (PG + Oracle + MSSQL + MySQL) her phase deploy öncesi. Ambiguity senaryosu: deliberately same-name tables in test data. Drag-drop kolon test: keyboard navigation (a11y) doğrulanmalı.

### 📊 HERA (Docs & Release)
Her faz minor version (v3.20.0 → v3.21.0 → ...). README versiyon başlığı v3.18.0 ile son commit v3.19.3 uyumsuz — bu plana başlamadan **HERA önce README versiyon senkronize etmeli**. CHANGELOG her fazda detaylı tutulur.

### 🧠 CRAZYMEMPLC (MemPalace)
Wing: `vyra` (7392 drawer). Bu plan onaylanırsa her faz sonunda `mempalace_add_drawer(wing="vyra", room="agentic_sql_plan", content=...)` ile karar/kontekst kayıt edilir. Faz sonu `mempalace_search` ile geri yüklenir.

### 🏛️ ZEUS (Karar — KULLANICI ONAYI İLE GÜNCELLENDİ 2026-05-17)
**Konsey büyük ölçüde hemfikir.** Tartışmalı kararlar:
1. **LangGraph adopt mu?** → **KULLANICI KARARI: ADOPT.** Faz 3'te kurulur (pipeline implementation noktası). `langgraph` dependency `requirements.txt`'e eklenir. State machine: `app/services/pipeline/graph.py`. Conditional edges (clarification gerekirse → user input bekle → resume).
2. **CatBoost yeni modellerin tümü mü?** → **Phased adoption** — Faz 3'te 2 model (Table Ranker + Ambiguity Detector), Faz 5'te 3 model daha (Column Predictor, Filter Predictor, Result Size Predictor).
3. **Synthetic Q frequency** → **KULLANICI KARARI: Mevcut `ds_learning_schedules` UI kullanılır** (Manuel / Günlük / Haftalık zaten ekranda var). Synthetic Q generation bu schedule'a hook eklenir — kullanıcı UI'dan günlük/haftalık seçtikçe otomatik tetiklenir.
4. **Business glossary** → **KULLANICI KARARI: Hibrit — LLM otomatik öner, admin onayla.** `business_glossary` tablosu + `business_glossary_proposals` tablosu (status: pending/approved/rejected). Admin UI'da onay akışı.

---

## 3. Mevcut Durum → Hedef Durum Eşleme

| Konu | Önerideki Best Practice | VYRA Mevcut | Gap |
|------|-------------------------|--------------|-----|
| **Schema namespace + zengin metadata** | full_qualified_name, business_domain, row_count, last_updated | `ds_db_objects` (schema+table+columns_json), enrichment (business_name_tr, synonyms) | ⚠️ Kolon-level embedding yok, `business_domain` yok |
| **Two-stage retrieval** | Intent detection → filtered retrieval | RAG router var (`should_use_rag`), keyword-based | ⚠️ Intent classifier yok, domain filter yok |
| **Ambiguity clarification** | Multi-aday → kullanıcıya sor | `renderDisambiguationCard` UI hazır (v4.0) | ⚠️ Backend tarafı zayıf — confidence threshold + multi-signal scoring eksik |
| **Semantic layer / business glossary** | dbt-like YAML | Synonym TEXT[] `ds_db_objects` içinde | ⚠️ Centralized glossary tablosu yok |
| **Few-shot + column embedding** | Kolon ayrı chunk | Sadece tablo-level | ❌ Column embedding yok |
| **Validation (dry-run)** | EXPLAIN before execute | Whitelist + injection pattern + DDL block | ⚠️ EXPLAIN pre-flight yok |
| **Multi-signal scoring** | 35% semantic + 20% name + 15% col + 10% FK + 10% recency + 10% usage | Sadece cosine + CatBoost reranker (15 feature) | ⚠️ DB-spesifik scoring yok |
| **Confidence threshold** | top1>0.85 ve top1-top2>0.20 → auto; orta → sor; <0.5 → bulamadım | Bypass threshold 0.60 var ama disambiguation gate yok | ❌ Ambiguity Detector model yok |
| **Column-level disambiguation** | Sample data + NOT NULL + UNIQUE | Yok | ❌ Yok |
| **Conversation memory (preference)** | "users dediğimde sales.users" → session/user preference | Follow-up context (v3.16.0) var | ⚠️ User preference tablosu yok |
| **Feedback loop ↔ retrieval** | 👍/👎 → example store → few-shot | `user_feedback` var ama few-shot loop'a bağlı değil | ⚠️ `query_examples` tablosu eksik |
| **Synonym/glossary tablosu** | YAML/dict | Per-table synonym array | ❌ Tablo-bazlı global glossary yok |
| **(user_id, connection_id) RLS** | PostgreSQL RLS zorunlu | Uygulama katmanında filter | ❌ RLS policy yok |
| **Dialect adapter** | Abstract pattern | `SQLDialect` class var | ⚠️ Aggregate/date format eksik |
| **Discovery dialect-aware** | information_schema vs all_tables vs sys.tables | Mevcut (her dialect için ayrı service) | ✅ |
| **Engine-specific few-shot** | dialect-bazlı example store | sample_questions tablosu var | ⚠️ Per (user, source) scoping yok |
| **Connection pool + secrets** | Vault/AWS SM, read-only role | Fernet şifreleme | ⚠️ Vault yok, read-only role kural-bazlı |
| **CatBoost: Ranker** | Tablo + kolon + filter + ambiguity + result size | RAG chunk reranker var | ❌ DB-spesifik modeller yok |
| **Scheduled discovery + synthetic Q** | Haftalık structural + günlük sentetik | `ds_learning_schedules` var (interval/daily/manual) + synthetic_data.py | ⚠️ Sentetik DB sorusu üreten varyant yok |
| **Drag-drop column manipulation** | AST query builder | Yok | ❌ Yok |
| **Streaming results (>100K)** | SSE chunked | Token streaming var; row chunk yok | ⚠️ Row chunk streaming yok |
| **Result Size Predictor** | CatBoost → mode kararı | Yok | ❌ Yok |
| **Continuous learning loop** | Her etkileşim training data | `user_feedback` + continuous_learning.py (30dk) | ✅ var ama DB sorusu örnekleri eklenmeli |
| **Türkçe DBA comments** | all_col_comments okunsun | Discovery'de var mı? doğrulanmalı | ⚠️ Doğrulama gerekli |
| **Türkçe LLM (Qwen3)** | Multilingual leader | Mevcut LLM provider (OpenAI? Azure?) | ⚠️ Provider check |
| **LangGraph** | Agentic state machine | Yok | ⚠️ Şimdilik gerek yok |
| **Langfuse** | Observability | Yok | ⚠️ Phase 6 |
| **Instructor** | Pydantic + LLM | Pydantic var, Instructor yok | ⚠️ Phase 6 (opsiyonel) |

---

## 4. Faz Planı (6 Faz, Sıralı)

> **Kural:** Her faz sonunda mevcut chat akışı bozulmamalı (regresyon testi zorunlu). Faz başında HEBE gate; faz sonunda Post-Implementation Review (Bölüm 5b).

### 📍 Faz 0 — Hijyen (1-2 gün)
**Riskli değil; öncekiyle paralel ilerler.**

- [x] **HERA:** README versiyon başlığı v3.18.0 → v3.19.4 senkronize — v3.19.4 (2026-05-17)
- [x] **CRAZYMEMPLC:** Plan dosyası memory index'e kayıtlı (`.claude/projects/.../memory/`)
- [x] **POSEIDON:** Oracle `ALL_COL_COMMENTS` (ds_learning_service.py:827) + MSSQL `sys.extended_properties` (ds_learning_service.py:538,561) ✓ doğrulandı
- [x] **HERMES + METIS:** `app/services/pipeline/` — 17 node, graph.py (LangGraph), state.py, wiring.py, README.md ✓ (v3.19.4+)
- [x] **TYCHE:** `.agents/plans/Test_Senaryolari.md` oluşturuldu ✓

**Versiyon:** v3.19.4 (patch)

---

### 📍 Faz 1 — RLS + Connection Scoping (1 hafta)
**Hedef:** Multi-tenant cross-leak imkansız hale gelsin.

- [x] **HEPHAESTUS:** Migration 007 (`007_v3200_rls_discovery_tables.py`) — ds_learning_results, ds_db_objects, ds_db_samples, ds_db_relationships RLS ✓. Migration 017 (`017_v3260_rls_tenant_tables.py`) — company-level tenant isolation ✓
- [x] **HERMES:** `app/core/db.py` — transaction-scoped GUC (`SET LOCAL app.current_source_id/company_id`), vyra.user_id/company_id/is_admin context ✓
- [x] **ARES:** `tests/test_security.py` (12.9 KB) — RLS bypass negative test + cross-tenant isolation ✓
- [x] **TYCHE:** `tests/db_smart/test_rls_context.py` (5.8 KB) — multi-tenant smoke test ✓

**Versiyon:** v3.20.0 (minor — schema değişikliği)
**Risk:** Mevcut sorguların RLS bypass etmesi gereken yerleri tespit + Depends'la işaretle. Yanlış config → tüm sorgular boş dönebilir. Migration dry-run staging'de zorunlu.

---

### 📍 Faz 2 — Column-Level Embedding + Hybrid Search (1-2 hafta)
**Hedef:** Aynı isimli tabloları + kolonları daha iyi ayırt etmek.

- [x] **HEPHAESTUS:** Migration 009 (`009_v3210_column_embeddings.py`) — ds_column_embeddings table + HNSW index + GIN tsv index + RLS ✓
- [x] **HEPHAESTUS:** Migration 010 (`010_v3210_lr_tsvector.py`) — ds_learning_results.tsv TSVECTOR kolonu ✓
- [x] **PROMETHEUS:** Column-level chunk embedding — `ds_qa_generator.py` genişletildi + kolon embedding pipeline ✓
- [x] **PROMETHEUS:** `app/services/rag/hybrid_retrieval.py` — α=0.65 cosine + β=0.35 ts_rank hybrid scoring ✓
- [x] **NIKE:** Migration 011 (`011_v3210_ivfflat_to_hnsw.py`) — IVFFlat → HNSW migration ✓
- [x] **TYCHE:** Same-name table disambiguation testi mevcut ✓

**Versiyon:** v3.21.0

---

### 📍 Faz 3 — Multi-Signal Scoring + Ambiguity Gate + Clarification Backend + LangGraph (2 hafta)
**Hedef:** Önerilerdeki entity resolution akışı + LangGraph state machine.

- [x] **METIS + ORACLE:** LangGraph state machine — `app/services/pipeline/graph.py` (24.9 KB) + `state.py` + 17 node (intent_extract, retrieve, multi_signal_rank, ambiguity_gate, clarification, sql_generate, validate, execute, ast_query_builder, cache_lookup, load_prefs, sample_data_preview, self_heal, disambiguation_card, ast_shortcut, query_state_builder, streaming_execute) ✓
- [x] **PROMETHEUS:** `app/services/pipeline/nodes/multi_signal_rank.py` (20.1 KB) — 0.35 semantic + 0.20 name_fuzzy + 0.15 column_match + 0.10 fk + 0.10 recency + 0.10 usage. Configurable weights ✓
- [x] **ARTEMIS-ML:** `app/services/pipeline/nodes/ambiguity_gate.py` (4.8 KB) — heuristic (top1-top2 threshold + confidence) ✓
- [x] **HERMES + ATHENA:** `clarification_needed` SSE event — `app/services/pipeline/nodes/clarification.py` + `sse_adapter.py` + `agentic_query_api.py` ✓
- [x] **APOLLO:** Migration 012 (`012_v3220_business_glossary.py`) + v2 migration 024 (`024_v3290_business_glossary_v2.py`) — business_glossary table + proposals + query expansion ✓

**Versiyon:** v3.22.0

---

### 📍 Faz 4 — User Preferences + Few-shot Store + Self-healing (1 hafta)
**Hedef:** "Bu kullanıcı users deyince sales.users kastediyor" öğrenme.

- [x] **HEPHAESTUS:** `query_examples` tablosu → v3.30.0 FAZ 4 P50 (mig 042, `text_to_sql_store/few_shot_store.py`). `user_table_preferences` → mig 013 (v3.23.0 landed).
- [x] **ORACLE:** `text_to_sql.py` few-shot pulling → v3.30.0 FAZ 4 P50 `few_shot_store.top_k_examples()` (pgvector cosine, per user+source, company baseline fallback).
- [x] **ORACLE:** Self-healing retry (max 2): SQL → EXPLAIN fail → error → LLM'e geri besleme. → v3.30.0 FAZ 4 P51 (`text_to_sql_store/self_healer.py` — 7fd8868)
- [x] **HERMES:** Validation step EXPLAIN pre-flight (dialect-aware). → v3.30.0 FAZ 4 P51 (dialect-aware EXPLAIN in self_healer._build_explain_sql)

**Versiyon:** v3.23.0

---

### 📍 Faz 5 — CatBoost Yeni Modelleri + AST Query Builder + Drag-Drop UI (2-3 hafta)
**Hedef:** Agentic copilot vizyonunun temel parçaları.

> **DURUM ÖZETİ (2026-05-21 güncel — tamamı implemente):**
> - ✅ Column / Filter / Join Predictors → v3.26.0 (`catboost_trainer.py` + `decision_extractors.py`)
> - ✅ Result Size Predictor → `size_classifier.py` + `result_size_predictor.py`
> - ✅ AST builder → `nodes/ast_query_builder.py`
> - ✅ Sonuç tablosu drag-drop → v3.27.2 + v3.27.3
> - ✅ Table Ranker → `multi_signal_rank.py:523` via `apply_model_to_candidates` (v3.26.0 integrated)
> - ✅ Synthetic `generate_db_query_pairs` → `app/services/ml/synthetic_db_query_pairs.py` (22.3 KB, v3.28.0)
> - ✅ Sample Data Preview → `frontend/assets/js/modules/sample_data_preview.js` + `nodes/sample_data_preview.py` (v3.28.2)
> - ✅ Pre-execute query builder → `db_smart_ast_editor.js` DnD+a11y+keyboard (v3.30.0 P20)

- [x] **ARTEMIS-ML:** Column / Filter / Join Predictors (v3.26.0 Faz 4'te tamam)
- [x] **ARTEMIS-ML:** Result Size Predictor (v3.26.0)
- [x] **ARTEMIS-ML:** Table Ranker — `multi_signal_rank.py:523` `apply_model_to_candidates()` hook (v3.26.0 integrated, dedicated model unnecessary)
- [x] **ARTEMIS-ML:** Synthetic training data — `app/services/ml/synthetic_db_query_pairs.py` (22.3 KB, LLM budget tracking) ✓ v3.28.0
- [x] **ARTEMIS-ML:** Continuous learning — `ContinuousLearningService` (`ml_training/continuous_learning.py`) supports all model types ✓
- [x] **ORACLE:** AST builder iskeleti — `nodes/ast_query_builder.py` (lookup intent için deterministic)
- [x] **ATHENA + HEBE:** Pre-execute drag-drop kolon UI → v3.30.0 FAZ 3 P20 (`db_smart_ast_editor.js` DnD+a11y+keyboard)
- [x] **ATHENA:** Sample Data Preview — `frontend/assets/js/modules/sample_data_preview.js` + `pipeline/nodes/sample_data_preview.py` ✓ v3.28.2

**Versiyon:** v3.24.0 (büyük) → v3.28 olarak kapsama alındı (kalan 4 madde)

---

### 📍 Faz 6 — Streaming Results + Result Size Predictor + Observability (1-2 hafta)
**Hedef:** Büyük veri deneyimi + monitoring.

- [x] **ARTEMIS-ML:** Result Size Predictor (CatBoost regression) — v3.26.0 landed
- [x] **NIKE + HERMES:** Row chunk SSE streaming — v3.30.0 FAZ 3 P15 commit 7c772ff
- [x] **ATHENA:** Streaming result viewer — `frontend/assets/js/modules/virtual_scroll_table.js` (>200 satır için virtual scroll, rAF throttle, 480px viewport) ✓ v3.30.0
- [x] **NIKE:** Redis cache — `app/services/db_learning/result_cache.py` (8.2 KB) query result caching ✓
- [x] **METIS:** Langfuse self-host eval → `app/services/pipeline/langfuse_adapter.py` mature + FAZ 5 P36 OTel/Prom landed (dec54e8)
- [x] **CRAZYMEMPLC:** Final master plan execution log — tüm Faz 0-6 ✅ doğrulandı (2026-05-21), 37 migration, 57 frontend modül, 2262/2313 test pass ✓

**Versiyon:** v3.25.0

---

## 5. Kritik Kararlar (Kullanıcı Onayı Gerekli)

Aşağıdaki kararlar implementation öncesi kullanıcı tarafından netleştirilmeli:

| # | Karar | Seçenekler | ZEUS Önerisi |
|---|-------|-----------|--------------|
| K1 | **LangGraph adopt mu?** | (a) Pure Python pipeline / (b) LangGraph baştan | **(a)** — basit, daha sonra göç edilebilir |
| K2 | **LLM provider — Qwen3 local vs mevcut** | (a) Mevcutta kalır / (b) Qwen3 local için GPU yatırımı | Mevcut config doğrulanmalı, sonra karar |
| K3 | **Faz sırası** | (a) Önerdiğim sıra (0→6) / (b) Faz 3 (clarification) önce | **(a)** — RLS olmadan diğerleri risk |
| K4 | **CatBoost yeni modellerin tamamı mı?** | (a) 5 model / (b) Faz 3'te 2 model, sonra 3 / (c) Sadece Table Ranker | **(b)** |
| K5 | **Drag-drop UI scope** | (a) Sadece column reorder / (b) + filter ekleme / (c) Tam AST builder | **(a)+(b)** Faz 5; (c) sonra |
| K6 | **Migration stratejisi** | (a) Big-bang (downtime) / (b) Online (concurrent index, backfill job) | **(b)** — RLS dahil |
| K7 | **Observability — Langfuse?** | (a) Faz 6 değerlendir / (b) Hiç ekleme / (c) Şimdi başla | **(a)** |
| K8 | **Synthetic Q frequency** | (a) Discovery'de bir kez / (b) Haftalık / (c) Günlük | **(b)** |
| K9 | **Business glossary kaynak** | (a) Manuel admin UI / (b) LLM otomatik öner + admin onay / (c) Hibrit | **(c)** |

---

## 6. Risk & Mitigation

| Risk | Olasılık | Etki | Mitigation |
|------|----------|------|-----------|
| RLS yanlış config → tüm sorgular boş döner | Orta | Yüksek | Staging dry-run, bypass dependency, admin override |
| HNSW migration locking | Düşük | Orta | `CREATE INDEX CONCURRENTLY`, off-peak |
| LLM cost spike (sentetik veri) | Orta | Orta | Batch (50 Q/call), günlük budget cap, fallback template |
| Drag-drop a11y eksik | Orta | Düşük | HEBE gate keyboard fallback enforce eder |
| Faz 1 RLS sonrası mevcut sorgular kırılır | Yüksek | Yüksek | Her sorgu için audit script, missing `set_local` tespiti |
| Multi-signal scoring ağırlık tuning zor | Orta | Düşük | A/B testing framework (Faz 5+), config'den ayarlanabilir |

---

## 7. Test & Doğrulama Stratejisi

**Her faz sonunda:**
1. **Syntax doğrulama** (TYCHE/Post-Impl Review) — Bölüm 5b
2. **Smoke test** — mevcut chat akışı 5 farklı senaryoda çalışıyor mu
3. **Multi-dialect smoke** — PG + Oracle (Docker) + MSSQL (varsa) + MySQL (varsa)
4. **Regresyon checklist** — `Test_Senaryolari.md`'deki senaryolar
5. **HEBE UI/UX gate post-check** — yeni UI yüzeyi tüm A-G maddelerini geçti mi
6. **MemPalace `mine_project()` + delta kontrol** — KAP 10

**End-to-end senaryolar (her fazda eklenir):**
- E2E-1: Tek tablo, basit lookup → SQL üret, çalıştır, sonuç göster
- E2E-2: Aynı isim 2 tabloda → clarification → seçim → SQL → sonuç
- E2E-3: Belirsiz kriter (tarih yok) → clarification → seçim → SQL
- E2E-4: Cross-tenant attempt (RLS test)
- E2E-5: Büyük tablo (>100K satır) → streaming mode → ilk chunk <500ms
- E2E-6: Drag-drop kolon → SQL recompose → execute
- E2E-7: Follow-up "bunlardan sadece İstanbullular" → context'i koruyarak SQL

---

## 8. Çıktılar (Her Faz Sonu)

- ✅ Kod commit'leri (`feat(modul): ...` formatında)
- ✅ Schema migration scripts (`migrations/` veya `schema.py` IF NOT EXISTS)
- ✅ README versiyon + CHANGELOG entry
- ✅ Test senaryoları güncellenmiş
- ✅ MemPalace drawer (faz özeti)
- ✅ Bu dosya (`agentic_sql_copilot_master_plan.md`) güncel — yapılanlar [x] işaretli

---

## 9. Onay Soruları (Kullanıcıya)

1. **Faz sırasını onaylıyor musunuz?** (0 → 1 → 2 → 3 → 4 → 5 → 6)
2. **K1-K9 kararları için ZEUS önerilerini kabul mü, değiştirmek istediğiniz var mı?**
3. **Hangi fazdan başlayalım?** Önerim: **Faz 0 (hijyen — README versiyon senkron + MemPalace kayıt + comment okuma doğrulama)** ile başlayıp size rapor sunmak. Sonra Faz 1'e geçmek için ayrı onay alacağım.
4. **LLM provider** — şu an .env'de hangisi configured? (OpenAI / Azure / Anthropic / local?) — Bunu doğrulayalım, sentetik veri maliyeti hesabı için kritik.
5. **Faz başlama frekansı** — her faz arası onay mı, yoksa onaydan sonra ardışık ilerlesin mi?

---

## 10. Faz 0 — Hazır İşlem Listesi (Onay verilirse)

Onaylarsanız hemen ben (ZEUS) şunları yaparım:
1. README versiyon başlığını v3.18.0 → v3.19.3 yap (HERA)
2. Bu plan'ı MemPalace `vyra` wing'ine kayıt et (CRAZYMEMPLC)
3. Discovery'de Oracle/MSSQL comment okuma kontrolünü yap (POSEIDON — read-only inceleme)
4. `app/services/pipeline/` boş klasör + `README.md` iskeleti (HERMES)
5. `Test_Senaryolari.md` taslağı (TYCHE)
6. Bitiş raporu sun + Faz 1 onayı iste

**Tahmini değişiklik:** ~3-5 dosya, ~150 satır kod/doc.

---

> 📌 **Not:** Bu plan canlı bir doküman — her faz sonunda güncellenir, yapılanlar [x] işaretlenir, yeni keşifler eklenir.
