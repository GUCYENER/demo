# VYRA Changelog

## Graphify v1.2 → v1.2.2 — 2026-05-26 — Coverage + Embedding + Bug-fix + Concurrency Sprint

> Graphify paketinin geliştirme adımları VYRA `CHANGELOG.md`'de izlenir; paket kendi git repo'sundadır (`General_Graphify/` initial commit `77330ab`, Wave D `d266249`). Tam detay: [`.agents/workflows/graphify_v12_release_notes.md`](.agents/workflows/graphify_v12_release_notes.md).

- **Wave A (G1-G8)** — File entity (55→633), Function AST emit (0→2102), `defined_in`/`imports`/`calls` predicate emission (0→16 621), post-mine embedding sweep (%0→%100), mine path resolution, KAP 10c.3 coverage threshold assert, `coverage-report` CLI subcommand.
- **Wave B (T1-T8)** — pytest paketi 171→186 test (%74 coverage); HEBE config (`pytest.ini` + `conftest.py`); ARES F1-F5 spec drift kaydı.
- **Wave C (v1.2.1)** — BUG-G1 `__pycache__` leak fix, BUG-G2 `database is locked` race partial fix (`PRAGMA busy_timeout=30000` + `_RetryingConnection` proxy; cross-instance race xfail strict=False → Wave D), R5 Class count UNION (0→298), BUG-G3 T7 entity-relative assertion düzeltmesi.
- **Wave D (v1.2.2)** — BUG-G2 final closure: class-level `_RetryingConnection._locks: Dict[str, threading.RLock]` map keyed by `db_path`; cross-instance writer serialization; `_tx()` lock-across-BEGIN/COMMIT; `_is_write_sql()` heuristic (SELECT/PRAGMA-read bypass). xfail kaldırıldı + yeni `test_two_instances_serialize_on_same_db_path` (40 yazım/2 thread, <5s).
- **Workflow** — `vyrazeus.md` KAP 10c.3 coverage threshold gate (`--threshold 0.95`); Graphify-first lookup + mine-after-fix kuralları (memory); sub-agent malware-reminder refusal pattern (memory feedback).
- **Final test**: 187/187 PASS, coverage %74.

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
