"""dbsmart_saved_reports CRUD + share token (v3.30.0 FAZ 3 P13 G3.3).

Sorumluluklar:
    - save(cur, user_ctx, *, name, wizard_state, ...): INSERT + RETURNING id, created_at
    - update(cur, report_id, user_ctx, *, **patch): UPDATE alanları (name, description,
      tags, wizard_state). RLS policy user_id'yi otomatik filtreliyor.
    - list_for_user(cur, user_ctx, *, limit, offset): paginated liste
    - get_by_id(cur, report_id, user_ctx): tek kayıt (RLS-bound)
    - create_share_token(cur, report_id, user_ctx, *, ttl_hours):
      secrets.token_urlsafe(32) ile opaque token + expires_at + is_shared=TRUE
    - get_by_share_token(cur, token): expiry check + is_shared=TRUE filtresi
    - revoke_share(cur, report_id, user_ctx)
    - mark_run(cur, report_id, user_ctx, *, snapshot): run_count++ + last_run_at NOW()

Tasarım notları:
    - Cursor caller'dan gelir; apply_vyra_user_context cursor üstüne set edilmiş
      olmalı (RLS policy user_id eşliyor — pol_dbsmart_saved_reports_isolation).
    - get_by_share_token PUBLIC endpoint'ten çağrılır → cursor RLS UYGULANMAMIŞ
      olabilir. Bu yüzden fonksiyon explicit `is_shared=TRUE AND
      share_expires_at > NOW()` filtreliyor; RLS bypass'a güvenmiyor.
      Caller endpoint kendi connection'ını apply_vyra_user_context'sız açar;
      caller report'un user_id/company_id'sini sonradan vyra context'e set
      edebilir (caller sorumluluğu).
    - Token urlsafe-base64 → 43 char (32 byte * 4/3). Migration 032 alan
      VARCHAR(64) → uyumlu.
    - is_shared=FALSE yapan revoke_share share_token NULL'a çekmez (audit
      için son token saklanır). Bypass için sadece is_shared bayrağı kullanılır.
"""
from __future__ import annotations

import json
import logging
import secrets
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_MAX_NAME_LEN = 200
_MAX_TAGS = 20
_MAX_LIMIT = 200


def _require_user_ctx(user_ctx: Dict[str, Any]) -> Tuple[int, int]:
    uid = user_ctx.get("id") if user_ctx else None
    cid = user_ctx.get("company_id") if user_ctx else None
    if uid is None or cid is None:
        raise ValueError("user_ctx eksik (id, company_id zorunlu)")
    return int(uid), int(cid)


def _normalize_tags(tags: Optional[List[str]]) -> Optional[List[str]]:
    if not tags:
        return None
    out: List[str] = []
    seen = set()
    for t in tags:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s or s in seen:
            continue
        out.append(s[:60])
        seen.add(s)
        if len(out) >= _MAX_TAGS:
            break
    return out or None


# ─────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────

