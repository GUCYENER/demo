---
plan_id: fix_wizard_authz_table_and_sql_modal
created: 2026-05-31
branch: hira
status: in_progress
version_target: v3.41.6
council_mod: 3
hebe_gate_required: true
---

# Akıllı Keşif: yetkili-ama-seçilmemiş tablo yanlış reddi + red mesajında tablo adı + SQL önizleme modal boyutu

## 1. Context (Neden)
Kullanıcı (admin, user_id=1, ORACLE-LOCAL-TEST/source 3, scope_mode=restricted; can_view+can_execute
grant'ları: ADRESLER, FATURALAR, MUSTERILER — `granted_at 2026-05-31 15:06`) Akıllı Keşif wizard'ında
*"Müşterileri adresleri ile birlikte listele"* talebinde **"yetkiniz yok"** mesajı aldı ve Akıllı Keşif'in
son yetki değişikliklerini görmediğinden (staleness) şüphelendi. Ayrıca: red mesajı **ilgili tablo adını**
yazsın; SQL önizleme modal'ı SQL uzayınca dikey büyüyüp **"Kapat"** butonunu gizliyor.

## 2. Mevcut Durum (kanıtlı — 2 read-only ajan + 3 canlı diag)
- **Staleness YOK (kanıtlı):** `data_source_access.user_accessible_tables` her çağrıda `data_source_*`
  tablolarını **canlı** okur — `@lru_cache`/modül-dict/Redis perm cache yok; admin grant düzenlemesi
  DELETE+INSERT ile aynı DB'ye commit → bir sonraki istekte görünür. Canlı `resolve_scope(can_execute)`
  user 1/source 3 için `{adresler, faturalar, musteriler}` döndü; `allows(ADRESLER)=True`,
  `allows(MUSTERILER)=True`. (diag: `Gecici_Dosyalar_Sil/_diag_scope2.py`)
- **KÖK NEDEN (kanıtlı):** `db_smart_api.py post_generate_report` `allowed_tables`'ı (`:2687-2731`)
  yalnız **picker'da seçilen** tablolardan (primary+join id) kurar. Not'tan LLM'in eklediği
  yetkili-ama-seçilmemiş ADRESLER, üretilen-SQL guard'ında (`:2784` `check_table_whitelist`) whitelist'te
  olmadığı için reddedilir. Deterministik repro (diag `_diag_whitelist.py`):
  - whitelist=picked-only `[MUSTERILER]` → `(False, '...vyra_test.adresler')`  ← bug
  - whitelist=tam execute-scope `[MUSTERILER,ADRESLER,FATURALAR]` → `(True, None)`  ← fix
  - whitelist=tam scope + yetkisiz SIPARISLER → `(False, '...siparisler')`  ← güvenlik korunur
- **Red mesajı:** site 2 (`:2792-2798`) HTTP 200 `{success:False, sql:"", error:"Üretilen sorgu yetkili
  olmadığınız bir tabloya erişiyor — gösterilmedi."}` — tablo adı YOK. Frontend bu 200-body error'ı
  `_computeFinalSqlForPreview` (`db_smart_wizard.js:3995`) ile aynen gösterir (➜ FE değişikliği gerekmez).
  site 1 (picker tablo 403, `:2719-2722`) "Seçilen tablolardan biri için çalıştırma yetkiniz yok." —
  ve FE `_mapApiError` (`db_smart_wizard.js:104`) her 403'ü generic i18n'e map'ler (server detail'i yutar).
- **Modal:** `_onShowSqlClick` (`db_smart_wizard.js:4001-4082`) paylaşılan `VyraModal.info`
  (`modal.js:80,205`) kullanır, **wrapper class YOK** → `modal.css`'teki bounded-height `:has()` kuralları
  (`:219-250`) eşleşmez → modal yüksekliği sınırsız; iki `<pre>` (her biri `max-height:320px`,
  `_db_smart_wizard.css:3068`) modal'ı taşırır; footer ("Kapat") normal akışta, ortalanmış modal
  viewport dışına itilir. (overlay z-index 11500)

## 3. Faz/Gate Haritası

