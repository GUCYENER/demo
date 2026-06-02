---
plan_id: fk_inference_prefix_pk
created: 2026-06-02
branch: hira
status: completed
version_target: v3.56.0
closed: 2026-06-02
closure_note: "İki kök fix (prefix-tolerant by_last_token + is_pk key) + code-review tie-break (deterministik). 51 test (yeni prefixed/is_pk). CANLI: kaynağı yeniden keşfet (inference populate). text_to_sql grounding ayrı (v3.57.0, kullanıcı istedi)."
council_mod: 3
hebe_gate_required: false
---

# FK inference prefixed-tablo + is_pk key fix (picker "FK ilişkisi yok" KÖK çözüm)

## Context (kanıtlı)
Akıllı Keşif "Tablo Seç" → T_ORG_USER ana tablo → "İlgili Tablolar (FK): FK ilişkisi yok".
Keşif "FK İLİŞKİLERİ 29" (2143 tablo için — yalnız declared). PG declared-FK sorgusu DOĞRU
(pg_constraint, tüm şema) — DB'de gerçekten ~29 declared FK var. Boşluğu FK INFERENCE doldurmalı
ama inference bu şemada ~0 üretiyor. v3.52.0'da yalnız log eklenmişti (görünürlük), kök DEĞİL.

## İki kök neden (fk_inference_service.py — koddan kanıtlı)
1. **Prefix-intolerant tablo eşleştirme** (_iter_fk_candidates:348-376): `by_norm_name` tabloları TAM
   normalize adla indeksliyor ("t_wf_instance"). "InstanceId"→root "instance"→candidate "instance"→
   `by_norm_name.get("instance")` → "t_wf_instance" ile eşleşmez (T_WF_/T_ORG_ prefix) → candidate yok.
2. **is_pk vs is_primary_key uyumsuzluğu:** detect_objects columns_json'a `is_pk` yazar (ds_learning_
   service:412/645/930); fk_inference `c.get("is_primary_key")` okur (_load_schema:197, _iter:360) →
   pk_columns HEP BOŞ → target_pk "id" fallback'ine düşer (379-384) → bu şemada PK "XxxId" (id değil) →
   `_column_dict(target,"id")=None` → continue → candidate yok. (Ayrıca PK-skip 360 hiç tetiklenmez.)

## Faz/Gate (Konsey: HEPHAESTUS primary, ORACLE + METIS review)
- **G1 (HEPHAESTUS):** is_pk fix — `c.get("is_pk")` (is_primary_key fallback) _load_schema:197 + _iter:360.
- **G2 (HEPHAESTUS+ORACLE):** prefix-tolerant eşleştirme — _iter_fk_candidates'e `by_last_token` indeksi
  (norm_name'in son "_"-token'ı → tablo). Exact match ÖNCE, son-token fallback SONRA. root "instance"→
  "t_wf_instance" (son token "instance") eşleşir. Aynı-şema önceliği korunur. False-positive: confidence
  0.60-0.80 + admin verify + is_inferred gate ile sınırlı (METIS).
- **G3 (TYCHE):** test — prefixed tablo (t_wf_instance) + XxxId PK ile inference candidate üretir;
  is_pk parse; mevcut test_fk_inference_service yeşil.
- **G4:** /code-review medium.
- **G5 (HERA):** v3.56.0.

## Critical Files
- `app/services/db_learning/fk_inference_service.py` (_load_schema + _iter_fk_candidates)
- `tests/test_fk_inference_service.py` (+ prefixed/XxxId senaryosu)
- `app/core/config.py` (versiyon)

## Risk
| Risk | Mit |
|---|---|
| Son-token false-positive FK | confidence-gated + admin_verified + is_inferred; admin reddedebilir |
| is_pk değişimi başka yeri etkiler | yalnız fk_inference okuması; detect_objects zaten is_pk yazıyor (kaynak doğru) |
| Mevcut declared FK'ler bozulur | inference yalnız EKLER (skipped_existing declared'ı korur) |
| **CANLI: re-keşif şart** | inference detect_objects'te koşar → kullanıcı kaynağı YENİDEN KEŞFETMELİ (yeni inferred FK'ler populate olsun); not düşülür |

## Verification
- Test: prefixed tablo + XxxId kolon → _iter_fk_candidates candidate üretir; pk_columns is_pk'dan dolu.
- mevcut pytest (test_fk_inference_service + dialects) yeşil + py_compile.
- Canlı: kaynağı yeniden keşfet → ds_db_relationships inferred FK artar → picker T_ORG_USER FK gösterir.

## Out-of-scope
- text_to_sql kolon-tipi grounding (ayrı iş, v3.57.0 — kullanıcı talebi).
- CamelCase çok-kelime root ("ActionUserId"→"actionuser" yerine "user") — ileride; bu fix temiz
  vakaları (InstanceId/PartyId/UserId) çözer.
</content>
