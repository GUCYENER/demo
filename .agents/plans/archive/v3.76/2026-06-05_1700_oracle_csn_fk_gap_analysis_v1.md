---
plan_id: oracle_csn_fk_gap_analysis
created: 2026-06-05
branch: hira
status: completed
version_target: v3.76.0
note: G4a (fuzzy+sample-validation) v3.76.0'da implemente edildi (opt-in, default OFF) + code-review 5 fix. G4b (per-source alias) + G4c (composite-PK) CSN teşhis SQL sonucu beklenerek ertelendi.
council_mod: 3
hebe_gate_required: false
---

# Oracle CSN Gerçek-Yapı FK Gap Analizi + Kalıcı Çözüm

## 1. Context
Kullanıcı canlı Oracle kaynağının (owner **CSN**, 383 tablo) gerçek yapısını teşhis SQL sonuçlarıyla verdi.
Soru: "kullanıcılar bu DB'ler için soru soracak" → FK ilişkileri JOIN için doğru çıkarılmalı. PG ONEDESKPG'de
"hiç gelmeyen FK" sorununu çözmüştük (declared FK düşmüş → inference); Oracle CSN için aynı değerlendirme.

## 2. Verilen SQL sonuçlarının değerlendirmesi (6 bölüm)

| # | Bulgu | Kod-etkisi |
|---|---|---|
| 0 | Owner **CSN** = 383 tablo (TCHGESOGLU 697 ama hedef CSN) | Doğru şema seçilmeli (discovery `owner='CSN'`) |
| 1 | "PK 38 / FK 5 / uidx 67" — ama bölüm-4 FK detayı **BOŞ** | ⚠️ **Çelişki**: sec-1 owner-scoped değil veya PG karşılaştırma sayısı. Net owner-scoped sorguyla teyit (aşağıda) |
| 2 | Identifier'lar **UPPER** (ACS_OFFERS, PRODUCT_ID, NUMBER) | ✅ OracleDialect.normalize_ident=UPPER — tutarlı eşleşme |
| 3 | Declared PK **TUTULUYOR** + **COMPOSITE** (SDP_ACCOUNT_ADJUSTMENT_PK: UNIQUEKEY+ACCOUNTNUMBER+ADJUSTMENTTIMESTAMP) | ✅ keşif `all_constraints type='P'`+`all_cons_columns` → composite'te TÜM kolon is_pk. ⚠️ FK hedefi composite'te pk_columns[0] seçer (imprecision) |
| 4 | FK constraint listesi **BOŞ** (declared FK yok, PG'deki gibi) | ✅ inference gerekli — mekanizma var |
| 5 | ACS_OFFERS kolonları: ID(PK) + PRODUCT_ID, SERVICE_CLASS_ID, PROVIDER_ID, PAM_SERVICE_ID (NUMBER, FK-aday) + MSISDN/tarihler | ✅ `*_ID` NUMBER → inference adayı |

## 3. Kanıt: gerçek koşturma (varsayım yok) — `Gecici_Dosyalar_Sil/verify_oracle_csn.py`

CSN ACS_OFFERS gerçek kolonlarıyla Oracle-dialect FK inference koşturuldu:

- **Hedef tablolar VAR ise: 4/4 ÇÖZÜLDÜ** —
  `PRODUCT_ID→PRODUCT.ID`, `SERVICE_CLASS_ID→SERVICE_CLASS.ID` (bileşik snake ad ✓),
  `PROVIDER_ID→PROVIDER.ID`, `PAM_SERVICE_ID→SERVICE.ID` (prefix-strip head-noun ✓).
- **Hedef tablo YOK ise: 4/4 `no_target_table`** ← **"hiç gelmeyen FK"nin tam mekanizması**.
- **Composite PK hedef:** `ACCOUNT_ADJUSTMENT_ID→SDP_ACCOUNT_ADJUSTMENT.UNIQUEKEY` (pk_columns[0]).

**Verdict:** v3.75.0 + mevcut kod Oracle CSN yapısını **doğru ele alıyor**. FK çözümü TEK koşula bağlı:
**hedef tablo adının kolon-köküyle eşleşmesi**. Eşleşme tier'ları: exact > plural > entity-token (son _-segment)
> prefix-strip (Hungarian/modül) > head-noun. CSN tabloları bu kalıplara uyuyorsa FK gelir; **arbitrary/kısaltma
adlandırma** (PRD, M_PRODUCT_DEF, SC) gelmez.

## 4. GERÇEK GAP'i ortaya çıkaran teşhis (kullanıcı canlıda koşacak)

**Adım 1 — Hızlı SQL ön-teşhis (çözülmeyen FK-aday kolonlar):**
```sql
-- ORACLE CSN — hangi *_ID kolonları hedef tabloya çözülür/çözülmez?
WITH fk_cands AS (
  SELECT c.table_name, c.column_name,
         LOWER(REGEXP_REPLACE(c.column_name, '_?ID$', '', 1, 1, 'i')) AS root
  FROM all_tab_columns c
  WHERE c.owner = 'CSN'
    AND (c.data_type LIKE 'NUMBER%' OR c.data_type IN ('INTEGER','INT'))
    AND REGEXP_LIKE(c.column_name, '_?ID$', 'i')
    AND UPPER(c.column_name) <> 'ID'
),
tbls AS (
  SELECT LOWER(table_name) AS tname,
         LOWER(REGEXP_SUBSTR(table_name, '[^_]+$')) AS ent
  FROM all_tables WHERE owner = 'CSN'
)
SELECT
  CASE WHEN EXISTS (
     SELECT 1 FROM tbls b
      WHERE b.tname = f.root OR b.tname = f.root||'s'
         OR b.ent   = f.root OR b.ent   = f.root||'s'
  ) THEN 'RESOLVES' ELSE 'NO_TARGET' END AS durum,
  f.table_name, f.column_name, f.root
FROM fk_cands f
ORDER BY durum, f.table_name, f.column_name;
```
> Bu SQL bizim tier'ların ALT-kümesi (prefix/head-noun hariç) → **NO_TARGET = gap üst-sınırı**.
> Asıl tier'lar bir kısmını daha çözer. NO_TARGET listesi gerçek kök-neden kaynağıdır.

**Özet sayım:**
```sql
WITH fk_cands AS ( ... yukarıdaki ... ), tbls AS ( ... )
SELECT durum, COUNT(*) FROM (
  SELECT CASE WHEN EXISTS (SELECT 1 FROM tbls b WHERE b.tname=f.root OR b.tname=f.root||'s'
         OR b.ent=f.root OR b.ent=f.root||'s') THEN 'RESOLVES' ELSE 'NO_TARGET' END AS durum
  FROM fk_cands f
) GROUP BY durum;
```

**Adım 2 — GROUND TRUTH (en doğru):** CSN'i VYRA'da kaynak ekle → **Keşfet** → FK inference koşar →
**Hata İzleme**'de `[FK Inference] CSN.<tablo>: ... no_target_table` uyarılarını paylaş (ONEDESKPG log3.txt gibi).
Tüm tier'lar uygulanmış gerçek çözülemeyen listesi budur.

## 5. Kalıcı çözüm (G4 yeniden tanımı — CSN gerçeğine göre)

> Planlanan G4 "by-code tier (CompanyCode→Company)" CSN'in ihtiyacı **DEĞİL** (CSN kolonları `*_ID`/NUMBER).
> Gerçek ihtiyaç: `*_ID` köklerinin **arbitrary hedef tablo adlarıyla** sağlam eşleşmesi. Hardcoded abbreviation
> map kırılgan/müşteri-özel (anti-pattern). Kalıcı/genel çözüm:

- **G4a — Sample-validation-gated fuzzy hedef eşleşme:** isim-tier'ları boş dönünce, PK-tipi uyumlu + adı kökü
  İÇEREN/token-paylaşan aday tablolar bulunur, **`_validate_sample` ile doğrulanır** (FK değerleri aday PK'da
  GERÇEKTEN var mı?). Yüksek-kapsama + false-positive'i sample engeller. Genel (her müşteri/dialect). Mevcut
  `_validate_sample` altyapısı kullanılır.
- **G4b — Per-source entity-alias haritası (config/DB-driven):** otomatik eşleşmeyenler için admin
  `PAM_SERVICE→SERVICE` gibi alias tanımlar (RB-v3.75.0 madde-2 ile birleşir). Hardcoded değil.
- **G4c (düşük öncelik) — Composite-PK FK hedefi:** tek-kolon FK composite PK'ya pk_columns[0] yerine
  tip-uyumlu/aynı-adlı kolonu tercih etsin (UNIQUEKEY yerine mantıklı surrogate).

**Sıra:** Adım-1/2 teşhis sonucu gelsin → NO_TARGET deseni görülsün → G4a (genel) + gerekirse G4b. Teşhissiz
G4 = varsayım.

## 6. Out-of-scope / Risk
- Sec-1 vs sec-4 FK sayısı çelişkisi → owner-scoped sorguyla teyit (kod-etkisi yok, sadece netlik).
- G4a fuzzy eşleşme false-positive riski → sample-validation ZORUNLU (admin_verified=FALSE kalır).
- Composite-PK çoklu-kolon FK (gerçek bileşik FK) → nadir, ayrı faz.
