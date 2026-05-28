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

# P0-1 defense-in-depth: update() SET clause yalnız bu whitelist'ten kolon
# adı kabul eder. Liste dışı her şey sessizce düşürülür; f-string sadece
# hardcoded üye için kullanılır → SQL injection yüzeyi kapalı.
_UPDATE_COLS_WHITELIST: Dict[str, str] = {
    "name": "name = %s",
    "description": "description = %s",
    "wizard_state": "wizard_state = %s::jsonb",
    "last_sql": "last_sql = %s",
    "last_dialect": "last_dialect = %s",
    "tags": "tags = %s",
}


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
    # default=str → datetime/Decimal/UUID gibi non-JSON tipler için güvenli fallback
    state_json = json.dumps(wizard_state or {}, default=str)

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
        # F16 (HEBE+ARES+POSEIDON): logger.exception → full traceback.
        # Önceki logger.warning(%s, e) sadece "TypeError: ..." stringi yazıyordu,
        # 500 diagnostiği için psycopg/RLS hata zinciri görünmüyordu.
        logger.exception("[db_smart.sr] save INSERT failed: %s", e)
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
    """Patch update. None alanlar dokunulmaz. RLS policy user_id eşliyor.

    SQL injection defense-in-depth (P0-1): SET clause parçaları yalnız
    `_UPDATE_COLS_WHITELIST` üyelerinden seçilir; değerler her zaman %s
    placeholder ile bind edilir. `updated_at = NOW()` statik literal.
    """
    _require_user_ctx(user_ctx)

    # (col_key, value) çiftleri — None olanlar zaten dışarıda.
    candidate_updates: List[Tuple[str, Any]] = []
    if name is not None:
        n = name.strip()
        if not n:
            raise ValueError("name boş olamaz")
        candidate_updates.append(("name", n[:_MAX_NAME_LEN]))
    if description is not None:
        candidate_updates.append(("description", description))
    if wizard_state is not None:
        candidate_updates.append(
            ("wizard_state", json.dumps(wizard_state, default=str))
        )
    if last_sql is not None:
        candidate_updates.append(("last_sql", last_sql))
    if last_dialect is not None:
        candidate_updates.append(("last_dialect", last_dialect))
    if tags is not None:
        candidate_updates.append(("tags", _normalize_tags(tags)))

    set_parts: List[str] = []
    params: List[Any] = []
    for col, val in candidate_updates:
        clause = _UPDATE_COLS_WHITELIST.get(col)
        if clause is None:
            # Whitelist dışı — sessizce düşür (defense-in-depth).
            continue
        set_parts.append(clause)
        params.append(val)

    if not set_parts:
        return False

    # Statik literal — kullanıcı girdisi yok.
    set_parts.append("updated_at = NOW()")
    params.append(int(report_id))

    # SET fragmanları yalnız hardcoded whitelist string'lerinden oluşur,
    # dolayısıyla join() sonucu SQL injection açısından güvenlidir.
    sql = (
        "UPDATE dbsmart_saved_reports SET "
        + ", ".join(set_parts)
        + " WHERE id = %s"
    )
    try:
        cur.execute(sql, tuple(params))
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
    name_exact: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """RLS policy izolasyonu (user_id eşliyor). Yeniden eskiye sıralı.

    v3.37.3 (bulgular-2 / Bulgu 7b risk): ``name_exact`` verilirse case-insensitive
    tam eşleşme filtresi uygulanır — frontend duplicate-name kontrolü 200-rapor
    listesi yerine doğrudan bu endpoint'i kullanabilir.
    """
    _require_user_ctx(user_ctx)
    n = max(1, min(int(limit or 50), _MAX_LIMIT))
    o = max(0, int(offset or 0))
    name_needle: Optional[str] = None
    if name_exact is not None:
        n_str = str(name_exact).strip()
        if n_str:
            name_needle = n_str[:_MAX_NAME_LEN]
    # Bulgular3 / Review fix #2: wizard_state JSONB'den table_label + object_name
    # extract et — frontend Saved Reports kart subtitle satiri (Bulgu 9) bu alanlara
    # ihtiyac duyuyor; yeni kolon eklemeden JSON path ile cekiyoruz (zero-migration).
    base_select = """
        SELECT id, name, description, source_id, last_dialect,
               tags, run_count, last_run_at, is_shared,
               created_at, updated_at,
               wizard_state->>'selectedTableLabel'      AS table_label,
               wizard_state->>'selectedTableObjectName' AS table_object_name
        FROM dbsmart_saved_reports
    """
    try:
        if name_needle is not None:
            cur.execute(
                base_select
                + " WHERE LOWER(name) = LOWER(%s) ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                (name_needle, n, o),
            )
        else:
            cur.execute(
                base_select
                + " ORDER BY updated_at DESC LIMIT %s OFFSET %s",
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
            "table_label": r[11], "table_object_name": r[12],
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
                (json.dumps(snapshot, default=str), int(report_id)),
            )
        return bool(getattr(cur, "rowcount", 0) or 0)
    except Exception as e:
        logger.warning("[db_smart.sr] mark_run %s failed: %s", report_id, e)
        return False


# ─────────────────────────────────────────────────────────────
# P38 — Share audience + audit log
# ─────────────────────────────────────────────────────────────

