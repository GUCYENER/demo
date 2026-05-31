---
plan_id: followup_querycontext_refine_engine
created: 2026-05-31
branch: hira
status: in_progress
version_target: v3.42.0
faz1_version: v3.41.7
council_mod: 3
hebe_gate_required: true
---

# Bağlam-Farkında İnteraktif Sorgu: QueryContext + refine() motoru (Veritabanında Ara + Akıllı Keşif ortak)

## 1. Context (Neden)
Kullanıcı vizyonu: "Veritabanında Ara" ve "Akıllı Keşif"in ortak amacı — yetkili DB şema+tablo+ilişkiler
elimizde, kullanıcı **bağlamı koruyarak interaktif** doğru veriye hızlı ulaşsın. Takip ("son konu ile
ilgili sor") = önceki SQL'i UNUTMA, yeni talebi ona EKLE/MODİFİYE et; sıfırdan tahmin etme. Yetkisiz
ek talep → "yetkin yok"; saçma talep → eldeki veriye göre netleştir; ana konuşmayı unutma.

## 2. Mevcut Durum (kanıtlı)
- **KÖK BUG (Faz 1 ile düzeltildi):** `process_stream_db_only` sırası `_scope_blocked → cache → golden_hit
  → generate_sql(follow_up_context)`. Takipte bile **cache/golden kısa-devresi** ateşleniyordu. Log (18:27):
  "Golden SQL hit score=0.9795 → SELECT DISTINCT m.* FROM SIPARISLER s JOIN MUSTERILER m ON s.MUSTERI_ID=
  m.MUSTERI_ID → 20 satır (TÜM müşteriler)". Çıpa (son sipariş) kayboldu; modifikasyon promptu HİÇ çalışmadı.
- **Modifikasyon promptu DOĞRU** (`text_to_sql.build_text_to_sql_prompt` 205-243): çıpa FROM koru + FK JOIN
  ekle + DIAGNOSTIC. Sorun prompt değil, ona HİÇ ulaşılmaması idi.
- **follow_up_context = {prev_sql, prev_columns, prev_source_db}** (processor.py:657-688). **Önceki SONUÇ
  (somut SIPARIS_ID=X) TAŞINMIYOR** → "bu siparişin müşterisi" anchoru metinden (prev_sql alt-sorgusu)
  türetiliyor; kırılgan.
- **FK grafiği elimizde:** `ds_db_relationships` (FATURALAR.SIPARIS_ID→SIPARISLER, SIPARISLER.MUSTERI_ID
  →MUSTERILER, ...). Şu an JOIN'i LLM tahmin ediyor (halüsinasyon/yanlış-join riski).
- **Wizard ("bu rapordan ne bekliyorsunuz"):** `llm_generate_report` + picked tables/AST/ilişkiler zaten
  structured state'te; ama ek talep ayrı LLM üretimine gidiyor, refine semantiği yok.

## 3. Faz/Gate Haritası (ekip uzmanlık eşleşmesi — 5e.2b)

| Gate | Konsey (primary + review) | Dosya | İş |
|---|---|---|---|
| **G1 ✅ Faz 1** Takip'te cache/golden skip | HERMES + METIS + TYCHE | `deep_think_service.py` | `_is_followup` → cache+golden kısa-devre atlanır, daima generate_sql(follow_up_context). **TAMAM.** |
| **G2 Faz 2a** Sonuç-anchor yakalama | HERMES + APOLLO + ORACLE | `dialog/processor.py`, `deep_think_service.py` | Önceki sorgunun döndürdüğü satırların PK/anahtar değerlerini (ör. SIPARIS_ID=7) `follow_up_context["result_anchors"]`'a ekle (RLS/scope korunur; PII maskelenmiş değil ham PK). |
| **G3 Faz 2b** Deterministik FK-join planlayıcı | ORACLE + HEPHAESTUS + ARES | yeni `app/services/db_smart/join_planner.py` | `ds_db_relationships`'ten scope-filtreli en kısa join yolu (BFS). Çıpa tablo → hedef tablo yolu LLM'e NET verilir (veya assemble). Yol scope-dışı tablo gerektiriyorsa → DIAGNOSTIC ("aradaki tabloya yetki yok"). |
| **G4 Faz 2c** Refine prompt + anchor binding | ORACLE + METIS | `text_to_sql.py` (build_text_to_sql_prompt + generate_sql) | follow_up_context'e result_anchors + join_plan eklenince prompt: "çıpa = SIPARIS_ID=7; müşteriyi şu yoldan getir; WHERE'i koru". Anchor varsa LLM "tüm X"e kayamaz. |
| **G5 Faz 3a** Ortak QueryContext modeli | HERMES + APOLLO | yeni `app/services/db_smart/query_context.py` | `{source_id, dialect, tables, join_graph_used, where_constraints, columns, result_anchors, nl_summary, scope_snapshot}`. deep_think + wizard ortak üretir/tüketir. |
| **G6 Faz 3b** refine() motoru + wizard entegrasyon | ATHENA + HEBE + ORACLE + HERMES | `llm_generate_report.py`, `db_smart_api.py`, wizard FE `db_smart_wizard.js` | "bu rapordan ne bekliyorsunuz" → seçili tablolar/ilişkiler QueryContext olur; ek talep refine() ile uygulanır; seçimler unutulmaz, sıfırdan üretilmez. |
| **G7 Faz 3c** Belirsizlik/saçma talep netleştirme | METIS + APOLLO | refine() (her iki yüzey) | Talep scope/FK'ya oturmuyorsa → DIAGNOSTIC + "X üzerinden getirebilirim; Y için ilişki/yetki yok" (eldeki veriye göre). |
| **G8** Test + scope regresyon | TYCHE + ARES | `tests/` | join_planner BFS (scope-filtreli, scope-dışı yol→deny), anchor binding (somut id→tek satır), refine (yetkili→çalışır / yetkisiz→deny), follow-up no-golden. |
| **G9** Code review + ekip onayı | (görev sahibi) + `/code-review` skill | — | **ATLANMAZ.** `/code-review high`; sonra council result onayı. |
| **G10** Build + versiyon + docs | HERA + ATHENA | build.mjs, README, config, system_settings | FE değişti → bundle rebuild. Faz1=v3.41.7, Faz2/3=v3.42.0. |

## 4. Critical Files
- `app/services/deep_think_service.py` (G1✅, G2, G4 wiring)
- `app/services/dialog/processor.py` (G2 — result_anchors)
- `app/services/text_to_sql.py` (G4 — prompt + anchor/join_plan)
- YENİ `app/services/db_smart/join_planner.py` (G3)
- YENİ `app/services/db_smart/query_context.py` (G5)
- `app/services/db_smart/llm_generate_report.py` + `app/api/routes/db_smart_api.py` (G6 wizard refine)
- `frontend/assets/js/modules/db_smart_wizard.js` (G6 FE)
- `tests/` (G8)

## 5. Yeniden Kullanılacak (kod tekrarı önle)
- `ds_db_relationships` + mevcut `_prune_schema_tables` BFS/Steiner (deep_think:3219) — G3 join_planner bunun
  scope-filtreli, deterministik çıktı veren refaktörü olabilir (yeni paralel BFS yazma).
- `resolve_scope`/`AccessScope.allows` — G3/G6 scope filtre.
- `enforce_sql_scope` / `check_table_whitelist` — refine çıktısı yine bu gate'ten geçer (yetki).
- RB-v3.41.6 #1 paylaşılan `sql_diag` util (DIAGNOSTIC/comment) — G7 ile birlikte yapılabilir.
- Wizard mevcut AST/picked-tables state (query_state) — G6 QueryContext kaynağı.

## 6. Risk
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Takipte golden/cache skip → her takip LLM çağrısı (yavaş) | yüksek | düşük | Kabul (doğruluk > hız); golden yalnız self-contained'de. |
| result_anchors PII/scope sızıntısı | düşük | yüksek | Yalnız PK/FK anahtarları (maskelenmiş kolon değil); scope_snapshot ile sınırla; ARES review. |
| join_planner yanlış/çok-yollu join | orta | orta | En kısa yol + scope filtre; belirsizse DIAGNOSTIC; ORACLE+HEPHAESTUS review + test. |
| QueryContext iki yüzeyi birden değiştirir (regresyon) | yüksek | yüksek | Faz sıralı; G1 izole (tamam), Faz2 deep_think-only, Faz3 wizard ayrı; her faz council+test+code-review. |
| LLM anchor'a rağmen drift | orta | orta | Anchor'ı WHERE'e DETERMİNİSTİK enjekte et (sadece prompt'a güvenme); G4. |

