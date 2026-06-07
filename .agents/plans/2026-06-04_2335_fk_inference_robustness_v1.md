---
plan_id: fk_inference_robustness
created: 2026-06-04
branch: hira
status: in_progress
version_target: v3.73.0
council_mod: 3
hebe_gate_required: true
---

# FK Keşfi — Her DB Türünde Sağlam Çıkarım + Arama İkon Hizası

## 1. Context (Neden bu değişiklik?)

Kullanıcı bulgusu (canlı, hem Oracle hem PostgreSQL kaynak): "Parametreler → Kaynaklar"
DB keşfinde **FK ilişkileri bulunamıyor** ("FK ilişkisi bulunamadı"). Kanıt: kullanıcı
`Gecici_Dosyalar_Sil/vyra-data.csv` (canlı sistem logları) + 5 ekran görüntüsü
(`bulgular6.docx` dahil).

**Kök neden (log + kod kanıtı):** Bu kaynaklarda declared FK constraint yok (taşınmış
telekom/BSCS sistemi — migrate edilmiş DB'lerde tipik). VYRA isim-tabanlı FK çıkarımına
düşüyor (`fk_inference_service.py`). Çıkarım iki açık yüzünden gerçek-dünya şemasını
çözemiyor:

1. **`no_target_table`** — Kolon kökündeki Hungarian tip-öneki (`N`=numeric, `V`=varchar)
   soyulmuyor: `NCUSTOMER_ID` → kök `ncustomer` aranıyor, gerçek tablo `CUSTOMER`.
   (Mevcut `by_last_token` v3.56.0 fix'i tablo-öneklerini `T_ORG_PARTY`→`party` çözüyor
   ama kolon-kökündeki öneki çözmüyor.)
2. **`target_pk_not_found`** — Hedef tablo eşleşse bile PK metadata boşsa motor PK'yı
   literal `"id"` varsayıyor (`fk_inference_service.py:486`). Gerçek PK `PartyId`/
   `NCUSTOMER_ID` → fail. Oracle PK sorgusu yetki hatası verirse (satır 931) `is_pk` hep
   boş → tüm hedefler bu tuzağa düşüyor.

**Mimari gerçek (de-risk):** Inferred FK'lar `admin_verified=FALSE` ile yazılır — bunlar
admin onayı bekleyen ÖNERİLERDİR, otomatik uygulanan gerçek değil. Dolayısıyla **recall >
precision**: gerçek bir FK'yı kaçırmak (false negative) fazladan aday önermekten (false
positive) daha kötü. Güvenlik ağı: (a) tip-uyumu, (b) opsiyonel sample-validation (gerçek
veride LEFT JOIN coverage), (c) admin onayı. → Eşleştirmede makul agresif olabiliriz.

**İkincil (kullanıcı talebi):** Görsellerde arama + arama-temizle (X) ikonlarının
authorization (Yetkilendirme) modalindeki `.ds-scope-search` kutusunda sola kayması.

## 2. Mevcut Durum (Explore bulguları)

- `app/services/db_learning/fk_inference_service.py` (711 satır) — dialect-agnostik çekirdek.
  - `_extract_root` (128) — snake/camel/Hungarian `f_x_id` kalıpları, Unicode (TR).
  - `_head_noun_from_name` (87) — rol-önekli FK (CreateUserId→user).
  - `_candidates_from_root` (165) — tekil/çoğul üretimi.
  - `_iter_fk_candidates` (393) — `by_norm_name` (exact) + `by_last_token` (v3.56.0
    prefix-tolerant) indeksleri; PK çözümü (484-488) `pk_columns[0]` ya da fallback `"id"`.
  - `_score` (504) — naming(0.6/head 0.45) + type(0.2) + sample(0.2). method CHECK-valid
    (v3.65.0: `ck_dsdrel_inference_method`).
  - persist (636-698) — v3.64.0 SAVEPOINT-izole INSERT (cascade-abort yok).
- `app/services/ds_learning_service.py` — keşifte PK yakalama (PG 335/412, MSSQL 586/660,
  MySQL 768, Oracle 922/977). Oracle PK sorgusu yetki hatasında `is_pk` boş kalır (931-932).
