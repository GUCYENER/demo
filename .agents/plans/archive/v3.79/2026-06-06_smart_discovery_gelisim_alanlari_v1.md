---
plan_id: smart_discovery_gelisim_alanlari
created: 2026-06-06
branch: hira
status: assessment (not-yet-scoped)
mode: CEO-review (understand + identify improvement areas)
note: /plan-ceo-review — "Akıllı Keşif + DB ara süreçleri incele, nasıl çalıştığını anla, gelişim alanlarını belirle". 3 paralel Explore (discovery / enrichment+FK / query-path) + audit. Plan onayı DEĞİL; teşhis + öncelik kararı için.
---

# Akıllı Keşif + DB Öğrenme Boru Hattı — Nasıl Çalışıyor + Gelişim Alanları

## 1. Nasıl çalışıyor (uçtan uca)

```
 KAYNAK BAĞLA
     │
     ▼  (1) TEKNOLOJİ KEŞFİ  ── discover_technology()  ds_learning_service.py:172
     │     dialect/sürüm/şema listesi → ds_discovery_jobs(type=technology)
     ▼  (2) OBJE TESPİTİ     ── detect_objects()        ds_learning_service.py:279
     │     • bulk kolon yükle (dialect başı tek sorgu)
     │     • PK: declared > IDENTITY CASCADE (unique-index proxy, 4 dialect, pk_source) > inferred
     │     • native comment (pg_description / MS_Description / all_col_comments …)
     │     • declared FK (pg_constraint / sys.foreign_keys / all_constraints …) [non-blocking try/except]
     │     → ds_db_objects(columns_json, pk_source) + ds_db_relationships(is_inferred=FALSE)
     ▼  (3) VERİ TOPLAMA     ── collect_samples()       sample_data_loader.py:144
     │     "Örneklenecek Şemaları Seç" → şema filtre + PII maskeleme + char/satır bütçesi
     │     → ds_db_samples(sample_data JSONB)
     ▼  (4a) ENRICHMENT      ── enrich_table()          ds_enrichment_service.py
     │     LLM: iş-adı/semantic-type/synonyms/açıklama. chunk(40) + overflow + _fill_missing_columns
     │     (case-insensitive) + toptan-başarısızlık yüzeyleme (columns_enriched==0)
     │     → ds_table_enrichments + ds_column_enrichments (admin_approved gate)
     ▼  (4b) FK INFERENCE    ── infer_fks_for_source()   fk_inference_service.py:692  [opsiyonel]
     │     naming tier (exact>plural>entity-token>prefix-strip>head-noun>self-ref>fuzzy)
     │     + type-uyumu + sample-coverage probe → ds_db_relationships(is_inferred=TRUE, evidence_json,
     │     confidence_score, admin_verified=FALSE)
     │
     ▼  SORU → CEVAP (Akıllı Keşif sorgu)
        get_schema_context() → format_schema_for_llm()  text_to_sql.py:820/1060
        (öğrenilen artefaktları prompt'a basar: iş-adı/synonym, FK, PK, tarih; relevance-pruning + 150 cap)
        → SQL üret (LLM, temp 0.1) → _check_column_hallucination → validate_sql (SELECT-only)
        → SafeSQLExecutor.execute (RLS GUC + row-limit + sensitive-mask + timeout) → sonuç/rapor
```

**Ara-süreç artefaktları (PostgreSQL meta, hepsi `source_id`-RLS scoped):**
`ds_discovery_jobs` (iş durum-makinesi) · `ds_db_objects` (şema snapshot + pk_source) · `ds_db_relationships`
(declared+inferred FK, `inference_method`/`confidence_score`/`evidence_json`/`admin_verified`) · `ds_db_samples`
(PII-maskeli örnek) · `ds_table_enrichments` + `ds_column_enrichments` (LLM iş-adı/synonym/semantic-type + admin onay).

