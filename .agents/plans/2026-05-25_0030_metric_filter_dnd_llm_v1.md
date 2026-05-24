# Plan — Metrik 0/405 + Filtre DnD kolon sıralama + LLM öneri
**Date:** 2026-05-25 00:30
**Branch:** `hira`
**Slug:** `metric_filter_dnd_llm`
**Trigger:** Kullanıcı bildirim (3 screenshot kanıtlı):
1. **Metrik step**: "Metrik kütüphanesi boş (migration 033 uygulanmamış olabilir)" — migration aslında uygulanmış, library'de 30 metrik var → endpoint `items=[]` dönüyor.
2. **Console 405** `POST /api/db-smart/sessions/<uid>/explain` → AST editor `_refreshExplain` 405 alıyor.
3. **Filtre step**: Sadece kolon listesi placeholder ("FAZ 1 P3'te tam UI") — rapor için sıralama/seçim yok.
4. **Yeni özellik**: Sürükle-bırak alanı (rapora dahil kolonlar + sıra) + "LLM ile öner" butonu (FK+tablo context).

---

## Council Owners

| Üye | Sorumluluk |
|---|---|
| **HEBE** | UI/UX — Filtre step layout, DnD alanı, LLM öneri butonu/loading state |
| **HERMES** | DOM — drag/drop event'leri (HTML5 DnD + klavye fallback), focus management |
| **ATHENA** | FSM — `_state.reportColumns` array (sıralı), `_state.metric` ile etkileşim |
| **POSEIDON** | Data flow — `/metrics` endpoint min_score fallback, `/columns/suggest-order` yeni endpoint, payload contract |
| **ARES** | Backend — metric_engine fallback path, explain endpoint route fix, LLM prompt builder |
| **APOLLO** | LLM — kolon sıralama prompt'u (tablo+FK context → JSON order), şema-bağımlı çıkış doğrulama |
| **TYCHE** | Tests — eligible=0 fallback unit, suggest-order LLM mock, DnD state assertion |

---

## Tanı

### M-1 — Metrik endpoint items=[]
- [`app/api/routes/db_smart_api.py:1505-1570`](app/api/routes/db_smart_api.py) `list_metrics` — `table_id` verilince `metric_engine.list_eligible(cur, sig, current_user, min_score=0.6)` çağrılıyor.
- `min_score=0.6` curation eşiği yüksek → ÖDEMELER tablosu için 0 dönüyor (ds_column_enrichments boş, default scoring < 0.6).
- **Fix yaklaşımı**: Eligible boşsa → tüm aktif library'den `applicable_when` basit filtre (table type/category eşleşmesi yok ise tümünü göster) + payload'a `fallback: true` flag ekle. Frontend "0 eligible — tümünü göster" hint'i basabilir.

### M-2 — `/sessions/<uid>/explain` 405
- Backend route `@router.post("/sessions/{session_uid}/explain")` mevcut (`db_smart_api.py:520`). Router prefix `/api/db-smart` → endpoint `POST /api/db-smart/sessions/<uid>/explain`.
- 405 → büyük olasılıkla `session_uid` parametresi henüz set değil (örn. `state.sessionUid` boş veya `undefined` literal) ve URL path normalize edilmedi → method bypass. Doğrulanması gereken:
  1. Backend route gerçekten kayıtlı mı (uvicorn restart sonrası): `app.include_router` çağrısı tetikleniyor mu?
  2. `state.sessionUid` ne zaman set ediliyor — wizard Önizleme step'inde mount oluyor; ama 405 Metrik step açılınca tetikleniyor mu? (subagent inceleyip CSV'leyecek)
  3. Eğer endpoint yoksa veya method farklıysa, route ekle/düzelt.

### F-1 — Filtre step P3 eksik UI
- [`db_smart_wizard.js`](frontend/assets/js/modules/db_smart_wizard.js) `_loadFilters` (~line 600+) sadece kolon listesi basıyor.
- Yeni UI:
  - **Üst**: Mevcut kolon listesi (kategorize: id/date/amount/code/name) — her satırda "Rapora ekle" butonu (+ ikon).
  - **Alt**: Drag-drop sıralı liste → "Raporda görünecek kolonlar (sürükleyerek sıralayın)" → her chip × ile çıkar.
  - **Sağ üst**: "✨ LLM ile öner" butonu → backend `/columns/suggest-order` POST → response'taki sırayla DnD alanını doldur.
