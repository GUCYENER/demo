"""
pipeline.wiring — Prod callable factory
=======================================
`_llm_callable`, `_execute_callable`, `_explain_callable` üreten
factory fonksiyonlar. Pipeline state'ine inject edilmek için API
endpoint'lerinden çağrılır.

Tasarım:
  - Saf fonksiyonlar — pipeline modülleri bunlardan habersiz.
  - Hata fırlatırsa pipeline error_category sınıflandırması devreye girer
    (self_heal node).
  - Tüm callable imzaları pipeline/nodes/*.py dokümantasyonundakiyle uyumlu.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM callable
# ---------------------------------------------------------------------------

def make_llm_callable(temperature: float = 0.0) -> Callable[[str, Dict[str, Any]], str]:
    """
    sql_generate node için LLM callable üretir.

    Beklenen imza: callable(prompt: str, meta: dict) -> str
      meta: {"intent": ..., "schema_ctx": ..., "examples": [...], "history": [...]}
    Dönüş: SQL string (ham — sql_generate node code-fence parse eder).
    """
    def _call(prompt: str, meta: Optional[Dict[str, Any]] = None) -> str:
        from app.core.llm import call_llm_api  # lazy
        meta = meta or {}
        system_msg = (
            "Sen kıdemli bir SQL uzmanısın. Sadece SELECT/WITH sorguları üret. "
            "DML/DDL yazma. Cevabını ```sql ... ``` bloğu içinde döndür."
        )
        msgs = [{"role": "system", "content": system_msg}]
        # History (varsa)
        for h in (meta.get("history") or [])[-4:]:
            role = h.get("role") or "user"
            content = h.get("content") or ""
            if content:
                msgs.append({"role": role, "content": content[:2000]})
        msgs.append({"role": "user", "content": prompt})
        try:
            return call_llm_api(msgs, temperature=temperature) or ""
        except Exception as e:
            logger.error("[wiring.llm] hata: %s", e)
            raise

    return _call


# ---------------------------------------------------------------------------
# Execute callable
# ---------------------------------------------------------------------------

def _load_source_dict(
    cursor, source_id: int, company_id: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    """
    data_sources tablosundan tek satır dict döner.

    Tenant izolasyonu: company_id verilirse WHERE company_id = %s zorlanır.
    Caller başka tenant'ın source_id'sini gönderirse None döner (None döndüğünde
    `_call` aşağıda RuntimeError ile pipeline'ı durdurur).
    """
    try:
        if company_id is not None:
            cursor.execute(
                "SELECT * FROM data_sources WHERE id = %s AND company_id = %s",
                (source_id, company_id),
            )
        else:
            cursor.execute("SELECT * FROM data_sources WHERE id = %s", (source_id,))
        row = cursor.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            return dict(row)
        # tuple ise sütun isimlerini al
        cols = [d[0] for d in cursor.description]
        return dict(zip(cols, row))
    except Exception as e:
        logger.warning("[wiring._load_source_dict] hata: %s", e)
        return None


def make_execute_callable(
    source_id: int,
    dialect: str = "postgresql",
    allowed_tables: Optional[List[str]] = None,
    timeout: Optional[int] = None,
    max_rows: Optional[int] = None,
    company_id: Optional[int] = None,
) -> Callable[[str], Dict[str, Any]]:
    """
    execute node için callable üretir. SafeSQLExecutor'u sarar.

    Returned imza: callable(sql) -> {rows, columns, row_count, elapsed_ms, truncated}

    company_id verilirse data_sources lookup tenant izolasyonu altında yapılır
    (cross-tenant source erişimini engeller).
    """
    from app.services.safe_sql_executor import SafeSQLExecutor
    from app.core.db import get_db_context

    # Source dict bir kez yüklenir — tenant izolasyonu altında.
    source_dict: Optional[Dict[str, Any]] = None
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            try:
                source_dict = _load_source_dict(cur, source_id, company_id=company_id)
            finally:
                cur.close()
    except Exception as e:
        logger.error("[wiring.execute] source yüklenemedi: %s", e)

    executor = SafeSQLExecutor(timeout=timeout, max_rows=max_rows)

    # Whitelist (opsiyonel)
    allow = allowed_tables
    if allow is None:
        try:
            allow = executor.get_allowed_tables(source_id) or None
        except Exception:
            allow = None

    def _call(sql: str) -> Dict[str, Any]:
        if source_dict is None:
            raise RuntimeError(f"data source bulunamadı: id={source_id}")
        res = executor.execute(sql, source=source_dict, dialect=dialect, allowed_tables=allow)
        if not res.success:
            raise RuntimeError(res.error or "execute failed")
        return {
            "rows": res.data,
            "columns": res.columns,
            "row_count": res.row_count,
            "elapsed_ms": int(res.elapsed_ms or 0),
            "truncated": bool(res.truncated),
        }

    return _call


# ---------------------------------------------------------------------------
# EXPLAIN callable (opsiyonel)
# ---------------------------------------------------------------------------

def make_explain_callable(
    source_id: int, dialect: str = "postgresql", company_id: Optional[int] = None,
) -> Callable[[str], Any]:
    """
    validate node için EXPLAIN callable. SQL'i hedefte EXPLAIN ile döndürür.

    PG: EXPLAIN (FORMAT JSON) ...
    Oracle: EXPLAIN PLAN FOR ... + SELECT cardinality FROM PLAN_TABLE
            (SafeSQLExecutor.explain_plan, v3.32.0 Ajan-F)
    MSSQL: SET SHOWPLAN_XML ON → query → SET SHOWPLAN_XML OFF; XML parse
            (SafeSQLExecutor.explain_plan, v3.32.0 Ajan-F)
    MySQL: EXPLAIN FORMAT=JSON ...

    Hata fırlatırsa validate node 'explain: ...' error'ı ekler.
    """
    from app.services.safe_sql_executor import SafeSQLExecutor
    from app.core.db import get_db_context

    source_dict: Optional[Dict[str, Any]] = None
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            try:
                source_dict = _load_source_dict(cur, source_id, company_id=company_id)
            finally:
                cur.close()
    except Exception:
        pass

    executor = SafeSQLExecutor(timeout=5, max_rows=100)

    def _explain(sql: str) -> Any:
        if source_dict is None:
            return None
        d = dialect.lower()
        if d in ("postgresql", "postgres", "pg"):
            explain_sql = f"EXPLAIN (FORMAT JSON) {sql.rstrip(';')}"
        elif d == "mysql":
            explain_sql = f"EXPLAIN FORMAT=JSON {sql.rstrip(';')}"
        elif d in ("mssql", "sqlserver", "oracle"):
            # v3.32.0 Ajan-F: SafeSQLExecutor.explain_plan dialect-aware
            # EXPLAIN yürütür (MSSQL=SHOWPLAN_XML, Oracle=EXPLAIN PLAN +
            # plan_table). Plan satır tahminini predictor'a
            # ``{"rows": N}`` formatında verir; predictor zaten bu anahtarı tanır.
            try:
                plan = executor.explain_plan(sql, dialect=d, source=source_dict)
            except Exception as e:
                logger.debug("[wiring.explain] %s err: %s", d, e)
                return None
            if not isinstance(plan, dict):
                return None
            rows = plan.get("estimated_rows")
            if rows is None:
                # Plan alınamadıysa predictor reltuples yoluna düşer
                logger.debug(
                    "[wiring.explain] %s estimate yok (err=%s)",
                    d, plan.get("error"),
                )
                return None
            return {"rows": int(rows)}
        else:
            return None
        try:
            res = executor.execute(explain_sql, source=source_dict, dialect=dialect)
            if res.success and res.data:
                # PG: data[0] = {"QUERY PLAN": [...]} olabilir
                first = res.data[0]
                if isinstance(first, dict):
                    for k, v in first.items():
                        if isinstance(v, (list, dict)):
                            if isinstance(v, list) and v and isinstance(v[0], dict):
                                return v[0]
                            return v
                return first
            return None
        except Exception as e:
            logger.debug("[wiring.explain] %s", e)
            return None

    return _explain


# ---------------------------------------------------------------------------
# Convenience: full inject
# ---------------------------------------------------------------------------

def inject_callables(
    state: Dict[str, Any], *, llm: bool = True, execute: bool = True, explain: bool = False
) -> Dict[str, Any]:
    """
    State'e callable'ları enjekte eder. Endpoint katmanından çağrılır.

    Kullanım:
        from app.services.pipeline.wiring import inject_callables
        inject_callables(state)
        run_pipeline(state, mode='auto')
    """
    source_id = state.get("source_id")
    company_id = state.get("company_id")
    dialect = state.get("db_dialect", "postgresql")
    if llm and "_llm_callable" not in state:
        state["_llm_callable"] = make_llm_callable()
    if execute and "_execute_callable" not in state and source_id:
        # company_id state'ten alınıp factory'ye geçirilir — cross-tenant
        # source_id leak'ini engeller (K7).
        state["_execute_callable"] = make_execute_callable(
            source_id, dialect=dialect, company_id=company_id,
        )
    if explain and "_explain_callable" not in state and source_id:
        state["_explain_callable"] = make_explain_callable(
            source_id, dialect=dialect, company_id=company_id,
        )
    return state