- `tests/test_fk_inference_service.py` — 34 test (extract_root, candidates, score,
  head_noun, prefixed-tables, self-fk). Genişletilecek, tekrar edilmeyecek.
- UI: `frontend/assets/js/modules/data_sources_module.js:1111-1120` authorization
  scope-search markup (`.ds-scope-search > i` magnifier + `.ds-search-clear` X).
  CSS: `data_sources.css:788` `.ds-search-clear { right:8px }` (left reset YOK);
  `ds_learning.css:1478` yalnız `.ds-schema-search` context'ine `left:auto` veriyor →
  authorization `.ds-scope-search` context'i korumasız.

## 3. Faz/Gate Haritası

| Gate | İş | Konsey | Dosya |
|---|---|---|---|
| G1 | E1: Kolon-kökü prefix-toleranslı hedef eşleşme (endswith/last-token) | ORACLE + HERMES + APOLLO | fk_inference_service.py |
| G2 | E2: Esnek PK çözümü (FK-col-adı / last-token+id / konvansiyon) | ORACLE + HEPHAESTUS | fk_inference_service.py |
| G3 | E3: Oracle PK-capture sağlamlaştırma (E2 zaten telafi; defansif log) | HEPHAESTUS + POSEIDON | ds_learning_service.py |
| G4 | E5: Golden-set testler (gerçek vakalar, 4 dialect) | TYCHE | tests/test_fk_inference_service.py |
| G5 | E6: `.ds-search-clear` bulletproof sağ-hiza (base `left:auto`) | HEBE + ATHENA | data_sources.css + bundle |
| G6 | Post-impl review + BİTİR kapıları + versiyon/commit | HERMES/ARES/TYCHE/HERA | — |

## 4. Critical Files to Modify / Create

- `app/services/db_learning/fk_inference_service.py` (E1, E2) — MODIFY
- `app/services/ds_learning_service.py` (E3, defansif) — MODIFY (minor)
- `tests/test_fk_inference_service.py` (E5) — MODIFY (additive)
- `frontend/assets/css/modules/data_sources.css` (E6) — MODIFY
- `frontend/dist/bundle.min.css` (rebuild) — REGEN

## 5. Yeniden Kullanılacak Mevcut Fonksiyonlar (kod tekrarı önle)

- `_extract_root`, `_head_noun_from_name`, `_candidates_from_root` — KORU, üzerine ekle.
- `by_last_token` indeksi (393) — E1 endswith eşleşmesi bu indeksi/tablo listesini kullanır.
- `_type_compatible`, `_validate_sample` — değişmez; E1/E2 adayları bunlardan geçer.
- `is_safe_identifier` — yeni PK/tablo adlarında da uygulanır (SQL injection guard).
- Persist SAVEPOINT bloğu (640) — değişmez.

## 6. Risk Özeti

| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| E1 prefix-strip false-positive FK | Orta | Düşük (admin_verified=FALSE öneri) | min token len ≥4 + len oranı; tip-uyumu; sample-validate; düşük confidence tier |
| E2 yanlış PK kolonu seçimi | Düşük | Orta (yanlış join hedefi) | aday sırası deterministik; seçilen kolon target'ta VAR olmalı + tip-uyumlu |
| Mevcut 34 testte regresyon | Düşük | Yüksek | testleri önce koştur (baseline), değişiklik sonrası tekrar; davranış-parity |
| E6 başka context'i bozar (perm/schema search) | Düşük | Düşük | `left:auto` sağ-hizayı korur, magnifier ayrı selektör (`> i`) |
| Canlı sunucu stale (v3.65.0 deploy bekliyor) | Kesin | — | Kod fix'i deploy gerektirir; kullanıcıya net bildir (ayrı süreç) |

## 7. Verification (uçtan uca)

- `./python/Scripts/python.exe -m pytest tests/test_fk_inference_service.py tests/test_fk_inference_dialects.py tests/test_fk_loop_improvements.py -q` → tümü yeşil (mevcut 34 + yeni).
- Golden-set yeni testler EXPLICIT şu gerçek vakaları doğrular:
  - `T_ORG_USER.PartyId → T_ORG_PARTY.PartyId` (camel + T_ORG_ + FK-col==PK-col) ✅
  - `CUR.RR_93.NCUSTOMER_ID → CUSTOMER.<pk>` (Hungarian N-prefix) PG + Oracle ✅
  - Cross-schema hedef ✅
  - Boş pk_columns → konvansiyon PK fallback çözer ✅
  - Kısa-token false-positive YOK (`node_id` ↛ `de`) ✅
