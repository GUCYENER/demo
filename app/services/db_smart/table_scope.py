"""Tablo seviyesi erişim kapsamı helper'ı (v3.38.0).

`data_source_access.user_accessible_tables` gate'ini Smart Discovery /
text-to-sql akışlarında tek satırda çözmek için ince bir sarmalayıcı.

Amaç: kod tekrarını önlemek + `is_admin` türetmesini (is_admin VEYA
role=='admin') tek yerde tutmak. v3.39.0: Admin → kaynakta açık grant YOKSA
`AccessScope(all_tables=True)`; açık grant varsa kısıt admin'e de uygulanır
(managed-admin — bkz. data_source_access.user_accessible_tables).

Kullanım:
    scope = resolve_scope(source_id, current_user)
    if not scope.all_tables and not scope.allows(schema, table):
        ...  # yetkisiz → filtrele / 404 / 403
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from app.services.data_source_access import AccessScope, user_accessible_tables


def is_admin_ctx(user_ctx: Optional[Dict[str, Any]]) -> bool:
    """current_user dict'inden admin durumunu türet (is_admin VEYA role=='admin')."""
    if not user_ctx:
        return False
    return bool(user_ctx.get("is_admin")) or user_ctx.get("role") == "admin"


def resolve_scope(
    source_id: int,
    user_ctx: Optional[Dict[str, Any]],
    *,
    permission: str = "can_view",
) -> AccessScope:
    """Kullanıcının `source_id` üzerindeki tablo erişim kapsamını döner.

    Args:
        source_id: data_sources.id
        user_ctx: get_current_user dict — {id, is_admin/role, company_id, ...}
        permission: 'can_view' (keşif/görüntüleme) veya 'can_execute' (çalıştırma)

    Returns:
        AccessScope. v3.39.0: Admin OTOMATİK all_tables DEĞİL — bu kaynakta açık
        grant varsa kısıt admin'e de uygulanır (user_accessible_tables managed-admin
        mantığı). Admin yalnız kaynakta hiç grant yokken all_tables=True alır.
        user_id yoksa: admin (sistem ctx) → ALL, aksi → fail-closed (boş kapsam).
    """
    admin = is_admin_ctx(user_ctx)
    uid = int((user_ctx or {}).get("id") or 0)
    if uid <= 0:
        # Kimlik yok: admin/sistem ctx → ALL; normal kullanıcı → fail-closed.
        return (AccessScope(all_tables=True) if admin
                else AccessScope(all_tables=False, tables=frozenset()))
    return user_accessible_tables(
        uid, int(source_id), is_admin=admin, permission=permission
    )
