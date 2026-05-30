---
plan_id: table_perm_unified_enforcement
created: 2026-05-31
branch: hira
status: completed
version_target: v3.40.0
completed: 2026-05-31
faz_durum: |
  TAMAMLANDI. Faz A (v3.39.2/G3) + Faz B (v3.40.0): G1 table_guard.enforce_sql_scope
  (fail-closed) + G5 tüm 4 yüzey bağlandı (query_builder/query_state/agentic/schedule_runner).
  G2 (sorulan tablo adı) + G4 (FK scope) bilinçli ertelendi (G3 yeterli). table_guard 5 test
  + standalone 4/4; G3 pytest 3/3. Canlı agentic/schedule smoke kullanıcı tarafından (LLM/cron).
  --- (eski) ---
  Faz A (DB-Only mesaj) — G3 TAMAM (v3.39.2): restricted kullanıcıda başarısızlık →
  "Yetkili tablolarınız: X" net mesajı (_scope_restricted_message); generic "Yalnızca
  SELECT" + check_table_whitelist yanlış-komşu sızıntısı bastırıldı. G2 (sorulan tablonun
  ADINI söyleme — filtresiz niyet çözümü gerektirir, existence-oracle + risk) ve G4 (FK
  scope — upstream filtre + G3 sayesinde gereksiz) BİLİNÇLİ ertelendi. G3 her iki semptomu çözer.
  Faz B (sistemik güvenlik: agentic/query_builder/query_state/schedule_runner fail-closed) → PENDING.
council_mod: 3
hebe_gate_required: true
---

# Tablo-Yetki: Tüm Sorgu Yüzeylerinde Tutarlı + Fail-Closed Uygulama + Net Mesaj (KALICI ÇÖZÜM)

## 1. Context (Neden)
Kullanıcı, tablo-bazlı yetkinin sorgu yüzeylerinde tutarsız davrandığını **kanıtla** raporladı:
- "Veritabanında Ara"da FATURA-only yetkiyle "müşteri listesi" → kimi zaman generic "Yalnızca SELECT / farklı sorun", kimi zaman **"sipariş yetkiniz yok"** (sormadığı tablo).
- Önceki turda saved-report rerun + Smart Discovery düzeltildi (v3.39.0) ama text-to-SQL/agentic + diğer execute yolları kaçmış.
Kullanıcı talebi: "süreci ekip ile incele, bu sorunlara kalıcı çözüm planı."

## 2. Mevcut Durum (2 ajan read-only audit — kanıtlı)

**Yol haritası (yönlendirme):** "Veritabanında Ara" → `dialog/processor.py:689` → `deep_think_service.process_stream_db_only:1960` (LangGraph `/api/agentic-query` DEĞİL — o ayrı, daha yeni pipeline).

**Senin bug'ının zinciri:**
1. `resolve_entities` (text_to_sql:1184) "müşteri"→MÜŞTERİ çözer (doğru). `combined_matched` (deep_think:2253) = sorulan tablolar.
2. `_prune_schema_tables` (deep_think:3219) FK `bfs_expand(max_depth=3)` + Steiner (3247-3253) ile **komşu tabloları** (SİPARİŞLER) LLM context'ine ekler — kullanıcı sormadı.
3. can_view scope schema context'i filtreler (text_to_sql:986-1011) ✅; can_execute whitelist (deep_think:2480-2501) ✅ — **yetkisiz tablo LLM'e/execute'a sızmaz (güvenli).**
4. Ama LLM yetkisiz komşuya JOIN atınca `check_table_whitelist` (safe_sql_executor:235) `"Tablo erişim yetkisi yok: SİPARİŞLER"` döner; `_sanitize_error_for_user` (deep_think:3291) `"tablo" in msg` erken-return'ü bu string'i AYNEN sızdırır → kullanıcı yanlış tabloyu görür.
5. Asked-table tamamen kapsam dışıysa LLM ya non-SELECT üretir → `validate_sql` (safe_sql_executor:138) "Yalnızca SELECT", ya DIAGNOSTIC → "farklı sorun". Mesaj tutarsızlığının kaynağı bu 3 farklı çıkış.

**Sistemik güvenlik açıkları (audit):**
| Yüzey | Durum |
|---|---|
| `/api/agentic-query` (+stream/resume) | **Tablo-yetki HİÇ YOK** — wiring `allowed_tables=None` → `get_allowed_tables`=tüm kaynak tabloları (wiring.py:241-262, retrieve.py:46) |
| `query_builder_api:504` /preview | `allowed_tables=None` → whitelist atlanır |
| `query_state_api:383-392` /preview | self-referential: `allowed=[req.table]` — kullanıcının `req.table`'a yetkisi DOĞRULANMAZ |
| `schedule_runner:200` | zamanlanmış rerun'da `allowed_tables` yok; sadece source-level can_execute re-check |
| `check_table_whitelist:180` | **boş allowed_tables = allow-all** (fail-OPEN footgun) — tüm gap'lerin ortak kökü |

**İyi durumda (referans):** generate_report (db_smart_api:2708), execute/stream (db_smart_api:1179 — v3.39.0), dialog DB-Only enforcement var ama mesaj karışık.