- `python -c "import py_compile..."` tüm değişen .py derlenir.
- `node frontend/build.mjs` exit 0; `dist/bundle.min.css` timestamp yeni.
- (Opsiyonel) Lokal servis ayakta → authorization modal render + screenshot ile ikon sağda.

## 8. Out-of-scope (sonraki faz)

- LLM-assisted FK eşleştirme (E1/E2 deterministik yeterli; pahalı yol ertelendi).
- Smart Discovery GROUP BY-all-columns kalite sorunu (image4'te görüldü, ayrı konu).
- `golden_sql` company_id not-null CheckViolation (satır 528139) — ayrı persist yolu,
  FK kapsamı dışı; REFACTOR_BACKLOG'a not düşülecek.
- Canlı sunucuya deploy (kullanıcının "canlıya taşıma" süreci).

## İlerleme Kaydı
- [x] G1 E1 — kolon-kökü prefix-soyma eşleşme (by_entity_token + deterministik strip)
- [x] G2 E2 — esnek PK çözümü (declared→FK-col-adı→entity-token→konvansiyon)
- [x] G3 E3 — Oracle PK: E2 ile karşılandı, keşif-tarafı kod değişikliği YOK (gereksiz risk; mevcut error-log korunur)
- [x] G4 E5 — +7 golden-set test (41 service test, tümü yeşil; 80 FK-suite)
- [x] G5 E6 — base `.ds-search-clear{left:auto}` evrensel sağ-hiza + scoped temizlik + bundle rebuild
- [ ] G6 — post-impl review ✅ (ruff 0, ARES temiz, 72 test) → commit (kullanıcı onayı bekliyor)

**Sonuç (v3.73.0):** Kod tarafı tamam, test yeşil. Commit 043bcc0 + push. Canlıya deploy edildi.

---

## v3.74.0 — Identity Cascade (deploy-sonrası KÖK NEDEN + uzman mimarisi)

**Deploy sonrası kullanıcı testi:** Hâlâ FK üretilemedi. Canlı log (`log.txt`) yeni kodu (E1/E2)
doğruladı ama her tabloda `target_pk_not_found` → hedef tablo bulunuyor (CreateUserId→T_ORG_USER ✅)
ama PK kolonu metadata'da yok. Self-PK'lar (ADGroupQueryId) da FK sanılıyor. **Tek kök: is_pk boş.**

**Kullanıcı DB-sorgu önerisi (doğru içgüdü) + canlı sonuç (tahmin değil, kanıt):**
- `pg_constraint`: PK constraint **70**, FK constraint **0**, UNIQUE INDEX **208**
- 3 tablonun declared PK'sı YOK ama `PK_T_ORG_USER → PartyId`, `PK_T_ORG_PARTY → PartyId`,
  `PK_T_ORG_PARTYPARTYRELATION → PartyPartyRelationId` **unique-index olarak duruyor**.
- KÖK: DB **MSSQL→PG migre** (index adları PK_*/NonClustered/UNQ_*). Constraint'ler düşmüş,
  PK bilgisi unique-index'te. Keşif yalnız `constraint_type='PRIMARY KEY'` sorguluyordu → 208 index ıskalanıyor.

**İdeal mimari (konsey onaylı): Şema Zekâsı Cascade.**
- **A) PK/Identity:** L1 declared PK → L2 unique index (tek-kolon, PK_*/`*id` tercihli) → L3 isim-sezgisi (E2'de).
- **B) FK/İlişki:** L1 declared FK → L2 isim-çıkarımı (E1/E2) → L3 veri-profili (`_validate_sample`).
- **Çapraz:** her kayıt provenance taşır (`declared|unique_index|inferred_name`); `admin_verified=FALSE` öneriler.

**Uygulanan (G7):**
- `ds_learning_service.py`: 4 dialect L2 unique-index → is_pk fallback (PG `pg_index`, Oracle `all_indexes`,
  MSSQL `sys.indexes`, MySQL `COLUMN_KEY=UNI`), her biri **try/except izole** (regresyon yok), `pk_source` tag.
