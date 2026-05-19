"""apply_vyra_user_context — SET LOCAL doğrulama (v3.30.0 FAZ 1 G1.1a)."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.services.db_smart.rls_context import (
    apply_vyra_user_context,
    clear_vyra_user_context,
)


class FakeCursor:
    """psycopg2-uyumlu kayıt eden test cursor'ı."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        self.calls.append((sql, params))


def test_apply_sets_user_id_company_id_and_is_admin_for_regular_user(fake_user_ctx: Dict[str, Any]) -> None:
    cur = FakeCursor()
    apply_vyra_user_context(cur, fake_user_ctx)

    # Beklenen 3 set_config çağrısı (user_id, company_id, is_admin)
    assert len(cur.calls) == 3
    sqls = [c[0] for c in cur.calls]
    assert all("set_config" in s for s in sqls)
    assert any("vyra.user_id" in s for s in sqls)
    assert any("vyra.company_id" in s for s in sqls)
    assert any("vyra.is_admin" in s for s in sqls)

    # is_admin literal "false"
    is_admin_call = next(c for c in cur.calls if "vyra.is_admin" in c[0])
    assert is_admin_call[1] == ("false",)


def test_apply_sets_is_admin_true_for_admin(fake_admin_ctx: Dict[str, Any]) -> None:
    cur = FakeCursor()
    apply_vyra_user_context(cur, fake_admin_ctx)
    is_admin_call = next(c for c in cur.calls if "vyra.is_admin" in c[0])
    assert is_admin_call[1] == ("true",)


def test_apply_skips_missing_user_id() -> None:
    cur = FakeCursor()
    apply_vyra_user_context(cur, {"company_id": 1, "is_admin": False})
    sqls = [c[0] for c in cur.calls]
    # user_id atlanır; company_id + is_admin set edilir
    assert not any("vyra.user_id" in s for s in sqls)
    assert any("vyra.company_id" in s for s in sqls)
    assert any("vyra.is_admin" in s for s in sqls)


def test_apply_uses_set_local_semantics(fake_user_ctx: Dict[str, Any]) -> None:
    """SET LOCAL = is_local=true (3. parametre 'true'). Transaction-scoped."""
    cur = FakeCursor()
    apply_vyra_user_context(cur, fake_user_ctx)
    # Tüm çağrılar set_config(..., ..., true) — son parametre is_local=True
    for sql, _ in cur.calls:
        assert "true" in sql, f"SET LOCAL semantics missing: {sql}"


def test_apply_swallows_exceptions() -> None:
    """set_config hatası endpoint'i düşürmez (RLS default-deny zaten devrede)."""
    class BrokenCursor:
        def execute(self, *_a, **_k) -> None:
            raise RuntimeError("simulated")

    # exception fırlatmamalı
    apply_vyra_user_context(BrokenCursor(), {"id": 1, "company_id": 1})


def test_clear_emits_three_empty_sets(fake_user_ctx: Dict[str, Any]) -> None:
    cur = FakeCursor()
    clear_vyra_user_context(cur)
    assert len(cur.calls) == 3
    for _, params in cur.calls:
        assert params == ()  # empty-string literal embed olmuş — params kullanılmaz


def test_role_admin_treated_as_is_admin() -> None:
    """user_ctx['role'] == 'admin' ise is_admin=true olarak set edilir."""
    cur = FakeCursor()
    apply_vyra_user_context(cur, {"id": 5, "company_id": 1, "role": "admin"})
    is_admin_call = next(c for c in cur.calls if "vyra.is_admin" in c[0])
    assert is_admin_call[1] == ("true",)