| Gate | Konsey | Dosya | İş |
|---|---|---|---|
| **G1** Yetkili-ama-seçilmemiş tablo bloğunu kaldır (KÖK) | HERMES + ARES | `app/api/routes/db_smart_api.py` | restricted kullanıcıda üretilen-SQL guard + executor whitelist'ini **tam can_execute scope**'tan kur (sadece picked değil). Picker per-tablo 403 (site 1) korunur. Yetkisiz tablo hâlâ reddedilir. |
| **G2** Red mesajında tablo adı (can_view-gated) | APOLLO + ARES + HEBE | `app/api/routes/db_smart_api.py` (+ ops. `db_smart_wizard.js`) | site 2 mesajına **reddedilen tablo adını** ekle — yalnız kullanıcının **can_view** kapsamındaysa (zaten görebildiği tablo → existence-oracle sızıntısı yok); değilse generic kalır. site 1 403 detail'e tablo adı + `_mapApiError` 403'te server detail'i göster. |
| **G3** SQL önizleme modal: geniş + sabit + iç scroll | ATHENA + HEBE | `db_smart_wizard.js`, `modal.css`, `_db_smart_wizard.css` | `_onShowSqlClick` HTML'ini `<div class="dsw-sql-modal">` ile sar; `modal.css` `:has(.dsw-sql-modal)` → `max-width:880px; max-height:85vh; display:flex; flex-direction:column`; body `overflow:auto; flex:1; min-height:0`; footer `flex-shrink:0`. `<pre>` `max-height` 320→260 (ops.). |
| **G4** Test | TYCHE | `tests/` | G1: whitelist 3 senaryo (picked-only deny / full-scope allow / unauthorized deny); G2: mesaj can_view-gating (görülen→adlı, görülmeyen→generic); behavior parity. |
| **G5** Build + Versiyon + Docs | HERA + ATHENA | `frontend/build.mjs`, README, config.py | `node frontend/build.mjs` (G3 sonrası ZORUNLU); APP_VERSION 3.41.5→3.41.6 + README + system_settings; CHANGELOG. |

## 4. Critical Files
- `app/api/routes/db_smart_api.py` (G1 + G2 — `post_generate_report` ~2684-2806)
- `frontend/assets/js/modules/db_smart_wizard.js` (G2 site-1 ops. + G3 modal wrapper ~4001-4082; `_mapApiError` ~104)
- `frontend/assets/css/modal.css` (G3 `:has(.dsw-sql-modal)` ~219-250)
- `frontend/assets/css/modules/_db_smart_wizard.css` (G3 `.dsw-sql-modal-pre` ~3068)
- `tests/...` (G4)

## 5. Yeniden Kullanılacak
- `resolve_scope` / `AccessScope.allows` / `.tables` (mevcut, v3.39.0+ fixli) — G1 whitelist + G2 can_view gate
- `check_table_whitelist` (`safe_sql_executor.py:164`) — değiştirmeden reuse; reddedilen ref `_gen_err`'de
- modal.css mevcut `:has()` bounded-height flex pattern (job-detail/samples-viewer) — G3 aynısını reuse
- `_sqlModalSeq`/`_finalSqlText` stale-DOM guard (`:4056-4081`) — wrapper bunu BOZMAZ (getElementById aynı)

