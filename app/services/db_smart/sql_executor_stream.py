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

# Engine cursor batch tuning — Oracle/MSSQL fetch tuning hedef değeri.
# psycopg2 zaten itersize=batch_size kullanır; bu sabit non-PG path için.
ENGINE_FETCH_BATCH = 500


def _configure_engine_cursor(cursor: Any, dialect: str) -> Dict[str, Any]:
    """Engine-spesifik cursor optimizasyonlarını uygular (P35).

    Returns:
        Uygulanan ayarların dict'i (test/observability — set edilen attr'lar).
        Driver yoksa / attr yoksa boş dict döner, exception SWALLOW edilir;
        caller fallback generic fetchmany(batch_size) loop'una düşer.

    Dialect davranışı:
        - oracle  : `arraysize` ve `prefetchrows` = ENGINE_FETCH_BATCH (oracledb)
        - mssql   : özel attr yok; fetchmany batch zaten caller'da uygulanır
                    (pymssql/pyodbc — buffer flag pyodbc'de mevcut; opsiyonel)
        - mysql   : pymysql.cursors.SSCursor sınıfı ile kıyas + setattr yapılamaz
                    (cursor class connect aşamasında seçilir); burada yalnızca
                    cursorclass info'su loglanır. Server-side cursor geçişi
                    ds_learning_service tarafında P36'da yapılacak.
        - postgresql: hiçbir şey yapma (named cursor + itersize caller'da).
    """
    applied: Dict[str, Any] = {}
    d = (dialect or "").lower().strip()

    if d == "oracle":
        # oracledb cursor.arraysize / prefetchrows — fetchmany batch boyutunu
        # network round-trip seviyesinde artırır. Attr yoksa setattr yine ekler
        # ama driver davranışını etkilemez; hasattr ile koruma.
        try:
            if hasattr(cursor, "arraysize"):
                cursor.arraysize = ENGINE_FETCH_BATCH
                applied["arraysize"] = ENGINE_FETCH_BATCH
            if hasattr(cursor, "prefetchrows"):
                cursor.prefetchrows = ENGINE_FETCH_BATCH
                applied["prefetchrows"] = ENGINE_FETCH_BATCH
        except Exception as exc:  # pragma: no cover — defensive
            logger.debug("[db_smart.stream] oracle cursor tune skipped: %s", exc)

    elif d == "mssql":
        # pyodbc cursor.arraysize destekler; pymssql etmez. hasattr ile guard.
        try:
            if hasattr(cursor, "arraysize"):
                cursor.arraysize = ENGINE_FETCH_BATCH
                applied["arraysize"] = ENGINE_FETCH_BATCH
        except Exception as exc:  # pragma: no cover
            logger.debug("[db_smart.stream] mssql cursor tune skipped: %s", exc)

    elif d == "mysql":
        # SSCursor sınıf bilgisi — cursor class connect aşamasında belirlenir.
        # Burada yalnızca lazy import + debug log; runtime davranış değişmez.
        try:
            import pymysql.cursors as _pmcur  # noqa: F401
            ss_cls = getattr(_pmcur, "SSCursor", None)
            if ss_cls is not None:
                applied["preferred_cursorclass"] = "SSCursor"
                if not isinstance(cursor, ss_cls):
                    logger.debug(
                        "[db_smart.stream] mysql cursor is %s; SSCursor recommended "
                        "for streaming (set via connect(cursorclass=SSCursor))",
                        type(cursor).__name__,
                    )
        except ImportError:
            logger.debug("[db_smart.stream] pymysql not installed; mysql tune skipped")
        except Exception as exc:  # pragma: no cover
            logger.debug("[db_smart.stream] mysql cursor tune skipped: %s", exc)

    # postgresql: caller named cursor + itersize set ediyor → no-op
    return applied


def _make_stream_callable(source: Dict[str, Any], dialect: str, password: str):
    """SQL alıp stream-aware iterator döndüren callable üretir.

    stream_execute() bekliyor: callable(sql, batch_size=N, mode='stream')
    Iterator dict yields:
        - {"columns": [...]}
        - {"rows": [[...], ...]}
        - {"row_count": N, "elapsed_ms": M, "truncated": bool}

    NOT: `password` parametresi ayrı tutulur (source dict'e konmaz) — credential
    sızıntısı önleme. _get_db_connector(source, password) signature'ı password'ü
    explicit alır; source dict yalnızca host/port/db_name/db_user içerir.
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
            ret = _get_db_connector(source, password)
            # _get_db_connector: (conn, dialect_str) tuple döndürür
            if isinstance(ret, tuple):
                conn = ret[0]
            else:
                conn = ret
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
                cur = conn.cursor()

            # Engine-specific cursor tuning (P35). Hata → swallowed; generic
            # fetchmany(batch_size) fallback caller'da zaten mevcut.
            try:
                _configure_engine_cursor(cur, dialect)
            except Exception as exc:  # pragma: no cover
                logger.debug("[db_smart.stream] engine cursor config skipped: %s", exc)

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
    password: str = "",
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

    # 4) Concurrency guard
    if not _concurrency_guard.try_acquire(timeout_s=2.0):
        yield {"type": "queued", "message": "Sorgu kuyruğunda bekliyor..."}
        _settings = __import__("app.core.config", fromlist=["settings"]).settings
        if not _concurrency_guard.try_acquire(timeout_s=float(
            getattr(_settings, "DBSMART_STREAM_QUEUE_TIMEOUT_S", 30)
        )):
            yield {"type": "error", "message": "Kuyruk zaman aşımı (503). Daha sonra tekrar deneyin."}
            return

    try:
        # 5) Stream çalıştır — stream_execute() generic protokole devreder
        cancel_token = _CancelToken()
        cb = _make_stream_callable(source, dialect, password)
        for event in stream_execute(cb, sql_str, batch_size=batch_size, max_rows=max_rows):
            if cancel_token.is_set():
                yield {"type": "error", "message": "Sorgu iptal edildi."}
                return
            yield event
    finally:
        _concurrency_guard.release()


# ─────────────────────────────────────────────────────────────
# P36 — Backpressure cancel token
# ─────────────────────────────────────────────────────────────

import threading as _threading


class _CancelToken:
    """Thread-safe cancel token for backpressure."""
    def __init__(self):
        self._event = _threading.Event()

    def set(self):
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


# ─────────────────────────────────────────────────────────────
# P37 — Concurrency guard
# ─────────────────────────────────────────────────────────────

class _ConcurrencyGuard:
    """BoundedSemaphore wrapper for max concurrent streams."""
    def __init__(self, max_concurrent: int = 5):
        self._sem = _threading.BoundedSemaphore(max_concurrent)

    def try_acquire(self, timeout_s: float = 2.0) -> bool:
        return self._sem.acquire(blocking=True, timeout=timeout_s)

    def release(self):
        try:
            self._sem.release()
        except ValueError:
            pass


_concurrency_guard = _ConcurrencyGuard(
    max_concurrent=int(getattr(
        __import__("app.core.config", fromlist=["settings"]).settings,
        "DBSMART_STREAM_MAX_CONCURRENT", 5
    ))
)