**İki-SQL modeli (db_smart wizard):**
- `baseSql` (assemble/render, `query_assembler.py` + `ast_renderer.inject_rls`) → `company_id` filtresi enjekte eder;
  **dış kaynakta (Oracle/MSSQL) `company_id` kolonu YOK** → assemble icrada kullanılamaz.
- `finalSql` (`llm_generate_report.py:516`) → WHERE/ORDER wizard'dan LLM prompt'una metin olarak girer (RLS enjeksiyonu
  yok), dış kaynakta çalışır. Anti-halüsinasyon: gerçek `columns_json` (≤500 kolon cap) prompt'a basılır.

## 2. CEO-lens teşhis — tek yapısal içgörü

Üç bağımsız Explore ajanı (keşif / enrichment+FK / sorgu-yolu) **aynı meta-boşlukta birleşti**: boru hattı
artefakt üretiyor (FK, enrichment) ve bu artefaktlar **cevap kalitesini KAPILIYOR**, ama:

- **Neyin yanlış olduğu görünmez.** Fuzzy FK sessiz eleniyor (diag dönüş-dict'te, kalıcı değil, admin erişemiyor).
  Enrichment kısmi-kaybı/​toptan-başarısızlık loglanıyor ama UI "hazır" gösteriyor. Sorgu fallback'i (LLM yok →
  `SELECT * LIMIT 100`) ve halüsinasyon sessiz. **"Cevap neden yanlış geldi?" sorusunun cevabı yok.**
- **Düzeltme yolu yok.** Inferred FK `admin_verified=FALSE` ile geliyor ama **bulk-onay/red UI yok** → doğrulanmayan
  FK RAG'de hiç kullanılmıyor (sessizce). Enrichment "score" hesaplanıyor ama **kullanılmıyor** (hepsi admin'e).
- **Yanlış proxy'yi optimize ediyoruz** (Bezos proxy-skepticism): metrik "kaç tablo öğrenildi / kaç FK çıkarıldı" —
  ama ürünün TEK değeri "kullanıcının DB sorusu DOĞRU cevaplandı mı". Upstream'in tamamı o tek anı için var.

**Kaldıraç noktası (Altman leverage):** boru hattını uçtan uca **gözlemlenebilir + düzeltilebilir** kılmak,
cevap-doğruluğuna çapalı. Mevcut tüm tier/constant/dual-path zaten çalışıyor; eksik olan **kapalı döngü**.

## 3. Gelişim alanları (öncelikli)

