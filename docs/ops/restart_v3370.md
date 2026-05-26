# v3.37.0 Restart Notes

- Backend: uvicorn reload gerekli (yeni 3 router: llm_metric / llm_column / llm_format).
- DB migration: `python run_migrations.py` (047 + 047b idempotent). 047b standalone — manuel `python migrations/047b_v3370_saved_reports_db_type_backfill.py --dry-run` ile önce kontrol et, sonra apply.
- Frontend: hard-reload önerilir (Ctrl+Shift+R). Cache-bust gerek değil; health.py cache-control no-store eklenmişti (önceki sprint).
- Redis: yeni cache key prefix `llm:metric:`, `llm:column:`, `llm:format:` (TTL 900s).
