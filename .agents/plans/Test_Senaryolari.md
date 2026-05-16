# 🧪 VYRA Agentic SQL Copilot — Test Senaryoları
**Versiyon:** Faz 0 draft (2026-05-17)
**Owner:** TYCHE
**Kapsam:** Her faz sonu çalıştırılacak regresyon + E2E senaryoları

> Bu doküman canlı — her yeni faz tamamlanınca senaryolar genişler ve sonuçlar `Sonuç` kolonuna işlenir (✅ Geçti / ⚠️ Kısmi / ❌ Başarısız / ⏭️ N/A).

---

## 0. Faz 0 Smoke (Şu an Geçerli)

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 0.1 | Mevcut chat akışı bozulmadı | KB modunda "vpn nasıl kurulur" sor | RAG sonucu döner, sistem mesajları temiz | Manuel test gerekli |
| 0.2 | Mevcut DB chat akışı bozulmadı | DB modunda bir tablo için soru sor | SQL üretilir, sonuç tablosu döner | Manuel test gerekli |
| 0.3 | Discovery hala çalışıyor | Bir data source için "DB Keşif" başlat | Job complete + ds_db_objects dolar | Manuel test gerekli |
| 0.4 | LLM moduna geçiş | LLM mode → genel soru | Cevap döner, sistem mesajları temiz | Manuel test gerekli |
| 0.5 | Backend syntax | `python -c "import app.services.pipeline"` | Hata yok | ✅ Geçti (Post-Impl) |
| 0.6 | Pipeline graph stub | `from app.services.pipeline.graph import build_query_graph; build_query_graph()` | `NotImplementedError` raise | ✅ Geçti (tasarım gereği) |

---

## 1. Faz 1 — RLS + Connection Scoping

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 1.1 | Cross-tenant leak attempt | User A, source A1 — `ds_learning_results` SELECT (RLS aktif, `app.current_source_id` ≠ A1) | 0 satır döner | ⏳ Faz 1 |
| 1.2 | Same-user different source | User A, source A1 set edilmiş → A2 verisi sorgulanamaz | 0 satır | ⏳ Faz 1 |
| 1.3 | Admin bypass | Admin user `app.bypass_rls='on'` ile tüm satırlar görünür | Tüm satırlar | ⏳ Faz 1 |
| 1.4 | Mevcut sorgu kırılmaz | Tüm mevcut chat akışları çalışır | Hiçbir sorgu boş dönmez (auth + middleware doğru) | ⏳ Faz 1 |
| 1.5 | Discovery RLS scoped | Yeni discovery → sadece o source_id altında satırlar yazılır | ✓ | ⏳ Faz 1 |
| 1.6 | Migration rollback | RLS policy DROP → eski davranışa dön | Risk azaltma | ⏳ Faz 1 |

---

## 2. Faz 2 — Column-Embedding + Hybrid Search

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 2.1 | Aynı isim tablo seçimi | Schema A.users + Schema B.users, "users tablosundan kayıtları getir" | Top-2 aday ve doğru disambiguation card | ⏳ Faz 2 |
| 2.2 | Aynı isim kolon | iki tabloda da `email`, sorgu "kullanıcı maili" | Column-level embedding daha alakalı tablo'yu seçer | ⏳ Faz 2 |
| 2.3 | Hybrid search (vector+BM25) | Yazım hatalı sorgu ("musteri mail") | BM25 sayesinde yine doğru kolon bulunur | ⏳ Faz 2 |
| 2.4 | Native comment kullanımı | DBA Türkçe comment'li bir Oracle DB | Comment LLM enrichment'a fallback olmadan kullanılır | ⏳ Faz 2 |
| 2.5 | HNSW migration | IVFFlat → HNSW geçiş + retrieval doğruluk | Recall@10 düşmedi, latency düşük | ⏳ Faz 2 |
| 2.6 | Empty state | Hiç embedding yoksa "Hiç aday tablo yok" | Empty state component görünür (HEBE D) | ⏳ Faz 2 |

---

## 3. Faz 3 — Multi-Signal + LangGraph + Ambiguity Gate

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 3.1 | LangGraph state persist | Clarification beklerken backend restart | State PostgresSaver'da, resume çalışır | ⏳ Faz 3 |
| 3.2 | Top1 dominant | Tek aday >0.85 + spread >0.20 | Auto-pick, transparency notu ("X kullandım") | ⏳ Faz 3 |
| 3.3 | Tight competition | Top1-Top2 < 0.20 | Clarification card gösterilir | ⏳ Faz 3 |
| 3.4 | Below threshold | Top1 < 0.5 | "Bulamadım, soruyu açıklayın" | ⏳ Faz 3 |
| 3.5 | Business glossary expansion | "müşteri" → query expansion: customers, clients, accounts | Beklenen aday tablolar gelir | ⏳ Faz 3 |
| 3.6 | LangGraph conditional edge | Ambiguity → clarification → user pick → SQL gen | Akış kesintisiz | ⏳ Faz 3 |
| 3.7 | Multi-signal feature ağırlıkları | Config'den ağırlıkları değiştir (PG'de) | Yeni request'te yeni skorlar | ⏳ Faz 3 |

---

