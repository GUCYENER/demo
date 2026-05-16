"""Data source access permission helpers (Faz 1, v3.20.0).

Kullanıcının bir `data_sources.id` üzerinde `can_view` (varsayılan) veya
`can_execute` yetkisine sahip olup olmadığını kontrol eder.

`data_source_permissions` tablosu polymorphic — `subject_type` 'user' veya
'org' olabilir. Org permission'ları `user_organizations` üzerinden çözümlenir.

Bu modül `data_sources_api.list_data_sources` SQL pattern'ini taşır
(yalnızca tek bir source_id için filtre).
"""
from __future__ import annotations

from app.core.db import get_db_context


def user_can_access_source(
    user_id: int,
    source_id: int,
    *,
    is_admin: bool = False,
    permission: str = "can_view",
) -> bool:
    """Kullanıcının `source_id` üzerinde belirtilen yetkisi var mı?

    Args:
        user_id: users.id
        source_id: data_sources.id
        is_admin: True ise yetki kontrolü atlanır (admin her şeye erişir)
        permission: 'can_view' (varsayılan) veya 'can_execute'

    Returns:
        bool: Erişim varsa True

    Raises:
        ValueError: permission geçersizse
    """
    if is_admin:
        return True

    if permission not in ("can_view", "can_execute"):
        raise ValueError(f"Geçersiz permission: {permission!r}")

    with get_db_context() as conn:
        cur = conn.cursor()
        # Hem user-direct hem org-membership üzerinden kontrol
        cur.execute(
            f"""
            SELECT 1
            FROM data_source_permissions p
            LEFT JOIN user_organizations uo
                   ON uo.user_id = %s
                  AND p.subject_type = 'org'
                  AND uo.org_id = p.subject_id
            WHERE p.source_id = %s
              AND p.{permission} = TRUE
              AND (
                  (p.subject_type = 'user' AND p.subject_id = %s)
                  OR
                  (p.subject_type = 'org'  AND uo.id IS NOT NULL)
              )
            LIMIT 1
            """,
            (user_id, source_id, user_id),
        )
        return cur.fetchone() is not None