def save(
    cur: Any,
    user_ctx: Dict[str, Any],
    *,
    name: str,
    wizard_state: Dict[str, Any],
    last_sql: Optional[str] = None,
    last_dialect: Optional[str] = None,
    source_id: Optional[int] = None,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """dbsmart_saved_reports INSERT. Dönüş: {id, created_at} | None (RLS reddi)."""
    user_id, company_id = _require_user_ctx(user_ctx)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name boş olamaz")
    name_clean = name.strip()[:_MAX_NAME_LEN]

    norm_tags = _normalize_tags(tags)
    state_json = json.dumps(wizard_state or {})

    try:
        cur.execute(
            """
            INSERT INTO dbsmart_saved_reports
                (user_id, company_id, source_id, name, description,
                 wizard_state, last_sql, last_dialect, tags)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                user_id, company_id, source_id, name_clean, description,
                state_json, last_sql, last_dialect, norm_tags,
            ),
        )
        row = cur.fetchone()
        if not row:
            logger.warning("[db_smart.sr] save INSERT RETURNING empty (RLS?)")
            return None
        rid = row[0] if not isinstance(row, dict) else row.get("id")
        created = row[1] if not isinstance(row, dict) else row.get("created_at")
        return {"id": int(rid), "created_at": created}
    except Exception as e:
        logger.warning("[db_smart.sr] save INSERT failed: %s", e)
        return None


def update(
    cur: Any,
    report_id: int,
    user_ctx: Dict[str, Any],
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    wizard_state: Optional[Dict[str, Any]] = None,
    last_sql: Optional[str] = None,
    last_dialect: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> bool:
    """Patch update. None alanlar dokunulmaz. RLS policy user_id eşliyor."""
    _require_user_ctx(user_ctx)
    fields: List[str] = []
    params: List[Any] = []
    if name is not None:
        n = name.strip()
        if not n:
            raise ValueError("name boş olamaz")
        fields.append("name = %s")
        params.append(n[:_MAX_NAME_LEN])
    if description is not None:
        fields.append("description = %s")
        params.append(description)
    if wizard_state is not None:
        fields.append("wizard_state = %s::jsonb")
        params.append(json.dumps(wizard_state))
    if last_sql is not None:
        fields.append("last_sql = %s")
        params.append(last_sql)
    if last_dialect is not None:
        fields.append("last_dialect = %s")
        params.append(last_dialect)
    if tags is not None:
        fields.append("tags = %s")
        params.append(_normalize_tags(tags))
    if not fields:
        return False
    fields.append("updated_at = NOW()")
    params.append(int(report_id))
    try:
        cur.execute(
            f"UPDATE dbsmart_saved_reports SET {', '.join(fields)} WHERE id = %s",
            tuple(params),
        )
        rowcount = getattr(cur, "rowcount", 0) or 0
        return rowcount > 0
    except Exception as e:
        logger.warning("[db_smart.sr] update %s failed: %s", report_id, e)
        return False


def list_for_user(
    cur: Any,
    user_ctx: Dict[str, Any],
    *,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """RLS policy izolasyonu (user_id eşliyor). Yeniden eskiye sıralı."""
    _require_user_ctx(user_ctx)
    n = max(1, min(int(limit or 50), _MAX_LIMIT))
    o = max(0, int(offset or 0))
    try:
        cur.execute(
            """
            SELECT id, name, description, source_id, last_dialect,
                   tags, run_count, last_run_at, is_shared,
                   created_at, updated_at
            FROM dbsmart_saved_reports
            ORDER BY updated_at DESC
            LIMIT %s OFFSET %s
            """,
            (n, o),
        )
        rows = cur.fetchall() or []
    except Exception as e:
        logger.warning("[db_smart.sr] list failed: %s", e)
        return []
    out: List[Dict[str, Any]] = []
    for r in rows:
        if isinstance(r, dict):
            out.append(dict(r))
            continue
        out.append({
            "id": r[0], "name": r[1], "description": r[2],
            "source_id": r[3], "last_dialect": r[4], "tags": list(r[5] or []),
            "run_count": r[6], "last_run_at": r[7], "is_shared": r[8],
            "created_at": r[9], "updated_at": r[10],
        })
    return out


def get_by_id(
    cur: Any, report_id: int, user_ctx: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """RLS-bound fetch. Dönüş wizard_state + last_sql dahil."""
    _require_user_ctx(user_ctx)
    try:
        cur.execute(
            """
            SELECT id, name, description, source_id, wizard_state,
                   last_sql, last_dialect, tags, run_count, last_run_at,
                   last_run_snapshot, is_shared, share_expires_at,
                   created_at, updated_at
            FROM dbsmart_saved_reports
            WHERE id = %s
            """,
            (int(report_id),),
        )
        r = cur.fetchone()
    except Exception as e:
        logger.warning("[db_smart.sr] get_by_id %s failed: %s", report_id, e)
        return None
    if not r:
        return None
    if isinstance(r, dict):
        return dict(r)
    return {
        "id": r[0], "name": r[1], "description": r[2], "source_id": r[3],
        "wizard_state": r[4], "last_sql": r[5], "last_dialect": r[6],
        "tags": list(r[7] or []), "run_count": r[8], "last_run_at": r[9],
        "last_run_snapshot": r[10], "is_shared": r[11], "share_expires_at": r[12],
        "created_at": r[13], "updated_at": r[14],
    }


# ─────────────────────────────────────────────────────────────
# Share token flow
# ─────────────────────────────────────────────────────────────

def _generate_token() -> str:
    """43-char URL-safe (32 byte rastgele) — migration 032 VARCHAR(64) uyumlu."""
    return secrets.token_urlsafe(32)


def create_share_token(
    cur: Any,
    report_id: int,
    user_ctx: Dict[str, Any],
    *,
    ttl_hours: int = 24,
) -> Optional[Dict[str, Any]]:
    """is_shared=TRUE + share_token + share_expires_at = NOW()+ttl. RLS-bound."""
    _require_user_ctx(user_ctx)
    if ttl_hours <= 0 or ttl_hours > 24 * 30:  # max 30 gün
        raise ValueError("ttl_hours 1..720 aralığında olmalı")

    token = _generate_token()
    try:
        cur.execute(
            """
            UPDATE dbsmart_saved_reports
            SET is_shared = TRUE,
                share_token = %s,
                share_expires_at = NOW() + (%s || ' hours')::interval,
                updated_at = NOW()
            WHERE id = %s
            RETURNING share_token, share_expires_at
            """,
            (token, str(int(ttl_hours)), int(report_id)),
        )
        row = cur.fetchone()
    except Exception as e:
        logger.warning("[db_smart.sr] create_share_token %s failed: %s", report_id, e)
        return None
    if not row:
        return None  # RLS reddi veya kayıt yok
    tok = row[0] if not isinstance(row, dict) else row.get("share_token")
    exp = row[1] if not isinstance(row, dict) else row.get("share_expires_at")
    return {"share_token": tok, "share_expires_at": exp, "ttl_hours": ttl_hours}


def revoke_share(
    cur: Any, report_id: int, user_ctx: Dict[str, Any],
) -> bool:
    """is_shared=FALSE; token kaydı audit için dokunulmaz."""
    _require_user_ctx(user_ctx)
    try:
        cur.execute(
            """
            UPDATE dbsmart_saved_reports
            SET is_shared = FALSE, updated_at = NOW()
            WHERE id = %s
            """,
            (int(report_id),),
        )
        return bool(getattr(cur, "rowcount", 0) or 0)
    except Exception as e:
        logger.warning("[db_smart.sr] revoke_share %s failed: %s", report_id, e)
        return False


def get_by_share_token(cur: Any, token: str) -> Optional[Dict[str, Any]]:
    """Public access. EXPLICIT is_shared=TRUE + expiry check (RLS bypass'a güvenme).

    Cursor RLS-set EDILMEDEN gelmiş olabilir; bu sorgu kendi izolasyonunu sağlar.
    Caller endpoint AUTH OLMAYAN bir route'tur — token-bound erişim.
    """
    if not isinstance(token, str) or not token:
        return None
    try:
        cur.execute(
            """
            SELECT id, user_id, company_id, name, description, source_id,
                   wizard_state, last_sql, last_dialect, tags,
                   last_run_snapshot, share_expires_at
            FROM dbsmart_saved_reports
            WHERE share_token = %s
              AND is_shared = TRUE
              AND share_expires_at IS NOT NULL
              AND share_expires_at > NOW()
            """,
            (token,),
        )
        r = cur.fetchone()
    except Exception as e:
        logger.warning("[db_smart.sr] get_by_share_token failed: %s", e)
        return None
    if not r:
        return None
    if isinstance(r, dict):
        return dict(r)
    return {
        "id": r[0], "user_id": r[1], "company_id": r[2], "name": r[3],
        "description": r[4], "source_id": r[5], "wizard_state": r[6],
        "last_sql": r[7], "last_dialect": r[8], "tags": list(r[9] or []),
        "last_run_snapshot": r[10], "share_expires_at": r[11],
    }


def mark_run(
    cur: Any,
    report_id: int,
    user_ctx: Dict[str, Any],
    *,
    snapshot: Optional[Dict[str, Any]] = None,
) -> bool:
    """run_count++ + last_run_at=NOW() + opsiyonel last_run_snapshot."""
    _require_user_ctx(user_ctx)
    try:
        if snapshot is None:
            cur.execute(
                """
                UPDATE dbsmart_saved_reports
                SET run_count = run_count + 1,
                    last_run_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (int(report_id),),
            )
        else:
            cur.execute(
                """
                UPDATE dbsmart_saved_reports
                SET run_count = run_count + 1,
                    last_run_at = NOW(),
                    last_run_snapshot = %s::jsonb,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (json.dumps(snapshot), int(report_id)),
            )
        return bool(getattr(cur, "rowcount", 0) or 0)
    except Exception as e:
        logger.warning("[db_smart.sr] mark_run %s failed: %s", report_id, e)
        return False
