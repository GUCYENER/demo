"""
VYRA - SQL Audit Log Service
==============================
SQL sorgularının loglanması ve admin izleme servisi.

Her çalıştırılan SQL sorgusu (başarılı/başarısız) loglanır:
- Kullanıcı ID
- Kaynak ID ve adı
- SQL metni
- Dialect
- Durum (success/error/security_rejected/timeout)
- Satır sayısı
- Yürütme süresi

Version: 2.58.0
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional

from app.services.logging_service import log_warning

logger = logging.getLogger(__name__)


# =====================================================
# SQL Audit Log Kaydı
# =====================================================

def log_sql_execution(
    user_id: int,
    source_id: int,
    source_name: str,
    sql_text: str,
    dialect: str,
    status: str,
    row_count: int = 0,
    elapsed_ms: float = 0.0,
    error_msg: Optional[str] = None,
    generation_method: str = "template",
    company_id: Optional[int] = None,
) -> None:
    """
    SQL yürütme olayını audit log'a kaydeder.

    Args:
        user_id: Kullanıcı ID
        source_id: Veri kaynağı ID
        source_name: Veri kaynağı adı
        sql_text: Çalıştırılan SQL
        dialect: DB dialect (postgresql, mssql, ...)
        status: Durum (success, error, security_rejected, timeout)
        row_count: Döndürülen satır sayısı
        elapsed_ms: Yürütme süresi (ms)
        error_msg: Hata mesajı (varsa)
        generation_method: SQL üretim yöntemi (template, llm, manual)
        company_id: Firma ID (multi-tenant)
    """
    try:
        from app.core.db import get_db_conn

        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            INSERT INTO sql_audit_log
            (user_id, company_id, source_id, source_name, sql_text, dialect,
             status, row_count, elapsed_ms, error_msg, generation_method)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id, company_id, source_id, source_name,
            sql_text[:2000],  # Max 2000 char SQL
            dialect, status, row_count,
            round(elapsed_ms, 2),
            (error_msg[:500] if error_msg else None),
            generation_method,
        ))

        conn.commit()
        conn.close()

    except Exception as e:
        # Audit log hatası ana akışı engellememeli
        log_warning(f"SQL audit log kayıt hatası: {e}", "hybrid_router")


# =====================================================
# SQL Audit Log Sorgulama
# =====================================================

def get_sql_audit_logs(
    page: int = 1,
    per_page: int = 20,
    status_filter: Optional[str] = None,
    source_id_filter: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Sayfalı SQL audit log listesi döndürür.

    Args:
        page: Sayfa numarası (1'den başlar)
        per_page: Sayfa başına kayıt sayısı
        status_filter: Durum filtresi (success, error, ...)
        source_id_filter: Kaynak ID filtresi

    Returns:
        {
            "logs": [...],
            "total": 123,
            "page": 1,
            "per_page": 20,
            "pages": 7
        }
    """
    try:
        from app.core.db import get_db_conn

        conn = get_db_conn()
        cur = conn.cursor()

        # Filtre koşulları
        where_parts = []
        params = []

        if status_filter:
            where_parts.append("status = %s")
            params.append(status_filter)

        if source_id_filter:
            where_parts.append("source_id = %s")
            params.append(source_id_filter)

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # Toplam kayıt sayısı
        cur.execute(f"SELECT COUNT(*) AS total FROM sql_audit_log {where_clause}", params)
        total = cur.fetchone()["total"]

        # Sayfalı veri
        offset = (page - 1) * per_page
        cur.execute(f"""
            SELECT id, user_id, company_id, source_id, source_name, sql_text, dialect,
                   status, row_count, elapsed_ms, error_msg, generation_method,
                   created_at
            FROM sql_audit_log
            {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [per_page, offset])

        logs = []
        for row in cur.fetchall():
            logs.append({
                "id": row["id"],
                "user_id": row["user_id"],
                "company_id": row["company_id"],
                "source_id": row["source_id"],
                "source_name": row["source_name"],
                "sql_text": row["sql_text"],
                "dialect": row["dialect"],
                "status": row["status"],
                "row_count": row["row_count"],
                "elapsed_ms": row["elapsed_ms"],
                "error_msg": row["error_msg"],
                "generation_method": row["generation_method"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            })

        conn.close()

        pages = (total + per_page - 1) // per_page if per_page > 0 else 1

        return {
            "logs": logs,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": pages,
        }

    except Exception as e:
        log_warning(f"SQL audit log sorgulama hatası: {e}", "hybrid_router")
        return {"logs": [], "total": 0, "page": page, "per_page": per_page, "pages": 0}


def get_sql_audit_stats() -> Dict[str, Any]:
    """
    SQL audit özet istatistikleri döndürür.

    Returns:
        {
            "total_queries": 120,
            "success_count": 100,
            "error_count": 15,
            "security_rejected_count": 5,
            "avg_elapsed_ms": 45.2,
            "template_count": 80,
            "llm_count": 40,
        }
    """
    try:
        from app.core.db import get_db_conn

        conn = get_db_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT 
                COUNT(*) AS total_queries,
                COUNT(*) FILTER (WHERE status = 'success') AS success_count,
                COUNT(*) FILTER (WHERE status = 'error') AS error_count,
                COUNT(*) FILTER (WHERE status = 'security_rejected') AS security_rejected_count,
                COUNT(*) FILTER (WHERE status = 'timeout') AS timeout_count,
                ROUND(AVG(elapsed_ms)::numeric, 2) AS avg_elapsed_ms,
                COUNT(*) FILTER (WHERE generation_method = 'template') AS template_count,
                COUNT(*) FILTER (WHERE generation_method = 'llm') AS llm_count
            FROM sql_audit_log
        """)

        row = cur.fetchone()
        conn.close()

        return {
            "total_queries": row["total_queries"] or 0,
            "success_count": row["success_count"] or 0,
            "error_count": row["error_count"] or 0,
            "security_rejected_count": row["security_rejected_count"] or 0,
            "timeout_count": row["timeout_count"] or 0,
            "avg_elapsed_ms": float(row["avg_elapsed_ms"] or 0),
            "template_count": row["template_count"] or 0,
            "llm_count": row["llm_count"] or 0,
        }

    except Exception as e:
        log_warning(f"SQL audit stats hatası: {e}", "hybrid_router")
        return {
            "total_queries": 0, "success_count": 0, "error_count": 0,
            "security_rejected_count": 0, "timeout_count": 0,
            "avg_elapsed_ms": 0, "template_count": 0, "llm_count": 0,
        }
