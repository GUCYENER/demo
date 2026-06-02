---
plan_id: smart_discovery_fk_enrich_robustness
created: 2026-06-03
branch: hira
status: completed
version_target: v3.60.0
closed: 2026-06-03
council_mod: 2
closure_note: "Canlı PG elysion T_ORG_* kanıtıyla 3 kök fix. (A) FK inference: CamelCase rol-önekli kolonlar (CreateUserId root='createuser' tabloya uymaz) → HEAD-NOUN fallback (→user, SCORE_NAMING_HEAD=0.45+tip) + Unicode regex (Türkçe) + [Ii][Dd]. (B) Görünürlük: logger.* system_logs'a yazmıyor → tablo-bazlı unresolved tanılama log_system_event(WARNING, tablo-aranabilir) + log_exception(inference/persist). (C) LLM etiketleme: 30-kolon kapağı → MAX_ENRICH_COLUMNS=100 + over-cap diag + case-insensitive eşleştirme. + Etiketleme paneli kolon-görünümü dikey scroll. 38 FK testi (5 yeni), 105 suite passed, code-review TEMİZ."
hebe_gate_required: false
---

# Akıllı Keşif FK + LLM-etiketleme robustluk & görünürlük

## Context (canlı kanıt — varsayım yok)
elysion.T_ORG_PARTY/T_ORG_USER (PostgreSQL) gerçek kolon adları: PartyId(PK), CreateUserId,
PADCompanyId, GCRecId, ErpCompanyCode... → **CamelCase + rol-önekli**. Picker "FK ilişkisi yok"
veriyordu ama sistem loglarında hata yoktu.

## Kök nedenler
1. **FK inference**: `CreateUserId` → eski root='createuser' (tüm stem) → hiçbir tabloya uymaz
   (gerçek hedef T_ORG_USER='user'). Türkçe kolonlar `[a-z]` regex'ine takılıp hiç yakalanmıyordu.
2. **Görünürlük**: standart `logger.*` system_logs'a YAZMIYOR → FK-okuma/inference hataları
   Hata İzleme'de görünmüyor (kullanıcı tablo adıyla arayınca boş).
3. **LLM etiketleme**: `columns[:30]` sabit kapağı → 30+ kolonlu tabloda 31+ kolon LLM'e hiç
   gitmiyor → "—"/'other'. + kolon-adı eşleştirmesi case-sensitive (ADGroupId≠adgroupid).

## Faz/Gate (POSEIDON veri-modelleme + DBA + ARES + TYCHE)
- **G1 FK matching**: head-noun fallback (`_head_noun_from_name`, all-caps & Unicode-safe),
  Unicode `_NAMING_RES`/`_CAMEL_ID_RE`, match_kind→SCORE_NAMING_HEAD(0.45), self-FK head guard,
  deterministik seçim korunur.
- **G2 Görünürlük**: `_iter_fk_candidates(diag=...)` unresolved kayıt (no_pattern/no_target/no_pk);
  ds_learning_service → log_system_event(WARNING, tablo başına) + log_exception(inference/persist).
- **G3 Enrichment**: MAX_ENRICH_COLUMNS=100 (2 spot), over-cap diag, case-insensitive eşleştirme.
- **G4 UI**: enrichment kolon-görünümü `.ds-enrich-table-wrap` inline flex+overflow-y+max-height:62vh.
- **G5 TYCHE**: 38 FK testi (5 yeni) + 105 suite passed. **G6**: /code-review TEMİZ. **G7**: v3.60.0.

## Critical Files
- app/services/db_learning/fk_inference_service.py (head-noun, Unicode, diag, score)
- app/services/ds_learning_service.py (diagnostics → system_logs)
- app/services/ds_enrichment_service.py (cap 100, case-insensitive, over-cap diag)
- frontend/assets/js/modules/ds_enrichment_module.js (scroll) + dist
- app/core/config.py (versiyon)
- tests/test_fk_inference_service.py (5 yeni test)

## Risk / Mit
| Risk | Mit |
|---|---|
| head-noun false-positive FK | düşük güven (0.45, tip uyumu şart) + tablo-eşleşme gate + self-FK guard + admin_verified=FALSE |
| all-caps tokenize (PARTYID→y) | all-caps/all-lower → camel-split YOK, bütün parça |
| diag log gürültüsü | tablo başına tek WARNING (per-column değil), items[:25] cap |
| LLM 100 kolon token | enrichment seyrek (admin keşfi); >100 tabloya tanılama, ileride chunk |

## DEPLOY / CANLI
- Backend restart: fk_inference_service.py + ds_learning_service.py + ds_enrichment_service.py + config.py
- Frontend: ds_enrichment_module.js + dist/*
- **KRİTİK**: canlıda kaynağı YENİDEN KEŞFET → inference yeni matching ile FK'ları repopulate eder;
  enrichment tüm kolonları (100'e kadar) etiketler. Sonra picker'da FK + etiketler görünür.
- Hâlâ FK yoksa: Hata İzleme'de tablo adıyla ara → unresolved tanılama (reason) kök nedeni verir.

## Out-of-scope (gelecek)
- >100 kolon tablolar için chunk'lı enrichment (şimdilik tanılama loglar).
- All-caps ayraçsız bileşik (CREATEDBYUSERID) tokenization (sözlük gerektirir; diag yüzeye çıkarır).
