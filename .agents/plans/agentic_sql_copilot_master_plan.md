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

- [ ] **HERA:** README versiyon başlığı v3.18.0 → v3.19.3 senkronize
- [ ] **CRAZYMEMPLC:** Bu plan dosyasını MemPalace'a kayıt (`mempalace_add_drawer wing=vyra room=plans`)
- [ ] **POSEIDON:** Discovery sırasında Oracle `ALL_COL_COMMENTS`, MSSQL `sys.extended_properties` okumasının yapılıp yapılmadığını doğrula; eksikse ekle (ds_db_objects.columns_json içine `comment` alanı)
- [ ] **HERMES + METIS:** `app/services/pipeline/` iskelet + `README.md` (LangGraph state machine mimari kararı dokümante)
- [ ] **TYCHE:** Mevcut chat akışı için regresyon test senaryoları yaz (manual checklist `Test_Senaryolari.md`)

**Versiyon:** v3.19.4 (patch)

---

### 📍 Faz 1 — RLS + Connection Scoping (1 hafta)
**Hedef:** Multi-tenant cross-leak imkansız hale gelsin.

- [ ] **HEPHAESTUS:** Migration script — RLS policy
  ```sql
  ALTER TABLE ds_learning_results ENABLE ROW LEVEL SECURITY;
  ALTER TABLE ds_db_objects ENABLE ROW LEVEL SECURITY;
  ALTER TABLE ds_db_samples ENABLE ROW LEVEL SECURITY;
  ALTER TABLE ds_db_relationships ENABLE ROW LEVEL SECURITY;
  CREATE POLICY ds_lr_scope ON ds_learning_results
    USING (source_id = current_setting('app.current_source_id', true)::int);
  -- benzer policy'ler diğer tablolarda
  ```
- [ ] **HERMES:** Her request başında `SET LOCAL app.current_source_id = X` set edilmesi (FastAPI middleware veya dependency). Admin/superuser için `app.bypass_rls=on` set edilebilir bir Depends.
- [ ] **ARES:** RLS bypass denemesi için negatif test (başka user'ın connection_id'sine geçiş denemesi).
- [ ] **TYCHE:** Multi-tenant smoke test (2 farklı user, 2 farklı source, cross-leak attempt).

**Versiyon:** v3.20.0 (minor — schema değişikliği)
**Risk:** Mevcut sorguların RLS bypass etmesi gereken yerleri tespit + Depends'la işaretle. Yanlış config → tüm sorgular boş dönebilir. Migration dry-run staging'de zorunlu.

---

### 📍 Faz 2 — Column-Level Embedding + Hybrid Search (1-2 hafta)
**Hedef:** Aynı isimli tabloları + kolonları daha iyi ayırt etmek.

- [ ] **HEPHAESTUS:** Yeni tablo
  ```sql
  CREATE TABLE ds_column_embeddings (
    id BIGSERIAL PK,
    source_id INT FK,
    schema_name VARCHAR, table_name VARCHAR, column_name VARCHAR,
    data_type VARCHAR, is_nullable BOOL, is_pk BOOL, is_fk BOOL,
    business_name_tr VARCHAR, synonyms TEXT[],
    semantic_type VARCHAR, -- email, phone, id, datetime, money, name vb.
    sample_values JSONB,
    description TEXT,
    embedding VECTOR(384),
    tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('turkish', coalesce(business_name_tr,'')||' '||coalesce(description,'')||' '||array_to_string(synonyms,' '))) STORED,
    UNIQUE(source_id, schema_name, table_name, column_name)
  );
  CREATE INDEX ON ds_column_embeddings USING hnsw (embedding vector_cosine_ops);
  CREATE INDEX ON ds_column_embeddings USING gin (tsv);
  -- RLS policy'si de
  ```
