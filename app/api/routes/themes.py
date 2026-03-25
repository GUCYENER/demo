"""
VYRA L1 Support API - Themes Routes
=====================================
Company theme CRUD, renk önerme ve firma-tema atama endpoint'leri.
v2.60.0 — Özel tema oluşturma ve firma atama desteği
"""

import logging
import colorsys
import json
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user, get_current_admin
from app.core.db import get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/themes", tags=["themes"])


# --- Pydantic Models ---

class ThemeCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    color1: str = Field(..., pattern=r'^#[0-9a-fA-F]{6}$')
    color2: str = Field(..., pattern=r'^#[0-9a-fA-F]{6}$')
    company_id: Optional[int] = None
    login_headline: Optional[str] = None
    login_subtitle: Optional[str] = None


class ThemeAssign(BaseModel):
    company_id: int
    theme_ids: List[int]
    default_theme_id: Optional[int] = None


class ColorSuggest(BaseModel):
    color: str = Field(..., pattern=r'^#[0-9a-fA-F]{6}$')


# --- Renk Yardımcıları ---

def hex_to_hsl(hex_color: str):
    """HEX → HSL dönüşümü"""
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16) / 255, int(hex_color[2:4], 16) / 255, int(hex_color[4:6], 16) / 255
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s * 100, l * 100


def hsl_to_hex(h: float, s: float, l: float) -> str:
    """HSL → HEX dönüşümü"""
    h, s, l = h / 360, s / 100, l / 100
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return '#{:02x}{:02x}{:02x}'.format(int(r * 255), int(g * 255), int(b * 255))


def hex_to_rgba(hex_color: str, alpha: float) -> str:
    """HEX → rgba() dönüşümü"""
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def generate_css_variables(color1: str, color2: str) -> dict:
    """İki ana renkten otomatik CSS variable seti oluşturur (dark + light mod)."""
    # Dark mod
    dark = {
        "--gold": color1,
        "--gold-2": color2,
        "--gold-dim": hex_to_rgba(color1, 0.12),
        "--gold-glow": hex_to_rgba(color1, 0.18),
        "--gold-subtle": hex_to_rgba(color1, 0.07),
        "--border-accent": hex_to_rgba(color1, 0.30),
        "--text-gold": color1,
        "--grad-logo": f"linear-gradient(135deg, {color1} 0%, {color2} 100%)",
        "--grad-btn": f"linear-gradient(135deg, {color1} 0%, {color2} 100%)",
        "--grad-acc": f"linear-gradient(135deg, {color1}, {color2})",
        "--shadow-btn": f"0 4px 20px {hex_to_rgba(color1, 0.25)}, 0 0 0 1px {hex_to_rgba(color1, 0.12)}",
        "--shadow-input": f"0 0 0 2px {hex_to_rgba(color1, 0.35)}, 0 0 16px {hex_to_rgba(color1, 0.08)}",
        "--orb-a": hex_to_rgba(color1, 0.12),
        "--orb-b": hex_to_rgba(color2, 0.08)
    }

    # Light mod — daha koyu tonlar
    h1, s1, l1 = hex_to_hsl(color1)
    h2, s2, l2 = hex_to_hsl(color2)
    light_c1 = hsl_to_hex(h1, min(s1, 90), max(l1 - 15, 30))
    light_c2 = hsl_to_hex(h2, min(s2, 90), max(l2 - 15, 30))

    light = {
        "--gold": light_c1,
        "--gold-2": light_c2,
        "--gold-dim": hex_to_rgba(light_c1, 0.08),
        "--gold-glow": hex_to_rgba(light_c1, 0.12),
        "--gold-subtle": hex_to_rgba(light_c1, 0.05),
        "--border-accent": hex_to_rgba(light_c1, 0.25),
        "--text-gold": light_c1,
        "--grad-logo": f"linear-gradient(135deg, {light_c1} 0%, {light_c2} 100%)",
        "--grad-btn": f"linear-gradient(135deg, {light_c1} 0%, {light_c2} 100%)",
        "--grad-acc": f"linear-gradient(135deg, {light_c1}, {light_c2})",
        "--shadow-btn": f"0 4px 20px {hex_to_rgba(light_c1, 0.20)}, 0 0 0 1px {hex_to_rgba(light_c1, 0.10)}",
        "--shadow-input": f"0 0 0 2px {hex_to_rgba(light_c1, 0.28)}, 0 0 12px {hex_to_rgba(light_c1, 0.06)}",
        "--orb-a": hex_to_rgba(light_c1, 0.06),
        "--orb-b": hex_to_rgba(light_c2, 0.05)
    }

    return {"dark": dark, "light": light}


