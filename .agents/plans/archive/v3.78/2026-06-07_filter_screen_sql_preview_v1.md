---
plan_id: filter_screen_sql_preview
created: 2026-06-07
branch: hira
status: done
version_target: v3.78.0
council_mod: 2
hebe_gate_required: true
note: Kullanıcı isteği (2026-06-07) — "Akıllı Veri Keşfi" Step-3 Filtre ekranına "SQL Önizle" butonu; "Bu rapordan ne bekliyorsunuz?" doluysa NİHAİ SQL'e (LLM) yansıyıp alt kısımda görünsün. Amaç: kullanıcı SQL'i ÖNCEDEN görsün. ŞU AN implementasyon YOK (ayrı planlandı).
---

# Filtre Ekranı (Step-3) SQL Önizleme Butonu

## 1. Context (Neden)
Kullanıcı: Step-4 Önizleme'ye gitmeden, **Step-3 Filtre** ekranında SQL'i önceden görmek istiyor —
hem SEÇİM-tabanlı (baseSql) hem **"Bu rapordan ne bekliyorsunuz?" talebiyle oluşan NİHAİ SQL** (LLM, finalSql).
Görsel hedef: mevcut "SQL Önizleme — Seçim vs Nihai" modalı (img_134223: üst=baseSql, alt=finalSql).

İlişki: Bug A fix'i (v3.77.x) ile `user_intent`/`userNote` artık güvenilir yakalanıyor → finalSql talebi doğru besler.

## 2. Mevcut Durum (Explore — gerçek kod, varsayım yok)
- **SQL önizleme modalı ZATEN var** (`db_smart_wizard.js` ~4230-4320): `_state.baseSql` (üst, seçim/assemble) +
  `_state.finalSql` (alt, LLM+talep). Başlık: `'SQL Önizleme — Seçim vs Nihai'` (4282).
- **`_computeFinalSqlForPreview()`** (4214) NİHAİ SQL'i **ÇALIŞTIRMADAN** üretir (`generate_only`), cache'li.
  Cache anahtarı **`_finalSqlCacheKey()`** (4161) seçim/metrik/**talep (user_intent)** değişince invalidate →
  yani finalSql zaten user_intent'i içerir. (İçerik backend `llm_generate_report.py` finalSql yolundan.)
- **Step-3 render `_renderStep3`** (1178): sol kolon-kataloğu + sağ "Raporda görünecek kolonlar" (DnD) +
  başlıkta **"✨ LLM ile öner"** butonu (`#dswSuggestOrderBtn`, 1248) + altta `#dswUserNote` textarea (1262).
- **baseSql** Step-4 `_loadPreview`'da set ediliyor (2037). Step-3'te baseSql henüz olmayabilir → önizleme
  butonu Step-3'te baseSql'i de assemble etmeli (mevcut `/preview` veya `_buildWizardState` + assemble).

## 3. Faz/Gate Haritası (taslak)
| Gate | İş | Konsey |
|---|---|---|
| G1 | E1: Step-3 başlığına/note yanına **"SQL Önizle"** butonu (`#dswPreviewSqlBtn`) — `_renderStep3`'e ekle | HEBE + ATHENA |
| G2 | E2: Buton handler → mevcut SQL-önizleme modalını aç (4230-4320 reuse); Step-3'te baseSql yoksa önce assemble et | HEBE + HERMES |
| G3 | E3: NİHAİ SQL talebi = güncel user_intent/userNote (Bug A fix sonrası `_state.user_intent`); cache-key talep'i içeriyor → otomatik | HERMES + APOLLO |
| G4 | E4: Boş-talep durumu: user_intent boşsa alt bölüm "talep girilmedi" bilgisi / yalnız baseSql göster (kullanıcı isteği: doluysa göster) | HEBE |
| G5 | E5: CSS + bundle rebuild + render kanıtı (headless-chrome) | HEBE |
| G6 | Post-impl code-review + council + test + sürüm/commit | HERMES/ARES/TYCHE |

## 4. Critical Files
- `frontend/assets/js/modules/db_smart_wizard.js` — `_renderStep3` (buton) + handler + modal reuse — MODIFY
- `frontend/assets/css/modules/db_smart*.css` — buton stili (gerekirse) — MODIFY
- `frontend/dist/bundle.min.*` + `home.html` — REGEN (build.mjs)

## 5. Yeniden Kullanılacak (kod tekrarı önle)
- SQL-önizleme modal fonksiyonu (~4230-4320) — KORU, yeni tetikleyiciden çağır.
- `_computeFinalSqlForPreview` (4214) + `_finalSqlCacheKey` (4161) — değişmez (talep'i zaten içerir).
- `_buildWizardState` + `/preview` (baseSql assemble) — Step-3'te baseSql üretimi için.
- `_prettyPrintSql` (modal SQL formatı) — değişmez.

## 6. Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Step-3'te baseSql yok → modal üst bölüm boş | Orta | Düşük | Buton önce assemble/preview çağırır; yoksa "seçim tamamlanmadı" bilgisi |
| finalSql LLM çağrısı Step-3'te gecikme/maliyet | Orta | Orta | generate_only + cache (talep değişmedikçe tekrar üretmez); buton "üret" niyeti açık |
| Çalışan Step-4 önizleme/Çalıştır akışını bozma | Düşük | Yüksek | Modal + finalSql fonksiyonları DEĞİŞMEZ; yalnız yeni tetikleyici eklenir (additive) |
| user_intent boşken yanıltıcı alt-SQL | Düşük | Düşük | Boş-talep → alt bölüm gizli/bilgi (G4) |

## 7. Verification
- Step-3'te "SQL Önizle" → modal açılır; üst=baseSql, alt=finalSql (user_intent doluysa onu yansıtır).
- user_intent boş → alt bölüm "talep girilmedi" (yalnız baseSql).
- Mevcut Step-4 Çalıştır/önizleme regresyon yok (modal fonksiyonu paylaşımlı, değişmedi).
- `node frontend/build.mjs` exit 0; headless-chrome render (buton + modal görünür).

## 8. Out-of-scope
- Bug B (kaydedilen rapor çalıştır→boş) — AYRI (kullanıcı test edip bilgi verecek; img_134223 ipucu: NİHAİ SQL `Username` küçük-harf).
- SQL düzenleme/elle yazma (önizleme salt-okuma).
- Backend finalSql üretim mantığı değişikliği (mevcut llm_generate_report yeterli).

## İlerleme Kaydı
- [x] G1 buton render (`#dswPreviewSqlBtn`, not kutusu altı) · [x] G2 handler+modal reuse (`_onStep3PreviewSqlClick` → `_refreshBaseSqlForPreview` → `_onShowSqlClick`) · [x] G3 talep wiring (`_computeFinalSqlForPreview` `userNote`'u zaten okur, Bug A fix'i tutarlı) · [x] G4 boş-talep (`_onShowSqlClick` yalnız baseSql gösterir) · [x] G5 CSS (`.dsw-user-note-actions` + reuse `dsw-llm-btn-sql`) + bundle · [x] G6 code-review (2 finder: F1 assembly-fail guard + F2 shared `_postPreviewSql`; minor accept) + sürüm v3.78.0

**Tamamlandı (v3.78.0):** reuse-ağırlıklı; backend YOK. Canlı görsel teyit + commit kullanıcı testinden sonra.