- `fk_inference_service.py`: evidence_json'a `to_pk_source` provenance (UI rozeti için).
- Test: +1 provenance test (73 FK-suite yeşil). PG sorgusu kullanıcı Q4'ü ile birebir doğrulandı.

**Sonraki faz (UI rozetleri — kullanıcı onaylı sıra):** `fk_inference_observability.js` provenance rozeti
(🔒declared/🟢unique-index/🟡çıkarım) + confidence renk + join picker "çıkarım" işareti.

## Code Review (high, 3 paralel finder + triyaj) — v3.74.0

**Düzeltilen (net bug/correctness):**
- 🔴 **MSSQL `%` kaçışı** — pymssql pyformat paramstyle; `LIKE 'PK%'` → `%i`/`%'` execute hatası →
  MSSQL fallback HİÇ çalışmıyordu. Fix: `%%`. (driver doğrulandı: pymssql)
- 🟢 **NOT NULL guard** (PG `attnotnull` / Oracle `nullable='N'` / MSSQL `is_nullable=0` / MySQL `NULLABLE<>'YES'`)
  — nullable proxy-PK INNER JOIN'de satır düşürür (downstream join_planner riski). Artık NOT NULL şart.
- 🟢 **Oracle `hidden_column='N'`** — function-based/DESC index'in SYS_NC$ virtual kolonu hariç (yanlış identity).
- 🟢 **MSSQL `has_filter=0`** — filtered (WHERE'li) unique index hariç (kısmi uniqueness, PK değil).
- 🟢 **MySQL: COLUMN_KEY='UNI' → STATISTICS bulk** — UNI tek-kolon garantisi vermez (composite ilk-kolon),
  ordinal seçim Email/Code'u PK sanardı. Gerçek tek-kolon + Python-rank (PRIMARY/'PK%' > '*id') + NOT NULL.
- 🟡 **`to_pk_source` provenance** — konvansiyonla çözülen hedef yanlış "declared" rozeti alıyordu →
  `unique_index | declared | inferred` ayrımı (UI rozeti doğru).

**Ertelenen (riskli/by-design — ayrı follow-up):**
- ⚠️ **G9 — PK-hem-FK (table-per-type):** `T_ORG_USER.PartyId` artık is_pk (unique-index) → FK inference
  onu source olarak atlıyor → `PartyId→T_ORG_PARTY` inheritance FK'sı çıkarılmıyor. Audit FK'lar
  (CreateUserId/UpdateUserId → ana değer) ÇALIŞIR. Self-PK vs cross-table-PK ayrımı çekirdek inference'ı
  değiştirir (self-FK gürültü riski) → ayrı, testli PR. **Bulkun %95'i etkilenmez.**
- 📋 incremental_schema_integrator unique-index uygulamıyor (provenance tutarsızlığı) → REFACTOR_BACKLOG.
- 📋 prefix-strip her candidate'a uygulanıyor (recall>precision by-design, admin onayı gate) → izlenir.

## İlerleme Kaydı (v3.74.0)
- [x] G7 — 4-dialect unique-index → is_pk cascade + provenance + test
- [x] G7b — code-review (high) düzeltmeleri: MSSQL %%, NOT NULL, Oracle hidden_column, MySQL STATISTICS, provenance
- [ ] G8 — UI provenance rozetleri (sonraki faz) → bekleyen, bkz. 2026-06-07_hata_izleme_info_ve_bekleyen_backlog
- [x] G9 — PK-hem-FK table-per-type → **v3.77.4 `extension` tier** ile YAPILDI (2026-06-07). `PartyId→T_ORG_PARTY` / `WFINSTANCEID→T_WF_INSTANCE` çıkarılıyor; self-PK vs cross-table-PK ayrımı `_pk_targets_own_table` + tek-kolon-PK guard + `_is_target_pk`; test edildi (`test_pk_extension_edge` case A). Code-review (4 finder + 2 adversarial geçiş).
- [ ] Deploy: `ds_learning_service.py` + `config.py` → backend restart → **kaynağı YENİDEN KEŞFET** → FK çıkarımı
