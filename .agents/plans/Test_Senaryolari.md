# VYRA Agentic SQL Copilot — Test Senaryoları

**Versiyon:** Faz 6 sonrası (2026-05-17)
**Owner:** TYCHE
**Kapsam:** Her faz sonu çalıştırılacak regresyon + E2E senaryoları

> Bu doküman canlı — her yeni faz tamamlanınca senaryolar genişler ve sonuçlar `Sonuç` kolonuna işlenir (✅ Geçti / ⚠️ Kısmi / ❌ Başarısız / ⏭️ N/A).

> **Otomatik test özeti:** `tests/test_agentic_pipeline_e2e.py` — 21 pytest senaryosu (predictor, streaming, pipeline E2E, wiring). Commit `218b724`. `pytest -q` ile 8 sn altı yeşil.

---

## 0. Faz 0 Smoke

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 0.1 | Mevcut chat akışı bozulmadı | KB modunda "vpn nasıl kurulur" sor | RAG sonucu döner, sistem mesajları temiz | ⚠️ Manuel UI test |
| 0.2 | Mevcut DB chat akışı bozulmadı | DB modunda bir tablo için soru sor | SQL üretilir, sonuç tablosu döner | ⚠️ Manuel UI test |
| 0.3 | Discovery hala çalışıyor | Bir data source için "DB Keşif" başlat | Job complete + ds_db_objects dolar | ⚠️ Manuel UI test |
| 0.4 | LLM moduna geçiş | LLM mode → genel soru | Cevap döner, sistem mesajları temiz | ⚠️ Manuel UI test |
| 0.5 | Backend syntax | `python -c "import app.services.pipeline"` | Hata yok | ✅ Geçti |
| 0.6 | Pipeline graph build | `build_query_graph()` çalışır | StateGraph veya sequential runner döner | ✅ Geçti (Faz 3 sonrası) |

---

## 1. Faz 1 — RLS + Connection Scoping

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 1.1 | Cross-tenant leak attempt | User A, source A1 — `ds_learning_results` SELECT (RLS aktif, `app.current_source_id` ≠ A1) | 0 satır döner | ✅ Kod hazır (`007_v3200_rls_discovery_tables`, `f63f12c`) |
| 1.2 | Same-user different source | User A, source A1 set edilmiş → A2 verisi sorgulanamaz | 0 satır | ✅ Kod hazır (`data_source_access.scoped_db`) |
| 1.3 | Admin bypass | Admin user `app.bypass_rls='on'` ile tüm satırlar görünür | Tüm satırlar | ✅ Kod hazır (`system.py` `17c691b`) — ⚠️ Manuel UI doğrulama gerek |
| 1.4 | Mevcut sorgu kırılmaz | Tüm mevcut chat akışları çalışır | Hiçbir sorgu boş dönmez | ⚠️ Manuel regresyon |
| 1.5 | Discovery RLS scoped | Yeni discovery → sadece o source_id altında satırlar yazılır | ✓ | ✅ Kod hazır (`8044f24`) |
| 1.6 | Migration rollback | RLS policy DROP → eski davranışa dön | Risk azaltma | ⚠️ Manuel test (downgrade script var) |

---

## 2. Faz 2 — Column-Embedding + Hybrid Search

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 2.1 | Aynı isim tablo seçimi | Schema A.users + Schema B.users, "users tablosundan kayıtları getir" | Top-2 aday + clarification card | ✅ Kod hazır (`ambiguity_gate.py` `75fd8e7`) — ⚠️ UI test |
| 2.2 | Aynı isim kolon | iki tabloda da `email`, sorgu "kullanıcı maili" | Column-level embedding doğru tabloyu seçer | ✅ Kod hazır (`ds_column_embeddings` `d24ecfe`, `a0c4f17`) |
| 2.3 | Hybrid search (vector+BM25) | Yazım hatalı sorgu ("musteri mail") | BM25 sayesinde yine doğru kolon bulunur | ✅ Kod hazır (`hybrid_retrieval.py` `6ad8069`, `040895a`) |
| 2.4 | Native comment kullanımı | DBA Türkçe comment'li bir Oracle DB | Comment LLM enrichment'a fallback olmadan kullanılır | ✅ Kod hazır (`a6eeb5c` — 4 dialect native comment) |
| 2.5 | HNSW migration | IVFFlat → HNSW geçiş + retrieval doğruluk | Recall@10 düşmedi | ✅ Kod hazır (`011_v3210_ivfflat_to_hnsw` `c57e785`) |
| 2.6 | Empty state | Hiç embedding yoksa "Hiç aday tablo yok" | Empty state component görünür | ⚠️ UI test |

---

