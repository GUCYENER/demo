---
plan_id: admin_company_first_pin
created: 2026-06-02
branch: hira
status: completed
version_target: v3.50.0
closed: 2026-06-02
closure_note: "rls_context (_first_company_id + resolve + apply) v3.50.0. test_rls_context.py 8 passed (restart sonrası) + izole 7/7 smoke. is_admin bypass + non-admin fail-closed KORUNDU. Commit+push edildi."
council_mod: 3
hebe_gate_required: false
---

# Admin NULL company_id → tanımlı ilk firmaya sabitleme (FK kaynak bulma hatasını önle)

## Context (Neden?)
Admin kullanıcı tasarımca NULL company_id taşıyor (schema.py:764 backfill yalnız non-admin'i
doldurur; v3.43.1 admin+NULL→sentinel 0 RLS bypass). Bu NULL, "keşif" + "veritabanında ara" FK
kaynak bulma akışlarında `resolve_effective_company_id` source_id=None iken None döndürüp
400/403 hatası veriyor. Kullanıcı: admin firma kodunu **tanımlı ilk firmaya** (ORDER BY id LIMIT 1,
kullanıcı kararı) sabitle, hata olmasın.

## Mevcut Durum (kanıtlı)
- `companies`: company_code YOK; kimlik = id (PK) + tax_number (UNIQUE). "ilk firma" = ORDER BY id.
- `resolve_effective_company_id` (rls_context.py:172): admin+NULL → kaynağın firması; source yok/NULL
  → **None** → caller 400/403. (db_smart_api.py:281/1287/1372)
- `apply_vyra_user_context` (rls_context.py:88): admin+NULL → **sentinel 0**. is_admin='true' GUC
  RLS bypass (mig 032: policy'ler `OR vyra.is_admin='true'`).
- Çok-tenant güvenliği: dbsmart RLS is_admin bypass → admin company_id pin'lense de çapraz-tenant
  erişim KORUNUR (kanıt mig 032:308-355). Pin yalnız kaynaksız oluşturulan kayıtların company'sini etkiler.

## Tasarım kararı — RUNTIME çözümleme (DB-level UPDATE DEĞİL)
DB'de `UPDATE users SET company_id` YAPILMAZ (v3.43.1'in bilinçli admin-NULL + is_admin-bypass
tasarımını tersine çevirmez; non-db-smart kodda "admin NULL = tüm firmalar" semantiği bozulmaz).
Bunun yerine yalnız iki rls_context fonksiyonu admin+NULL'da ilk firmaya düşer.

## Faz/Gate Haritası
- **G1 — Helper (HERMES + HEPHAESTUS):** `_first_company_id(cur)` → `SELECT id FROM companies
  WHERE is_active=TRUE ORDER BY id LIMIT 1` (dict/tuple-safe, hata→None).
- **G2 — resolve_effective_company_id (HERMES + ARES):** admin+NULL → önce kaynağın firması,
  yoksa _first_company_id. NON-admin+NULL → None (fail-closed KORUNUR).
- **G3 — apply_vyra_user_context (HERMES + ARES):** admin+NULL → _first_company_id (firma yoksa
  sentinel 0 fallback). is_admin='true' GUC değişmez (bypass korunur).
- **G4 — Test (TYCHE):** py_compile + rls_context/db_smart testleri + sahte-cursor smoke
  (admin+NULL+source / admin+NULL+no-source / non-admin+NULL fail-closed).
- **G5 — Code review (ZORUNLU):** /code-review medium.
- **G6 — Versiyon (HERA):** v3.50.0.

## Critical Files
- `app/services/db_smart/rls_context.py` (_first_company_id + 2 fonksiyon)
- `app/core/config.py` (versiyon)

## Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Admin çapraz-tenant kaybı | Düşük | admin tek firmaya kısılır | is_admin='true' bypass DEĞİŞMEZ (mig 032 kanıt); GUC company yalnız bilgi |
| Boş DB (firma yok) | Düşük | _first None | apply'da sentinel 0 fallback; resolve None (caller handle) |
| non-admin NULL sızıntı | Düşük | cross-tenant | non-admin+NULL → None KORUNUR (fail-closed) |
| Her istekte companies sorgusu | Düşük | minik PK sorgu | yalnız admin+NULL (nadir) yolunda; normal kullanıcı etkilenmez |

## Verification
- Sahte-cursor: admin+NULL+source→source firma; admin+NULL+source yok→ilk firma; non-admin+NULL→None.
- py_compile + pytest (rls_context/db_smart varsa).
- Canlı: admin kaynaksız wizard/arama → 400/403 yok (kullanıcı testi).

## ⏸️ CHECKPOINT (2026-06-02, PC restart öncesi — RESUME BURADAN)

**Kod TAMAM, COMMIT EDİLMEDİ.** Çalışma ağacında bekliyor:
- `app/services/db_smart/rls_context.py` — `_first_company_id` helper + `resolve_effective_company_id`
  (admin: kaynak firması → yoksa ilk firma) + `apply_vyra_user_context` (admin+NULL → ilk firma, yoksa 0).
- `app/core/config.py` — APP_VERSION = "3.50.0" (+ changelog notu).

**Doğrulama durumu:**
- ✅ py_compile OK (python3).
- ✅ İzole sahte-cursor smoke 7/7 GEÇTİ (python3, `/tmp/rls_smoke.py`): admin+source→source firma,
  admin+no-source→ilk firma, admin+source(NULL)→ilk firma, non-admin+NULL→None (fail-closed),
  user→kendi, boş DB→None, companies-hata→None. apply admin+NULL → GUC company=ilk firma, is_admin='true'.
- ✅ Fixture analizi: `fake_admin_ctx` company_id=1 (NULL değil) → mevcut test_rls_context.py testleri
  admin+NULL branch'ini TETİKLEMEZ → kırılmaz.
- ⚠️ **Windows python.exe pytest WSL'de FLAKY** (vsock "accept4 failed 110" / hang / timeout 124) —
  test_rls_context.py'yi gerçek pytest ile koşamadım (ortam sorunu, kod değil). **RESTART SONRASI İLK İŞ:**
  `PYTHONUTF8=1 ./python/Scripts/python.exe -m pytest tests/db_smart/test_rls_context.py -q` koş (yeşil bekleniyor).
- ✅ Code-review (manuel + companies/data_sources RLS'siz doğrulandı): CONFIRMED bug yok.

**RESTART SONRASI KALAN ADIMLAR:**
1. `pytest tests/db_smart/test_rls_context.py` (+ istenirse test_rls_integration DB ile) → yeşil teyit.
2. Commit: `feat(v3.50.0): admin NULL company_id → tanımlı ilk firmaya runtime sabitleme` —
   dosyalar: rls_context.py + config.py + bu plan. (canlida_*.bat HARİÇ.)
3. `git push origin hira`.
4. Canlı test (kullanıcı): admin kaynaksız wizard/arama → 400/403 yok.

**Genel oturum durumu (3 commit PUSH'LANDI — origin/hira f4954bf..c2251d7):**
- 4f79e41 graphify söküm · a23648e FK sentetik keşfedilen-tablo · c2251d7 Yetkilendirme+picker (v3.49.0)
- Backlog R022 (P1, v3.50.0): test_api_db_smart.py 8 pre-existing failure — ayrı iş, sıraya alındı.

## Out-of-scope
- DB-level `UPDATE users` admin company backfill (tasarım gereği yapılmadı; istenirse ayrı karar).
- Keşif (db_learning) tarafı — zaten source-based çalışıyor (Explore doğruladı), dokunulmaz.
</content>
