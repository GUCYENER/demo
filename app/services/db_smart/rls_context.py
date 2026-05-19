"""Wizard RLS context injection (v3.30.0 FAZ 1 G1.1a — ARES carry-over).

Migration 032'de dbsmart_* tabloları aşağıdaki session setting'lerine bağlı
RLS policy ile kuruldu:

    current_setting('vyra.user_id',    true)::int  → kullanıcı izolasyonu
    current_setting('vyra.company_id', true)::int  → tenant izolasyonu
    current_setting('vyra.is_admin',   true)        → admin bypass ('true' literal)

Bu modül FastAPI endpoint'leri içinde — middleware'de DEĞİL — aktif transaction'a
SET LOCAL uygular. ARES (FAZ 0 code-review notu): middleware-tabanlı set yerine
endpoint-içi enjeksiyon mevcut `apply_company_scope` pattern'iyle uyumludur ve
pipeline cursor'ı havuza dönerken kendiliğinden temizlenir.

Kullanım:
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        cur.execute("SELECT ... FROM dbsmart_sessions ...")
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def apply_vyra_user_context(cur: Any, user_ctx: Dict[str, Any]) -> None:
    """Aktif transaction'a `vyra.*` RLS setting'lerini SET LOCAL uygular.

    Args:
        cur: Aktif psycopg2 cursor (transaction-scoped).
        user_ctx: get_current_user dict'i — {id, company_id, is_admin/role, ...}

    Notlar:
        - SET LOCAL transaction-scoped: commit/rollback sonrası bağlantı pool'a
          dönünce setting temizlenir (mevcut `apply_company_scope` ile aynı garanti).
        - `is_admin` literal string `'true'` / `'false'` olarak gönderilir; RLS
          policy `current_setting('vyra.is_admin', true) = 'true'` karşılaştırır.
        - user_ctx eksik alan içeriyorsa (örn. test fixture'ı) sessizce atlanır;
          RLS policy `NULLIF(..., '')::int` ile NULL'a düşer ve default-deny davranır.
    """
    user_id = user_ctx.get("id")
    company_id = user_ctx.get("company_id")
    is_admin = bool(user_ctx.get("is_admin")) or user_ctx.get("role") == "admin"

    try:
        if user_id is not None:
            cur.execute(
                "SELECT set_config('vyra.user_id', %s, true)",
                (str(int(user_id)),),
            )
        if company_id is not None:
            cur.execute(
                "SELECT set_config('vyra.company_id', %s, true)",
                (str(int(company_id)),),
            )
        cur.execute(
            "SELECT set_config('vyra.is_admin', %s, true)",
            ("true" if is_admin else "false",),
        )
    except Exception as e:
        # SAVEPOINT-style: set_config hatası kritik değil — RLS default-deny ile
        # sessizce engellenir; app-layer auth zaten geçmiş durumda.
        logger.warning("[db_smart.rls] apply_vyra_user_context failed: %s", e)


def clear_vyra_user_context(cur: Any) -> None:
    """Explicit clear — testlerde veya idempotency için.

    SET LOCAL transaction sonunda zaten temizlenir; bu helper sadece test
    ortamında veya tek bağlantıyı arka arkaya farklı user'larla kullanan
    fixture'lar için sağlanır.
    """
    try:
        cur.execute("SELECT set_config('vyra.user_id', '', true)")
        cur.execute("SELECT set_config('vyra.company_id', '', true)")
        cur.execute("SELECT set_config('vyra.is_admin', '', true)")
    except Exception as e:
        logger.warning("[db_smart.rls] clear_vyra_user_context failed: %s", e)
