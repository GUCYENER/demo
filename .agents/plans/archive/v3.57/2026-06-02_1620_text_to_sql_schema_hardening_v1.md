---
plan_id: text_to_sql_schema_hardening
created: 2026-06-02
branch: hira
status: completed
version_target: v3.57.0
council_mod: 2
hebe_gate_required: false
closed: 2026-06-02
closure_note: "format_schema_for_llm bozuk columns_json defansif hardening (.get + non-dict/boş-ad guard + tablo label .get). 21 test (2 yeni). Code-review temiz. NOT: text_to_sql kolon-tipi grounding ZATEN mevcuttu (col_dtype + temporal öncelik + halüsinasyon ban + post-check) — yeni özellik gerekmedi, yalnız bu micro-hardening."
---

# text_to_sql format_schema_for_llm defansif hardening (v3.57.0)

## Context
Kullanıcı "Veritabanında Ara kolon-tipi grounding" istedi. İnceleme: text_to_sql ZATEN kolon adı+tipi
(`{col_name} ({col_dtype})`) + temporal öncelik + halüsinasyon yasağı + `_check_column_hallucination`
post-check'e sahip — grounding mevcut, yeni özellik gerekmedi (kanıt: format_schema_for_llm:1099+).
İnceleme sırasında bulunan tek defansif boşluk: `c['name']`/`c['data_type']`/`t['name']` doğrudan key
erişimi → bozuk/eski columns_json kaydında KeyError → format çöker → text_to_sql ŞEMASIZ kalır
(halüsinasyon yasağı şemaya dayandığından kritik).

## Değişiklik (HERMES + TYCHE)
- `format_schema_for_llm` kolon döngüsü: non-dict guard + `c.get('name') or ''` (boş-ad skip) +
  `c.get('data_type') or ''`. Tablo label `t['name']` → `t.get('name','')`.

## Verification
- py_compile OK. tests/test_text_to_sql.py 21 passed (2 yeni: malformed columns + missing table name).
- Code-review (medium): TEMİZ — col_dtype='' downstream güvenli, skip tutarlı, geçerli veri çıktısı
  birebir aynı (regresyon yok), backward-compat.

## Out-of-scope
- Pre-existing quirk (1152-1158 yalnız son kolonun PK/date status'u) — patch'le ilgisiz, ayrı.
</content>
