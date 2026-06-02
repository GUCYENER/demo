"""Merkezi fail-closed tablo-yetki guard'ı (v3.40.0 Faz B).

`SafeSQLExecutor.check_table_whitelist` (safe_sql_executor.py) **boş allowed_tables =
allow-all** döner (footgun). Bu yüzden `allowed_tables=None`/boş geçen her execute yolu
(agentic wiring, query_builder/preview, query_state/preview, schedule_runner) tablo-yetkiyi
SESSİZCE ATLIYORDU. Bu modül tek choke-point: restricted kullanıcıda boş kapsam → **DENY**
(asla allow-all), yetkisiz tablo içeren SQL → **DENY** (yanlış-tablo adı sızdırmadan).

Kullanım (her execute öncesi):
    from app.services.db_smart.table_guard import enforce_sql_scope
    ok, allowed_tables, deny_msg = enforce_sql_scope(sql, source_id, user_ctx, dialect)
    if not ok:
        # kullanıcıya deny_msg göster, çalıştırma
        ...
    executor.execute(sql, source, dialect=dialect, allowed_tables=allowed_tables)  # None=all-access
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.db_smart.table_scope import resolve_scope
from app.services.safe_sql_executor import check_table_whitelist


def _log_scope_deny(source_id, user_ctx, permission, all_tables, scope_names, allowed, sql, reason) -> None:
    """v3.52.0: tablo-yetki RED'ini diagnostic olarak loglar (WARNING — Hata İzleme'de görünür).

    "Yetki var ama red" şikayetlerinde scope NEDEN boş/eşleşmiyor canlıda görünür: admin durumu,
    permission, scope'taki tablolar, üretilen SQL. Sızıntı yok (zaten yetkili kullanıcının kendi
    bağlamı). Asla exception fırlatmaz (best-effort).
    """
    try:
        from app.services.logging_service import log_system_event
        uc = user_ctx or {}
        log_system_event(
            "WARNING",
            f"[scope-deny] source={source_id} user={uc.get('id')} "
            f"admin={bool(uc.get('is_admin')) or uc.get('role') == 'admin'} perm={permission} "
            f"all_tables={all_tables} reason={reason} | scope_tables={list(scope_names)[:25]} "
            f"| allowed={list(allowed)[:25]} | sql={(sql or '')[:400]}",
            module="db_smart.table_guard",
        )
    except Exception:
        pass


def _denial_message(allowed_names: List[str]) -> str:
    """Tutarlı, sızıntısız red mesajı (Faz A/_scope_restricted_message ile aynı dil)."""
    allow_txt = ", ".join(allowed_names) if allowed_names else "(yetkili tablonuz bulunmuyor)"
    return (
        "Bu sorgu yetkili olmadığınız bir tabloya erişiyor. "
        f"Yetkili tablolarınız: {allow_txt}."
    )


def enforce_sql_scope(
    sql: str,
    source_id: Any,
    user_ctx: Optional[Dict[str, Any]],
    dialect: str,
    *,
    permission: str = "can_execute",
) -> Tuple[bool, Optional[List[str]], Optional[str]]:
    """Fail-closed tablo-yetki kapısı.

    Returns:
        (ok, allowed_tables_or_None, denial_msg)
        - ok=True  → çalıştır. allowed_tables_or_None: all-access ise None (kısıt yok),
                     aksi halde DOĞRULANMIŞ whitelist (executor'a aynen geçir = defense-in-depth).
        - ok=False → REDDET. denial_msg kullanıcıya gösterilir (yetkili tablo listesi;
                     SQL'deki yetkisiz tablo adını/FK-komşusunu SIZDIRMAZ).
    """
    scope = resolve_scope(int(source_id), user_ctx, permission=permission)
    if scope.all_tables:
        return True, None, None  # kısıtsız (admin-no-grant veya scope_mode='all')

    names = sorted({t for _s, t in scope.tables if t})
    # check_table_whitelist hem "schema.table" hem çıplak "table" karşılaştırır;
    # her iki varyantı da ekle (lowercase — scope zaten _norm'lu).
    allowed: List[str] = []
    for sch, tbl in scope.tables:
        if not tbl:
            continue
        if sch:
            allowed.append(f"{sch}.{tbl}")
        allowed.append(tbl)

    if not allowed:
        # restricted ama çalıştırılabilir tablo YOK → DENY (boş=allow-all'a DÜŞME)
        # v3.52.0: false-deny tanısı için diagnostic log (WARNING — Hata İzleme'de level=WARNING/ALL ile
        # görünür). "Yetki var ama red" şikayetinde scope NEDEN boş (admin can_execute grant'ı yok mu,
        # table_permissions kaydedilmemiş mi) canlıda görünür.
        _log_scope_deny(source_id, user_ctx, permission, scope.all_tables, names, [], sql,
                        "BOŞ-SCOPE (yetkili/çalıştırılabilir tablo yok)")
        return False, None, _denial_message(names)

    ok_wl, _err = check_table_whitelist(sql or "", allowed, dialect)
    if not ok_wl:
        _log_scope_deny(source_id, user_ctx, permission, scope.all_tables, names, allowed, sql,
                        _err or "whitelist mismatch")
        return False, None, _denial_message(names)

    return True, allowed, None
