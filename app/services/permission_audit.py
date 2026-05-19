"""
İzin Değişiklik Audit Helper (v3.18.0)
=======================================
data_source_permissions ve feature_permissions değişikliklerini
permission_audit_log tablosuna yazar.

Compliance ve forensic analiz için tasarlanmıştır.
"""

import json
import logging
from typing import Any, Dict, Optional

from psycopg2.extras import Json

logger = logging.getLogger(__name__)


def log_permission_change(
    cur,
    actor_user_id: Optional[int],
    company_id: Optional[int],
    permission_type: str,           # 'data_source' | 'feature'
    target_key: str,
    action: str,                    # 'replace' | 'grant' | 'revoke'
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
) -> None:
    """
    Aynı transaction içinde audit kaydı oluşturur.
    Caller'ın açtığı cursor'u kullanır → atomicity korunur.
    Hata oluşursa loglar ama exception fırlatmaz (audit ana işlemi bloklamaz).
    """
    try:
        payload = {"before": before or {}, "after": after or {}}
        cur.execute("""
            INSERT INTO permission_audit_log
            (actor_user_id, company_id, permission_type, target_key,
             action, change_payload, ip_address)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            actor_user_id,
            company_id,
            permission_type,
            str(target_key),
            action,
            Json(payload),
            ip_address,
        ))
        logger.info(
            "[PermissionAudit] %s/%s action=%s actor=%s company=%s",
            permission_type, target_key, action, actor_user_id, company_id
        )
    except Exception as e:
        logger.error("[PermissionAudit] Audit yazımı başarısız: %s", e)
        # Audit fail olsa bile ana akış bozulmasın — sadece logla
