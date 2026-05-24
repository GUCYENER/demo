# Brief — agentEDIT_F7_multi_columns

**Date:** 2026-05-25
**Plan:** `.agents/plans/2026-05-25_0330_v336_smart_discovery_completion_v1.md`
**Deliverable:** F7 — Multi-table column endpoint + UI grouping
**Council:** POSEIDON (data flow) + ARES (backend route) + HEBE (UI grouping)
**Status:** in_flight (do NOT auto-move to done/)

## Scope
Filter step (`dswStep3`) sol paneli, şu ana kadar yalnızca `_state.selectedTableId`
(primary tablo) kolonlarını gösteriyordu. Kullanıcı master-detail iş akışında,
seçili tüm tabloların (primary + join'ler) kolonlarını seçim sırasında, tablo
başlıklarıyla gruplu görmek istiyor.

## Changes

### Backend — `app/api/routes/db_smart_api.py`
- Yeni route: `GET /api/db-smart/sources/{source_id}/tables/columns?table_ids=1,2,3`
- Helper extraction: `_fetch_table_columns(cur, source_id, table_id)` — mevcut
  `list_columns` içindeki ds_db_objects + ds_column_enrichments birleştirme
  mantığı tek yere alındı; iki route da bu helper'ı çağırır.
- Per-table max 50 kolon (R-4 cap).
- Response: `{tables: [{table_id, table_name, business_name_tr, columns: [...]}, ...]}`
  CSV request order korunur.

### Frontend — `frontend/assets/js/modules/db_smart_wizard.js`
- `_loadColumns`: artık `_state.selectedTables` üzerinden CSV oluşturup yeni
  multi endpoint'i çağırır; her kolona `table_id` + `table_name` enrich edilir.
- `_renderStep3`: sol panelde `<h5 class="dsw-table-group">Tablo: …</h5>`
  separator'ları ile tablo bazlı gruplama yapar; sıra request order'a sadıktır.
- `_addReportColumn`: `table_name` ek olarak korunuyor (SQL qualify için).

### Acceptance
- 3 tablo seçili → sol panelde 3 grup başlığı, master-detail sırada.
- "+ Ekle" hâlâ çalışır; rapor kolon listesi `table_name` ile birlikte zenginleşir.

## Restart
- **uvicorn restart**: yeni route registrar olduğu için zorunlu.
- **frontend rebuild + hard reload**: bundle güncellendi.

## Verification
- `python -c "from app.api.routes.db_smart_api import router; [print(r.path) for r in router.routes if 'columns' in r.path]"`
  → hem `/columns` (single) hem `/tables/columns` (multi) listelenir.
- `cd frontend && npm run build` başarılı.