_VALID_AUDIENCES = ("public", "tenant", "users")
_MAX_AUDIT_ENTRIES = 20


def create_share_token_with_audience(
    cur,
    report_id: int,
    user_ctx: dict,
    *,
    audience: str = "public",
    allowed_user_ids: Optional[List[int]] = None,
    ttl_hours: int = 720,
) -> Optional[Dict[str, Any]]:
    """Share token oluşturur audience bilgisiyle (P38).

    audience: 'public' (herkes), 'tenant' (aynı company), 'users' (belirli kullanıcılar).
    """
    if audience not in _VALID_AUDIENCES:
        return None

    if audience == "users" and not allowed_user_ids:
        return None

    token = secrets.token_urlsafe(32)
    user_id = user_ctx.get("user_id")
    allowed_ids = allowed_user_ids[:50] if allowed_user_ids else None

    try:
        # Update share columns
        cur.execute(
            """
            UPDATE dbsmart_saved_reports
            SET is_shared = TRUE,
                share_token = %s,
                share_expires_at = NOW() + (%s || ' hours')::interval,
                share_audience = %s,
                share_allowed_user_ids = %s,
                share_audit = (
                    COALESCE(share_audit, '[]'::jsonb) || %s::jsonb
                ),
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, share_token, share_expires_at, share_audience
            """,
            (
                token,
                str(ttl_hours),
                audience,
                allowed_ids,
                json.dumps([{
                    "action": "share_created",
                    "audience": audience,
                    "by_user_id": user_id,
                    "at": "now()",
                    "allowed_user_ids": allowed_ids,
                }]),
                int(report_id),
            ),
        )
        row = cur.fetchone()
        if not row:
            return None

        # Trim audit to MAX entries
        _trim_audit(cur, report_id)

        return {
            "token": token,
            "expires_at": str(row[2]) if row[2] else None,
            "audience": audience,
        }
    except Exception as e:
        logger.warning("[db_smart.sr] create_share_token_with_audience failed: %s", e)
        return None


def check_share_audience(
    cur,
    token: str,
    viewer_user_id: Optional[int] = None,
    viewer_company_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Token doğrulaması + audience kontrolü.

    Returns report dict if allowed, None if denied/expired/missing.
    """
    try:
        cur.execute(
            """
            SELECT id, user_id, company_id, share_audience,
                   share_allowed_user_ids, share_expires_at,
                   name, last_run_snapshot, wizard_state
            FROM dbsmart_saved_reports
            WHERE share_token = %s
              AND is_shared = TRUE
              AND share_expires_at > NOW()
            """,
            (token,),
        )
        row = cur.fetchone()
        if not row:
            return None

        report_id, owner_user_id, report_company_id = row[0], row[1], row[2]
        audience = row[3] or "public"
        allowed_ids = row[4]

        # Audience check
        if audience == "tenant":
            if viewer_company_id is None or viewer_company_id != report_company_id:
                return None
        elif audience == "users":
            if not allowed_ids or viewer_user_id not in allowed_ids:
                return None
        # "public" → always allowed

        # Append audit entry
        _append_audit(cur, report_id, {
            "action": "share_viewed",
            "viewer_user_id": viewer_user_id,
            "at": "now()",
        })

        return {
            "id": report_id,
            "name": row[6],
            "last_run_snapshot": row[7],
            "wizard_state": row[8],
        }
    except Exception as e:
        logger.warning("[db_smart.sr] check_share_audience failed: %s", e)
        return None


def revoke_share_token(cur, report_id: int, user_ctx: dict) -> bool:
    """Share token'ı iptal eder (is_shared=FALSE)."""
    try:
        _append_audit(cur, report_id, {
            "action": "share_revoked",
            "by_user_id": user_ctx.get("user_id"),
            "at": "now()",
        })
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
        logger.warning("[db_smart.sr] revoke_share_token failed: %s", e)
        return False


def _append_audit(cur, report_id: int, entry: dict):
    """Audit log'a yeni entry ekler (max 20)."""
    try:
        cur.execute(
            """
            UPDATE dbsmart_saved_reports
            SET share_audit = (
                COALESCE(share_audit, '[]'::jsonb) || %s::jsonb
            )
            WHERE id = %s
            """,
            (json.dumps([entry]), int(report_id)),
        )
        _trim_audit(cur, report_id)
    except Exception:
        pass


def _trim_audit(cur, report_id: int):
    """Audit log'u MAX_AUDIT_ENTRIES'e kırpar (en yeniler kalır)."""
    try:
        cur.execute(
            f"""
            UPDATE dbsmart_saved_reports
            SET share_audit = (
                SELECT jsonb_agg(elem)
                FROM (
                    SELECT elem
                    FROM jsonb_array_elements(COALESCE(share_audit, '[]'::jsonb)) AS elem
                    ORDER BY elem->>'at' DESC NULLS LAST
                    LIMIT {_MAX_AUDIT_ENTRIES}
                ) sub
            )
            WHERE id = %s
              AND jsonb_array_length(COALESCE(share_audit, '[]'::jsonb)) > {_MAX_AUDIT_ENTRIES}
            """,
            (int(report_id),),
        )
    except Exception:
        pass
