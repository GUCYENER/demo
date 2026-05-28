---
plan_id: data_sources_validation
created: 2026-05-28
branch: hira
status: in_progress
version_target: v3.37.7
council_mod: 2
hebe_gate_required: true
---

# data_sources Validation + Saved-Report Rerun Resilience (HERMES + ATHENA + HEBE + ARES)

## Context

Kullanıcı görsel raporu (2026-05-28):
> "HTTP 500 'host alani bozuk (source_id=1, deger='host')' — kayıtlı rapor açıp çalıştırınca."

Kök neden (kullanıcı tespiti onaylı):
> "muhtemelen kaydederken yanlış bilgileri ile kaydediyor."

İki bağımsız bulgu birleşince hata bütünleşiyor:
- **B2 (kök):** `data_sources` CREATE/UPDATE'de validation eksik. FE sadece boş kontrolü; BE `Field(max_length=500)`. Kullanıcı literal `"host"` yazınca FE+BE kabul → DB'ye bozuk satır.
- **B1 (knock-on):** `report_detail_modal.js` saved-report rerun yolunda `_report.source_id ‖ ws.source_id ‖ ws.sourceId` snapshot fallback — B2'den gelen bozuk source_id veya orphan reference yakalanır → `_load_source` HTTP 500 (data_corruption_500).

Memory: [[feedback_transparency]] — "yaptım/temiz/geçti" demeden önce icra+kanıt.

## Mevcut Durum (Explore bulguları)

- `app/api/routes/data_sources_api.py:27-53` — DataSourceCreate/Update modelleri, host sadece `Field(max_length=500)`
- `app/api/routes/data_sources_api.py:349-400` — create_data_source endpoint, INSERT yolu
- `app/api/routes/db_smart_api.py:835-961` — `_load_source` defansif kontrol, `_DATA_CORRUPTION_CANARIES = {"port","host","db_type","db_name","db_user","db_password_encrypted","id"}`
- `app/api/routes/db_smart_api.py:945-953` — `_data_corruption_500` 500 fail-loud, admin-actionable UPDATE komutu mesajda
- `frontend/assets/js/modules/data_sources_module.js:611-628` — FE host/port validation sadece boş kontrol
- `frontend/assets/js/modules/report_detail_modal.js:478` — `const sourceId = _report.source_id || ws.source_id || ws.sourceId;`
- `frontend/assets/js/modules/db_source_selector.js` — mevcut active source picker modülü (reuse edilecek)

## Faz/Gate Haritası

| Gate | Sorumlu Konsey | Açıklama |
|---|---|---|
| G1 | HERMES (BE) | `DataSourceCreate`/`Update` Pydantic `field_validator('host')` + `min_length=1` + canonical canary import |
| G2 | ATHENA (FE) | `data_sources_module.js` ek validation — kanary kontrol + minimum karakter, toast HEBE diliyle |
| G3 | ATHENA + HEBE (FE) | `report_detail_modal.js` snapshot fallback kaldırılır; saved_report.source_id NULL ise `db_source_selector` ile picker aç, kullanıcı seçer, rerun seçilen id ile |
| G4 | HERMES + ARES (BE) | `post_execute_stream` (db_smart_api.py:1078) — `_load_source` corruption → mevcut 500 detail değişmez (admin-actionable korunur) ama frontend friendly toast için response shape'e `error_code` ekle: `{detail, error_code: "source_corrupted"}`. FE handler bunu yakalar, generic toast gösterir. |
| G5 | TYCHE | Manuel test senaryoları (a-e — bkz. council görüş) |
| G6 | HERA | README v3.37.7 entry + versiyon güncelleme + bundle rebuild |

## Critical Files to Modify

- **EDIT** `app/api/routes/data_sources_api.py` — Pydantic validators
- **EDIT** `frontend/assets/js/modules/data_sources_module.js` — ek FE validation
- **EDIT** `frontend/assets/js/modules/report_detail_modal.js` — fallback kaldır, picker entegrasyonu
- **EDIT** `app/api/routes/db_smart_api.py` — `_data_corruption_500` response shape genişletme (error_code field)
- **EDIT** `README.md` — v3.37.7 entry
- **REBUILD** `frontend/dist/bundle.min.{js,css}` — `node frontend/build.mjs`

## Yeniden Kullanılacak Mevcut Fonksiyonlar

- `_DATA_CORRUPTION_CANARIES` set (db_smart_api.py:933) — BE'de Pydantic validator import edip aynı set'i kullanır
- `window.showToast`, `db_source_selector` open API — FE'de yeni UI yok
- `vyraFetch` API client — mevcut

## Risk Özeti

| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Mevcut bozuk data_source satırlar PATCH ile düzeltilemez (validation reject) | Orta | Yüksek (admin can't fix in UI) | Pydantic validator UPDATE'te bypass YOK — admin DB UPDATE ile düzeltir (gerçek senaryoda 1-2 row var); migration ayrı sprintte opsiyonel |
| Active source picker UX'i farklı yere düşürür | Düşük | Orta | HEBE picker title metin onaylı; kullanıcı her zaman iptal edebilir |
| FE bundle rebuild atlanırsa fix etkisiz | Orta | Yüksek | KAP 4 (ATHENA) zorunlu — commit öncesi `node frontend/build.mjs` |
| Saved_reports table'ında source_id mass-NULL ise her rerun picker patlar | Düşük | Orta | DB'de mevcut saved_reports sayısı az (psql sayım gerekirse) |

## Verification

```bash
# G1 — BE Pydantic
curl -X POST http://localhost:8002/api/data-sources/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"test","source_type":"database","db_type":"postgresql","host":"host","port":5432,"db_name":"x","db_user":"x","db_password":"y","company_id":1}'
# beklenen: HTTP 422 — host literal kanary

# G3 — FE rerun snapshot fallback
# saved_reports.source_id NULL bir kayıt aç → picker açılmalı
# Geçerli source seç → rerun çalışmalı

# G4 — BE error_code response
# Bozuk source_id ile execute/stream → 400 + {error_code:"source_corrupted"}
```

## Out-of-scope

- Mevcut DB'de bozuk satırların temizlenmesi (migration) — opsiyonel, kullanıcı talep ederse ayrı PR
- `port` field için ileri seviye semantic validation (default-port suggestion) — Pydantic ge=1,le=65535 yeterli
- saved_reports.source_id NULL'ları backfill — picker UI ile interactive backfill yapılabilir ama scope dışı

---

**Council konsensüs:** 7/7 ✅ (HERMES + ATHENA + HEBE + ARES + APOLLO + HEPHAESTUS + TYCHE)
**Kullanıcı onayı:** ✅ ("onay" 2026-05-28 22:58)
