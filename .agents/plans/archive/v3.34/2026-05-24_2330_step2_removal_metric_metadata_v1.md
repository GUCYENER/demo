# Plan — Step 2 ("İlişkiler") kaldırma + Metric/Column endpoint RealDictCursor fix
**Date:** 2026-05-24 23:30
**Branch:** `hira`
**Slug:** `step2_removal_metric_metadata`
**Trigger:** Kullanıcı bildirim (screenshot kanıtlı):
- "Artık 2. sekmeye, İlişkiler'e gerek yok. Kaldırabilirsiniz. İlk tablo seçimde o işleri yapıyoruz zaten."
- Step 3 (Metrik): "Metrik kütüphanesi boş (migration 033 uygulanmamış olabilir)" — yanlış mesaj.
- Step 4 (Filtre): "Bu tablo için kolon metadata'sı bulunamadı."

---

## Tanı (yapılan inceleme)

### Migration & Data Doğrulama
- `alembic_version = 046_v3350_dbsmart_interactions_company_id_index` → migration 033 ZATEN uygulanmış.
- `dbsmart_metric_library` tablosunda **30 metrik** seed'lenmiş ✅
- `ds_db_objects` tablosunda 11 tablo var (VYRA_TEST), `columns_json` jsonb alanı kullanılıyor.

### Root Cause — backend `RealDictCursor` int-index bug (sistemik)
Aynı pattern eligibility.py + fk_graph.py'da bu sprintte düzeltildi. Şimdi tespit edilen ek hot-path'ler:

**B6.a — `app/api/routes/db_smart_api.py:1432-1498` `list_columns`**
- Line 1454-1456: `row[2]`, `row[0]`, `row[1]` → KeyError → `except` yutuyor → `columns=[]`
- Line 1471: `r[0]..r[3]` aynı sorun
- Sonuç: step 4 (Filtre) "kolon metadata'sı bulunamadı"

**B6.b — `app/api/routes/db_smart_api.py:1505-1570` `list_metrics`**
- Line 1548-1556: `r[0]..r[6]` → KeyError → `items=[]`
- Sonuç: step 3 (Metrik) "metrik kütüphanesi boş"
- Bu yalnızca `table_id` parametresi yok yolu için. Wizard `table_id` GÖNDERİYOR (line 521) → `metric_engine.list_eligible()` çağrılır.

**B6.c — `app/services/db_smart/metric_engine.py`**
- Aynı bug ihtimali; subagent doğrulayıp düzeltsin.

### Step 2 Kaldırma
HTML/JS'de step numaralandırması: panel ID `dswStep0..dswStep4` (0-indexed); UI label `1..5`.
- **dswStep1** = "2 · İlişkiler" (kaldırılacak)
- **dswStep2** = "3 · Metrik" → yeni: "2 · Metrik"
- **dswStep3** = "4 · Filtre" → yeni: "3 · Filtre"
- **dswStep4** = "5 · Önizleme" → yeni: "4 · Önizleme"

---

## Council Owners

| Üye | Sorumluluk |
|---|---|
| **HEBE** | UI — stepper, label renumbering, hint metinleri |
| **ATHENA** | FSM — `_setStep` mapping, prev/next disabled state, progress "Adım N / 4" |
| **POSEIDON** | Data flow — kaldırılan `_loadRelated` referansları, state cleanup |
| **HERMES** | DOM — `dswStep1` panel'inin HTML'den silinmesi, tab event binding |
| **ARES** | Backend — RealDictCursor uyumlu `_col()` helper |
| **TYCHE** | Tests — backend pytest (columns + metrics endpoint smoke) |

---

## Deliverables

### B5 — Frontend: Step 2 ("İlişkiler") tamamen kaldırma (HEBE+ATHENA+POSEIDON+HERMES)
**Dosyalar**: `frontend/home.html`, `frontend/assets/js/modules/db_smart_wizard.js`, `frontend/assets/js/i18n/aki_kesif_*.json`

1. **home.html**:
   - `dswStep1` panel (`<div class="dsw-step-panel" data-step="1" id="dswStep1">...</div>`) SİL.
   - Stepper: `dswTab1` button (`<button ... data-step="1" id="dswTab1" aria-selected="false" ...>2 · İlişkiler</button>`) SİL.
   - Kalan stepleri renumber:
     - `dswTab2` label → `"2 · Metrik"` (was `"3 · Metrik"`)
     - `dswTab3` label → `"3 · Filtre"`
     - `dswTab4` label → `"4 · Önizleme"`
   - **NOT**: `data-step` ve `id` değerlerini KORU (dswTab2 hâlâ data-step="2", id="dswTab2" — JS bunlara güveniyor). Sadece görünen Türkçe label değişiyor.
   - Tab `aria-controls` değerleri korunsun: `dswTab2 aria-controls="dswStep2"` vb.

2. **db_smart_wizard.js**:
   - `_loadRelated` fonksiyonunu SİL (lines 461-501).
   - `_setStep` (line ~780-790) içinde `else if (n === 1) _loadRelated();` satırını SİL.
   - Total step count yerleri (örn. progress "Adım 1 / 5") → "Adım N / 4" YA DA: `dswStep1` artık yok ama state machine 0,2,3,4 olarak gidecek; renderProgress: hangi index'in kaçıncı olduğunu hesapla.
     - **Önerilen**: `dswStep1` ve `dswTab1`'i HTML'den sildiğimiz için, FSM'i bozmamak için en basit yol: `data-step="1"`'i artık skipliyoruz; `_state.step` 0'dan 2'ye, sonra 3'e, sonra 4'e gidecek. Progress hesabı: `[0,2,3,4].indexOf(currentStep) + 1` / 4.
     - Alternatif daha temiz: tüm `data-step` değerlerini renumber et (1=Metrik, 2=Filtre, 3=Önizleme) ve panel id'lerini de değiştir. Bu daha invaziv ama temiz. **Subagent karar versin** — basit/güvenli olanı seçsin (skip approach tercih edilir).
   - `_state.joinCandidates` step 2 için kullanılıyordu — picker'dan zaten geliyor; state cleanup gerekmez.

