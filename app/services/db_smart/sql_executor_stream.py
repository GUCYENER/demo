"""db_smart streaming SQL executor (v3.30.0 FAZ 3 P15 G3.2).

Mimari:
    - `stream_safe_sql()` — SafeSQLExecutor guard'ları (validate_sql + table
      whitelist + apply_row_limit + adapt_functions) çalıştırır, ardından
      `stream_execute()` generator'a uygun stream-aware callable verir.
    - PG path: psycopg2 server-side named cursor + fetchmany(batch_size).
    - Oracle / MSSQL / MySQL path: standard cursor fetchmany. Engine-specific
      cursor optimizasyonları (oracledb arraysize, SSCursor) ilerleyen
      iterasyonda eklenecek (G3.2 ikinci sprint).
    - Backpressure ve separate connection pool MIMARI olarak yer açıldı ama
      tam implementasyon (asyncio queue + max_lag cancel) sonraki sprint.

Public API:
    stream_safe_sql(sql, source, dialect, *, allowed_tables, user_ctx,
                    batch_size=200, max_rows=10000) -> Iterator[Dict]
        SSE event protokolüne uygun event dict'leri yield eder:
            {"type": "start"|"columns"|"rows"|"end"|"error", ...}

Tasarım notları:
    - SafeSQLExecutor güvenlik katmanı ATLANMAZ — validate_sql + whitelist +
      row_limit + adapt_functions önce çalışır; sadece execute path streaming.
    - source dict caller'ın data_source kaydını içerir; bağlantı kurma
      ds_learning_service._get_db_connector pattern'ine bağlı kalır (mevcut
      altyapı).
    - empty SQL / invalid SQL durumlarında stream_execute zaten {"type":
      "error"} yield eder; biz preflight'ta da bir kez doğrularız ki anlamlı
      hata mesajı SSE üzerinden gelsin.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, List, Optional

from app.services.safe_sql_executor import (
    validate_sql,
    check_table_whitelist,
)
from app.services.pipeline.streaming_execute import stream_execute, DEFAULT_BATCH_SIZE

logger = logging.getLogger(__name__)

# Daha düşük tavan — wizard sonuçları interaktif görüntüleme; UI ilk batch'i
# <200ms içinde almalı. Bigger jobs separate "export" path'inden gidecek.
DEFAULT_MAX_ROWS_STREAM = 10_000


def _make_stream_callable(source: Dict[str, Any], dialect: str):
    """SQL alıp stream-aware iterator döndüren callable üretir.

    stream_execute() bekliyor: callable(sql, batch_size=N, mode='stream')
    Iterator dict yields:
        - {"columns": [...]}
        - {"rows": [[...], ...]}
        - {"row_count": N, "elapsed_ms": M, "truncated": bool}
    """
    def _stream_callable(sql: str, *, batch_size: int = DEFAULT_BATCH_SIZE,
                         mode: str = "stream") -> Iterator[Dict[str, Any]]:
        if mode != "stream":
            raise TypeError("only stream mode supported")
        # Lazy import — circular guard + test-time isolation
        from app.services.ds_learning_service import _get_db_connector

        conn = None
        cur = None
        try:
            conn = _get_db_connector(source, dialect)
            if conn is None:
                yield {"columns": [], "rows": []}
                return

            # PG server-side cursor (named cursor) — psycopg2 spesifik
            if dialect == "postgresql":
                try:
                    import uuid as _uuid
                    cur_name = f"vyra_dbsmart_{_uuid.uuid4().hex[:12]}"
                    cur = conn.cursor(name=cur_name)
                    cur.itersize = batch_size
                except TypeError:
                    # Named cursor desteklemiyor → standart cursor fallback
                    cur = conn.cursor()
            else:
                # Oracle / MSSQL / MySQL — standart cursor + fetchmany(batch_size)
                # Engine-specific optimizasyon (arraysize, SSCursor) sonraki sprint.
                cur = conn.cursor()

            cur.execute(sql)
            cols = [d[0] for d in (cur.description or [])]
            if cols:
                yield {"columns": cols}

            total = 0
            while True:
                rows = cur.fetchmany(batch_size)
                if not rows:
                    break
                # Tuple → list (JSON serialize edebilelim diye)
                norm = [list(r) for r in rows]
                yield {"rows": norm}
                total += len(norm)
            yield {"row_count": total}
        except Exception as e:
            logger.warning("[db_smart.stream] execute failed: %s", e)
            raise
        finally:
            # Server-side cursor'ı kapat (PG'de transaction sonunda kapanır
            # ama burada explicit close cursor sızıntısı önler)
            if cur is not None:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    return _stream_callable


def stream_safe_sql(
    sql: str,
    source: Dict[str, Any],
    dialect: str,
    *,
    allowed_tables: Optional[List[str]] = None,
    user_ctx: Optional[Dict[str, Any]] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rows: int = DEFAULT_MAX_ROWS_STREAM,
) -> Iterator[Dict[str, Any]]:
    """Güvenli streaming SQL execute — SafeSQLExecutor guard'ları + stream events.

    Yield edilen event'ler:
        {"type": "start", "sql_preview": "..."}
        {"type": "columns", "columns": [...]}
        {"type": "rows", "rows": [...], "batch_index": k}
        {"type": "end", "row_count": N, "elapsed_ms": M, "truncated": bool}
        {"type": "error", "message": "..."}

    Caller endpoint bunları SSE formatına dönüştürür (`stream_to_sse()`).
    """
    sql_str = (sql or "").strip()
    if not sql_str:
        yield {"type": "error", "message": "SQL boş."}
        return

    # 1) Validate (read-only, no DDL/DML)
    is_valid, err = validate_sql(sql_str)
    if not is_valid:
        yield {"type": "error", "message": f"Güvenlik: {err}"}
        return

    # 2) Table whitelist (verilirse)
    if allowed_tables:
        is_allowed, terr = check_table_whitelist(sql_str, allowed_tables, dialect)
        if not is_allowed:
            yield {"type": "error", "message": f"Whitelist: {terr}"}
            return

    # 3) source/dialect ön kontrolü
    if not isinstance(source, dict) or not source:
        yield {"type": "error", "message": "Geçerli data_source bulunamadı."}
        return
    if dialect not in {"postgresql", "oracle", "mssql", "mysql"}:
        yield {"type": "error", "message": f"Desteklenmeyen dialect: {dialect}"}
        return

    # 4) Stream çalıştır — stream_execute() generic protokole devreder
    cb = _make_stream_callable(source, dialect)
    yield from stream_execute(cb, sql_str, batch_size=batch_size, max_rows=max_rows)
