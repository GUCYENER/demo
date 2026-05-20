"""dbsmart_sessions CRUD (v3.30.0 FAZ 1 P5 G1.7).

Sorumluluklar:
    - create_session(cur, user_ctx, source_id) → session_uid (UUID4)
    - load_session(cur, session_uid, user_ctx) → context dict | None
    - update_context(cur, session_uid, partial_state) — jsonb merge
    - mark_completed(cur, session_uid) — status='completed' + completed_at
    - mark_abandoned(cur, session_uid) — status='abandoned'

Tasarım notları:
    - Cursor caller'dan gelir (apply_vyra_user_context zaten set edilmiş).
      Bu sayede RLS policy `pol_dbsmart_sessions_isolation` otomatik filtre uygular.
    - SQL'de session_uid bind param ile, UPDATE'lerde RLS predicate'i policy'ye
      bırakıldı (USING (user_id = vyra.user_id OR is_admin)).
    - context JSONB merge için PostgreSQL `||` operatörü kullanılır (top-level
      key-replace). İç-içe path için update_context'e key path verilirse jsonb_set
      genişletilebilir; FAZ 1 için sığ merge yeterli.
    - Redis L1 cache (TTL 30dk): P6'ya ertelendi. Bu modül DB-only.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def create_session(
    cur: Any,
    user_ctx: Dict[str, Any],
    source_id: Optional[int] = None,
    initial_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Yeni wizard oturumu aç ve session_uid (UUID4) döndür.

    Args:
        cur: aktif psycopg2 cursor (apply_vyra_user_context set edilmiş).
        user_ctx: get_current_user dict (id, company_id, is_admin/role).
        source_id: opsiyonel başlangıç data_sources.id.
        initial_context: opsiyonel başlangıç JSONB içeriği.

    Returns:
        session_uid (UUID4 string).
    """
    session_uid = str(uuid.uuid4())
    user_id = user_ctx.get("id")
    company_id = user_ctx.get("company_id")
    if user_id is None or company_id is None:
        # RLS policy default-deny olsa da explicit hata istemcide daha net.
        raise ValueError("create_session: user_id ve company_id zorunlu")

    ctx_json = json.dumps(initial_context or {})
    cur.execute(
        """
        INSERT INTO dbsmart_sessions
            (session_uid, user_id, company_id, source_id, current_step, status, context)
        VALUES
            (%s::uuid, %s, %s, %s, 0, 'active', %s::jsonb)
        RETURNING session_uid
        """,
        (session_uid, int(user_id), int(company_id), source_id, ctx_json),
    )
    row = cur.fetchone()
    if not row:
        # INSERT RETURNING fail olduysa RLS policy reddetmiş demektir.
        raise RuntimeError("create_session: INSERT RETURNING boş döndü (RLS?)")
    logger.info(
        "[db_smart.session] created user=%s source=%s uid=%s",
        user_id, source_id, session_uid,
    )
    return session_uid