## 3. Faz/Gate Haritası

| Gate | Konsey | Dosya | İş |
|---|---|---|---|
| **G1** Fail-closed merkezi helper | HERMES + ARES | yeni `app/services/db_smart/table_guard.py` | `enforce_sql_table_scope(sql, source_id, user_ctx, permission, dialect) -> (ok, denied_tables, allowed_list)`; restricted+boş → DENY (asla allow-all). check_table_whitelist boş-tuzağını sarar. |
| **G2** Pre-generation intent gate (senin bug) | APOLLO + ORACLE + METIS | deep_think_service.py:~2253 (combined_matched sonrası, _prune ÖNCESİ) | Sorulan tablolar (combined_matched, FK-expansion ÖNCESİ) can_execute scope'a karşı kontrol; HEPSİ kapsam dışıysa LLM'e gitmeden tek net mesaj + return |
| **G3** Birleşik red mesajı | HEBE + APOLLO | deep_think_service.py:3276 `_sanitize_error_for_user` | `"tablo" in msg` sızıntısını düzelt; tüm scope-denial string'lerini (safe_sql:233/235, deep_think:2500) tek formata çevir: **"Yetkili olduğunuz tablolar: {liste}. Sorunuz bu kapsam dışında olabilir."** |
| **G4** FK genişletmeyi scope ile sınırla | ORACLE + ARES | deep_think_service.py:3219 `_prune_schema_tables` | BFS/Steiner komşularını can_view scope ile kesiştir → yetkisiz komşu LLM context'ine hiç girmesin (yanlış-tablo mesajı kökten biter) |
| **G5** Sistemik açıkları G1 ile kapat | ARES + HERMES + NIKE | agentic wiring.py, query_builder_api.py:504, query_state_api.py:383, schedule_runner.py:200 | Her execute yolu G1 helper'ından geçsin (fail-closed). agentic pipeline'a user_ctx + scope wire et. |
| **G6** Test | TYCHE | tests/ | G1 helper (boş→deny), G2 pre-gen gate, G3 mesaj normalizasyonu, G4 FK-scope, G5 her yüzey için unauthorized→deny. |

## 4. Critical Files
- YENİ: `app/services/db_smart/table_guard.py` (merkezi fail-closed helper)
- `app/services/deep_think_service.py` (G2,G3,G4)
- `app/services/pipeline/wiring.py` + nodes (G5 agentic)
- `app/api/routes/query_builder_api.py`, `query_state_api.py` (G5)
- `app/services/db_smart/schedule_runner.py` (G5)
- `app/services/safe_sql_executor.py` (check_table_whitelist — opsiyonel `strict=True` fail-closed mod)

## 5. Yeniden Kullanılacak
- `resolve_scope` / `AccessScope.allows` (mevcut, v3.39.0 fixli)
- `check_table_whitelist` (G1 bunu sarar, boş-tuzağını kapatır)
- generate_report/execute-stream enforcement deseni (referans)

## 6. Risk
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| FK-scope sınırlama (G4) join kalitesini düşürür | orta | orta | Yalnız komşuları filtrele; asked+scope-içi join'ler korunur; ORACLE review |
| agentic pipeline'a scope wire breaking | orta | yüksek | G5 ayrı faz; agentic UI'da kullanılıyor mu önce doğrula; fail-closed ama feature-flag opsiyonu |
| Merkezi helper tüm execute'u etkiler | yüksek | orta | Önce G1+test, sonra çağıran migrasyonu tek tek + regresyon |
| LLM-pipeline değişikliği unit-test zor | yüksek | orta | G2/G3/G4 saf-fonksiyon parçalara ayrılıp unit test; canlı app smoke (kullanıcı doğrular) |

## 7. Verification
- Unit: table_guard (boş scope→deny), pre-gen gate (asked all-out-of-scope→mesaj), sanitize (3 string→tek format), FK-scope.
- Canlı smoke (kullanıcı + ZEUS): FATURA-only admin → "müşteri listesi" → **"Yetkili tablolarınız: FATURA..."** net mesaj, sipariş adı GEÇMEZ; FATURA sorusu → çalışır; her yüzey (agentic/query_builder/query_state) yetkisiz tablo → deny.
- Backend restart + bundle (FE mesaj değişmezse rebuild gerekmez).

## 8. Out-of-scope / sıralama
- **Önce kapatılacak (bu plandan ÖNCE commit edilmemiş):** v3.39.1 alias fix (ast_renderer `_quote_output_alias`) + wizard eksik i18n key'leri — küçük, hazır, ayrı commit.
- Discovery yüzeylerinde "silent filter vs mesaj" tutarlılığı (P3 — şimdilik silent kabul, existence-leak yok).
- `/suggested-queries` text leak (P3, minor).
- check_table_whitelist şema-agnostik (RB-v3.39.0, ayrı).

## 9. Faz Önceliği (öneri)
**Faz A (acil — senin gördüğün):** G2 + G3 + G4 → "Veritabanında Ara" net+doğru mesaj. (deep_think tek dosya, izole)
**Faz B (güvenlik):** G1 + G5 → tüm execute yolları fail-closed. (sistemik)
**Faz C:** G6 testler her faz ile beraber.