def generate_color_suggestions(base_color: str) -> List[dict]:
    """Verilen renge göre uyumlu renk çiftleri önerir."""
    h, s, l = hex_to_hsl(base_color)
    suggestions = []

    pairs = [
        ("Complementary", (h + 180) % 360),
        ("Analogous +30°", (h + 30) % 360),
        ("Analogous -30°", (h - 30) % 360),
        ("Triadic +120°", (h + 120) % 360),
        ("Triadic -120°", (h - 120) % 360),
        ("Split Comp. +150°", (h + 150) % 360),
        ("Split Comp. -150°", (h - 150) % 360),
    ]

    for label, h2 in pairs:
        color2 = hsl_to_hex(h2, min(s, 85), min(l, 55))
        suggestions.append({
            "label": label,
            "color1": base_color,
            "color2": color2,
            "preview": [base_color, color2]
        })

    return suggestions


# =====================================================
# ENDPOINTS
# =====================================================
# ÖNEMLİ: Route sırası kritik!
# Starlette parametrik route'lar (/{id}) spesifik path'leri yakalar.
# Bu yüzden spesifik route'lar (GET /full, POST /suggest, GET /company/...)
# parametrik route'dan (GET /{theme_id}) ÖNCE tanımlanmalı.
# =====================================================


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
            WHERE is_active = TRUE AND (is_custom = FALSE OR is_custom IS NULL)
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
                   login_headline, login_subtitle, features_json, sort_order,
                   company_id, is_custom
            FROM company_themes
            WHERE is_active = TRUE
            ORDER BY sort_order
        """)
        rows = cur.fetchall()

    return [dict(row) for row in rows]


@router.post("/")
def create_theme(data: ThemeCreate, current_user: Dict[str, Any] = Depends(get_current_admin)):
    """
    Yeni özel tema oluşturur. Admin only.
    İki renk girdisinden otomatik CSS variables hesaplanır.
    """
    css_vars = generate_css_variables(data.color1, data.color2)
    code = f"custom_{data.color1.lstrip('#')}_{data.color2.lstrip('#')}"

    with get_db_context() as conn:
        cur = conn.cursor()

        # Aynı code varsa kontrol
        cur.execute("SELECT id FROM company_themes WHERE code = %s", (code,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Bu renk kombinasyonu zaten mevcut.")

        cur.execute("""
            INSERT INTO company_themes (
                name, code, description, css_variables, preview_colors,
                login_headline, login_subtitle, sort_order,
                company_id, is_custom, is_active
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 99, %s, TRUE, TRUE)
            RETURNING id, name, code, preview_colors
        """, (
            data.name,
            code,
            f"{data.color1} + {data.color2} özel renk demeti",
            json.dumps(css_vars),
            json.dumps([data.color1, data.color2]),
            data.login_headline or 'Yapay zeka ile,<br><strong>akıllı destek deneyimi</strong>',
            data.login_subtitle or 'Dokümanlardan anlık yanıt, bağlam duyarlı diyalog yönetimi ve RAG bilgi tabanı platformu.',
            data.company_id
        ))
        row = cur.fetchone()
        conn.commit()

    logger.info(f"[Themes] Yeni özel tema oluşturuldu: {row['name']} (id={row['id']})")
    return dict(row)


@router.post("/suggest")
def suggest_colors(data: ColorSuggest, current_user: Dict[str, Any] = Depends(get_current_admin)):
    """
    Verilen ana renge uyumlu renk çiftleri önerir (complementary, analogous, triadic).
    Mevcut temalarla çakışanları filtreler.
    """
    suggestions = generate_color_suggestions(data.color)

    # Mevcut preview_colors ile çakışma kontrolü
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT preview_colors FROM company_themes WHERE is_active = TRUE")
        rows = cur.fetchall()

    existing_pairs = set()
    for row in rows:
        pc = row["preview_colors"]
        if isinstance(pc, str):
            try:
                pc = json.loads(pc)
            except Exception:
                pc = []
        if isinstance(pc, list) and len(pc) >= 2:
            existing_pairs.add((pc[0].lower(), pc[1].lower()))

    # Çakışanları işaretle
    for s in suggestions:
        pair = (s["color1"].lower(), s["color2"].lower())
        s["already_exists"] = pair in existing_pairs

    return {"suggestions": suggestions}


@router.post("/assign")
def assign_themes(data: ThemeAssign, current_user: Dict[str, Any] = Depends(get_current_admin)):
    """
    Firmaya tema atar. Admin only.
    Mevcut atamaları siler ve yenilerini ekler.
    """
    with get_db_context() as conn:
        cur = conn.cursor()

        # Mevcut atamaları temizle
        cur.execute("DELETE FROM company_theme_assignments WHERE company_id = %s", (data.company_id,))

        # Yeni atamaları ekle
        for tid in data.theme_ids:
            is_default = (tid == data.default_theme_id) if data.default_theme_id else (tid == data.theme_ids[0])
            cur.execute("""
                INSERT INTO company_theme_assignments (company_id, theme_id, is_default)
                VALUES (%s, %s, %s)
                ON CONFLICT (company_id, theme_id) DO UPDATE SET is_default = EXCLUDED.is_default
            """, (data.company_id, tid, is_default))

        # Firma default theme_id güncelle
        default_id = data.default_theme_id or (data.theme_ids[0] if data.theme_ids else None)
        if default_id:
            cur.execute("UPDATE companies SET theme_id = %s WHERE id = %s", (default_id, data.company_id))

        conn.commit()

    logger.info(f"[Themes] Firma {data.company_id} → {len(data.theme_ids)} tema atandı")
    return {"status": "ok", "assigned": len(data.theme_ids)}


@router.get("/company/{company_id}")
def get_company_themes(company_id: int, current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Firmaya atanmış tema listesi (CSS variables dahil).
    Kullanıcılar kendi firmalarını, adminler tüm firmaları görebilir.
    """
    is_admin = current_user.get("is_admin", False) or current_user.get("role") == "admin"
    user_company = current_user.get("company_id")

    if not is_admin and user_company != company_id:
        raise HTTPException(status_code=403, detail="Bu firmaya erişim yetkiniz yok.")

    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT ct.id, ct.name, ct.code, ct.description, ct.css_variables,
                       ct.preview_colors, ct.is_custom,
                       cta.is_default
                FROM company_theme_assignments cta
                JOIN company_themes ct ON ct.id = cta.theme_id
                WHERE cta.company_id = %s AND ct.is_active = TRUE
                ORDER BY cta.is_default DESC, ct.sort_order
            """, (company_id,))
            rows = cur.fetchall()

        return [dict(row) for row in rows]
    except Exception as e:
        logger.warning(f"[Themes] company_theme_assignments sorgu hatası: {e}")
        return []


# =====================================================
# PARAMETRİK ROUTE'LAR — EN SONA!
# /{theme_id} her path'i yakalar, bu yüzden spesifik
# route'lardan SONRA tanımlanmalı.
# =====================================================

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


@router.delete("/{theme_id}")
def delete_theme(theme_id: int, current_user: Dict[str, Any] = Depends(get_current_admin)):
    """
    Özel temayı siler. Sadece is_custom=True temalar silinebilir.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, is_custom, name FROM company_themes WHERE id = %s", (theme_id,))
        row = cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Tema bulunamadı.")

        if not row["is_custom"]:
            raise HTTPException(status_code=403, detail="Hazır temalar silinemez.")

        # Atamalardan kaldır
        cur.execute("DELETE FROM company_theme_assignments WHERE theme_id = %s", (theme_id,))
        # Firmalardan theme_id bağını kaldır
        cur.execute("UPDATE companies SET theme_id = NULL WHERE theme_id = %s", (theme_id,))
        # Temayı sil
        cur.execute("DELETE FROM company_themes WHERE id = %s", (theme_id,))
        conn.commit()

    logger.info(f"[Themes] Özel tema silindi: {row['name']} (id={theme_id})")
    return {"status": "ok", "deleted": row["name"]}