## 4. Faz 4 — User Pref + Few-shot + Self-heal + EXPLAIN

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 4.1 | User preference yakalama | User aynı belirsizlikte 2 kez sales.users seçti | 3. kez auto-pick + transparency | ⏳ Faz 4 |
| 4.2 | Few-shot retrieval | Aynı user + source için benzer eski soru → SQL | LLM prompt'unda example olarak görünür | ⏳ Faz 4 |
| 4.3 | EXPLAIN fail → self-heal | LLM yanlış kolon adı üretti → EXPLAIN fail | Error LLM'e döner, retry doğru üretir | ⏳ Faz 4 |
| 4.4 | Max retry sınırı | 2 başarısız → kullanıcıya hata + sample SQL | "SQL üretemedim" + manuel düzenleme önerisi | ⏳ Faz 4 |
| 4.5 | Oracle EXPLAIN | Oracle dialect'inde EXPLAIN PLAN çalışır | Plan döner, tahmini cost log'lanır | ⏳ Faz 4 |
| 4.6 | MSSQL EXPLAIN | SET SHOWPLAN_XML ON | Plan döner | ⏳ Faz 4 |

---

## 5. Faz 5 — CatBoost + AST + Drag-Drop UI

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 5.1 | Table Ranker accuracy | Sentetik test set (200 soru/SQL pair) | Top-1 accuracy > 0.75 | ⏳ Faz 5 |
| 5.2 | Ambiguity Detector accuracy | Belirsiz / net soru karması | Precision/recall > 0.80 | ⏳ Faz 5 |
| 5.3 | Drag-drop kolon ekle/sil | Üretilen SQL üzerinde kolon ekle/çıkar | SQL recompose, execute → yeni sonuç | ⏳ Faz 5 |
| 5.4 | Drag-drop keyboard | Tab + Space + Arrow + Enter | A11y akışı tam çalışır (HEBE F) | ⏳ Faz 5 |
| 5.5 | Sample preview kartı | Üretilen SQL'in ilk satırı + onay | "Bu mu?" → kullanıcı ✅ veya ✏️ | ⏳ Faz 5 |
| 5.6 | Synthetic Q schedule | UI'dan günlük/haftalık → cron trigger | `ml_training_samples` dolar | ⏳ Faz 5 |
| 5.7 | Continuous training | Yeni feedback → 30 dk içinde model retrain | Yeni `.cbm` üretilir, is_active swap | ⏳ Faz 5 |

---

## 6. Faz 6 — Streaming + Result Size + Observability

| # | Senaryo | Adımlar | Beklenen | Sonuç |
|---|---------|---------|----------|-------|
| 6.1 | Streaming threshold | >100K satır tahmin → streaming mode | İlk chunk <500ms, scroll akar | ⏳ Faz 6 |
| 6.2 | Pagination mode | 1K-100K → cursor-based, "1-100 / 45K" UI | Sonraki butonu çalışır | ⏳ Faz 6 |
| 6.3 | Direct mode | <1K → tek seferde JSON | Hızlı render | ⏳ Faz 6 |
| 6.4 | Result Size accuracy | Tahmin vs gerçek satır farkı | ±%30 tolerans | ⏳ Faz 6 |
| 6.5 | Redis cache | Aynı sorgu 5dk içinde tekrar | Cache hit, SQL execute edilmez | ⏳ Faz 6 |
| 6.6 | Langfuse trace | Bir akış end-to-end trace | Span'lar görünür (opsiyonel) | ⏳ Faz 6 |

---

## Multi-Dialect Smoke (Her Faz Sonu)

| # | Senaryo | PG | Oracle | MSSQL | MySQL |
|---|---------|----|----|----|----|
| MD.1 | Basit SELECT + LIMIT | ⏳ | ⏳ | ⏳ | ⏳ |
| MD.2 | JOIN 2 tablo | ⏳ | ⏳ | ⏳ | ⏳ |
| MD.3 | WHERE + tarih filtresi | ⏳ | ⏳ | ⏳ | ⏳ |
| MD.4 | GROUP BY + aggregate | ⏳ | ⏳ | ⏳ | ⏳ |
| MD.5 | TOP/LIMIT/FETCH FIRST syntax | ⏳ | ⏳ | ⏳ | ⏳ |

---

## A11y / HEBE Sürekli Kontrol

| # | Kontrol | Sonuç |
|---|---------|-------|
| H.1 | Tüm yeni button'larda aria-label | ⏳ |
| H.2 | Modal ESC + click-outside + return-focus | ⏳ |
| H.3 | Drag-drop keyboard fallback (Space/Arrow/Enter) | ⏳ Faz 5 |
| H.4 | Streaming sırasında skeleton göster | ⏳ Faz 6 |
| H.5 | Empty state component (DB hiç tablo yok) | ⏳ Faz 2 |
| H.6 | Renk değişkenleri (no hard-coded hex) | ⏳ |

---

## Güvenlik / ARES Sürekli Kontrol

| # | Kontrol | Sonuç |
|---|---------|-------|
| A.1 | SQL injection — comment, UNION, xp_cmdshell | ✅ Mevcut (`safe_sql_executor.py`) |
| A.2 | RLS bypass denemesi | ⏳ Faz 1 |
| A.3 | Prompt injection (user message → system prompt override) | ⏳ |
| A.4 | Sensitive column masking | ✅ Mevcut |
| A.5 | EXPLAIN aşamasında DML yakalanır | ⏳ Faz 4 |
| A.6 | Read-only DB role kullanımı (operational) | ⚠️ Kural-bazlı, deployment doc |

---

> **Test Çalıştırma Sırası (her faz sonu):**
> 1. Smoke (mevcut akış bozulmadı mı?)
> 2. Faz-spesifik senaryolar
> 3. Multi-dialect smoke (en az 1 dialect + production dialect)
> 4. A11y check (HEBE)
> 5. Güvenlik check (ARES)
> 6. Post-Implementation Review formatı doldurulur, commit yapılır.
