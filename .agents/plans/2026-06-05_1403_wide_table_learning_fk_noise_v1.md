---
plan_id: wide_table_learning_fk_noise
created: 2026-06-05
branch: hira
status: completed
version_target: v3.75.0
council_mod: 3
hebe_gate_required: true
---

# Geniş-Tablo Tam Öğrenme + FK Inference Gürültü Temizliği

## 1. Context (Neden bu değişiklik?)

Kullanıcı bulgusu (ONEDESKPG kaynağı — MSSQL→PG migre, declared PK/FK düşmüş; ref: `reference_canli_kaynak_onedeskpg.md`):

1. **FK uyarı seli** — `log3.txt` ve "ML Öğrenme Sonuçları" panelinde yüzlerce FK üretilemedi uyarısı. Dağılım: **242 `no_target_table` + 154 `no_pattern_match`**. Tek başına **`GCRecId` 93 uyarı** (~%38), `ParentId` 5, `AppId` 3, gerisi değer-kolonu (`Code`/`Key`/`No`).
2. **Geniş tablo enrich olmuyor** — `elysion_soxdata_ict.T_ICT_DYNAMIC_DATA` (~312 kolon): "312 LLM BEKLEYEN", hepsi `İş Adı: —`, `semantic: other`, skor 0.55. Etiketleme çalışmamış.
3. **Kullanıcı direktifi (KESİN):** *"max 50 olmamalı, tablo kolonu ne kadar varsa öğrenmeli."* → kolon kapakları kalkacak, tablo kaç kolonluysa hepsi öğrenilecek.

## 2. Mevcut Durum (kaynak-doğrulanmış bulgular)