## 7. Verification
- **Faz 1 (şimdi):** "son siparişi listele" → "bu siparişin müşteri detayı" → **tek satır** (son siparişin müşterisi), tüm müşteriler DEĞİL. (kullanıcı canlı + log: golden hit YOK, generate_sql + modifikasyon çalıştı.)
- **Faz 2:** anchor binding unit (somut id→WHERE), join_planner BFS (scope-içi yol bulur, scope-dışı→DIAGNOSTIC).
- **Faz 3:** wizard "bu rapordan ne bekliyorsunuz" → seçili tablolar korunur + ek talep uygulanır; saçma talep→netleştirme.
- **Güvenlik (her faz):** yetkisiz tablo ek talebi → DENY (enforce_sql_scope); anchor PII sızdırmaz.
- Build (FE), 4-dialect (ORACLE/PG/MSSQL/MySQL) join_planner.

## 8. Out-of-scope / sıralama
- Faz 1 → hemen ship (v3.41.7), izole.
- Faz 2 (deep_think anchor+join_planner) → v3.42.0 sprint.
- Faz 3 (QueryContext birleştirme + wizard) → v3.42.0 ya da v3.43.0 (en büyük, en riskli; Faz 2 sonrası yeniden değerlendir).
- RB-v3.41.6 sql_diag/denial-parse konsolidasyonu G7 ile birleştirilebilir.