### TEMA 1 — Kapalı-döngü gözlemlenebilirlik & düzeltme  ⭐ EN YÜKSEK KALDIRAÇ
| # | Madde | Kanıt | Efor | Etki |
|---|---|---|---|---|
| 1.1 | **FK diagnostics kalıcı** (`ds_fk_diagnostics`): çözülemeyen FK kolonları + sebep (no_target/no_pk/fuzzy_low_cov) + trend + admin "elle FK kur" akışı | unresolved tek-atımlık dönüş-dict (fk_inference:752), tekrar koşunca aynı | M | yüksek |
| 1.2 | **Inferred-FK bulk verify/reject UI** (admin_verified gate VAR, UI YOK → doğrulanmayan FK RAG'de kullanılmıyor) | agent A+B: "rejected FKs not surfaced", confidence≥0.70 OR admin_verified | M | yüksek |
| 1.3 | **Query audit lineage** (`query_audits`: schema_fetch→llm→validate→hallucination→rls→execute, status/details) + fallback-sebebi & halüsinasyonu KULLANICIYA göster (şu an sadece log) | agent C: "silent fallback", "hallucination logged not shown" | M | yüksek |
| 1.4 | **Kısmi-kayıp UI sinyali**: enrichment `columns_enriched==0` + FK-eksik + "Yeniden Öğren" rozeti | v3.75.0 surfacing log var, UI "hazır" gösteriyor | S | orta-yüksek |

### TEMA 2 — Cevap doğruluğu (ürünün çekirdek değeri)
| # | Madde | Efor | Etki |
|---|---|---|---|
| 2.1 | **Deterministik join-path skorlama**: cardinality/selectivity ile top-N FK sırala, LLM'i düşük-güven/cross-tenant path'ten uzak tut (`join_planner` + `fk_graph`) | M | yüksek |
| 2.2 | **Domain synonymy/co-selection grafiği** onaylı sorgu geçmişinden → kolon-grounding (relevance-pruning'i besler) | M | orta-yüksek |
| 2.3 | **Belirsiz-soru clarify akışı**: N aday SQL döndür, kullanıcı seçsin ("top 10 müşteri" = ciroya mı adede mi?) | M | orta |
| 2.4 | ~~Case-normalization köprüsü~~ **✅ İNCELENDİ-HANDLED (2026-06-07)**: ZATEN savunuluyor — (1) prompt quote-kuralı `text_to_sql:92` (ŞEMA/TABLO/SÜTUN DAİMA çift-tırnak exact-case, örn `"elysion"."T_ORG_USER"`), (2) self-heal case-retry `text_to_sql:671` ("büyük/küçük harf farkı olabilir"), (3) keşif `object_name`'i information_schema'dan exact-case saklıyor (kaydırmıyor), (4) `quote_identifier(name,dialect)` helper var. Canlı doğrulama: ONEDESKPG mixed-case identifier VAR (elysion: T_AD_ACCOUNTTYPE/RootCaseSetCode) + canlı meta-DB kanıt: VYRA object_name'i 2661/2672 (%99.6) mixed-case KORUMUŞ (kaydırma YOK → "case-shift" premise'i çürük) AMA `errors.jsonl`'de "does not exist" YOK → savunma çalışıyor. **İş gerekmiyor** (deterministik rewriter = regex-on-SQL B1-riski, non-bug için değmez). | S | orta |

### TEMA 3 — Keşif sağlamlığı & ölçek
| # | Madde | Kanıt | Efor | Etki |
|---|---|---|---|---|
| 3.1 | **İş durumu kalıcılık + resumability**: daemon-thread çökünce 30-dk reaper'a kadar "running"; multi-worker görünürlük; aşamalı ilerleme (X/N tablo) | agent A: "Başlatıldı ama bitmedi" | M | orta-yüksek |
| 3.2 | **Idempotent re-discover / FK-merge**: tekrar-keşif sample/FK üzerine yazıyor (merge yok) → kaza ile veri kaybı | agent A | M | orta |
| 3.3 | **Büyük-DB streaming + statement_timeout** keşifte (10k tablo OOM; "45-dk asılı kaldı") | agent A | M | orta |
| 3.4 | **Enrichment fan-out bütçesi**: 2000-kolon → ~50 çağrı; `_fill_missing_columns` 2-pass kuyruğu kaçırır → heuristic fallback ("—" yerine) | agent B | S-M | orta |

### TEMA 4 — Maliyet / gecikme / bakım (DRY + verim)
| # | Madde | Kanıt | Efor | Etki |
|---|---|---|---|---|
| 4.1 | **Cached schema delta**: her soruda 30-tablo şema tekrar gidiyor → hash+delta ile ~%40 token | agent C | S | orta (maliyet) |
| 4.2 | **Dialect SQL dedup** (`build_sample_validate_sql` 4×) | RB-v3.76.1 #9 | S | düşük (bakım) |
| 4.3 | **Per-source FK konvansiyon/alias kaydı** (Hungarian prefix global → çok-vendor gürültü) | RB-v3.42.0/75.0 | M | orta |
| 4.4 | **FuzzyPolicy config** (magic number + min_confidence gizli kuplaj tek yerde) | RB-v3.76.0 | S | düşük |
| 4.5 | **Büyük result-set streaming** (>100k satır OOM; SSE altyapısı mevcut) | agent C | M | orta |

## KARAR (2026-06-06)
Kullanıcı **TEMA 1** seçti (kapalı-döngü gözlemlenebilirlik). İlk dilim: **1.1 + 1.2** (FK-diagnostics kalıcı +
inferred-FK bulk verify/reject UI) — `admin_verified` gate zaten var, sadece görünürlük+UI eksik = en hızlı kaldıraç.
Sonra 1.3 (query-audit lineage, ayrı/büyük), 1.4 (kısmi-kayıp rozeti, küçük). Her dilim /plan-eng-review + council
ile scope'lanacak; ŞU AN implementasyon yok (CEO-review = teşhis).

## GERÇEKLİK KONTROLÜ (implementasyon sırasında, 2026-06-06 — varsayım yok, koda bakıldı)
CEO-review teşhisi 3 Explore ajanından sentezlendi; implementasyonda ajanların **boşlukları abarttığı** çıktı
(mevcut observability katmanını görmemişler). Gerçek durum:
- **Dilim 1 (1.1 diagnostics) = GERÇEK boşluk** → yapıldı (v3.77.0, `dc58725`). 1.2 verify/reject BACKEND zaten
  vardı (sadece UI'ye bağlandı + diagnostics görünümü eklendi).
- **Dilim 2 (1.3 query-audit) = BÜYÜK ORANDA MEVCUT.** `learned_query_failures` (error_class/signature/failed_sql/
  recurrence) + `/observability/failures-top` + `pipeline_traces` + `agentic_query_decisions` + `agentic_query_feedback`
  + `ds_synthetic_query_runs` + `learning_recorder`. Yeni `query_audits` tablosu = DUPLİKASYON → YAPILMADI.
  Kalan dar boşluk (varsa): (a) failure lineage'in **son-kullanıcıya** ("senin sorun şu yüzden cevaplanamadı")
  yüzeylenmesi, (b) db_smart wizard yolunun (agentic değil) outcome kaydı. İkisi de KÖR yapılmadan ÖNCE
  hedefli doğrulama ister.
- **Dilim 3 (1.4 kısmi-kayıp rozeti)** = enrichment `columns_enriched==0` zaten log_system_event'e yazıyor
  (v3.75.0); UI rozeti var mı doğrulanmalı (muhtemelen küçük gerçek boşluk).

**Sonuç:** Tema-1'in EN YÜKSEK KALDIRAÇLI ve TEK gerçek-eksik parçası (FK kapalı-döngü) tamamlandı. 2/3
büyük oranda mevcut → duplikasyon yerine, dar residual boşluk hedefli doğrulanıp gerekiyorsa eklenmeli
(ayrı odaklı oturum/PR). Bu, "varsayım yapma, çalışanı yeniden yazma" ilkesinin sonucu.

## 4. Öneri
**TEMA 1'den başla** (kapalı-döngü gözlemlenebilirlik). Sebep: Tema 2 (doğruluk) ve Tema 3 (sağlamlık) iyileştirmelerinin
ETKİSİNİ ölçemiyorsun — "FK'yı düzelttim, cevap düzeldi mi?" sorusunun aracı yok. Tema 1 o aracı kurar (diagnostics +
audit + admin düzeltme), sonra Tema 2/3 veriye-dayalı önceliklenir. 1.1+1.2 (FK diagnostics + bulk-verify UI) en yüksek
kaldıraç: hâlihazırda `admin_verified` gate'i var, sadece görünürlük+UI eksik.

## 5. Not (kapsam/risk)
- Bu bir TEŞHİS; her madde ayrı /plan-eng-review + council onayı ile scope'lanmalı (yeni tablo/migration → ARES+METIS).
- RB backlog'daki maddeler (v3.42/75/76) bu temalarla örtüşüyor — yeni iş açmadan önce onlarla birleştir.
- Eski silinmiş audit (R021, 2026-05-24, ~40 P2/P3 finding) bu teşhisin alt-kümesi; fresh teşhis (bu doc) onu güncelliyor.
