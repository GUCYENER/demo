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
import threading
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# L1 cache (Redis-backed, graceful fallback)
# ─────────────────────────────────────────────────────────────
# Pattern: app/services/db_learning/result_cache.py — thread-safe lazy
# singleton + JSON-only serialization (pickle yok → RCE risk azaltma).
# Redis yoksa in-memory fallback (RedisCache içinde zaten var).
# Test'lerde patch için `app.services.db_smart.session_manager._SESSION_CACHE`
# attribute'una set/None yapılabilir.

_SESSION_CACHE = None
_SESSION_CACHE_LOCK = threading.Lock()
_SESSION_CACHE_INIT_FAILED = False
_SESSION_CACHE_TTL = 1800  # 30dk
_CACHE_KEY_PREFIX = "vyra:dbsmart:sess:"


def _get_session_cache():
    """Lazy singleton accessor — Redis yoksa veya init başarısızsa None döner."""
    global _SESSION_CACHE, _SESSION_CACHE_INIT_FAILED
    if _SESSION_CACHE is not None:
        return _SESSION_CACHE
    if _SESSION_CACHE_INIT_FAILED:
        return None
    with _SESSION_CACHE_LOCK:
        if _SESSION_CACHE is not None:
            return _SESSION_CACHE
        if _SESSION_CACHE_INIT_FAILED:
            return None
        try:
            from app.core.config import settings
            from app.core.redis_cache import RedisCache
            url = getattr(settings, "REDIS_URL", "redis://localhost:6379/1")
            _SESSION_CACHE = RedisCache(
                redis_url=url,
                default_ttl=_SESSION_CACHE_TTL,
                key_prefix=_CACHE_KEY_PREFIX,
            )
        except Exception as e:
            logger.info("[db_smart.session] L1 cache init skipped: %s", e)
            _SESSION_CACHE_INIT_FAILED = True
            _SESSION_CACHE = None
    return _SESSION_CACHE


def _cache_key(session_uid: str) -> str:
    """RedisCache zaten key_prefix uyguluyor → burada sade uid yeter."""
    return session_uid


def _cache_get(session_uid: str) -> Optional[Dict[str, Any]]:
    cache = _get_session_cache()
    if cache is None:
        return None
    try:
        raw = cache.get_raw(_cache_key(session_uid))
        if not raw:
            return None
        data = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.debug("[db_smart.session] cache_get failed uid=%s: %s", session_uid, e)
        return None


def _cache_set(session_uid: str, payload: Dict[str, Any]) -> None:
    cache = _get_session_cache()
    if cache is None:
        return
    try:
        cache.set_raw(
            _cache_key(session_uid),
            json.dumps(payload, default=str).encode("utf-8"),
            ttl=_SESSION_CACHE_TTL,
        )
    except Exception as e:
        logger.debug("[db_smart.session] cache_set failed uid=%s: %s", session_uid, e)


def _cache_delete(session_uid: str) -> None:
    cache = _get_session_cache()
    if cache is None:
        return
    try:
        cache.delete(_cache_key(session_uid))
    except Exception as e:
        logger.debug("[db_smart.session] cache_delete failed uid=%s: %s", session_uid, e)


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
    # ARES YÜKSEK fix: cache warm-up burada YAPILMAZ. Caller'ın transaction'ı
    # rollback ederse cache phantom oturum tutar → sonraki load'lar stale/leaked
    # state döner. Caller, conn.commit() başarılı olduktan sonra opsiyonel
    # `cache_warm_created(...)` çağırabilir; aksi halde ilk load_session DB'den
    # okuyup cache'i taze payload ile kendisi warm-up eder (idempotent).
    return session_uid


