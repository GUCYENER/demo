"""
VYRA L1 Support API - Themes Routes
=====================================
Company theme CRUD endpoint'leri.
v2.59.0
"""

import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException
from app.api.routes.auth import get_current_user
from app.core.db import get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/themes", tags=["themes"])


@router.get("/")
def get_themes():
    """
    Aktif tema listesi. Auth gerektirmez (login ekranında kullanılır).
    CSS variables hariç özet bilgi döner.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, code, description, preview_colors,
                   login_headline, login_subtitle, features_json, sort_order
            FROM company_themes
            WHERE is_active = TRUE
            ORDER BY sort_order
        """)
        rows = cur.fetchall()

    return [dict(row) for row in rows]


@router.get("/full")
def get_themes_full(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Aktif tema listesi — CSS variables dahil tam bilgi.
    Auth gerekli (admin panel / firma tanım ekranı).
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, code, description, css_variables, preview_colors,
                   login_headline, login_subtitle, features_json, sort_order
            FROM company_themes
            WHERE is_active = TRUE
            ORDER BY sort_order
        """)
        rows = cur.fetchall()

    return [dict(row) for row in rows]


@router.get("/{theme_id}")
def get_theme(theme_id: int):
    """
    Tema detayı (CSS variables dahil). Auth gerektirmez (login branding).
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, code, description, css_variables, preview_colors,
                   login_headline, login_subtitle, features_json, sort_order
            FROM company_themes
            WHERE id = %s AND is_active = TRUE
        """, (theme_id,))
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Tema bulunamadı.")

    return dict(row)
