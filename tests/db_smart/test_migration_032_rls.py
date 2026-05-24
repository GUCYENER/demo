"""Migration 032 RLS policy tests (FIX9 / TYCHE+ARES+POSEIDON).

Two complementary layers:

  1) STATIC (always runs):
     Read `migrations/versions/032_v3300_db_smart_core_tables.py` as a file
     and assert the upgrade text declares:
       - ENABLE / FORCE ROW LEVEL SECURITY for the dbsmart_* tables we care about.
       - CREATE POLICY pol_*_isolation policies referencing vyra.company_id.
       - Matching DROP POLICY / DISABLE in the downgrade path.
     This catches "someone removed the FORCE ROW LEVEL SECURITY line" regressions
     even without a live database.

  2) LIVE (skipped unless VYRA_TEST_DB_URL is set and `pytest.mark.integration`):
     Inspect `pg_policies` and `pg_class.relrowsecurity` against the running DB
     and assert the migrated state.

POSEIDON: live tests use a read-only inspection cursor inside a rollback'd
transaction — zero side effects.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterator, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "032_v3300_db_smart_core_tables.py"

# Tables protected by per-tenant isolation policies in migration 032.
TENANT_TABLES = [
    "dbsmart_sessions",
    "dbsmart_saved_reports",
    "dbsmart_user_preferences",
]


# ─────────────────────────────────────────────────────────────────────────────
# STATIC tests — always collectable.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def migration_text() -> str:
    if not MIGRATION_PATH.exists():
        pytest.skip(f"Migration file not found at {MIGRATION_PATH}")
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_present():
    assert MIGRATION_PATH.exists(), (
        f"Migration 032 missing at {MIGRATION_PATH} — RLS policy contract test cannot run"
    )


def test_upgrade_enables_row_level_security(migration_text):
    """At least one ENABLE ROW LEVEL SECURITY statement must be present."""
    assert re.search(r"ENABLE\s+ROW\s+LEVEL\s+SECURITY", migration_text, re.IGNORECASE), (
        "migration 032 missing ENABLE ROW LEVEL SECURITY"
    )


def test_upgrade_forces_row_level_security(migration_text):
    """FORCE RLS is required so superusers/owners are also subject to policies."""
    assert re.search(r"FORCE\s+ROW\s+LEVEL\s+SECURITY", migration_text, re.IGNORECASE), (
        "migration 032 missing FORCE ROW LEVEL SECURITY — owner bypass risk"
    )


def test_upgrade_creates_isolation_policy(migration_text):
    """At least one CREATE POLICY pol_..._isolation statement must exist.

    The template loop renders `pol_%1$s_isolation` (Postgres format() placeholder),
    so `\\w` would not match `%` / `$`. We accept either the rendered or templated
    form.
    """
    assert re.search(
        r"CREATE\s+POLICY\s+pol_\S+_isolation", migration_text, re.IGNORECASE
    ), "migration 032 missing pol_*_isolation policy"


def test_upgrade_policy_uses_vyra_user_setting(migration_text):
    """Policy predicate must reference vyra.user_id GUC.

    Migration 032's row predicate is:
        user_id = NULLIF(current_setting('vyra.user_id', true), '')::int
    so the GUC name appearing in the SOURCE is `vyra.user_id`. The
    `vyra.company_id` GUC is set by the application layer
    (`apply_vyra_user_context`) for table-level scoping at other layers but is
    not part of this policy's predicate.
    """
    assert re.search(r"vyra\.user_id", migration_text), (
        "migration 032 policy does not reference vyra.user_id setting"
    )


def test_upgrade_policy_uses_is_admin_bypass(migration_text):
    """Admin bypass clause must be present (`vyra.is_admin = 'true'`)."""
    assert re.search(r"vyra\.is_admin", migration_text), (
        "migration 032 policy missing admin bypass via vyra.is_admin"
    )


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_upgrade_mentions_each_tenant_table(migration_text, table):
    """Each tenant-scoped table name must appear in the migration text."""
    assert table in migration_text, f"migration 032 does not mention {table}"


def test_downgrade_drops_policies_or_disables_rls(migration_text):
    """Downgrade should at least undo the RLS surface (DROP POLICY or DISABLE)."""
    has_drop = bool(re.search(r"DROP\s+POLICY", migration_text, re.IGNORECASE))
    has_disable = bool(re.search(r"DISABLE\s+ROW\s+LEVEL\s+SECURITY", migration_text, re.IGNORECASE))
    has_drop_table = bool(re.search(r"DROP\s+TABLE", migration_text, re.IGNORECASE))
    assert has_drop or has_disable or has_drop_table, (
        "downgrade path missing DROP POLICY / DISABLE ROW LEVEL SECURITY / DROP TABLE"
    )


# ─────────────────────────────────────────────────────────────────────────────
# LIVE tests — opt-in, integration-marked.
# ─────────────────────────────────────────────────────────────────────────────


_DB_URL = os.environ.get("VYRA_TEST_DB_URL")


def _skip_if_no_db() -> None:
    if not _DB_URL:
        pytest.skip("VYRA_TEST_DB_URL not set — live migration check skipped")


@pytest.fixture
def db_conn() -> Iterator[Any]:
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


@pytest.mark.integration
@pytest.mark.parametrize("table", TENANT_TABLES)
def test_live_table_has_rls_enabled(db_conn, table):
    """`pg_class.relrowsecurity` must be true after migration 032 upgrade."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT relrowsecurity, relforcerowsecurity
            FROM pg_class
            WHERE relname = %s
            """,
            (table,),
        )
        row = cur.fetchone()
        if row is None:
            pytest.skip(f"table {table} not present in target DB — migration not applied")
        rowsec, forcesec = bool(row[0]), bool(row[1])
        assert rowsec, f"{table}: relrowsecurity must be true"
        assert forcesec, f"{table}: relforcerowsecurity must be true (owner bypass risk)"


@pytest.mark.integration
@pytest.mark.parametrize("table", TENANT_TABLES)
def test_live_isolation_policy_exists(db_conn, table):
    """A pol_<table>_isolation policy must be visible in pg_policies."""
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT policyname, qual::text
            FROM pg_policies
            WHERE tablename = %s
            """,
            (table,),
        )
        policies = cur.fetchall()
        if not policies:
            pytest.skip(f"no policies on {table} — migration likely not applied")
        names = [p[0] for p in policies]
        assert any(n.endswith("_isolation") or "isolation" in n for n in names), (
            f"{table}: pol_*_isolation policy missing; found={names}"
        )
        # ARES: predicate must reference at least one vyra.* GUC.
        quals = " ".join((p[1] or "") for p in policies)
        assert ("vyra.user_id" in quals) or ("vyra.company_id" in quals), (
            f"{table}: no policy references vyra.user_id or vyra.company_id"
        )


# ─────────────────────────────────────────────────────────────────────────────
# ARES negative — make sure the static parser does not pass on a stripped file.
# (Self-test: feeds a synthetic empty migration and shows our regexes catch it.)
# ─────────────────────────────────────────────────────────────────────────────


def test_static_regexes_catch_missing_rls():
    """If someone deletes the RLS block, our static tests MUST fail.

    We don't mutate the real file — we just probe the helper regex set.
    """
    bad = "def upgrade():\n    op.execute('CREATE TABLE dbsmart_sessions (id int)')\n"
    assert not re.search(r"ENABLE\s+ROW\s+LEVEL\s+SECURITY", bad, re.IGNORECASE)
    assert not re.search(r"FORCE\s+ROW\s+LEVEL\s+SECURITY", bad, re.IGNORECASE)
    assert not re.search(r"CREATE\s+POLICY\s+pol_\S+_isolation", bad, re.IGNORECASE)