def cache_warm_created(
    session_uid: str,
    user_ctx: Dict[str, Any],
    source_id: Optional[int] = None,
    initial_context: Optional[Dict[str, Any]] = None,
    current_step: int = 0,
    status: str = "active",
) -> None:
    """create_session sonrası COMMIT BAŞARILI olunca caller'ın elle çağırması
    için warm-up helper. Hata durumunda sessiz no-op (cache opsiyonel).

    Args:
        session_uid: create_session'ın döndürdüğü uid.
        user_ctx: create_session'a verilen user_ctx (id + company_id zorunlu).
        source_id: opsiyonel.
        initial_context: opsiyonel başlangıç context.
        current_step / status: warm-up payload default'ları.
    """
    user_id = user_ctx.get("id") if user_ctx else None
    company_id = user_ctx.get("company_id") if user_ctx else None
    if user_id is None or company_id is None:
        return
    try:
        _cache_set(session_uid, {
            "session_uid": session_uid,
            "user_id": int(user_id),
            "company_id": int(company_id),
            "current_step": current_step,
            "status": status,
            "source_id": source_id,
            "context": initial_context or {},
            "dialect": None,
            "generated_sql": None,
            "created_at": None,
            "last_activity_at": None,
            "completed_at": None,
        })
    except Exception as e:
        logger.debug("[db_smart.session] cache_warm_created skipped uid=%s: %s",
                     session_uid, e)


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
    # L1 cache hit → DB hit'sız dön. ARES guard: payload'taki user_id/company_id
    # caller user_ctx ile birebir eşleşmeli, aksi halde cross-tenant leak.
    # Eşleşmezse cache miss gibi davranıp DB'ye (RLS-bound) git.
    #
    # ARES KRİTİK fix: admin için de aynı company_id eşleşmesi şarttır.
    # `is_admin=True` cross-tenant cache hit'ini açmak, admin'in kendi tenant
    # context'i dışındaki bir oturumu side-effect olarak okumasına yol açar
    # (apply_vyra_user_context admin'in OWN company_id'sini set eder; cache
    # path bunu bypass etmemeli). Cross-tenant erişim açık ayrı admin API ile
    # yapılmalı, is_admin flag'inin yan etkisi olarak değil.
    cached = _cache_get(session_uid)
    if cached is not None:
        c_user = cached.get("user_id")
        c_company = cached.get("company_id")
        req_user = user_ctx.get("id") if user_ctx else None
        req_company = user_ctx.get("company_id") if user_ctx else None
        if (
            c_user is not None and c_company is not None
            and req_user is not None and req_company is not None
            and int(c_user) == int(req_user) and int(c_company) == int(req_company)
        ):
            # Caller payload'tan user_id/company_id alanlarını görmemeli.
            out = {k: v for k, v in cached.items() if k not in ("user_id", "company_id")}
            return out
        logger.warning(
            "[db_smart.session] cache cross-tenant mismatch uid=%s — falling back to DB",
            session_uid,
        )
    try:
        cur.execute(
            """
            SELECT session_uid::text, current_step, status, source_id,
                   context, dialect, generated_sql,
                   created_at, last_activity_at, completed_at,
                   user_id, company_id
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
    # F16b (ARES+POSEIDON): RealDictCursor uyumu — row dict olarak gelebilir.
    # Önceki int-index erişimi `row[4]` RealDictCursor altında KeyError: 4 üretti
    # (save-report 500 root cause). Tek noktada normalize → dict tabanlı erişim.
    if isinstance(row, dict):
        _ru = row.get
        r0 = _ru("session_uid"); r1 = _ru("current_step"); r2 = _ru("status")
        r3 = _ru("source_id"); r4 = _ru("context"); r5 = _ru("dialect")
        r6 = _ru("generated_sql"); r7 = _ru("created_at")
        r8 = _ru("last_activity_at"); r9 = _ru("completed_at")
        r10 = _ru("user_id"); r11 = _ru("company_id")
    else:
        r0 = row[0]; r1 = row[1]; r2 = row[2]; r3 = row[3]; r4 = row[4]
        r5 = row[5]; r6 = row[6]; r7 = row[7]; r8 = row[8]; r9 = row[9]
        r10 = row[10] if len(row) > 10 else None
        r11 = row[11] if len(row) > 11 else None
    # context: psycopg2 jsonb → dict; string ise normalize et.
    ctx = r4
    if isinstance(ctx, str):
        try:
            ctx = json.loads(ctx)
        except Exception:
            ctx = {}
    out = {
        "session_uid": r0,
        "current_step": int(r1) if r1 is not None else 0,
        "status": r2,
        "source_id": r3,
        "context": ctx or {},
        "dialect": r5,
        "generated_sql": r6,
        "created_at": r7.isoformat() if r7 else None,
        "last_activity_at": r8.isoformat() if r8 else None,
        "completed_at": r9.isoformat() if r9 else None,
    }
    # Cache'e (user_id/company_id ile) yaz — ARES guard'ı için.
    try:
        row_user_id = r10
        row_company_id = r11
        if row_user_id is not None and row_company_id is not None:
            payload = dict(out)
            payload["user_id"] = int(row_user_id)
            payload["company_id"] = int(row_company_id)
            _cache_set(session_uid, payload)
    except Exception as e:
        logger.debug("[db_smart.session] post-load cache_set skipped: %s", e)
    return out


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
    ok = affected is not None and affected > 0
    if ok:
        # Cache invalidate — bir sonraki load_session DB'den okuyup taze payload yazar.
        _cache_delete(session_uid)
    return ok


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
    ok = (cur.rowcount or 0) > 0
    if ok:
        _cache_delete(session_uid)
    return ok


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
    ok = (cur.rowcount or 0) > 0
    if ok:
        _cache_delete(session_uid)
    return ok
