"""
VYRA Query State API — v3.28.3 G4
==================================
Pre-execute Drag-Drop Query Builder backend.

POST /api/query-state/preview
    Drag-drop UI state'inden parametrize SELECT SQL üretir.
    Sample data fetch ETMEZ — sadece sanity SQL döndürür.
    Kullanıcı SQL'i editöre kopyalayıp execute edebilir.

Body örneği:
    {
        "source_id": 5,                 # opsiyonel; dialect inference için
        "schema": "public",
        "table": "orders",
        "dialect": "postgresql",        # opsiyonel; source_id verilirse override
        "selected_columns": ["id", "total"],
        "filters": [{"column": "status", "op": "=", "value": "PAID"}],
        "order_by": {"column": "created_at", "direction": "DESC"},
        "limit": 50
    }
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.routes.auth import get_current_user
from app.core.db import apply_company_scope, get_db_context
from app.services.pipeline.nodes.query_state_builder import build_sql_from_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/query-state", tags=["query_state"])


class FilterClause(BaseModel):
    column: str = Field(..., max_length=63)
    op: str = Field(..., max_length=20)
    value: Optional[Any] = None


class OrderByClause(BaseModel):
    column: str = Field(..., max_length=63)
    direction: str = Field("ASC", pattern=r"^(?i)(ASC|DESC)$")


class QueryStateRequest(BaseModel):
    # `schema` BaseModel'de reserved — alias ile JSON anahtarını koruyup field adını schema_name yapıyoruz
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())

    source_id: Optional[int] = Field(None, ge=1)
    schema_name: Optional[str] = Field(None, alias="schema", max_length=63)
    table: str = Field(..., min_length=1, max_length=63)
    dialect: Optional[str] = Field(None, pattern=r"^(postgresql|mssql|mysql|oracle)$")
    selected_columns: List[str] = Field(default_factory=list)
    filters: List[FilterClause] = Field(default_factory=list)
    order_by: Optional[OrderByClause] = None
    limit: Optional[int] = Field(None, ge=1, le=10000)
    # v3.32.0: True ise preview SQL'i SafeSQLExecutor üzerinden 5s timeout,
    # 100 satır cap ile yürütüp sonucu da döndürür. Tek-tablo whitelist + DDL ban
    # SafeSQLExecutor tarafında zaten enforce edilir.
    execute: bool = False


def _inline_literal(value: Any, dialect: str) -> Optional[str]:
    """Param değerini dialect-aware güvenli literal'a çevirir.

    Güvenlik diskaline alınan tipler için ``None`` döner — caller execute'tan
    vazgeçer. Whitelist mantığı (kabul edilen tip + escape):
      - None         → NULL
      - bool         → TRUE/FALSE (PG/Oracle) veya 1/0 (MSSQL/MySQL)
      - int/float    → ``str(value)`` (NaN/inf reddedilir)
      - str          → single-quote double escape ('it''s')
      - list/tuple   → ``(v1, v2, ...)`` (IN clause için)

    SafeSQLExecutor params kabul etmediği için bu helper kullanılarak SQL inline
    embed edilir. SQL injection vektörü str içerikleridir; double-quote escape
    PG/Oracle/MSSQL/MySQL standard SQL davranışıdır (MySQL NO_BACKSLASH_ESCAPES
    sql_mode varsayımı — VYRA kontrolündeki source'larda set edilir).
    """
    import math

    if value is None:
        return "NULL"

    if isinstance(value, bool):
        if dialect in ("postgresql", "oracle"):
            return "TRUE" if value else "FALSE"
        return "1" if value else "0"

    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return str(value)

    if isinstance(value, str):
        # Standard SQL: tek tırnak içinde tek tırnağı '' olarak escape et.
        # Null byte, control char varsa reddet (DB driver'da hata yapabilir + güvenlik).
        if "\x00" in value:
            return None
        escaped = value.replace("'", "''")
        # v3.32.0 H1 fix: MySQL'de default sql_mode NO_BACKSLASH_ESCAPES SET DEĞİL
        # → backslash hâlâ escape karakteri sayılır ve `O\'Brien` payload'u
        # `'O\''Brien'` olarak inline edildiğinde \' aktif kalır, kapanış tırnağı
        # kaçar → SQL injection. MySQL için backslash'ı ön escape yap.
        if dialect == "mysql":
            escaped = escaped.replace("\\", "\\\\")
            return f"'{escaped}'"
        if dialect == "mssql":
            return f"N'{escaped}'"
        return f"'{escaped}'"

    # bytes / bytearray / memoryview → execute reddet (cast belirsiz, BLOB risk).
    if isinstance(value, (bytes, bytearray, memoryview)):
        return None

    if isinstance(value, (list, tuple)):
        if not value:
            return "(NULL)"
        parts = []
        for v in value:
            inlined = _inline_literal(v, dialect)
            if inlined is None:
                return None
            parts.append(inlined)
        return "(" + ", ".join(parts) + ")"

    # date/datetime/Decimal vs. — ISO string formatına çevirip quotelu döndür.
    try:
        s = str(value).replace("'", "''")
        return f"'{s}'"
    except Exception:
        return None


def _inline_params_into_sql(sql: str, params: List[Any], dialect: str) -> Optional[str]:
    """`%s` placeholder'larını sırayla _inline_literal sonuçlarıyla değiştirir.

    Placeholder sayısı != params sayısı veya herhangi bir param güvensiz tipte
    ise ``None`` döner (execute reddedilir). pyformat (`%(name)s`) desteklenmez —
    build_sql_from_state sadece positional `%s` üretir.
    """
    if not sql:
        return None
    if "%s" not in sql:
        # Placeholder yok — param da olmamalı
        return sql if not params else None
    if sql.count("%s") != len(params):
        return None
    out_parts: List[str] = []
    idx = 0
    i = 0
    while i < len(sql):
        if sql[i:i + 2] == "%s":
            literal = _inline_literal(params[idx], dialect)
            if literal is None:
                return None
            out_parts.append(literal)
            idx += 1
            i += 2
        else:
            out_parts.append(sql[i])
            i += 1
    return "".join(out_parts)


def _resolve_source_info(source_id: int, company_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """data_sources tablosundan SafeSQLExecutor.execute() için gereken
    connection dict'i çeker. company_id RLS scope'u uygulanır → cross-tenant
    IDOR engellenir. company_id None ise hiçbir kayıt dönmemeli (defensive).
    """
    if not company_id:
        # Tenant scope yoksa source connection'a erişim verilmez.
        return None
    try:
        with get_db_context() as conn:
            with conn.cursor() as cur:
                # RLS GUC'u set et — data_sources tablosu company_id policy'sine sahipse
                # bu satır cross-tenant satır leak'ini engeller.
                apply_company_scope(cur, company_id=company_id)
                cur.execute(
                    """
                    SELECT id, db_type, db_host, db_port, db_name,
                           db_username, db_password_encrypted, schema_name,
                           company_id
                    FROM data_sources
                    WHERE id = %s AND company_id = %s
                    """,
                    (source_id, company_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
    except Exception as e:
        logger.warning("[query_state] source lookup failed for %s: %s", source_id, e)
        return None


def _resolve_dialect(source_id: Optional[int], requested: Optional[str]) -> str:
    """source_id verilirse DB'den db_type oku — yoksa requested ya da postgresql."""
    if source_id:
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT db_type FROM data_sources WHERE id = %s", (source_id,))
                    row = cur.fetchone()
                    if row and row[0]:
                        return str(row[0]).lower()
        except Exception as e:
            logger.warning("[query_state] dialect lookup failed for source %s: %s", source_id, e)
    return (requested or "postgresql").lower()


@router.post("/preview")
def preview_query_state(
    req: QueryStateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Query state → SQL preview.

    Sample data fetch ETMEZ — yalnızca parametrize SELECT SQL döner.
    Frontend bu SQL'i editöre yapıştırır veya execute path'ine yönlendirir.
    """
    dialect = _resolve_dialect(req.source_id, req.dialect)

    state: Dict[str, Any] = {
        "schema": req.schema_name,
        "table": req.table,
        "dialect": dialect,
        "selected_columns": list(req.selected_columns or []),
        "filters": [f.model_dump() for f in (req.filters or [])],
        "order_by": req.order_by.model_dump() if req.order_by else None,
        "limit": req.limit,
    }

    try:
        result = build_sql_from_state(state)
    except Exception as e:
        logger.exception("[query_state] build failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Sorgu inşa hatası: {e}")

    if not result.get("valid"):
        # 400: kullanıcının düzeltebileceği warnings döner
        return {
            "valid": False,
            "sql": None,
            "params": [],
            "dialect": dialect,
            "warnings": result.get("warnings", []),
        }

    response: Dict[str, Any] = {
        "valid": True,
        "sql": result["sql"],
        "params": result.get("params", []),
        "dialect": dialect,
        "warnings": list(result.get("warnings", [])),
        "executed": False,
    }

    # v3.32.0: Opsiyonel sample execute — SafeSQLExecutor 5s timeout, 100 satır cap
    if req.execute and req.source_id:
        # Tenant scope: current_user.company_id ile data_sources'tan çekiyoruz.
        # Tenant mismatch veya kayıt yok → 404 değil 403 benzeri generic mesaj
        # (information leak'i azaltır).
        source = _resolve_source_info(
            int(req.source_id),
            company_id=current_user.get("company_id"),
        )
        if not source:
            response["executed"] = True
            response["success"] = False
            response["execute_error"] = "Veri kaynağına erişim yok veya bulunamadı"
            return response

        inlined_sql = _inline_params_into_sql(
            result["sql"], result.get("params") or [], dialect
        )
        if inlined_sql is None:
            response["executed"] = True
            response["success"] = False
            response["execute_error"] = (
                "Filtre değerleri güvenli embed edilemedi (tip kısıtı). "
                "SQL'i kopyalayıp dış araçta çalıştırabilirsiniz."
            )
            return response

        try:
            from app.services.safe_sql_executor import SafeSQLExecutor

            executor = SafeSQLExecutor(timeout=5, max_rows=100)
            # Whitelist: kullanıcının seçtiği tek tablo + opsiyonel schema-qualified isim
            allowed = [req.table]
            if req.schema_name:
                allowed.append(f"{req.schema_name}.{req.table}")
            sql_result = executor.execute(
                inlined_sql,
                source,
                dialect=dialect,
                allowed_tables=allowed,
                use_result_cache=False,
            )
            response["executed"] = True
            response["success"] = bool(sql_result.success)
            response["sql_inlined"] = inlined_sql
            response["columns"] = getattr(sql_result, "columns", []) or []
            response["rows"] = getattr(sql_result, "data", None) or getattr(sql_result, "rows", []) or []
            response["row_count"] = getattr(sql_result, "row_count", 0) or 0
            response["elapsed_ms"] = getattr(sql_result, "elapsed_ms", 0) or 0
            response["truncated"] = bool(getattr(sql_result, "truncated", False))
            if not sql_result.success:
                response["execute_error"] = sql_result.error
        except Exception:
            # v3.32.0 L5 fix: driver error message schema/perm leak edebilir
            # (örn. "permission denied for table xyz"). Traceback log'a düşer
            # ama kullanıcıya generic mesaj döner.
            logger.exception("[query_state] execute failed")
            response["executed"] = True
            response["success"] = False
            response["execute_error"] = "Sorgu çalıştırılamadı (teknik detay log'da)."

    return response