- State: `_state.reportColumns = [{column_name, semantic_type}, ...]` (sıralı). Önizleme step'i bu sırayla SELECT üretmeli.

### L-1 — LLM öneri endpoint
- Yeni: `POST /api/db-smart/columns/suggest-order`
- Body: `{ source_id, primary_table_id, join_table_ids: [], available_columns: [{name, semantic_type, table}, ...] }`
- LLM prompt: `app/services/llm.py` (mevcut LLM wrapper) → "Bir rapor için en mantıklı kolon sırası nedir? FK ilişkileri ve tablo bağlamı verildi. JSON döndür: {ordered: [col_name, ...], rationale: 'kısa Türkçe'}"
- Response validate: `ordered ⊂ available_columns names`; geçersiz key varsa 400.

---

## Deliverables

### B7 — Backend metrics fallback (POSEIDON+ARES)
**Dosya**: `app/services/db_smart/metric_engine.py`, `app/api/routes/db_smart_api.py`

1. `list_eligible` 0 dönerse (`min_score` filtresi sonrası boş) → tüm aktif library'yi `min_score=0.0` ile yeniden çağır + `fallback=True` döndür.
2. `db_smart_api.py:list_metrics` response'a `"fallback": bool` ekle.
3. Frontend `_loadMetrics`: `data.fallback` true ise hint mesajı: "Bu tablo için özel skorlu metrik bulunamadı; tüm library gösteriliyor."

### B8 — Explain 405 tanısı + fix (ARES+POSEIDON)
**Dosya**: `app/api/routes/db_smart_api.py`, `frontend/assets/js/modules/db_smart_ast_editor.js`

1. Route handler signature + dekoratör tetkiki — `Depends(get_current_user)` v.b. CORS preflight'ı 405'e çevirebilir mi? OPTIONS handler ekle.
2. `state.sessionUid` undefined ise `_refreshExplain` early return (önleyici guard).
3. Eğer endpoint çalışıyorsa: subagent curl ile doğrulasın → çalışıyorsa frontend kaynak; çalışmıyorsa backend kaynak.

### B9 — Filtre step DnD UI (HEBE+HERMES+ATHENA)
**Dosya**: `frontend/assets/js/modules/db_smart_wizard.js`, `frontend/assets/css/modules/_db_smart_wizard.css`, `frontend/home.html` (gerekirse panel structure)

1. `_loadFilters` rewrite:
   - Sol panel: kolon kataloğu (mevcut listede her satırda "+ Ekle" butonu).
   - Sağ panel: `<ul id="dswReportColumns" class="dsw-dnd-list">` — boşsa "Henüz kolon eklenmedi" placeholder.
   - Her DnD item: `draggable="true"`, `role="listitem"`, klavye için ↑↓ + Space (a11y).
   - `×` ile çıkar; "Tümünü temizle" butonu.
   - "✨ LLM ile öner" butonu → loading state → `/columns/suggest-order` POST → response.ordered ile listeyi doldur + rationale toast.
2. `_state.reportColumns`: ordered array of `{column_name, semantic_type, table_name}`.
3. CSS: `.dsw-dnd-list` (border-dashed when empty, grid when items), `.dsw-dnd-item` (cursor:grab + drag hover state).
4. Önizleme step'inde (`_loadPreview` veya wizard preview SQL builder) `_state.reportColumns` varsa o sırayla SELECT.

### B10 — LLM suggest-order endpoint (POSEIDON+APOLLO+ARES)
**Dosya**: `app/api/routes/db_smart_api.py` (yeni route), `app/services/db_smart/llm_column_order.py` (yeni)