def load_session(
    cur: Any,
    session_uid: str,
    user_ctx: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Mevcut oturum context'ini DB'den getir. RLS politikası user/company izole.

    Args:
        cur: aktif psycopg2 cursor (apply_vyra_user_context set edilmiş).
        session_uid: UUID string.
        user_ctx: yetki bilgisi (loglama için; RLS zaten cursor'a uygulanmış).

    Returns:
        {
          "session_uid": str,
          "current_step": int,
          "status": str,
          "source_id": int | None,
          "context": dict,
          "dialect": str | None,
          "generated_sql": str | None,
          "created_at": iso,
          "last_activity_at": iso,
          "completed_at": iso | None,
        }
        None — oturum yok veya RLS reddetti.
    """
    try:
        cur.execute(
            """
            SELECT session_uid::text, current_step, status, source_id,
                   context, dialect, generated_sql,
                   created_at, last_activity_at, completed_at
            FROM dbsmart_sessions
            WHERE session_uid = %s::uuid
            """,
            (session_uid,),
        )
    except Exception as e:
        # invalid uuid format → 22023; RLS reddi normal None döner.
        logger.warning("[db_smart.session] load failed uid=%s: %s", session_uid, e)
        return None
    row = cur.fetchone()
    if not row:
        return None
    # context: psycopg2 jsonb → dict; string ise normalize et.
    ctx = row[4]
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except Exception:
            ctx = {}
    return {
        "session_uid": row[0],
        "current_step": int(row[1]) if row[1] is not None else 0,
        "status": row[2],
        "source_id": row[3],
        "context": ctx or {},
        "dialect": row[5],
        "generated_sql": row[6],
        "created_at": row[7].isoformat() if row[7] else None,
        "last_activity_at": row[8].isoformat() if row[8] else None,
        "completed_at": row[9].isoformat() if row[9] else None,
    }


def update_context(
    cur: Any,
    session_uid: str,
    partial: Dict[str, Any],
    user_ctx: Optional[Dict[str, Any]] = None,
    current_step: Optional[int] = None,
) -> bool:
    """context JSONB'yi top-level merge ile günceller + last_activity_at=NOW().

    Args:
        cur: aktif cursor (RLS set edilmiş).
        session_uid: UUID string.
        partial: top-level key/value (mevcut context'le shallow merge).
        user_ctx: yalnız log için.
        current_step: opsiyonel; verilirse current_step de güncellenir.

    Returns:
        True — bir satır güncellendi; False — eşleşmedi (yok/RLS).
    """
    if not partial and current_step is None:
        return False
    sets = ["last_activity_at = NOW()"]
    params: list = []
    if partial:
        # PG `||` operatörü shallow merge — sağdaki key'ler soldakileri override eder.
        sets.append("context = context || %s::jsonb")
        params.append(json.dumps(partial))
    if current_step is not None:
        sets.append("current_step = %s")
        params.append(int(current_step))
    params.append(session_uid)
    sql = (
        "UPDATE dbsmart_sessions SET "
        + ", ".join(sets)
        + " WHERE session_uid = %s::uuid"
    )
    try:
        cur.execute(sql, tuple(params))
    except Exception as e:
        logger.warning("[db_smart.session] update failed uid=%s: %s", session_uid, e)
        return False
    affected = cur.rowcount if hasattr(cur, "rowcount") else 0
    return affected is not None and affected > 0


def mark_completed(
    cur: Any,
    session_uid: str,
    generated_sql: Optional[str] = None,
    dialect: Optional[str] = None,
    user_ctx: Optional[Dict[str, Any]] = None,
) -> bool:
    """status='completed' + completed_at=NOW(). İsteğe bağlı SQL/dialect snapshot."""
    sets = [
        "status = 'completed'",
        "completed_at = NOW()",
        "last_activity_at = NOW()",
    ]
    params: list = []
    if generated_sql is not None:
        sets.append("generated_sql = %s")
        params.append(generated_sql)
    if dialect is not None:
        sets.append("dialect = %s")
        params.append(dialect)
    params.append(session_uid)
    sql = (
        "UPDATE dbsmart_sessions SET "
        + ", ".join(sets)
        + " WHERE session_uid = %s::uuid AND status = 'active'"
    )
    try:
        cur.execute(sql, tuple(params))
    except Exception as e:
        logger.warning("[db_smart.session] mark_completed failed uid=%s: %s", session_uid, e)
        return False
    return (cur.rowcount or 0) > 0


def mark_abandoned(
    cur: Any,
    session_uid: str,
    user_ctx: Optional[Dict[str, Any]] = None,
) -> bool:
    """status='abandoned' — kullanıcı çıkış / TTL doldu."""
    try:
        cur.execute(
            """
            UPDATE dbsmart_sessions
            SET status = 'abandoned', last_activity_at = NOW()
            WHERE session_uid = %s::uuid AND status = 'active'
            """,
            (session_uid,),
        )
    except Exception as e:
        logger.warning("[db_smart.session] mark_abandoned failed uid=%s: %s", session_uid, e)
        return False
    return (cur.rowcount or 0) > 0