## 3. Faz 3 — Multi-Signal + LangGraph + Ambiguity Gate

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 3.1 | LangGraph state persist | Clarification beklerken backend restart | State persist edilir, resume çalışır | ✅ Kod hazır (`graph.py` `resume_pipeline`) — ⚠️ Restart smoke gerek |
| 3.2 | Top1 dominant | Tek aday >0.85 + spread >0.20 | Auto-pick | ✅ Kod hazır (`ambiguity_gate.py`) — pytest mock'lar kapsıyor |
| 3.3 | Tight competition | Top1-Top2 < 0.20 | Clarification card | ✅ Kod hazır (`clarification.py` `f0088a4`) |
| 3.4 | Below threshold | Top1 < 0.5 | "Bulamadım, soruyu açıklayın" | ✅ Kod hazır |
| 3.5 | Business glossary expansion | "müşteri" → customers/clients/accounts | Aday tablolar gelir | ✅ Kod hazır (`012_v3220_business_glossary` `19ec221`) |
| 3.6 | LangGraph conditional edge | Ambiguity → clarification → user pick → SQL gen | Akış kesintisiz | ✅ pytest `test_ambiguity_interrupt_in_auto_mode` |
| 3.7 | Multi-signal feature ağırlıkları | Config'den ağırlıkları değiştir | Yeni request'te yeni skorlar | ✅ Kod hazır (`multi_signal_rank.py` `b11af1b`) |

---

## 4. Faz 4 — User Pref + Few-shot + Self-heal + EXPLAIN

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 4.1 | User preference yakalama | User aynı belirsizlikte 2 kez sales.users seçti | 3. kez auto-pick + transparency | ✅ Kod hazır (`load_prefs.py` + `user_preferences_service.py` `53fc473`) |
| 4.2 | Few-shot retrieval | Aynı user + source için benzer eski soru → SQL | LLM prompt'unda example olarak görünür | ✅ Kod hazır (`few_shot_selector.py` `f097460`) |
| 4.3 | EXPLAIN fail → self-heal | LLM yanlış kolon adı → EXPLAIN fail → retry | Error LLM'e döner, retry doğru üretir | ✅ pytest `test_self_heal_retry_success` |
| 4.4 | Max retry sınırı | 2 başarısız → kullanıcıya hata + sample SQL | "SQL üretemedim" + manuel düzenleme önerisi | ✅ Kod hazır (`self_heal.py` `90929f2`) |
| 4.5 | Oracle EXPLAIN | Oracle dialect'inde EXPLAIN PLAN çalışır | Plan döner | ⚠️ Oracle docker kapalı, manuel test |
| 4.6 | MSSQL EXPLAIN | SET SHOWPLAN_XML ON | Plan döner | ⚠️ Manuel test |

---

## 5. Faz 5 — CatBoost + AST + Drag-Drop UI

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 5.1 | Table Ranker accuracy | Sentetik test set (200 soru/SQL pair) | Top-1 accuracy > 0.75 | ⚠️ Sentetik veri toplama bekliyor (`catboost_trainer.py` hazır `646a613`) |
| 5.2 | Ambiguity Detector accuracy | Belirsiz / net soru karması | Precision/recall > 0.80 | ⚠️ Sentetik veri toplama bekliyor |
| 5.3 | Drag-drop kolon ekle/sil | Üretilen SQL üzerinde kolon ekle/çıkar | SQL recompose, execute → yeni sonuç | ✅ Frontend hazır (`schema_picker.js` `e51121f`) — ⚠️ UI test |
| 5.4 | Drag-drop keyboard | Tab + Space + Arrow + Enter | A11y akışı tam | ⚠️ UI test (HEBE F) |
| 5.5 | Sample preview kartı | Üretilen SQL'in ilk satırı + onay | "Bu mu?" → ✅ / ✏️ | ⚠️ UI test |
| 5.6 | Synthetic Q schedule | UI'dan günlük/haftalık → cron trigger | `ml_training_samples` dolar | ⚠️ Cron scheduler bağlanmadı |
| 5.7 | Continuous training | Yeni feedback → 30 dk içinde model retrain | Yeni `.cbm`, is_active swap | ✅ Kod hazır (`catboost_inference.py` `e5d7755`) — ⚠️ Scheduler bağlanmadı |
| 5.8 | AST lookup shortcut | Lookup intent + tek tablo → LLM bypass | Deterministik SQL | ✅ Kod hazır (`ast_query_builder.py` `6241489`) — pytest `test_force_mode_runs_to_execute` |

---