### A. FK Inference (`app/services/db_learning/fk_inference_service.py` — 769 satır)
- `_iter_fk_candidates` (satır 396) her non-PK kolonda root/head çıkarır, tabloyu eşler; eşleşmezse `diag`'a yazar → çağıran `unresolved` olarak **WARNING** loglar (satır 500-507).
- `GCRecId` → `_CAMEL_ID_RE` (satır 81) → root `gcrec`, head `rec` → denenen `[gcrec,gcrecs,rec,recs]` → hiç tablo yok. **Her tabloda var → gerçek FK DEĞİL, framework satır-kimliği** (MS Dynamics `RecId` sınıfı). 93 uyarının kaynağı.
- `_REF_ISH_SUFFIXES = ("id","ref","code","key","no","fk")` (satır 121) → `Code`/`ApiKey`/`MethodNo` "referans-benzeri" sayılıp `no_pattern_match` uyarısı üretir (154×). Bunlar çoğunlukla **değer kolonu**, FK değil → gürültü.
- `ParentId` → root/head `parent`, denenen `[parent,parents]` → tablo yok. Ama bu **klasik self-reference** (parent_id → kendi tablosunun PK'sı); kod self-FK'yı sadece hedef tablo bulununca destekliyor (satır 494, 509).

### B. Discovery (`app/services/ds_learning_service.py`)
- Kolon introspection **toplu** sorgu (information_schema.columns / all_tab_columns), `columns_json` JSONB'ye yazılır — **kolon sayısı kapağı YOK** (312 kolon tam keşfedilir; image 2 hepsini gösteriyor).
- **Örnekleme kapağı (satır 1646-1648): 50 kolon** — geniş tabloda yalnız 50 kolona örnek-veri toplanır → 51+ kolon enrichment'a örneksiz gider (kalite düşer).
- Toplu sorgu hata yutma riski (except log'lar, devam eder) — bu kaynakta tetiklenmedi (discover 200).

### C. Enrichment (`app/services/ds_enrichment_service.py`)
- `MAX_ENRICH_COLUMNS=100` (satır 251, ana prompt) + `_COL_CHUNK_SIZE=80` (overflow) + **`_MAX_TOTAL_ENRICH_COLUMNS=500` (satır 254 — SERT TAVAN)**: 500+ kolonlu tabloda kalanı "etiketsiz" loglanır (satır 323-331).
- `enrich_table` (satır ~460-535): ana çağrı → `_enrich_overflow_columns` → `_fill_missing_columns` (v3.74.2). Ana+fallback **ikisi de None dönerse** → `_generate_fallback_analysis` (satır 88) → `{"columns":{}}` → 312 kolon `business_name_tr=""`, `semantic_type="other"` yazılır = **"312 LLM BEKLEYEN"**.
- `ENRICH_LLM_TIMEOUT=150` var ama **otomatik tekrar deneme YOK**; başarısızlıkta boş placeholder kalır, "Yeniden Öğren" gerekiyor (non-determinism v3.74.2 yorumunda kayıtlı).

### D. Query-builder payload (`app/api/routes/db_smart_api.py`)
- **`_MAX_COLUMNS_PER_TABLE=50` (satır 2004)** → `_fetch_table_columns` (satır 2074) `[:50]`: query-builder/akıllı-sorgu wide tabloda yalnız **ilk 50 kolonu** görür → kalan kolonlar sorguda **görünmez** ("keşfedilemiyor" algısının asıl kaynağı). Yorum: "R-4 payload guard".

### E. Query-grounding + anti-halüsinasyon (`app/services/text_to_sql.py`) — 🛡️ KORUNACAK YAPILAR
> Kullanıcı uyarısı (2026-06-05): "llm halüsinasyonu ya da eksik kalanları tekrar kontrol eden bir yapı vardı, çalışanı bozma." Tespit edilen 3 çalışan yapı — regresyon YASAK:
- **`get_schema_context` (820):** tam `columns_json` saklar (kolon kapağı YOK).
- **`format_schema_for_llm` (1060):** SQL-gen prompt'una kolon render eder. **`cols[:80]` (satır 1097)** yalnız ilk 80 kolonu RELEVANCE-kontrol eder + `[:50]` göster-kapağı (1146/1149/1172). Geniş tabloda **81+ kolon LLM'e HİÇ gitmez** → Akıllı Keşif sorgusunda da "keşfedilemiyor". Relevance-pruning (v3.14.0) bilinçli token-bütçesi → KORUNACAK, sadece kontrol-kapağı genişletilecek.
- **`_check_column_hallucination` (744):** üretilen SQL'in kolonlarını **TAM** şema kolon setiyle (get_schema_context kapaksız) karşılaştırır → prompt kapağını yükseltmek bunu **BOZMAZ, hizalar** (gerçek kolon "uydurma" sanılmaz).
- **`_fill_missing_columns` (ds_enrichment_service.py:336, v3.74.2):** ana çağrı sonrası DÜŞEN kolonları chunk'lı doldurur (case-insensitive, 2-pass) — dünkü "eksik-kolon tekrar-kontrol". Cap raise (500→2000) ≤500-kolon tabloda davranışı DEĞİŞTİRMEZ → KORUNUR.

### Q. Schema-context cap (`app/services/db_smart/llm_generate_report.py`) — rapor SQL-gen
- **`MAX_SCHEMA_COLUMNS_PER_TABLE=80` (satır 55, 363)** → rapor SQL-gen prompt'unda tablo başına 80 kolon (token bütçesi + grounding). Wide tabloda aynı "81+ görünmez".

## 3. Faz/Gate Haritası

| Gate | Sorumlu Konsey | Brief |
|---|---|---|
| G1 | HERMES + ORACLE + NIKE | (ZEUS doğrudan — disjoint) |
| G2 | METIS + HERMES + TYCHE | (ZEUS doğrudan) |
| G3 | HEPHAESTUS + APOLLO + ARES | (ZEUS doğrudan) |
| G5 | ORACLE + METIS + TYCHE | (ZEUS doğrudan — anti-halüsinasyon korunur) |
| G4 | APOLLO + ORACLE | (opsiyonel, faz-2) |

### G5 — Query-grounding kolon kapağı (sorguda tüm kolonlar görünür) — 🛡️ çalışan yapı korunur
- `text_to_sql.py:format_schema_for_llm` **`cols[:80]` → TÜM kolonları relevance-kontrol** et (kolon #200 de eşleşebilsin); göster-kapağını (50) makul yükselt ama **relevance-pruning + token-bütçesi KORUNUR** (ilgisiz kolonlar yine "... +N kolon daha" ile özetlenir).
- `llm_generate_report.py:MAX_SCHEMA_COLUMNS_PER_TABLE` 80→500 (rapor SQL-gen grounding).
- **`_check_column_hallucination` DOKUNULMAZ** — tam kolon setiyle çalışır; prompt genişlemesi onu güçlendirir.
- TYCHE: behavior-parity — dar tablo (≤50 kolon) prompt'u AYNEN kalmalı; yalnız geniş tablo genişler.

### G1 — Kolon kapaklarını kaldır (kullanıcı direktifi) — token-farkında
- **`_MAX_COLUMNS_PER_TABLE=50` (db_smart_api.py:2004)** → kaldır/yükselt. Query-gen prompt'u şişmesin diye: token-farkında alt-paketleme veya semantic-tip/aranabilirlik önceliği ile kolon sıralama (tüm kolonlar erişilebilir, ama prompt'a relevance-ranked girer). **Karar: tüm kolonlar payload'da, prompt token-bütçesi METIS+ORACLE ile ayarlanır.**
- **Örnekleme 50-kapağı (ds_learning_service.py:1646)** → yükselt/konfigüre et (geniş tabloda örnek-veri tüm kolonlara). Perf: `_safe_identifier` korunur (ARES), SELECT kolon sayısı NIKE ile sınır-test.
- **`_MAX_TOTAL_ENRICH_COLUMNS=500` (ds_enrichment_service.py:254)** → "chunk-until-done" (tavansız döngü); 500+ kolonlu tabloda da hepsi etiketlenir.

### G2 — Geniş-tablo enrichment güvenilirliği (312→0 pending)
- Runtime teşhis: `T_ICT_DYNAMIC_DATA` için `call_llm_api` gerçekten başarısız mı (timeout/empty/quota)? → "all pending" = tam LLM-yol çökmesi.
- **Boş-placeholder ayrımı:** LLM çökünce 312 kolonu `""`/`other` ile "yapılmış gibi" yazma → gerçek hatayı Hata İzleme'ye yaz + kolonları **"truly pending"** işaretle (re-run hedefler).
- **Otomatik bounded retry** (chunk başına) + chunk hata yutmasını yüzeye çıkar (`_llm_enrich_columns_only` {} dönüşünü logla).
- 312-kolon prompt'unu daha küçük güvenli chunk'lara böl (LLM JSON truncation riski ↓).

### G3 — FK gürültü temizliği + ParentId self-ref
- **Framework non-FK denylist:** `gcrecid`, `recid` (+ konfigüre edilebilir liste) → ne FK adayı ne uyarı. 93+ gürültü silinir.
- **Diagnostic suffix daralt:** `_REF_ISH_SUFFIXES`'ten `code`/`key`/`no` çıkar (ya da uyarıyı INFO'ya indir) → 154 `no_pattern_match` gürültüsü ↓.
- **ParentId self-reference:** `parent`-kökü → hedef = KENDİ tablosu PK'sı (org-chart/hiyerarşi). Gerçek FK kazanımı.

### G4 — (OPSİYONEL, faz-2) Gerçek FK kapsamını genişlet
- By-code FK tier: `CompanyCode → Company` (iş-anahtarı FK, id değil).
- Kısaltma/sinonim haritası: `app→application` (`AppId → T_CMN_APPLICATION`).
- Riskli (false-positive) → ayrı sprint, sample-validation zorunlu.

## 4. Critical Files to Modify
- `app/api/routes/db_smart_api.py` (G1 — `_MAX_COLUMNS_PER_TABLE`, `_fetch_table_columns`)
- `app/services/ds_learning_service.py` (G1 — örnekleme 50-kapağı ~1646)
- `app/services/ds_enrichment_service.py` (G1 tavan + G2 retry/teşhis/placeholder)
- `app/services/db_learning/fk_inference_service.py` (G3 — denylist, suffix, self-ref)
- (olası) `frontend/assets/js/modules/ds_learning_module.js` (G2 — "okunamadı"/pending UX; HEBE gate)

## 5. Yeniden Kullanılacak Mevcut Fonksiyonlar
- `_llm_enrich_columns_only` / `_enrich_overflow_columns` / `_fill_missing_columns` (chunk altyapısı zaten var — tavanı kaldır, retry ekle)
- `_safe_identifier` (sample SQL güvenliği — kapak kalkınca da uygulanır)
- `_extract_root` / `_head_noun_from_name` / `by_entity_token` (FK eşleme — denylist önce devreye girer)
- `log_system_event` / `log_exception` (gerçek LLM hatasını yüzeye çıkar)

## 6. Risk Özeti

| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Cap kalkınca query-gen prompt token patlaması | Orta | Yüksek (LLM maliyet/limit) | Token-farkında alt-paketleme + relevance-rank (METIS+ORACLE) |
| Geniş tabloda örnekleme perf düşüşü (312-kol SELECT) | Orta | Orta | Satır sayısı cap + TABLESAMPLE; kolon-cap yerine row-cap (NIKE) |
| Enrichment retry → LLM maliyet artışı | Orta | Orta | Bounded retry (2-3), yalnız truly-missing kolonlar |
| FK denylist gerçek bir FK'yı bastırır | Düşük | Orta | Liste konfigüre edilebilir; yalnız her-tabloda-var framework kolonları |
| Suffix daraltma gerçek by-code FK'yı kaçırır | Düşük | Düşük | G4'te by-code tier ile telafi (faz-2) |

## 7. Verification (uçtan-uca)
- `pytest tests/db_learning/ tests/.../test_fk_inference*.py` — FK self-ref + denylist yeni testleri yeşil; mevcut 72 FK testi regresyonsuz.
- `pytest tests/.../test_ds_enrichment*.py` — 312-kolon (ve 600-kolon) tam-enrich + chunk-until-done testi.
- Smoke (gstack/manuel): ONEDESKPG `T_ICT_DYNAMIC_DATA` → "Yeniden Öğren" → 312 kolon etiketli, "0 LLM BEKLEYEN".
- log3 tekrarı: FK WARNING sayısı GCRecId/Code gürültüsünden temiz; ParentId self-FK persist edildi.
- Query-builder: wide tabloda 50+ kolon görünür/sorgulanabilir.

## 8. Out-of-scope
- G4 (by-code FK + abbreviation map) — ayrı sprint, sample-validation zorunlu.
- Discovery toplu-sorgu hata-yutma sağlamlaştırması (ayrı; bu kaynakta tetiklenmedi) — error_logging_hardening planına bağlanabilir.
- 2000+ tablolu kaynakta tam-örnekleme perf profili (gerekirse ayrı NIKE çalışması).