## 6. Risk
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| G1 whitelist genişlemesi yetkisiz tablo sızdırır | düşük | yüksek | whitelist = tam **execute-scope** (grant'lı tablolar); yetkisiz hâlâ deny (diag #3 kanıt); ARES review + TYCHE test |
| G1 admin (all_tables) path'i bozar | düşük | orta | `not exec_scope.all_tables` guard'ı korunur — yalnız restricted etkilenir |
| G2 tablo adı existence-oracle sızdırır | orta | orta | can_view-gate: yalnız kullanıcının görebildiği tablo adlandırılır; LLM'in eklediği görünmez FK-komşu → generic |
| G3 `:has()` tarayıcı desteği | düşük | düşük | kodbase zaten `:has()` kullanıyor (modal.css:219+); yeni risk yok |
| G3 modal HEBE a11y'i zayıf (VyraModal: focus-trap/return-focus/role=dialog yok) | mevcut | düşük | kapsam-dışı (mevcut VyraModal sınırı); iç `aria-label`/`aria-live`/`tabindex` KORUNUR; ayrı backlog |

## 7. Verification (uçtan-uca)
- **Unit (TYCHE):** `_diag_whitelist.py` 3 senaryosu kalıcı teste dönüştürülür (picked-only deny / full-scope allow / unauthorized deny); G2 can_view-gate unit (görülen tablo→adlı mesaj, scope-dışı→generic).
- **Canlı smoke (kullanıcı + ZEUS):** user 1 → *"Müşterileri adresleri ile birlikte listele"* → NİHAİ SQL **çalışır** (ADRESLER artık geçer), red yok. Yetkisiz tablo (örn. SIPARISLER içeren talep) → red + (can_view'daysa) **"SIPARISLER ..."** adıyla. Modal: uzun SQL'de "Kapat" görünür, SQL alanları iç scroll, modal ~880px/85vh sabit.
- **Build:** `node frontend/build.mjs` → `dist/bundle.min.{js,css}` timestamp kaynaklardan yeni; hard refresh.
- `Gecici_Dosyalar_Sil/_diag_*.py` 3 dosya: fix doğrulandıktan sonra silinir (KAP 9).

## 8. Out-of-scope
- VyraModal a11y derinleştirme (focus-trap/return-focus/role=dialog/aria-modal) → REFACTOR_BACKLOG (5c.2 WCAG).
- z-index ölçek refactor (RB-v3.41.5 #3) — ayrı.
- query_builder/query_state preview aynı whitelist genişletmesi gerekiyor mu? → audit follow-up.

## 9. Faz D — "Veritabanında Ara" (deep_think DB-Only) KAPSAMA ALINDI (kullanıcı talebi 2026-05-31)
Kullanıcı: G1 davranışı + tutarlılık "Veritabanında Ara" → "son konu ile ilgili sor" alanında da olsun;
ayrıca **yetkisi olan müşteriye soru sordu, "yetki yok" dedi** (bug #3, "dün düzeltmiştik").

**Kök neden (read-only ajan, kanıtlı):** `deep_think_service.py:2545-2563` — restricted kullanıcıda SQL
üretimi `success=False` olunca **her** başarısızlık "kapsam-dışı tablo" sayılıp `_scope_restricted_message`
("Yetki Notu: Yetkili tablolarınız: ...") gösteriliyordu. Eliptik follow-up'ta ("müşteri listesinde dahil et")
parse/DIAGNOSTIC/LLM hatası → kullanıcının YETKİLİ olduğu MUSTERILER yanlışça reddediliyordu.
NOT: "G2 pre-gen gate" YOK; bu flow zaten **tam can_execute scope** whitelist'i kullanıyor (check_table_whitelist
generated SQL'de) → kapsam-genişletme yapısal olarak MEVCUT. Defект yalnız failure→deny kısayoluydu.

| Gate | Konsey | Dosya | İş | Durum |
|---|---|---|---|---|
| **G6** Error-kind gating (bug #3 KÖK) | HERMES + ARES + APOLLO | `deep_think_service.py` | `_is_scope_denial_error(err)` helper; "Yetki Notu" YALNIZ gerçek scope reddinde ("erişim yetkisi yok" / "çalıştırma yetkiniz olan tablo bulunmuyor"). Diğer hatalar → "farklı şekilde sorun" (DIAGNOSTIC korunur). `scope_restricted` metadata flag gerçek kararı yansıtır. | ✅ done |
| **G7** Test | TYCHE | `tests/test_deep_think_service.py` | `TestIsScopeDenialError` 7 test (whitelist/no-exec-table→scope; parse/DIAGNOSTIC/infra/None→değil). | ✅ 45 passed |

**Kapsam-dışı (Faz D):** deep_think genuine-denial mesajında reddedilen tablo adını söyleme (wizard G2'deki
gibi) — kullanıcı deep_think için açıkça istemedi + paylaşılan parser refactor gerektirir (RB). Follow-up
context robustness (badge'siz eliptik follow-up auto-resolve) — ayrı davranış değişikliği, RB.

## 10. İLERLEME / VERIFICATION LOG
- ✅ G1+G2 (wizard) — db_smart_api.py: `_execute_scope_whitelist` (tam scope) + `_parse_denied_ref` + can_view-gated mesaj. Diff ZEUS-review temiz.
- ✅ G3+G2site1 (frontend) — modal `.dsw-sql-modal` wrapper + modal.css `:has()` 880px/85vh/min-height:0/sticky footer + pre 260px + `_serverDetailMessage` (403 detail, raw-leak guard).
- ✅ G6+G7 (deep_think) — error-kind gating + 7 test.
- ✅ Build: `node frontend/build.mjs` OK; dist bundle yeni; `dsw-sql-modal` bundle'da doğrulandı.
- ✅ Test: test_safe_sql_executor 44 pass; test_deep_think_service 45 pass.
- ✅ Regresyon: tests/db_smart 16 fail PRE-EXISTING (baseline 799cb70 ile birebir aynı — git stash ile ZEUS doğruladı; bizim değişikliğimiz DEĞİL).
- ⏳ Canlı smoke (kullanıcı): backend restart + hard refresh sonrası 3 senaryo.
- ⏳ Versiyon bump (3.41.5→3.41.6) + system_settings + commit — smoke onayından sonra.
