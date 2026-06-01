# VYRA Changelog

## v3.43.3 — 2026-06-01 — Frontend cache-bust KÖK fix (ATHENA + NIKE)

> **Kullanıcı raporu:** v3.43.2'de eklenen Yetkilendirme "Tümünü Temizle"/"Seçilenleri Göster"
> kontrolleri UI'da görünmüyor.
> **Kök (varsayım değil):** `home.html` bundle'ı `?v=3.41.3` ile istiyordu (statik, ELLE bump
> ediliyor) — 2 minor geride kalmıştı. nginx `js|css` için `immutable` + `expires 30d` → tarayıcı
> eski bundle'ı servis ediyor. Kod + bundle DOĞRUydu (kontroller source ve bundle'da mevcut, render
> yolu `_renderScopeBlock`); yalnız cache-bust damgası bayattı → v3.43.0-3.43.2 TÜM frontend
> değişiklikleri (progress UI, scope kontrolleri, Etiketleme filtre) cache'li tarayıcıda görünmüyordu.
> **Fix:** (1) `home.html` `?v=` güncellendi; (2) `build.mjs` artık `?v=`'yi **bundle içerik-hash'iyle
> OTOMATİK** günceller (sha256[:10]) → drift bir daha olmaz (bundle değişmezse home.html'e dokunulmaz).
> README v3.37.9'da da "version drift fix" geçiyordu — kalıcı çözüm.

## v3.43.2 — 2026-06-01 — Keşif/Yetkilendirme UX: 4 bulgu/istek (ATHENA + HEBE + HEPHAESTUS)

> Kullanıcı raporu — kaynak DB keşfi sonrası yetkilendirme + etiketleme ekranı tutarsızlıkları.

- **🗄️ Yetkilendirme keşfedilmiş VIEW'ı göstermiyordu:** `get_source_schema_tree`
  (`data_sources_api.py`) `object_type = 'table'` ONLY sorguluyordu; Etiketleme paneli
  (`get_all_tables_status`) ise `IN ('table','view')` → elysion'da **245 table vs 388 (table+view)**,
  143 view Yetkilendirme'de yoktu ("kaynakta keşfedilen tablo aratınca gelmiyor"). Fix:
  `object_type IN ('table','view')`. Liste zaten yalnız `ds_db_objects` (keşfedilmiş) → "yalnız
  keşfedilmiş listelensin" isteği de karşılandı (artık tam küme).
- **🌐 Etiketleme "Onaylıları Göster" keşif-bekleyenleri sızdırıyordu:** `_filterLowScore`
  kapalıyken keşif-bekleyen (`enrichment_id` NULL) tablolar gizlenmiyordu. Yeni `discoveryMatch`:
  enrichment_id NULL satırlar yalnız "Düşük Skor / İsimsizleri Göster" açıkken veya "Keşif
  Bekleyenler"/"Devam Edenler" sekmesinde görünür; "Onaylıları Göster"de artık gelmez.
- **💎 Yetkilendirme "Seçili tablolar" — global kontroller:** "Tümünü Temizle" (tüm seçili tabloları
  temizle) + "Seçilenleri Göster" (yalnız seçili tabloları listele) eklendi. HEBE polish: aria-label,
  data-tooltip, `:focus-visible` outline, marka CSS değişkenleri, disabled state.

## v3.43.1 — 2026-06-01 — Hotfix: Admin kullanıcı db-smart 500 (NULL company_id)

> **Canlı kök fix (ARES + APOLLO).** Admin kullanıcılar `/api/db-smart/sources`, `/saved-reports`,
> `/sessions` vb. tüm db-smart endpoint'lerinde **500** alıyordu (yetki vardı ama çöküyordu).
> **Kök:** admin'ler tasarımca NULL `company_id`'li (`schema.py:764` backfill yalnız `is_admin=FALSE`
> kullanıcılara firma atar); `apply_vyra_user_context` ise `_coerce_tenant_int(company_id)`'i is_admin
> kontrolünden ÖNCE çağırıp NULL'da `RLSContextError` → 500. Localde admin'in company_id'si dolu
> (çalışıyor), canlıda NULL (çöküyor).
> **Fix:** `is_admin` company_id'den ÖNCE hesaplanır; **admin + NULL company_id → sentinel 0**
> (RLS `is_admin='true'` bypass'ı erişimi zaten açar, `::int` cast güvenli). **Non-admin + NULL
> company_id fail-closed KORUNUR** (cross-tenant sızıntı guard'ı bozulmaz). 5 senaryo sahte-cursor ile
> doğrulandı (admin/non-admin × NULL/dolu).

## v3.43.0 — 2026-06-01 — DB Keşif Sertleştirme (P0-A/B + P1-C/D + P2-E) + canlı düzeltmeler

> DB keşif/enrichment hattının 4 fazlı iyileştirmesi + canlıda gözlenen 2 hatanın kökten giderilmesi.
> Her faz code-review'den geçti; BİTİR `/code-review medium` HIGH bulgu (quote-aware JSON onarımı) giderildi.

- **🔴 P0-A — Re-keşif admin onaylarını artık SİLMİYOR (veri kaybı kapatıldı):** `detect_objects`
  koşulsuz `DELETE ds_table_enrichments/ds_column_enrichments` kaldırıldı; yerine diff-tabanlı
  `_invalidate_enrichments_on_diff` — silinen tablo→`is_active=FALSE` (arşiv), değişen→`schema_hash=NULL`
  (re-enrich, `admin_approved/admin_label_tr` KORUNUR), geri-eklenen→reaktivasyon (drop→recreate'te onay
  geri kazanılır), kaldırılan kolon→selektif `ds_column_enrichments` temizliği.
- **🔴 P0-B — Örnekleme temsil gücü:** `collect_samples` boyut-farkında RASTGELE örnekleme
  (`_build_sample_query`: küçük→`ORDER BY random()/NEWID()/RAND()/DBMS_RANDOM`, büyük→`TABLESAMPLE/SAMPLE`,
  4 dialect) + tablo başına `statement_timeout`/`call_timeout` + hata sonrası `rollback`. `randomize=False`
  ile eski davranış (geri-uyumlu).
- **🟠 P1-C — Enrichment hızlandırma:** `enrich_tables_batch` `ThreadPoolExecutor(max_workers=4)` sınırlı
  eşzamanlılık; her worker kendi `get_db_conn()` (pool maxconn=15), `max_workers=1`→eski sıralı yol. ~4× hız.
- **🟠 P1-D — Canlı ilerleme:** `ds_discovery_jobs.progress_current/total/stage/updated_at` (migration 050
  + `schema.py` startup garantisi), `update_job_progress`, `check_running_job` progress döner, frontend
  "X/N tablo" göstergesi.
- **🟡 P2-E — Sağlamlaştırma:** `create_job` `pg_advisory_xact_lock` ile TOCTOU (çift running job önleme);
  `_auto_invalidate_schema_records` silinen tabloda tüm `content_type`'ları temizler (orphan giderildi).
- **🐞 Prod fix — Admin paneli çöp gösteriyordu:** `get_pending_approvals`/`get_approved_enrichments`
  çıplak `dict(zip(cols, RealDictRow))` değer yerine kolon adı döndürüyordu (RealDictCursor) → dual-mode.
- **🐞 Prod fix — `system_logs.request_id` UndefinedColumn crash:** SCHEMA_SQL partial index'ten ÖNCE
  `ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS request_id VARCHAR(32)`.
- **🐞 Prod fix — LLM JSON parse hataları:** `_coerce_llm_json` çok-stratejili (json.loads →
  `extract_json_obj` → quote-aware trailing-comma stripper + literal-newline collapse) + prompt sertleştirme;
  `get_active_llm` `finally` ile connection iade (eşzamanlılık sızıntısı).
- **🧪 Test:** dual-mode + 2 pre-existing test bug (limit pagination execute-index, olmayan fixture)
  düzeltildi; batch testleri `max_workers=1` ile DB'siz deterministik.

## v3.38.8 — 2026-05-30 — BİTİR code-review düzeltmeleri

> `/code-review medium` (BİTİR KAP 1 sonrası) v3.38.4-3.38.7'yi inceledi; gerçek bulgular giderildi.

- **🔴 KRİTİK (v3.38.7'de eklenen regresyon):** `report_detail_modal` mark-run snapshot bloğu
  `result`'ı `const result` tanımından ÖNCE okuyordu → TDZ `ReferenceError` → HER Çalıştır
  catch'e düşüp "başarısız" toast veriyor, snapshot hiç yazılmıyordu. Fix: `result` tanımı +
  render ÖNCE, mark-run SONRA.
- **`_prettyPrintSql` marker collision:** v3.38.6 STX baytlarını silip düz `'KW'`/`'STR'` marker'ları
  bıraktı → `KWH_total` gibi alias keyword-marker sanılıp bozuluyor, `STR2024` placeholder restore'da
  düşüyordu. Fix: keyword marker **OBJECT** (`{kw}` — content daima string, marker daima object →
  çakışma imkânsız + kontrol baytı yok), STR placeholder `__VYRA_STR_N__`. node ile doğrulandı.
- **mark-run snapshot DoS guard:** server-side `rows≤100` + ~600KB tavan (client `slice` bir guard değil).
- **vyrazeus DB kuralı düzeltildi:** "psycopg2 default tuple döner" YANLIŞTI — `get_db_context`
  RealDictCursor; doğru desen `dict(row) if isinstance(row, dict)`. + REFACTOR_BACKLOG'a sistemik
  `dict(zip(cols,row))` site listesi (schedule_runner vb. — latent aynı bug sınıfı).

## v3.38.7 — 2026-05-30 — "Çalıştır kolon var veri yok" + duplicate-name uyarısı (modern + i18n)

> Kullanıcı testi: (1) "Çalıştır" 500 düzeldi ama sonuç tablosu kolonları gösterip satırları
> boş bırakıyor. (2) Duplicate isim uyarısı native browser popup + ham i18n key
> (`wizard.confirm.duplicate_name`). Konsey: HERMES (run/snapshot), ATHENA+HEBE (confirm UI+i18n).

- **"Çalıştır → kolon var veri yok" KÖK fix:** `report_detail_modal._renderRunResult` SSE/snapshot
  rows'u **pozisyonel dizi** (`[v0,v1,…]`) iken `row[c]` ile **kolon ADIYLA** indeksliyordu → her
  hücre `undefined` → boş ("kolon var veri yok"). Fix: `Array.isArray(row) ? row[ci] : row[c]`.
  Ek: `/mark-run` artık sonucu `last_run_snapshot`'a yazıyor (eskiden body'siz çağrılıp NULL
  kalıyordu) + modal açılışta snapshot'ı render ediyor (Çalıştır'a basmadan veri görünür).
- **Duplicate-name uyarısı modern:** native `window.confirm` (+ ham i18n key) yerine modern
  `VyraModal.confirm` (onConfirm=üzerine yaz, onCancel=alan hatası+focus, isim XSS-escape).
  Eksik i18n key'ler TR+EN eklendi: `wizard.confirm.duplicate_name[.title/.confirm/.cancel]`,
  `wizard.error.duplicate_name_field`, `wizard.toast.report_updated`.

## v3.38.6 — 2026-05-30 — SQL üretme W0/W garbage KÖK fix (frontend pretty-print STX korupsiyonu)

> Kullanıcı: "farklı tablo seçince SELECT yanlış üretiliyor (W0SELECT/W0FROM…). Bu SQL üretme
> kısmını adam akıllı incele; daha önce bu harf ekleme/temizleme gerek olmadan çalışıyordu."
> Kanıt: backend `generate_report` TEMİZ SQL döndürüyor (repair'li); garbage tamamen frontend display'de.

- **KÖK NEDEN:** `db_smart_wizard.js _prettyPrintSql` keyword marker'ı `'\x02KW\x02'` — gizli
  STX (0x02) kontrol baytları (bayt korupsiyonu; _tblKey NUL ile aynı sınıf). Marker 4 karakter
  ama `kw = p.slice(2)` sadece ilk 2'sini (`\x02K`) atıyordu → geriye `W\x02`+keyword kalıyordu
  → ekranda `W0SELECT` / `W0FROM` / `W0LEFT JOIN` / `W0ON` (STX görünmez veya `0` gibi).
- **Fix:** 4 STX baytı silindi → marker temiz `KW` → `slice(2)` doğru strip eder. node ile
  doğrulandı: temiz formatlı SQL, W yok. (report_detail_modal `JOIN_MARK=''` ESCAPE olarak
  doğru kullanıyor — dokunulmadı.)
- **NOT:** Backend `_repair_glued_keyword_garbage` (v3.37.9) bu W0'ı "LLM garbage" sanıp band-aid
  eklemişti — **yanlış teşhis**; W hiç LLM/backend'den gelmiyordu. Repair zararsız no-op olarak
  korunuyor (gerçek LLM garbage'ı için savunma).

## v3.38.5 — 2026-05-30 — B4-3 silinen kayıtlı rapor anında kaybolmuyor (eksik fix tamam)

> Kullanıcı: "Akıllı Keşif'te kayıtlı rapor silinince ekrandan hemen kaybolmuyor — düzeltmedin mi?"

- v3.38.1 optimistic `removeItem` eklemişti (kart anında gider) AMA `home.html onDeleted` hemen
  ardından `refresh()` çağırıyordu; refresh'in taze GET'i DELETE commit'ini görmeden race edip
  silinen kaydı geri getirebiliyordu (skeleton flash + reappear). Fix:
  `SavedReportsGrid._deletedIds` Set — optimistic-silinen id'ler refresh re-fetch'inde filtrelenir
  (reappear engellenir); sunucu artık döndürmeyince takipten düşer (self-heal; serial id reuse yok).

## v3.38.4 — 2026-05-30 — Bulgular4 kalan 2 madde: KÖK fix (Çalıştır 500 + WHERE 409)

> Kullanıcı testi: 2 madde hâlâ kırık. Hata izleme (v3.38.3) çalışan backend'e henüz
> yansımadığı için (eski kod; `/api/system/errors` 404) traceback'ler **reproduce** ile
> alındı. Konsey: HERMES+POSEIDON (B4-4), ORACLE+HERMES (B4-1).

- **B4-4 — "Çalıştır" / kayıtlı rapor rerun → 500 "Veri kaynağı bozuk":** KÖK NEDEN
  `_load_source` (db_smart_api.py): `get_db_context` **RealDictCursor** döndürür → `row`
  bir dict; `dict(zip(keys, row))` dict'i yinelerken **ANAHTARLARINI** verir → `rec`
  değerleri kolon adlarına eşitleniyordu (`host='host'` → canary guard → HER saved-report
  rerun "kaynak bozuk" 500; password decrypt fail de aynı bug'ın semptomuydu — yanlış
  string'i çözüyordu). Fix: `dict(row) if isinstance(row, dict) else dict(zip(keys, row))`.
  **Uçtan uca kanıt:** Oracle source 3'ten 10 satır SSE ile aktı (start/columns/rows/end).
- **B4-1 — WHERE kriter ekleyince hata (artık 409):** v3.38.1 fix'i 400 TypeError'ı çözdü
  ama session `context.ast` stale/empty olunca `ast/patch` **409 "AST oluşturulmadı"**
  veriyordu. Fix: `AstPatchRequest.base_ast` (client canonical AST) — session AST boşsa onu
  taban al (SAVE'deki wizard_state override deseninin AST karşılığı); FE `state.ast` gönderir.

## v3.38.3 — 2026-05-30 — Merkezi Hata Gözlemi (Centralized Error Observability)

> Kullanıcı: "loglama/hata yakalama zayıf; tüm hataları tek yerden gör, UI ekle, ajanlar
> önce oraya baksın." Plan: `.agents/plans/2026-05-30_0252_centralized_error_observability_v1.md`.
> Konsey: HERMES+HEPHAESTUS (log çekirdek), ARES (savunma+redaksiyon), ATHENA+HEBE (UI),
> APOLLO (CLI), ZEUS (ajan kuralı), TYCHE (test 4/4).

- **Kök eksik (kanıtlı):** `JSONFormatter` `exc_info`'yu (traceback) yazmıyordu → global
  exception handler `exc_info=True` ile loglasa bile traceback yalnız uvicorn konsoluna
  düşüyor, `vyra.log`'a girmiyordu (v3.38.2 500'ünü bulmak bu yüzden saatler aldı).
- **errors.jsonl:** ayrı ERROR+ akışı — her satır JSON (ts/level/path/method/status/request_id/
  message/**traceback**/redaksiyonlu context). "Tek yerden bak" dosyası.
- **log_exception():** tam traceback + context; PG **NUL-strip** (v3.38.2 dersi) + hassas alan
  **redaksiyonu** (password/token/…) + boyut limiti; loglama hatası isteği kırmaz.
- **request_id / X-Request-ID:** her isteğe id; 500 yanıt header + `detail.request_id` →
  kullanıcının gördüğü hata ↔ log kaydı birebir eşleşir.
- **GET /api/system/errors (+/stats):** admin, sayfalı, filtre (level/since/q/request_id).
- **"Hata İzleme" admin UI sekmesi:** Sistem Parametreleri → tablo + satır aç → tam traceback +
  request_id kopyala + filtre + özet (error_monitor.js/css).
- **CLI:** `python .agents/tools/show_errors.py --full` (DB'siz, dosyadan okur).
- **mig 049:** `system_logs.request_id` + (level,created_at) & request_id indeksleri.
- **Ajan kuralı:** vyrazeus.md "HATA AYIKLAMA — ÖNCE errors.jsonl" + kalıcı memory.

## v3.38.2 — 2026-05-30 — Tablo-yetki kaydet 500 + sessiz veri bozulması (kök: NUL ayraç)

> Ekran: `PUT /api/data-sources/3/permissions → 500` ("Save permissions error"). Bayt düzeyinde
> kanıt. Konsey: ORACLE+HERMES (kök neden), ARES (savunma+durability), ATHENA+HEBE (FE).

- **Kök neden:** `data_sources_module.js` `_tblKey` join ayracı **NUL (0x00)** baytıydı; save
  split boşluk kullanıyordu → (1) şema/tablo bölünmüyor (schema='' + composite), (2) NUL'lı
  string PostgreSQL'e gidince "null character not permitted" → **INSERT 500**.
- **Fix:** paylaşılan sabit `_TBL_SEP` = U+001F (unit separator) — join==split, çakışmasız,
  kaynak saf ASCII. + backend NUL/U+FFFD savunma stripi + bozuk satır temizliği +
  `.gitattributes *.js text` (yeniden bayt-bozulma guard'ı). Code-review: ayraç-çakışması +
  sapma + altitude bulguları shared-const ile giderildi.

## v3.38.1 — 2026-05-30 — Bulgular4 Round 2 (5 Smart Discovery fix)

> Kullanıcı: "bu bulguları daha önce düzeltmiştin ama sorun değişti" (v3.37.9 eksik/regresyon).
> Kök nedenler **kanıtla** doğrulandı (kod okundu + regex test + DB sorgulandı). Plan:
> `.agents/plans/2026-05-29_2336_bulgular4_round2_v1.md`. Konsey: ORACLE+HERMES (B4-1),
> ORACLE+ARES (B4-2), ATHENA+HEBE (B4-3), HERMES+POSEIDON (B4-4), ATHENA+APOLLO+HEBE (B4-5).

- **B4-1 — WHERE kriter ekleyince 400 "kabul etmiyor":** FE filtreyi DÜZ `{expr,op,value}`
  olarak `/ast/patch` `args`'ında gönderiyordu; backend `add_filter(ast, **args)` ama imza tek
  `filt` dict → **TypeError → 400 "AST args hatası"**. `ast_renderer.add_filter` artık hem düz
  alanları (expr/op/value/column) hem `{filt:{...}}` kabul eder (geriye uyumlu).
- **B4-2 — "Çalıştır"da W0SELECT/W0FROM garbage devam:** `_GLUED_KW_RE` anchor'ı `(?<![^\n])`
  YALNIZ satır başı garbage'ını yakalıyordu; LLM tek-satır SQL üretince `W0FROM` (boşluk sonrası)
  kaçıyordu (regex testiyle kanıtlandı). Anchor → `(?:^|(?<=\s))` (satır başı VEYA whitespace
  sonrası). String-literal/quoted-ident FP guard'ları korundu.
- **B4-3 — Silinen kayıtlı rapor ekrandan hemen kaybolmuyor:** `refresh()` taze GET'i DELETE
  commit'ini race ediyordu. `SavedReportsGrid.removeItem(id)` (optimistic) eklendi; `onDeleted(id)`
  kartı anında çıkarır, sonra refresh ile reconcile.
- **B4-4 — Kayıtlı raporu çalıştır → "Veri kaynağı bilgisi bozuk veya eksik":** DB sorgusu
  rapor source_id kolonunun **NULL** kaldığını gösterdi (save endpoint client'a güveniyordu,
  wizard_state.source_id'ye düşmüyordu; last_dialect hep None). Save (`post_save_report_flat` +
  session) artık `source_id`/`dialect`'i wizard_state'ten fallback eder; mevcut NULL rapor
  wizard_state'ten backfill edildi.
- **B4-5 — "Yeni Keşif" fresh değil + çevrilmemiş i18n key:** (a) `_resetWizardState` `#dswResults`
  (Seçilen tablolar özeti) DOM'unu temizlemiyordu → panel reuse'da eski raporun tabloları
  görünüyordu; reset'e temizlik eklendi. (b) Kod `wizard.toast.select_table_first` çağırıyordu
  ama i18n'de yalnız `wizard.hint.*` vardı → ham key; toast key TR/EN eklendi.
- **Test:** `tests/db_smart/test_bulgular4_round2.py` 11/11 PASS (add_filter flat/wrapped/
  positional/unary/value-0/missing-expr + regex inline/linestart/literal-FP/quoted-FP/clean).
- ⚠️ Backend `--reload` yok → bu fix'ler için uvicorn restart edildi; frontend bundle rebuild.

## v3.38.0 — 2026-05-29 — Tablo Bazlı Yetkilendirme (DB + Schema + Tablo)

> Konsey: HEPHAESTUS + ARES (model/migration) · HERMES + APOLLO (API) · ORACLE + ARES (Smart Discovery/text-to-sql filtre) · ATHENA + HEBE (frontend) · TYCHE (test). Plan: `.agents/plans/2026-05-29_2158_table_level_permissions_v1.md`.

Kaynak (data source) yetkilendirmesi DB seviyesinden **DB + schema + tablo** seviyesine indirildi. Bir subject (kullanıcı/org) için kaynak bazlı `scope_mode`: `all` (tüm tablolar, geriye uyumlu varsayılan) veya `restricted` (yalnız seçili tablo allowlist'i). **Yalnız schema seçilip tablo seçilmezse hiçbir tablo okunamaz.** Kullanıcının nihai erişimi direkt + org grant'larının birleşimidir; herhangi bir grant `all` ise tüm tablolar.

- **Model (mig 048):** `data_source_permissions.scope_mode` kolonu + yeni `data_source_table_permissions` (source, subject, schema, table allowlist). RLS yok (admin-yönetimli, mevcut izin tabloları ile tutarlı). schema.py fresh-install DDL'i de güncellendi.
- **Gate:** `data_source_access.user_accessible_tables() → AccessScope` (case-insensitive, admin bypass, union, fail-closed) + `db_smart/table_scope.resolve_scope()` sarmalayıcı.
- **API:** GET/PUT `/data-sources/{id}/permissions` `scopes` (scope_mode + tables) ile genişletildi; yeni GET `/data-sources/{id}/schema-tree` (akordion ağacı). Audit before/after `scope_mode` taşır.
- **Uçtan uca filtre (yetkisiz tablo görülemez/tahmin edilemez):** Discover (`discovered-schemas`/`samples`), Smart Discovery (`search_tables`, `related` FK graph node+edge, `list_columns`/`multi` → 404/skip), **text-to-sql `get_schema_context` LLM bağlamı** (tek choke-point), `deep_think` ML schema_record, ve **SQL execute whitelist** (`deep_think` DB-Only + `generate_report`) kullanıcının `can_execute` kapsamıyla kesiştirilir; boş restricted kapsam → çalıştırma reddedilir (allow-all'a düşmez).
- **Frontend:** Yetkilendirme modalında subject başına "Tüm tablolar / Seçili tablolar" + schema akordion + tablo checkbox + arama (db_smart_picker pattern reuse, ARIA/escape/toast korunur).
- **Test:** `tests/api/test_table_level_permissions.py` (16) + `tests/db_smart/test_table_perm_filter.py` (4) — allowlist, restricted+0 tablo=deny, union, admin bypass, case-insensitive, fail-closed. 35 ilgili + 35 deep_think regresyon yeşil.
- **code-review (medium):** deep_think DB-Only execute whitelist ve generate_report `allowed_tables or None` boş-liste→allow-all açıkları kapatıldı (scope-kesişimi + boş→reddet); `get_schema_context` opt-in süzgeç tüm production caller'larda `user_ctx` geçtiği doğrulandı.
- ⚠️ **Deploy:** Migration 048 PG kapalı olduğu için bu oturumda uygulanmadı — `python run_migrations.py` ile çalıştırılmalı.

## Graphify v1.2 → v1.2.2 — 2026-05-26 — Coverage + Embedding + Bug-fix + Concurrency Sprint

> Graphify paketinin geliştirme adımları VYRA `CHANGELOG.md`'de izlenir; paket kendi git repo'sundadır (`General_Graphify/` initial commit `77330ab`, Wave D `d266249`). Tam detay: [`.agents/workflows/graphify_v12_release_notes.md`](.agents/workflows/graphify_v12_release_notes.md).

- **Wave A (G1-G8)** — File entity (55→633), Function AST emit (0→2102), `defined_in`/`imports`/`calls` predicate emission (0→16 621), post-mine embedding sweep (%0→%100), mine path resolution, KAP 10c.3 coverage threshold assert, `coverage-report` CLI subcommand.
- **Wave B (T1-T8)** — pytest paketi 171→186 test (%74 coverage); HEBE config (`pytest.ini` + `conftest.py`); ARES F1-F5 spec drift kaydı.
- **Wave C (v1.2.1)** — BUG-G1 `__pycache__` leak fix, BUG-G2 `database is locked` race partial fix (`PRAGMA busy_timeout=30000` + `_RetryingConnection` proxy; cross-instance race xfail strict=False → Wave D), R5 Class count UNION (0→298), BUG-G3 T7 entity-relative assertion düzeltmesi.
- **Wave D (v1.2.2)** — BUG-G2 final closure: class-level `_RetryingConnection._locks: Dict[str, threading.RLock]` map keyed by `db_path`; cross-instance writer serialization; `_tx()` lock-across-BEGIN/COMMIT; `_is_write_sql()` heuristic (SELECT/PRAGMA-read bypass). xfail kaldırıldı + yeni `test_two_instances_serialize_on_same_db_path` (40 yazım/2 thread, <5s).
- **Workflow** — `vyrazeus.md` KAP 10c.3 coverage threshold gate (`--threshold 0.95`); Graphify-first lookup + mine-after-fix kuralları (memory); sub-agent malware-reminder refusal pattern (memory feedback).
- **Final test**: 187/187 PASS, coverage %74.

## v3.37.0 — 2026-05-26 — Smart Discovery bulgular B1-B8 + LLM augmentation

- **B1** — Smart Discovery saved-report rerun fix (`_load_source` db_type normalize + DS guard + backfill 047b).
- **B2** — SQL pretty-print önizleme paneli (keyword newlines).
- **B3** — Saved report delete → grid auto-refresh + toast.
- **B4** — LLM Metric Suggest endpoint (`POST /api/db/smart/llm/metric-suggest`).
- **B5a** — Step 3 Next disable + toast (empty columns).
- **B5b** — LLM Column Suggest endpoint (2 kategori: metric-bound + dimensions).
- **B6** — "Bu rapordan ne bekliyorsunuz?" sticky footer textarea + `state.user_intent`.
- **B7a/B7b** — Çalıştır button sticky bottom-right + ORDER BY editable chip (ASC/DESC + drag-reorder).
- **B8** — LLM Format Suggest endpoint (3-5 format card + `chart_type` whitelist).
- **Migration** — 047 (app_version bump) + 047b (saved_reports db_type backfill — standalone).
- **Tests** — 79 yeni pytest PASS (10 + 8 + 17 + 20 + 15 + 9).
