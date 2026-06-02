---
plan_id: llm_report_column_grounding
created: 2026-06-02
branch: hira
status: completed
version_target: v3.55.0
closed: 2026-06-02
closure_note: "_fetch_table_columns + generate_report wiring + _build_prompt kolon bloğu (cap 80) + UYDURMA guard. 4 test geçti (grounding + fetch). Backward-compat + fail-soft. Code-review temiz. Mevcut kayıtlı rapor için kullanıcı Düzenle/yeniden üret."
council_mod: 3
hebe_gate_required: false
---

# generate-report LLM kolon grounding — "CreatedDate uydurma" (halüsinasyon) fix

## Context (kanıtlı)
Kayıtlı rapor "İş Akışında En Uzun İşlem Süreleri" Çalıştır → `stream_error: column "CreatedDate"
does not exist`. SELECT'teki 10 kolon geçerli; yalnız `"CreatedDate"` yok. Named-cursor (v3.52.0)
fix'i çalıştı (SQL artık DB'de koşuyor) — bu AYRI bir SQL-üretim doğruluğu sorunu.

## Kök neden (kod-seviyesi)
`llm_generate_report._build_prompt` (satır 286-294) LLM'e: tablo ADI + kullanıcı-seçili kolonlar
(`col_lines`) veriyor; tablonun GERÇEK tam kolon envanterini VERMİYOR. `generate_report`
`_fetch_table_names` ile yalnız ad çekiyor (columns_json çekmiyor). Kullanıcı "en uzun süre" istedi →
LLM süre için tarih kolonu gerekti, gerçek kolonları bilmediğinden `"CreatedDate"`'i UYDURDU.

## Faz/Gate (Konsey: ORACLE primary, METIS + HEPHAESTUS review)
- **G1 (HEPHAESTUS):** `_fetch_table_columns(cur, source_id, table_ids)` → ds_db_objects.columns_json'dan
  {table_name: [(col, data_type)]}. _fetch_table_names deseni + aynı RLS-scoped cur.
- **G2 (HEPHAESTUS):** generate_report — name lookup yanında columns lookup; `table_columns` dict.
- **G3 (ORACLE+METIS):** _build_prompt'a `table_columns` param + "Tablo kolonları (GERÇEK şema)" bloğu
  (ad+tip, per-table cap MAX_SCHEMA_COLUMNS_PER_TABLE=80) + sertleştirme: "listede OLMAYAN kolonu ASLA
  uydurma; gerekli kolon (tarih vb.) yoksa o metriği HESAPLAMA, rationale'da belirt".
- **G4 (TYCHE):** test — _build_prompt columns block + talimat; _fetch_table_columns fake-cursor; mevcut
  llm_generate_report testleri yeşil.
- **G5:** /code-review medium.
- **G6 (HERA):** v3.55.0.

## Token bütçe (ORACLE/METIS)
- Per-table kolon cap 80 (büyük tablolarda taşmayı önle). Tablo sayısı zaten primary+join (genelde ≤5).
- Format kompakt: `tablo: "col1"(tip), "col2"(tip), ...`.

## Critical Files
- `app/services/db_smart/llm_generate_report.py` (_fetch_table_columns + generate_report + _build_prompt)
- `tests/...` (yeni/mevcut llm_generate_report testleri)
- `app/core/config.py` (versiyon)

## Risk
| Risk | Mit |
|---|---|
| Token taşması (büyük tablo) | per-table 80 cap + tip kısa |
| columns_json boş/eski tablo | bloğu atla (boşsa eski davranış) — fail-soft |
| LLM hâlâ uydurursa | route enforce_sql_scope + DB column-check zaten yakalar; bu fix oranı düşürür |
| Mevcut prompt testleri kırılır | yeni blok additive; test güncelle |

## Verification
- _build_prompt(table_columns=...) → prompt'ta kolon listesi + "uydurma" talimatı (assert).
- _fetch_table_columns fake-cursor → {table: [(col,type)]}.
- mevcut pytest yeşil + py_compile.
- Canlı: aynı rapor yeniden üretilince gerçek tarih kolonu (veya "uygun kolon yok") — kullanıcı testi.

## Out-of-scope
- Mevcut KAYITLI raporun düzeltilmesi (kullanıcı "Düzenle"/yeniden üret) — bu fix YENİ üretimleri grounding'ler.
- deep_think DB-Only text-to-SQL ayrı prompt (gerekirse ayrı faz).
</content>
