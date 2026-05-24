# Smart Discovery — Post-Test User Feedback Fixes (v3.34.3)

**Tarih**: 2026-05-24 22:00
**Konsey**: ATHENA (lead) + HEBE (UI/UX) + METIS (code audit) + HEPHAESTUS (build)
**Bağlam**: Kullanıcı manuel browser testi sonrası 3 net bulgu raporladı. "12 bulgu bulup düzelttin, hiçbir şey yansımamış" feedback'i.

## User-Reported Bulgular (3 adet, kanıtlanmış)

### Bug-1 [KRİTİK]: Picker modal arka planda açılıyor
- **Görsel**: 2. ekran. Wizard modal açık iken "Ara"ya tıklanınca picker görünmüyor.
- **Root cause**: `frontend/assets/css/modules/_db_smart_wizard.css:215` wizard modal `z-index: 1100`, line 759 picker modal `z-index: 1100`. **AYNI değer**. Comment "wizard modal'ın üstünde" yanıltıcı; DOM sıralamasına bağlı, picker önce render edilirse arkada kalıyor.
- **Fix**: Picker modal stacking → `z-index: 1300` (overlay+dialog tüm child'lar dahil). Filter modal (line 215) da kontrol et — picker'dan düşük olsun.

### Bug-2 [ORTA]: Wizard step 1'de "Veri kaynağı" göstergesi yok
- **Görsel**: 2. ekran. Sadece "Ara" butonu + "Arama sonuçları burada görünecek". Hangi kaynağa karşı çalıştığı belirsiz.
- **Root cause**: `db_smart_wizard.js:204-210` "v3.34.2 koşullu görünürlük" — `>1 source varsa select göster`, tek source ise `hidden`. User'ın setup'ında tek source var → tamamen gizli.
- **Fix**: Tek source durumunda **readonly badge** göster ("Kaynak: ORACLE-LOCAL-TEST"), multi-source'da select kalmaya devam etsin. Wizard step 0 panel HTML'inde (home.html:823–832 arası dsw-ara-card) hidden select'in yanına `<span class="dsw-ara-source-label" hidden></span>` ekle, JS `_loadSources()` içinden tek-source durumunda doldur ve göster.

### Bug-3 [DÜŞÜK]: "Rapor ara" × icon görünmüyor (user perception)
- **Görsel**: 1. ekran. "Rapor ara..." input → × yok.
- **Doğrulama**: `saved_reports_grid.js:127-134` × button mevcut, `searchClear.hidden = true` (boş input'ta saklı, dolduğunda görünür). `_saved_reports_grid.css:96+` styling tanımlı. Bundle'da da var (grep count: 1).
- **Olası gerçek sorun**: 
  - (a) User input'a yazmamış (boş → hidden by design — yanlış algı), VEYA
  - (b) CSS `.srg-search-wrap.is-filled .srg-search-clear` kuralı (line 124) — `is-filled` class JS'te eklenmiyor olabilir, fallback `searchClear.hidden = false` ile çalışıyor ama `is-filled` styling yine de eksik.
- **Fix**: 
  1. `saved_reports_grid.js` input handler'da `searchWrap.classList.toggle('is-filled', hasValue)` ekle (eğer yoksa). Bu da × hover/positioning'i düzeltir.
  2. CSS'te × tanımı `position: absolute` ise wrap `position: relative` olmalı — kontrol et.

## Ek Audit (proaktif — "12 bulgu yansımamış" şüphesine karşılık)

ATHENA+METIS aşağıdaki dosyalarda **bundle vs source diff** yapsın:
- `frontend/dist/bundle.min.js` içinde tüm v3.34.0+ enhancement marker'ları (`dsw-picker-accordion`, `_clearAllSelections`, `_BodyScrollLock`, `_mapApiError`, `accordionOpen`, `dswSourceSelect` v3.34.2 conditional) **GERÇEKTEN var mı**. Eğer biri eksikse → bundle stale, rebuild gerekli.
- Bundle build script'i (`scripts/build_bundle.js` veya benzeri) hangi modülleri include ediyor? Yeni eklenen kod entry-point'e bağlı mı?

## Görev Dağılımı (subagent — tek toplu)

**Subagent**: HEBE (lead) + ATHENA (code audit) + METIS (verify) + HEPHAESTUS (build)

1. **Bug-1 fix**: `_db_smart_wizard.css` picker modal + overlay + dialog z-index 1100 → **1300**.
2. **Bug-2 fix**: `home.html` step 0 panel'e source badge HTML eklenmesi + `db_smart_wizard.js` `_loadSources()` tek-source dolumu + CSS `.dsw-ara-source-label` styling.
3. **Bug-3 fix**: `saved_reports_grid.js` `is-filled` toggle + CSS pozisyon kontrolü.
4. **Bundle audit**: 6 marker grep, eksik varsa diff → rebuild stratejisi.
5. **Bundle rebuild**: Tüm değişiklik sonrası tek seferde rebuild + verify (marker count yeniden çalıştır).
6. **Self-verify**: Her bug için `read after write` — düzeltme gerçekten dosyada mı, bundle'da mı.

## Done Criteria

- [ ] Picker modal wizard modal'ın **görsel olarak üstünde** açılıyor (z-index: 1300)
- [ ] Wizard step 0 panel'de "Kaynak: ORACLE-LOCAL-TEST" badge görünüyor
- [ ] "Rapor ara" input'a yazınca × görünüyor; tıklayınca temizleniyor
- [ ] Bundle'da tüm enhancement marker'ları doğrulandı (grep count > 0)
- [ ] Rapor: değişen dosyalar + bundle SHA + grep count'ları

## Constraints
- Tek subagent (paralel parçalama yok — bağımlı işler)
- Read-after-write zorunlu (yanlış done iddiası YASAK — memory rule)
- Manuel olarak elle de düzelt yapma — subagent içinde
