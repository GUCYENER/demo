"""
Sistem Özelliği Yetkilendirme API (v3.18.0)
=============================================
Ana sayfadaki 3 mod (kb/db/llm) için kullanıcı/org bazlı görünürlük.

Mantık:
- Admin → her zaman hepsini görür (DB bypass)
- user-level effect='deny' → her zaman gizler (org allow olsa bile)
- user-level effect='allow' → görür
- user için kayıt yok → user'ın üye olduğu org'larda effect='allow' varsa görür
- Hiç kayıt yok → DEFAULT göster (geriye uyumlu)
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.routes.auth import get_current_user
from app.core.db import get_db_context
from app.services.permission_audit import log_permission_change

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feature-permissions", tags=["feature_permissions"])

# Sistem tarafından tanınan sabit feature key'ler
KNOWN_FEATURE_KEYS = {"kb", "db", "llm", "aki_kesif"}  # aki_kesif: v3.30.0

# UI etiketleri (admin paneli için)
FEATURE_LABELS = {
    "kb":        "Bilgi Tabanında Ara",
    "db":        "Veritabanında Ara",
    "llm":       "VYRA ile Sohbet Et",
    "aki_kesif": "Akıllı Veri Keşfi",  # v3.30.0
}


# --- Pydantic ---

class FeaturePermissionUpdate(BaseModel):
    user_allow_ids: List[int] = []
    user_deny_ids:  List[int] = []
    org_allow_ids:  List[int] = []


# --- Helpers ---

def _is_admin(current_user: Dict[str, Any]) -> bool:
    return bool(current_user.get("is_admin")) or current_user.get("role") == "admin"


def _validate_feature_key(feature_key: str) -> None:
    if feature_key not in KNOWN_FEATURE_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz feature_key: {feature_key}. Beklenenler: {sorted(KNOWN_FEATURE_KEYS)}"
        )


# --- Endpoints ---

@router.get("/my")
def get_my_feature_permissions(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Mevcut kullanıcının 3 özelliğe görünürlüğünü döner.
    Format: {"features": {"kb": true, "db": false, "llm": true}, "is_admin": false}

    Semantik (v3.19.0 — sıkı mod):
      - Admin → her zaman hepsini görür
      - Tabloda HİÇ kayıt yoksa (ilk kurulum) → herkes hepsini görür (open mode)
      - Tabloda en az bir kayıt varsa → STRICT MODE:
          • user-level deny → her zaman gizler (org allow olsa bile)
          • user-level allow → görür
          • org-level allow + user o org'a üye → görür
          • Diğer her durum → gizli (default deny)
    """
    user_id = current_user.get("id")
    if _is_admin(current_user):
        return {
            "features": {k: True for k in KNOWN_FEATURE_KEYS},
            "is_admin": True,
        }

    with get_db_context() as conn:
        cur = conn.cursor()

        # Global mod tespiti: tabloda hiç kayıt yoksa hepsi açık (geriye uyum)
        cur.execute("SELECT 1 FROM feature_permissions LIMIT 1")
        strict_mode = cur.fetchone() is not None

        if not strict_mode:
            return {
                "features": {k: True for k in KNOWN_FEATURE_KEYS},
                "is_admin": False,
            }

        # Strict mode → default deny
        result = {k: False for k in KNOWN_FEATURE_KEYS}

        # Kullanıcının org üyelikleri
        cur.execute("""
            SELECT org_id FROM user_organizations WHERE user_id = %s
        """, (user_id,))
        org_ids = [r["org_id"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

        for feature_key in KNOWN_FEATURE_KEYS:
            # 1) User-level kayıt en güçlü
            cur.execute("""
                SELECT effect FROM feature_permissions
                WHERE feature_key = %s AND subject_type = 'user' AND subject_id = %s
            """, (feature_key, user_id))
            user_row = cur.fetchone()
            if user_row:
                eff = user_row["effect"] if isinstance(user_row, dict) else user_row[0]
                result[feature_key] = (eff == "allow")
                continue

            # 2) Org-level: kullanıcı en az bir izinli org'a üyeyse göster
            if not org_ids:
                result[feature_key] = False
                continue

            cur.execute("""
                SELECT 1 FROM feature_permissions
                WHERE feature_key = %s AND subject_type = 'org'
                  AND subject_id = ANY(%s) AND effect = 'allow'
                LIMIT 1
            """, (feature_key, org_ids))
            result[feature_key] = cur.fetchone() is not None

    return {"features": result, "is_admin": False}


@router.get("/admin")
def list_all_feature_permissions(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Admin paneli için: tüm feature'lara atanmış user/org listesini döner.
    Format:
      {
        "kb":  {"user_allow_ids":[..], "user_deny_ids":[..], "org_allow_ids":[..]},
        "db":  {...}, "llm": {...},
        "features": [{"key":"kb","label":"..."}, ...]
      }
    """
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Sadece admin erişebilir.")

    payload: Dict[str, Any] = {
        "features": [{"key": k, "label": FEATURE_LABELS[k]} for k in ("kb", "db", "llm", "aki_kesif")]
    }

    with get_db_context() as conn:
        cur = conn.cursor()
        for feature_key in KNOWN_FEATURE_KEYS:
            cur.execute("""
                SELECT subject_type, subject_id, effect FROM feature_permissions
                WHERE feature_key = %s
            """, (feature_key,))
            user_allow, user_deny, org_allow = [], [], []
            for row in cur.fetchall():
                if isinstance(row, dict):
                    st, sid, eff = row["subject_type"], row["subject_id"], row["effect"]
                else:
                    st, sid, eff = row[0], row[1], row[2]
                if st == "user" and eff == "allow":
                    user_allow.append(sid)
                elif st == "user" and eff == "deny":
                    user_deny.append(sid)
                elif st == "org" and eff == "allow":
                    org_allow.append(sid)
            payload[feature_key] = {
                "user_allow_ids": user_allow,
                "user_deny_ids":  user_deny,
                "org_allow_ids":  org_allow,
            }

    return payload


@router.put("/{feature_key}")
def update_feature_permission(
    feature_key: str,
    data: FeaturePermissionUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    Bir feature'ın izin atamalarını tam liste replace ile günceller.
    user_allow ∩ user_deny ⇒ deny kazanır (güvenli varsayılan).
    """
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Sadece admin yetki düzenleyebilir.")

    _validate_feature_key(feature_key)

    # Conflict resolution: deny her zaman kazanır
    deny_set  = set(data.user_deny_ids)
    allow_set = set(data.user_allow_ids) - deny_set
    org_set   = set(data.org_allow_ids)

    actor_id = current_user.get("id")
    company_id = current_user.get("company_id")

    with get_db_context() as conn:
        cur = conn.cursor()

        # Önceki durum (audit için)
        cur.execute("""
            SELECT subject_type, subject_id, effect FROM feature_permissions
            WHERE feature_key = %s ORDER BY subject_type, subject_id
        """, (feature_key,))
        before_rows = []
        for r in cur.fetchall():
            if isinstance(r, dict):
                before_rows.append({"subject_type": r["subject_type"], "subject_id": r["subject_id"], "effect": r["effect"]})
            else:
                before_rows.append({"subject_type": r[0], "subject_id": r[1], "effect": r[2]})

        # Replace
        cur.execute("DELETE FROM feature_permissions WHERE feature_key = %s", (feature_key,))

        rows_to_insert = []
        for uid in allow_set:
            rows_to_insert.append((feature_key, "user", uid, "allow", company_id, actor_id))
        for uid in deny_set:
            rows_to_insert.append((feature_key, "user", uid, "deny", company_id, actor_id))
        for oid in org_set:
            rows_to_insert.append((feature_key, "org", oid, "allow", company_id, actor_id))

        for row in rows_to_insert:
            cur.execute("""
                INSERT INTO feature_permissions
                (feature_key, subject_type, subject_id, effect, company_id, granted_by)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, row)

        after_rows = [
            {"subject_type": r[1], "subject_id": r[2], "effect": r[3]}
            for r in rows_to_insert
        ]
        log_permission_change(
            cur,
            actor_user_id=actor_id,
            company_id=company_id,
            permission_type="feature",
            target_key=feature_key,
            action="replace",
            before={"permissions": before_rows},
            after={"permissions": after_rows},
        )

        conn.commit()

    logger.info(
        "[FeaturePerm] %s güncellendi: allow_users=%d, deny_users=%d, orgs=%d",
        feature_key, len(allow_set), len(deny_set), len(org_set)
    )
    return {
        "success": True,
        "feature_key": feature_key,
        "user_allow_count": len(allow_set),
        "user_deny_count":  len(deny_set),
        "org_allow_count":  len(org_set),
    }


@router.get("/audit")
def list_permission_audit(
    limit: int = 100,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Admin: son N izin değişikliği kaydı."""
    if not _is_admin(current_user):
        raise HTTPException(status_code=403, detail="Sadece admin görüntüleyebilir.")
    if limit < 1 or limit > 1000:
        limit = 100

    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, actor_user_id, company_id, permission_type, target_key,
                   action, change_payload, ip_address, created_at
            FROM permission_audit_log
            ORDER BY created_at DESC
            LIMIT %s
        """, (limit,))
        rows = []
        for r in cur.fetchall():
            if isinstance(r, dict):
                rows.append({**r, "created_at": r["created_at"].isoformat() if r.get("created_at") else None})
            else:
                rows.append({
                    "id": r[0], "actor_user_id": r[1], "company_id": r[2],
                    "permission_type": r[3], "target_key": r[4], "action": r[5],
                    "change_payload": r[6], "ip_address": r[7],
                    "created_at": r[8].isoformat() if r[8] else None,
                })

    return {"items": rows, "count": len(rows)}