1. Pydantic body: `SuggestOrderReq { source_id, primary_table_id, join_table_ids=[], available_columns: List[ColumnInfo] }`.
2. Service: tablo metadata + FK graf bilgisini topla → prompt template:
   ```
   Sen bir BI uzmanısın. Aşağıda bir raporun kaynak tablosu ve ilişkili tablolarının kolonları var.
   Bir BI kullanıcısının raporda göreceği en doğal kolon sırasını öner.
   Kural:
   - Identifier (id) sola
   - İsimler (name/title) sonra
   - Tarih kolonları orta
   - Tutar/sayısal kolonlar sağa
   - Foreign key id'ler grubun sonunda
   Çıktı SADECE JSON: {"ordered": ["col1", "col2", ...], "rationale": "kısa Türkçe açıklama"}
   ```
3. `llm.call(...)` (mevcut wrapper, model: config'ten) → JSON parse → validate (ordered ⊂ available).
4. Response: `{ ordered: [...], rationale: str }`.
5. **NOT**: Tenant scoping — source_id user'ın company'sine ait olmalı (data_sources WHERE company_id=?).

### B11 — Tests (TYCHE+ARES)
**Dosya**: `tests/db_smart/test_metric_fallback.py`, `tests/db_smart/test_suggest_order.py`

1. `test_list_metrics_falls_back_when_eligible_empty()` — high min_score → fallback path → items > 0 + flag.
2. `test_suggest_order_validates_columns()` — LLM mock döndüğü `ordered` available_columns subset değilse 422 fırlat.
3. `test_suggest_order_tenant_isolation()` — başka tenant'ın source_id'si → 404/403.

---

## Subagent Dispatch (4 paralel)

| Brief | Owner | Files |
|---|---|---|
| `agentEDIT7_metric_fallback` | general-purpose | metric_engine.py, db_smart_api.py (list_metrics) |
| `agentEDIT8_explain_405_diag` | general-purpose | db_smart_api.py (explain route), db_smart_ast_editor.js (guard) |
| `agentEDIT9_filter_dnd_ui` | general-purpose | db_smart_wizard.js (_loadFilters), css, home.html |
| `agentEDIT10_llm_suggest_order` | general-purpose | db_smart_api.py (new route), llm_column_order.py (new), wizard integration |

Sırasıyla: B7+B8+B9 paralel, B10 wizard entegrasyonu B9 mount noktası gerektirir → B9 done sonrası B10 frontend hook ekleyebilir. Backend route B7-B8-B9'dan bağımsız.

---

## Acceptance

1. Metrik step: tablo seçili → endpoint 200, `items.length > 0` (fallback ile bile), "boş" mesajı görünmez.
2. Console: `/explain` 405 yok (ya geçerli 200 ya da hiç çağrılmıyor).
3. Filtre step: sol kolon listesi + sağ "Raporda görünecek" DnD listesi + LLM öner butonu.
4. "+ Ekle" tıkla → kolon DnD'ye geçer; sürükle → sıra değişir; × → kaldırılır.
5. "✨ LLM ile öner" → 1-3sn loading → DnD listesi LLM önerisi sırasıyla dolar + toast "Önerilen sıra uygulandı".
6. Önizleme step'i: `SELECT col1, col2, ...` reportColumns sırasıyla.

---

## Risks

- **R-1**: LLM yanıtı invalid JSON → backend retry 1x + fallback (orijinal sıra) + 502 değil 200 + warning.
- **R-2**: Çok fazla kolon (50+) → prompt token bütçesi taşar → ilk 30 kolon ile sınırla + uyarı.
- **R-3**: DnD a11y — klavye-only kullanıcılar için ↑↓ shortcut zorunlu (HEBE doğrulasın).
- **R-4**: `/explain` 405 backend bug ise tüm AST editor session'ları etkilenir — öncelik medium ama log spam'i temizlemek için B8 yine de yapılmalı.

---

## Restart/Reload requirements (memory rule)
- Backend değişiklikleri: **uvicorn restart şart** (B7, B8, B10).
- Frontend değişiklikleri: `npm run build` + **browser hard-reload Ctrl+Shift+R** (B8 frontend guard, B9, B10 wizard hook).
