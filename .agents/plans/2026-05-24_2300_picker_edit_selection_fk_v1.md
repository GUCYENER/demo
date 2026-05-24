# Plan — Picker "Seçimi Düzenle" + Chip × + FK Restore + Ara-Disabled
**Date:** 2026-05-24 23:00
**Branch:** `hira`
**Slug:** `picker_edit_selection_fk`
**Trigger:** Kullanıcı bildirim (screenshot kanıtlı): (a) "Seçimi düzenle" tıklanınca seçimler hatırlanmıyor; (b) seçim varken `Ara` butonu hâlâ aktif; (c) chip'lerde silme ikonu yok; (d) sağdaki "İlgili Tablolar (FK)" paneli **MUSTERILER** için boş — DB'de FK olmasına rağmen.

---

## Council Owners (per memory rule)

| Üye | Sorumluluk |
|---|---|
| **HEBE** | UI/UX — chip × ikonu, "Ara" disabled state, "Seçimi düzenle" akışı |
| **ATHENA** | State management — wizard ↔ picker state round-trip doğruluğu |
| **POSEIDON** | Data flow — `initialSelection` payload, picker `open(opts)` API |
| **HERMES** | DOM events — chip × handler, picker reopen idempotency, focus restore |
| **ARES** | Edge cases — son chip silme, edit→cancel, FK pasif kalma |
| **TYCHE** | Tests — state preservation + delete chip + Ara disabled toggle |

---

## Root Causes (kod okumasından)

