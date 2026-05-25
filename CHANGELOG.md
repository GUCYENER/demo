# VYRA Changelog

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