- [ ] **HEPHAESTUS:** `ds_learning_results.tsv` TSVECTOR kolonu eklenir (hybrid için).
- [ ] **PROMETHEUS:** `ds_qa_generator.py` genişlet → kolon-level chunk üret (her kolon için ayrı embedding). Sentetik açıklama LLM'le (Türkçe, tek seferde batch).
- [ ] **PROMETHEUS:** Yeni hybrid retrieval query:
  ```python
  hybrid_score = 0.65 * (1 - cosine_dist) + 0.35 * ts_rank
  ```
  `app/services/rag/hybrid_retrieval.py` (yeni).
- [ ] **NIKE:** IVFFlat → HNSW migration (`ds_learning_results` ve yeni tablo).
- [ ] **TYCHE:** Aynı isimde tablo testi (deliberately seed edilmiş test data ile).

**Versiyon:** v3.21.0

---

### 📍 Faz 3 — Multi-Signal Scoring + Ambiguity Gate + Clarification Backend + LangGraph (2 hafta)
**Hedef:** Önerilerdeki entity resolution akışı + LangGraph state machine.

- [ ] **METIS + ORACLE:** Yeni pipeline (LangGraph state machine)
  ```
  app/services/pipeline/
    __init__.py
    state.py          # QueryState TypedDict (LangGraph state)
    graph.py          # build_query_graph() -> CompiledGraph (entry/exit/conditional edges)
    nodes/
      intent_extract.py
      retrieve.py
      multi_signal_rank.py
      ambiguity_gate.py    # conditional: clarification needed?
      clarification.py     # interrupt + resume pattern
      sql_generate.py
      validate.py          # EXPLAIN pre-flight
      execute.py
    checkpointer.py   # MemorySaver / PostgresCheckpointer
  ```
  Dependency: `langgraph>=0.2`, `langgraph-checkpoint-postgres` (PG checkpoint için).
- [ ] **PROMETHEUS:** Multi-signal scorer:
  ```python
  final = 0.35*semantic + 0.20*name_fuzzy + 0.15*column_match + 0.10*fk_centrality + 0.10*recency + 0.10*usage_freq
  ```
  Ağırlıklar configurable (`config.py` veya `system_settings`).
- [ ] **ARTEMIS-ML:** Ambiguity Detector v1 — heuristic önce (top1-top2 < 0.20 veya top1 < 0.6 → clarification). CatBoost'a sonra.
- [ ] **HERMES + ATHENA:** Backend → clarification event yapısı standardize (`renderDisambiguationCard` zaten var). Yeni event: `clarification_needed` SSE.
- [ ] **APOLLO:** `business_glossary` tablosu:
  ```sql
  CREATE TABLE business_glossary (
    id BIGSERIAL PK, company_id INT, term VARCHAR, synonyms TEXT[],
    canonical_table VARCHAR, canonical_column VARCHAR, description TEXT
  );
  ```
  Query expansion `app/services/pipeline/steps/query_expand.py` içinde.

**Versiyon:** v3.22.0

---

### 📍 Faz 4 — User Preferences + Few-shot Store + Self-healing (1 hafta)
**Hedef:** "Bu kullanıcı users deyince sales.users kastediyor" öğrenme.

- [ ] **HEPHAESTUS:**
  ```sql
  CREATE TABLE query_examples (
    id BIGSERIAL PK, user_id INT, source_id INT, db_engine VARCHAR,
    question TEXT, generated_sql TEXT, was_correct BOOLEAN,
    user_feedback TEXT, embedding VECTOR(384),
    chosen_tables TEXT[], chosen_columns TEXT[],
    created_at TIMESTAMPTZ
  );
  CREATE TABLE user_table_preferences (
    user_id INT, source_id INT, ambiguous_term VARCHAR,
    chosen_table VARCHAR, count INT DEFAULT 1,
    PRIMARY KEY (user_id, source_id, ambiguous_term)
  );
  ```