3. **i18n**:
   - `wizard.empty.related`, `wizard.hint.loading_related`, `wizard.hint.related_summary`, `wizard.hint.junction_table`, `wizard.hint.relationship_count`, `wizard.error.related_failed` anahtarlarını koru (geriye uyum için, başka modülde kullanılıyor olabilir).
   - Tab Türkçe label'larını JSON içinde (varsa) renumber et.

4. **Acceptance**:
   - Modal'da stepper 4 step gösterir: "1 · Tablo Seç", "2 · Metrik", "3 · Filtre", "4 · Önizleme".
   - Step 1'den İleri → Metrik (skip İlişkiler).
   - Geri/İleri navigation döngü olmadan akıyor.
   - "Adım N / 4" progress doğru.

5. **Build**: `cd frontend && npm run build` → `dist/bundle.min.js` ve `dist/bundle.min.css` regenerate; grep ile "İlişkiler" minified output'tan kaybolmalı.

---

### B6 — Backend: list_columns + list_metrics + metric_engine RealDictCursor fix (ARES+ATHENA)
**Dosyalar**: `app/api/routes/db_smart_api.py`, `app/services/db_smart/metric_engine.py`

1. **`db_smart_api.py:1432-1498` `list_columns`**:
   - `row[2]`, `row[0]`, `row[1]` → kolon adıyla: SELECT zaten named columns (`schema_name, object_name, columns_json`).
   - `r[0]..r[3]` for-loop → `_col(r, 'column_name', 0)`, `_col(r, 'semantic_type', 1)`, vs.
   - Helper `_col` veya inline `isinstance(row, dict)` ile pattern eligibility.py'daki gibi.

2. **`db_smart_api.py:1505-1570` `list_metrics`**:
   - For-loop `r[0]..r[6]` → kolon adıyla: SQL alias'ları zaten var (`metric_key, name_tr, category, description_tr, default_viz, applicable_when, sql_templates`).
   - `_col(r, 'metric_key', 0)`, vs.

3. **`metric_engine.py` (full audit)**:
   - Grep `r\[\d+\]|row\[\d+\]` → tüm hit'leri dict-compat hale getir.
   - `list_eligible(cur, sig, current_user, min_score)` ve `load_table_signature(cur, source_id, table_id)` özellikle önemli (wizard bunları çağırıyor table_id mevcutsa).

4. **Verification snippet** (subagent çalıştırsın):
   ```bash
   cd d:/demo_vyra && python << 'PYEOF'
   import sys; sys.path.insert(0, '.')
   from app.core.db import get_db_context
   from app.services.db_smart.rls_context import apply_vyra_user_context
   from app.services.db_smart import metric_engine
   uctx = {'id':1,'company_id':1,'is_admin':True}
   with get_db_context() as conn:
       cur = conn.cursor()
       apply_vyra_user_context(cur, uctx)
       cur.execute("SELECT id FROM ds_db_objects WHERE source_id=3 AND UPPER(object_name)='MUSTERILER' LIMIT 1")
       row = cur.fetchone()
       tid = row['id'] if isinstance(row, dict) else row[0]
       sig = metric_engine.load_table_signature(cur, 3, tid)
       print('signature columns:', len(sig.get('columns', [])) if sig else 'NONE')
       items = metric_engine.list_eligible(cur, sig, uctx, min_score=0.6) if sig else []
       print('eligible metrics:', len(items))
       # Test raw list_metrics path (no table_id)
       cur.execute("SELECT metric_key, name_tr FROM dbsmart_metric_library WHERE is_active IS TRUE OR is_active IS NULL LIMIT 5")
       for r in cur.fetchall():
           mk = r['metric_key'] if isinstance(r, dict) else r[0]
           print(' library:', mk)
   PYEOF
   ```
   Expected: signature_columns ≥ 5, eligible_metrics ≥ 1, library rows printed.

5. **Acceptance**:
   - `GET /api/db-smart/metrics?source_id=3&table_id=<MUSTERILER_id>` → `items.length > 0`.
   - `GET /api/db-smart/sources/3/tables/<MUSTERILER_id>/columns` → `columns.length > 0`.

---

## Subagent Dispatch

Paralel 2 task (B5 ve B6 bağımsız dosyalar):

| Brief | Owner | Files |
|---|---|---|
| `agentEDIT5_remove_step2` | general-purpose | home.html, db_smart_wizard.js, i18n JSON |
| `agentEDIT6_columns_metrics_realdict_fix` | general-purpose | db_smart_api.py (list_columns, list_metrics), metric_engine.py |

---

## Risk & Notes

- **R-1**: Step removal HTML'i değiştirir → kullanıcı browser hard-reload (Ctrl+Shift+R) yapmalı.
- **R-2**: Backend list_columns/list_metrics değişir → uvicorn restart şart (memory rule: açıkça bildir).
- **R-3**: 12 db_smart servis dosyasında benzer pattern var (custom_metric_parser, learning_recorder, saved_reports, etc.). Bu plan yalnız hot-path'leri kapsıyor; full audit ayrı bir brief olabilir.
- **R-4**: i18n `wizard.empty.related` vs. arama anahtarlarını silmek geriye uyumu bozabilir — koruyoruz.
