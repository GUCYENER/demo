"""RLS integration tests — tenant isolation contract (FIX9 / TYCHE+ARES).

Covers the full DB-side enforcement that complements the unit-level
`apply_vyra_user_context` contract tested in `test_rls_context.py`:

    1) TYCHE happy:   owner-company user CAN read its own rows.
    2) ARES negative: non-owner user CANNOT read another tenant's rows
                      (must return 0 rows under RLS — fail-closed).
    3) ARES negative: missing RLS context → fail-closed (RLSContextError OR
                      zero-row read on policy-protected table).
    4) TYCHE edge:    admin / role='admin' is honoured only inside its OWN
                      company_id; admin flag does NOT leak cross-tenant.

DB-required — skipped unless `VYRA_TEST_DB_URL` env var is set. Marked
`pytest.mark.integration` so the default `addopts = -m "not integration"`
selector in `pytest.ini` keeps unit runs fast.

POSEIDON: every test runs in an explicit transaction and rolls back at
teardown — no schema drift, no leaked rows, idempotent across re-runs.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict, Iterator

import pytest

# Soft imports — production module presence guarded.
try:
    from app.services.db_smart.rls_context import (
        RLSContextError,
        apply_vyra_user_context,
        clear_vyra_user_context,
    )
except Exception:  # pragma: no cover - import-time fail surfaces via skip below
    RLSContextError = RuntimeError  # type: ignore[assignment]
    apply_vyra_user_context = None  # type: ignore[assignment]
    clear_vyra_user_context = None  # type: ignore[assignment]


pytestmark = pytest.mark.integration


_DB_URL = os.environ.get("VYRA_TEST_DB_URL")


def _skip_if_no_db() -> None:
    if not _DB_URL:
        pytest.skip("VYRA_TEST_DB_URL not set — RLS integration requires live Postgres")
    if apply_vyra_user_context is None:
        pytest.skip("rls_context module unavailable in this environment")


@pytest.fixture
def db_conn() -> Iterator[Any]:
    """Open a psycopg2 connection inside an explicit transaction; rollback at teardown."""
    _skip_if_no_db()
    try:
        import psycopg2  # type: ignore
    except Exception:
        pytest.skip("psycopg2 not installed")
    conn = psycopg2.connect(_DB_URL)
    conn.autocommit = False
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


@pytest.fixture
def fresh_session_uids() -> Dict[str, str]:
    """Two UUIDs used as canary rows: one per tenant in the cross-tenant matrix."""
    return {"tenant_a": str(uuid.uuid4()), "tenant_b": str(uuid.uuid4())}


@pytest.fixture
def user_ctx_a() -> Dict[str, Any]:
    return {"id": 9001, "company_id": 7001, "role": "user", "is_admin": False}


@pytest.fixture
def user_ctx_b() -> Dict[str, Any]:
    return {"id": 9002, "company_id": 7002, "role": "user", "is_admin": False}


@pytest.fixture
def admin_ctx_a() -> Dict[str, Any]:
    return {"id": 9099, "company_id": 7001, "role": "admin", "is_admin": True}


def _seed_session(cur: Any, session_uid: str, user_id: int, company_id: int) -> None:
    """Insert a canary dbsmart_sessions row under the *currently applied* RLS ctx."""
    cur.execute(
        """
        INSERT INTO dbsmart_sessions
            (session_uid, user_id, company_id, source_id, current_step, status, context)
        VALUES
            (%s::uuid, %s, %s, NULL, 0, 'active', '{}'::jsonb)
        """,
        (session_uid, user_id, company_id),
    )


def _count_visible(cur: Any, session_uid: str) -> int:
    cur.execute(
        "SELECT COUNT(*) FROM dbsmart_sessions WHERE session_uid = %s::uuid",
        (session_uid,),
    )
    return int(cur.fetchone()[0])


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE happy: owner-company user sees its own row
# ─────────────────────────────────────────────────────────────────────────────


def test_owner_company_allow(db_conn, user_ctx_a, fresh_session_uids):
    """User with company_id=X can read its OWN session row."""
    uid = fresh_session_uids["tenant_a"]
    with db_conn.cursor() as cur:
        apply_vyra_user_context(cur, user_ctx_a)
        _seed_session(cur, uid, user_ctx_a["id"], user_ctx_a["company_id"])
        assert _count_visible(cur, uid) == 1, "owner must see its own RLS-scoped row"


# ─────────────────────────────────────────────────────────────────────────────
# ARES negative: non-owner tenant cannot read another tenant's row
# ─────────────────────────────────────────────────────────────────────────────


def test_non_owner_company_deny(db_conn, user_ctx_a, user_ctx_b, fresh_session_uids):
    """User with company_id=Y querying tenant_X session uid → 0 rows."""
    uid_a = fresh_session_uids["tenant_a"]
    with db_conn.cursor() as cur:
        # 1) Seed under tenant A.
        apply_vyra_user_context(cur, user_ctx_a)
        _seed_session(cur, uid_a, user_ctx_a["id"], user_ctx_a["company_id"])
        assert _count_visible(cur, uid_a) == 1  # sanity

        # 2) Switch GUCs to tenant B (same transaction is fine for SET LOCAL).
        clear_vyra_user_context(cur)
        apply_vyra_user_context(cur, user_ctx_b)

        # 3) Tenant B must NOT see tenant A's row.
        assert _count_visible(cur, uid_a) == 0, (
            "ARES: cross-tenant read leaked — RLS policy not enforcing company_id"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ARES negative: missing RLS context → fail-closed
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_rls_context_fail_closed(db_conn, fresh_session_uids):
    """No SET LOCAL ⇒ policy default-deny ⇒ 0 visible rows for protected tables.

    We assert the *application-layer* contract: callers that try to skip
    `apply_vyra_user_context` cannot accidentally see other tenants' data.
    The policy compares `current_setting('vyra.company_id', true)::int`; with
    the GUC unset, the cast either errors (rolled back) or returns NULL → no row.
    """
    uid = fresh_session_uids["tenant_a"]
    with db_conn.cursor() as cur:
        # First seed *with* a context so a row exists.
        apply_vyra_user_context(cur, {"id": 9003, "company_id": 7003, "is_admin": False})
        _seed_session(cur, uid, 9003, 7003)
        clear_vyra_user_context(cur)

    # Open a NEW cursor *without* applying context — query must yield 0 rows.
    with db_conn.cursor() as cur2:
        try:
            count = _count_visible(cur2, uid)
        except Exception:
            # Acceptable fail-closed: policy/cast aborts with an exception.
            db_conn.rollback()
            return
        assert count == 0, "fail-closed violated: rows visible without RLS context"


# ─────────────────────────────────────────────────────────────────────────────
# TYCHE edge: admin within own tenant
# ─────────────────────────────────────────────────────────────────────────────


def test_admin_within_own_tenant_allow(db_conn, admin_ctx_a, fresh_session_uids):
    """Admin user sees rows in its OWN company_id; admin flag is NOT cross-tenant."""
    uid = fresh_session_uids["tenant_a"]
    with db_conn.cursor() as cur:
        apply_vyra_user_context(cur, admin_ctx_a)
        _seed_session(cur, uid, admin_ctx_a["id"], admin_ctx_a["company_id"])
        assert _count_visible(cur, uid) == 1


def test_admin_flag_does_not_leak_cross_tenant(
    db_conn, admin_ctx_a, user_ctx_b, fresh_session_uids
):
    """ARES: admin within tenant_A must NOT magically see tenant_B's rows.

    Admin bypass — if implemented — applies to the admin's OWN company_id only;
    `is_admin=true` is not a cross-tenant override.
    """
    uid_b = fresh_session_uids["tenant_b"]
    with db_conn.cursor() as cur:
        apply_vyra_user_context(cur, user_ctx_b)
        _seed_session(cur, uid_b, user_ctx_b["id"], user_ctx_b["company_id"])
        clear_vyra_user_context(cur)
        apply_vyra_user_context(cur, admin_ctx_a)
        # admin_a's company_id = 7001 ≠ 7002 → must NOT see uid_b.
        assert _count_visible(cur, uid_b) == 0, (
            "ARES: admin flag leaked across tenants — admin bypass must be scoped"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ARES negative: malformed ctx never reaches the DB
# ─────────────────────────────────────────────────────────────────────────────


def test_apply_with_malformed_ctx_raises_before_db(db_conn):
    """Sanity: validation aborts before any set_config — covered also in unit suite."""
    with db_conn.cursor() as cur:
        with pytest.raises(RLSContextError):
            apply_vyra_user_context(cur, {"company_id": 1, "is_admin": False})  # missing id