### RC-1 — Wizard `_openPicker` initialSelection geçmiyor
- [`frontend/assets/js/modules/db_smart_wizard.js:230-249`](frontend/assets/js/modules/db_smart_wizard.js#L230-L249)
- `DbSmartPicker.open({ sourceId, initialQuery, onConfirm })` çağrılıyor — `initialSelection` yok.
- "Seçimi düzenle" → `editBtn.addEventListener('click', _openPicker)` (line 295), aynı boş open.
- Sonuç: picker her açılışta `_state.primaryId=null, _state.joins=new Map()` ile başlıyor.

### RC-2 — Wizard `_renderSelectedSummary` chip'lerde × yok
- [`frontend/assets/js/modules/db_smart_wizard.js:274-296`](frontend/assets/js/modules/db_smart_wizard.js#L274-L296)
- `<li>` üretiliyor, ama `<button class="dsw-chip-remove">×</button>` yok.
- Silme handler'ı + per-chip `data-table-id` yok.

### RC-3 — "Ara" butonu disabled state yönetilmiyor
- [`frontend/home.html:830-833`](frontend/home.html#L830-L833): `dswSearchBtn` her durumda aktif.
- Wizard'da seçim varken pasif olmalı (UX: önce mevcut seçimi temizle / düzenle).

### RC-4 — Backend `fk_graph.py` `RealDictRow` integer-index bug
- [`app/services/db_smart/fk_graph.py:304-315`](app/services/db_smart/fk_graph.py#L304-L315): `r[0]..r[9]` kullanılıyor.
- [`app/core/db.py`](app/core/db.py) `get_db_context()` → `RealDictCursor` → satırlar dict → `KeyError: 0` → `db_smart_api.py:1420-1422` try/except yutuyor → `{neighbors:[], junctions:[], subgraph:{nodes:[],edges:[]}}` → frontend "FK ilişkisi yok".
- **Eligibility ile birebir aynı pattern**: bu sprintte zaten eligibility.py'da düzeltildi; fk_graph.py + builds_subgraph yardımcı satırları (line 106, 131) da düzeltilmeli.

---

## Çıktılar (Deliverables)

### B1 — Wizard: chip × + Ara disabled (HEBE+ATHENA+HERMES)
**Dosya:** `frontend/assets/js/modules/db_smart_wizard.js`, `frontend/assets/css/modules/_db_smart_wizard.css`

- `_renderSelectedSummary(primary, joins)` her chip için:
  - `<span class="dsw-chip-remove" role="button" tabindex="0" aria-label="...sil" data-remove-id="...">×</span>` ekle.
  - Primary chip silinince join'ler de iptal (kullanıcıya toast: "Ana tablo silindi, seçim temizlendi").
  - Join chip silinince yalnızca o join state'ten düşer.
- Yeni handler: `_removeChip(tableId)` → `_state.selectedTables` filtrele, `_state.joinCandidates` filtrele, gerekirse `_state.selectedTableId=null` ve `dswResults` boşalt + Ara aktif et.
- "Ara" butonu: `_updateAraButtonState()` → seçim varsa `disabled=true` + `title="Önce mevcut seçimi temizleyin"`, yoksa aktif. Render ve chip silme sonrası çağır.
- CSS: `.dsw-chip-remove` (8px üst-sağ, hover: kırmızı), `.dsw-ara-btn:disabled` (opacity 0.5, cursor not-allowed).

### B2 — Picker: initialSelection desteği (POSEIDON+HERMES)
**Dosya:** `frontend/assets/js/modules/db_smart_picker.js`

- `open(opts)` yeni opsiyonel alanlar:
  - `initialSelection: { primaryId: number, joinIds: number[] }`
- Reset bloğundan sonra (line ~654-664), `opts.initialSelection` varsa:
  - `_state.primaryId = initialSelection.primaryId`
  - `_state.joins = new Map(initialSelection.joinIds.map(id => [id, true]))` (mevcut data structure'a uyumlu)
- `_loadTables()` tamamlanınca render zaten doğru state'i gösterir (checkbox işaretli, primary "ANA" badge'li).
- `_loadFkForPrimary()` primary varsa otomatik tetiklenmeli (zaten primaryId set → mevcut akış).

### B3 — Backend: fk_graph RealDictCursor uyumu (ATHENA+POSEIDON)
**Dosya:** `app/services/db_smart/fk_graph.py`

- Tüm `r[N]` / `row[N]` integer index'leri `_col(r, 'colname', N)` helper'ı ile değiştir (eligibility.py'daki pattern aynısı).
- Satırlar:
  - Line 106: `{row[0]: (_norm(row[1]), _norm(row[2])) for ...}` — kolon adlarını SQL'den oku ve dict access yap.
  - Line 131: aynı pattern.
  - Line 304-315: `_norm(r[0])`, `_norm(r[1])`, ... — 10 alan.
- SQL aliaslarını kontrol et: kolon isimlerinin SELECT'te eşleştiğinden emin ol.

### B4 — Test (TYCHE+ARES)
**Dosya:** `tests/test_db_smart_picker_edit_selection.py` (yeni)

- `test_fk_graph_build_subgraph_returns_neighbors()` — postgres direct, source_id=3 (Oracle FK test set), expected ≥1 neighbor.
- (Frontend testi: manual smoke note — pure JS test infra yok bu repo'da.)

---

## Subagent Dispatch Plan

Paralel 3 worktree (B1, B2, B3 bağımsız), sonra B4 sequential (B3 doğrulandıktan sonra).

| Brief | Owner agent | Scope |
|---|---|---|
| `agentEDIT1_chip_x_ara_disabled` | general-purpose | B1 — wizard.js + css |
| `agentEDIT2_picker_initial_selection` | general-purpose | B2 — picker.js |
| `agentEDIT3_fk_graph_realdict_fix` | general-purpose | B3 — fk_graph.py |
| `agentEDIT4_fk_test` | general-purpose | B4 — pytest |

Tüm subagent'lar:
1. Brief'i `.agents/in_flight/<id>.md` olarak yazsın
2. Done check: kod + bundle (frontend) + grep doğrulama
3. Council kararı bende kalır (memory: brief done/'a taşıma için onayım şart)

---

## Acceptance (kullanıcı testi)

1. Ana sayfada "Akıllı Veri Keşfi" → Ara → tablo seç → onayla.
2. Step 1'de chip görünür + her chip'in sağ üstünde × var.
3. "Ara" butonu **disabled** (cursor pointer-events: none görünür).
4. Chip × tıkla → chip kaybolur, son chip de gidince Ara aktif olur.
5. "Seçimi düzenle" tıkla → picker önceki seçimle açılır (Müşteri ANA badge'li ✓, join'ler işaretli).
6. Sol panelde Müşteri seçili iken sağ panel **FK ilişkili tabloları gösterir** (FATURALAR, SIPARISLER, ADRESLER, vs.).

---

## Risks

- **R-1**: Picker `initialSelection.joinIds` ile geldiğinde FK cache henüz yüklü değil; primary checkbox açıkken FK fetch tetiklenmeli — mevcut `_loadFkForPrimary` zaten primaryId set'inde tetikleniyor (B2 dispatcher doğrulasın).
- **R-2**: fk_graph diğer endpoint'leri (`expand_with_fk`, `build_subgraph`) de aynı bug'ı taşıyor; B3 hepsini tek seferde düzeltsin.
- **R-3**: Body-level picker DOM (v3.34.4) hâlâ geçerli; bu plan ona dokunmuyor.