## 6. Faz 6 — Streaming + Result Size + Observability

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 6.1 | Streaming threshold | >100K satır tahmin → streaming mode | İlk chunk <500ms | ✅ pytest `test_explicit_limit_huge`, `test_max_rows_truncation` |
| 6.2 | Pagination mode | 1K-100K → batch'li streaming | Sonraki chunk akar | ✅ pytest `test_buffered_fallback_batches_correctly` |
| 6.3 | Direct mode | <1K → tek seferde JSON | Hızlı render | ✅ pytest `test_pk_equality`, `test_aggregate_only_small` |
| 6.4 | Result Size accuracy | Tahmin vs gerçek satır farkı | ±%30 tolerans | ✅ Predictor 8 senaryo (pytest `TestResultSizePredictor`) |
| 6.5 | Redis cache | Aynı sorgu 5dk içinde tekrar | Cache hit | ⚠️ Implementasyon yapılmadı (opsiyonel) |
| 6.6 | Langfuse trace | Bir akış end-to-end trace | Span'lar görünür | ⚠️ Opsiyonel — `pipeline_events` tablo + admin dashboard bunun yerini tutuyor (`db39840`) |
| 6.7 | Observability dashboard | Admin sayfası — son N saat run istatistiği | runs/nodes/sql_source/bucket/recent | ✅ Endpoint + UI hazır (`agentic_query_api`, `agentic_observability.{html,js,css}`) |
| 6.8 | SSE wire format | `event: T\ndata: {...}\n\n` | Standart SSE | ✅ pytest `test_sse_wire_format` |
| 6.9 | LLM/execute/explain wiring | Pipeline state'ine callable injection | Üzerine yazmadan placeholder set | ✅ pytest `test_inject_callables_skips_existing` |

---

## Multi-Dialect Smoke (Her Faz Sonu)

| # | Senaryo | PG | Oracle | MSSQL | MySQL |
|---|---------|----|----|----|----|
| MD.1 | Basit SELECT + LIMIT | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| MD.2 | JOIN 2 tablo | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| MD.3 | WHERE + tarih filtresi | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| MD.4 | GROUP BY + aggregate | ⚠️ | ⚠️ | ⚠️ | ⚠️ |
| MD.5 | TOP/LIMIT/FETCH FIRST syntax | ⚠️ | ⚠️ | ⚠️ | ⚠️ |

> Not: Multi-dialect smoke manuel — Oracle Docker kapalı, MSSQL/MySQL test instance'ı gerek.

---

## A11y / HEBE Sürekli Kontrol

| # | Kontrol | Sonuç |
|---|---------|-------|
| H.1 | Tüm yeni button'larda aria-label | ⚠️ Spot-check gerek (observability dashboard ARIA tam) |
| H.2 | Modal ESC + click-outside + return-focus | ⚠️ Manuel test |
| H.3 | Drag-drop keyboard fallback (Space/Arrow/Enter) | ⚠️ UI test |
| H.4 | Streaming sırasında skeleton göster | ✅ Dashboard'da `vyra-skeleton-shimmer` kullanıldı; chat tarafı manuel test |
| H.5 | Empty state component (DB hiç tablo yok) | ⚠️ Manuel test |
| H.6 | Renk değişkenleri (no hard-coded hex) | ✅ Yeni CSS'ler `var(--vyra-*)` ile (commits faz5/6) |

---

## Güvenlik / ARES Sürekli Kontrol

| # | Kontrol | Sonuç |
|---|---------|-------|
| A.1 | SQL injection — comment, UNION, xp_cmdshell | ✅ Mevcut (`safe_sql_executor.py`) |
| A.2 | RLS bypass denemesi | ✅ Faz 1 deployed (`3ec52cd`, `f63f12c`) |
| A.3 | Prompt injection (user msg → system prompt override) | ⚠️ Manuel pentest gerek |
| A.4 | Sensitive column masking | ✅ Mevcut |
| A.5 | EXPLAIN aşamasında DML yakalanır | ✅ `validate` node + `make_explain_callable` (`a2d0ef5`) |
| A.6 | Read-only DB role kullanımı (operational) | ⚠️ Kural-bazlı, deployment doc |

---

## Otomatik Test Kapsamı (pytest)

| Sınıf | Test Sayısı | Kapsam |
|-------|-------------|--------|
| `TestResultSizePredictor` | 9 | bucket logic, dialect, EXPLAIN callable, empty SQL |
| `TestStreamingExecute` | 5 | buffered fallback, stream-aware, max_rows, empty SQL, SSE format |
| `TestPipelineE2E` | 5 | force mode, self-heal, ambiguity interrupt, run_id, prediction attach |
| `TestWiring` | 2 | callable factory signature, inject_callables skip existing |

> Çalıştırma: `pytest tests/test_agentic_pipeline_e2e.py -q` → 21 passed ≈ 8s

---

> **Test Çalıştırma Sırası (her faz sonu):**
> 1. Smoke (mevcut akış bozulmadı mı?)
> 2. `pytest tests/test_agentic_pipeline_e2e.py -q` (otomatik regresyon)
> 3. Faz-spesifik manuel senaryolar
> 4. Multi-dialect smoke (en az 1 dialect + production dialect)
> 5. A11y check (HEBE)
> 6. Güvenlik check (ARES)
> 7. Post-Implementation Review formatı doldurulur, commit yapılır.