- [ ] **ORACLE:** `text_to_sql.py` few-shot pulling — per `(user_id, source_id)` top-5 nearest example by embedding.
- [ ] **ORACLE:** Self-healing retry (max 2): SQL → EXPLAIN fail → error → LLM'e geri besleme.
- [ ] **HERMES:** Validation step EXPLAIN pre-flight (dialect-aware).

**Versiyon:** v3.23.0

---

### 📍 Faz 5 — CatBoost Yeni Modelleri + AST Query Builder + Drag-Drop UI (2-3 hafta)
**Hedef:** Agentic copilot vizyonunun temel parçaları.

> **DURUM ÖZETİ (2026-05-18 güncel):**
> - ✅ Column / Filter / Join Predictors → v3.26.0 Faz 4'te yapıldı (`app/services/ml/catboost_trainer.py` + `decision_extractors.py`)
> - ✅ Result Size Predictor → `app/services/ml/size_classifier.py` + `app/services/pipeline/result_size_predictor.py`
> - ✅ AST builder → `app/services/pipeline/nodes/ast_query_builder.py` (Faz 5d, prototype tamam)
> - ✅ Sonuç tablosu drag-drop + visibility + localStorage persist → v3.27.2 + v3.27.3 (tüketici tarafı UI)
> - ❌ **Table Ranker model** (ml_models entry yok) — v3.28 kapsamında
> - ❌ **Synthetic `generate_db_query_pairs`** (tablo+FK+sample → Q/SQL pair) — v3.28 kapsamında
> - ❌ **Sample Data Preview kartı** (`renderSampleDataPreview`) — v3.28 kapsamında
> - ❌ **Pre-execute query builder UI** (`query_builder.js` — DRAG kolon ekleme akışı, sonuçtaki drag-drop'tan farklı) — v3.28 kapsamında

- [x] **ARTEMIS-ML:** Column / Filter / Join Predictors (v3.26.0 Faz 4'te tamam)
- [x] **ARTEMIS-ML:** Result Size Predictor (v3.26.0)
- [ ] **ARTEMIS-ML:** Table Ranker (`ml_models` üzerinde `model_name=table_ranker`)
- [ ] **ARTEMIS-ML:** Synthetic training data: `synthetic_data.py` extend — `generate_db_query_pairs(source_id)` (tablo+sample+FK → 30-50 Q/SQL pair via LLM)
- [ ] **ARTEMIS-ML:** Continuous learning'e yeni model job tipi eklenir
- [x] **ORACLE:** AST builder iskeleti — `nodes/ast_query_builder.py` (lookup intent için deterministic)
- [ ] **ATHENA + HEBE:** Pre-execute drag-drop kolon UI (`query_builder.js`) — Keyboard fallback (Space/Arrow/Enter), `aria-grabbed`, her değişimde `/api/query-state/update` → to_sql() preview
- [ ] **ATHENA:** Sample Data Preview kartı — `renderSampleDataPreview()` (`dialog_chat_utils.js`)

**Versiyon:** v3.24.0 (büyük) → v3.28 olarak kapsama alındı (kalan 4 madde)

---

### 📍 Faz 6 — Streaming Results + Result Size Predictor + Observability (1-2 hafta)
**Hedef:** Büyük veri deneyimi + monitoring.

- [ ] **ARTEMIS-ML:** Result Size Predictor (CatBoost regression)
- [ ] **NIKE + HERMES:** Row chunk SSE streaming (`SafeSQLExecutor` cursor.fetchmany(500) → SSE event `result_chunk`)
- [ ] **ATHENA:** Streaming result viewer (virtual scroll, ilk chunk gelir gelmez göster, geri kalan akar)
- [ ] **NIKE:** Redis cache key strategy: `sql_cache:{user_id}:{source_id}:{hash(question)}` TTL 5dk
- [ ] **METIS:** Langfuse self-host eval (opsiyonel; karar phase 6 başında)
- [ ] **CRAZYMEMPLC:** Final master plan execution log

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
