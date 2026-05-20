"""apply_vyra_user_context — SET LOCAL doğrulama (v3.30.0 FAZ 1 G1.1a).

Fail-closed semantik (ARES KRİTİK fix): set_config hatası ve malformed input
RLSContextError fırlatır; eski "silent swallow" davranışı kaldırıldı.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from app.services.db_smart.rls_context import (
    RLSContextError,
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


def test_apply_uses_set_local_semantics(fake_user_ctx: Dict[str, Any]) -> None:
    """SET LOCAL = is_local=true (3. parametre 'true'). Transaction-scoped."""
    cur = FakeCursor()
    apply_vyra_user_context(cur, fake_user_ctx)
    # Tüm çağrılar set_config(..., ..., true) — son parametre is_local=True
    for sql, _ in cur.calls:
        assert "true" in sql, f"SET LOCAL semantics missing: {sql}"


def test_clear_emits_three_empty_sets(fake_user_ctx: Dict[str, Any]) -> None:
    cur = FakeCursor()
    clear_vyra_user_context(cur)
    assert len(cur.calls) == 3
    for _, params in cur.calls:
        assert params == ()  # empty-string literal embed olmuş — params kullanılmaz


def test_role_admin_treated_as_is_admin() -> None:
    """user_ctx['role'] == 'admin' ise is_admin=true olarak set edilir."""
    cur = FakeCursor()
    apply_vyra_user_context(
        cur, {"id": 5, "company_id": 1, "role": "admin", "is_admin": False}
    )
    is_admin_call = next(c for c in cur.calls if "vyra.is_admin" in c[0])
    assert is_admin_call[1] == ("true",)


# ---------------------------------------------------------------------------
# Fail-closed contract (v3.30.0 P15+ — ARES KRİTİK fix)
# ---------------------------------------------------------------------------


def test_set_config_failure_raises() -> None:
    """cur.execute set_config hatası → RLSContextError (fail-closed).

    Eski davranış: logger.warning + silent continue → cross-tenant sızıntı riski.
    Yeni kontrat: yükselt; endpoint guard sorguya geçmemeli.
    """
    class BrokenCursor:
        def execute(self, *_a, **_k) -> None:
            raise RuntimeError("simulated DB outage")

    with pytest.raises(RLSContextError) as exc_info:
        apply_vyra_user_context(BrokenCursor(), {"id": 1, "company_id": 1, "is_admin": False})
    # Asıl DB hatası __cause__ üzerinden korunmalı.
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "simulated DB outage" in str(exc_info.value.__cause__)


def test_malformed_input_rejected() -> None:
    """Eksik / yanlış-tipli id/company_id/is_admin → RLSContextError; DB'ye hiç gitmemeli."""
    cur = FakeCursor()

    # Eksik user_id
    with pytest.raises(RLSContextError, match="user_id"):
        apply_vyra_user_context(cur, {"company_id": 1, "is_admin": False})
    assert cur.calls == []  # validation DB'den ÖNCE patlamalı

    # Eksik company_id
    with pytest.raises(RLSContextError, match="company_id"):
        apply_vyra_user_context(cur, {"id": 1, "is_admin": False})
    assert cur.calls == []

    # user_id bool — int alt-sınıfı olduğu için kaza sınırını test et
    with pytest.raises(RLSContextError, match="user_id"):
        apply_vyra_user_context(cur, {"id": True, "company_id": 1, "is_admin": False})
    assert cur.calls == []

    # company_id float — kabul edilmemeli
    with pytest.raises(RLSContextError, match="company_id"):
        apply_vyra_user_context(cur, {"id": 1, "company_id": 1.5, "is_admin": False})
    assert cur.calls == []

    # is_admin int — bool şart
    with pytest.raises(RLSContextError, match="is_admin"):
        apply_vyra_user_context(cur, {"id": 1, "company_id": 1, "is_admin": 1})
    assert cur.calls == []

    # Negatif/sıfır user_id reddedilmeli
    with pytest.raises(RLSContextError, match="user_id"):
        apply_vyra_user_context(cur, {"id": 0, "company_id": 1, "is_admin": False})
    assert cur.calls == []

    # Sayısal string toleransı — pozitif tarafta accept (auth bazen str gönderebilir)
    cur2 = FakeCursor()
    apply_vyra_user_context(cur2, {"id": "42", "company_id": "1", "is_admin": False})
    assert len(cur2.calls) == 3

    # Non-numeric string reddedilmeli
    with pytest.raises(RLSContextError, match="user_id"):
        apply_vyra_user_context(
            FakeCursor(), {"id": "abc", "company_id": 1, "is_admin": False}
        )


def test_non_dict_user_ctx_rejected() -> None:
    """user_ctx dict değilse programlama hatası — TypeError."""
    with pytest.raises(TypeError):
        apply_vyra_user_context(FakeCursor(), "not-a-dict")  # type: ignore[arg-type]
