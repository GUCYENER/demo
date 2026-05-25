"""VYRA v3.37.0 B1 — 047b backfill script regression suite.

Brief: .agents/in_flight/2026-05-25_2235_v3370_b1_load_source_fix.md
Owner: TYCHE+ARES (test author)

Hedef:
    - `--dry-run` modu DB'ye yazmıyor mu? Sayım doğru mu?
    - İkinci çalıştırmada 0 UPDATE (idempotent)?
    - data_sources tablosundaki bozuk db_type değerleri normalize ediliyor mu?

Stratejiler:
    - In-memory SQLite mock yerine fake cursor / fake connection kullanıyoruz
      (script saf psycopg2 cursor interface'i bekliyor; SQL dialect-spesifik
      bir özellik yok — basit UPDATE/SELECT COUNT).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, List, Optional, Tuple

import pytest


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "047b_v3370_saved_reports_db_type_backfill.py"
)


@pytest.fixture(scope="module")
def m047b():
    spec = importlib.util.spec_from_file_location("m047b", str(MIGRATION_PATH))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Fake DB (in-memory state machine)
# ---------------------------------------------------------------------------

class _FakeRows:
    """Minimum data_sources tablosu simülasyonu (sadece backfill için)."""

    def __init__(self, rows: List[dict]):
        self.rows = rows

    def count_targets(self) -> int:
        return sum(
            1 for r in self.rows
            if r.get("is_active") and r.get("db_type") in (None, "", "db_type")
        )

    def apply_update(self) -> int:
        count = 0
        for r in self.rows:
            if r.get("is_active") and r.get("db_type") in (None, "", "db_type"):
                r["db_type"] = "postgresql"
                count += 1
        return count


class _FakeCursor:
    def __init__(self, store: _FakeRows):
        self.store = store
        self._last_result: Optional[Tuple[Any, ...]] = None
        self.rowcount = 0

    def execute(self, sql: str, params: Any = None) -> None:
        s = " ".join(sql.split()).upper()
        if s.startswith("SELECT COUNT(*)"):
            self._last_result = (self.store.count_targets(),)
            self.rowcount = 1
        elif s.startswith("UPDATE DATA_SOURCES"):
            self.rowcount = self.store.apply_update()
            self._last_result = None
        else:  # pragma: no cover — script bunlardan başka SQL üretmiyor
            raise AssertionError(f"Beklenmeyen SQL: {sql}")

    def fetchone(self):
        return self._last_result

    def close(self):
        pass


class _FakeConn:
    def __init__(self, store: _FakeRows):
        self.store = store
        self.committed = False
        self.rolled_back = False
        self.autocommit = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self.store)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store_dirty():
    return _FakeRows([
        {"id": 1, "is_active": True, "db_type": "db_type"},     # bozuk literal
        {"id": 2, "is_active": True, "db_type": None},          # NULL
        {"id": 3, "is_active": True, "db_type": ""},            # boş
        {"id": 4, "is_active": True, "db_type": "postgresql"},  # zaten temiz
        {"id": 5, "is_active": False, "db_type": "db_type"},    # is_active=False, dokunma
        {"id": 6, "is_active": True, "db_type": "mssql"},       # zaten temiz
    ])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_047b_module_loads(m047b):
    """Module yüklenebilir + temel API expose ediliyor."""
    assert callable(m047b.run)
    assert callable(m047b.main)
    assert "postgresql" in m047b._SUPPORTED_DIALECTS


def test_047b_normalize_dialect_alias(m047b):
    assert m047b._normalize_dialect("postgres") == "postgresql"
    assert m047b._normalize_dialect("oracledb") == "oracle"
    assert m047b._normalize_dialect("sqlserver") == "mssql"
    assert m047b._normalize_dialect("mysql") == "mysql"
    # Whitelist dışı → postgresql fallback (F22c ile uyumlu)
    assert m047b._normalize_dialect("snowflake") == "postgresql"
    assert m047b._normalize_dialect(None) == "postgresql"
    assert m047b._normalize_dialect("") == "postgresql"


def test_047b_dry_run_no_mutation(m047b, store_dirty):
    """--dry-run sayım veriyor, DB değişmiyor, commit yok."""
    conn = _FakeConn(store_dirty)
    result = m047b.run(conn, dry_run=True)

    # 3 satır hedef (id=1,2,3); id=4/6 zaten temiz, id=5 inaktif.
    assert result["target_count"] == 3
    assert result["updated"] == 0
    assert result["dry_run"] is True

    # State değişmedi
    assert store_dirty.rows[0]["db_type"] == "db_type"
    assert store_dirty.rows[1]["db_type"] is None
    assert store_dirty.rows[2]["db_type"] == ""
    assert conn.committed is False


def test_047b_apply_updates_dirty_rows(m047b, store_dirty):
    """Dry-run KAPALI: bozuk değerler 'postgresql'e normalize ediliyor + commit."""
    conn = _FakeConn(store_dirty)
    result = m047b.run(conn, dry_run=False)

    assert result["target_count"] == 3
    assert result["updated"] == 3
    assert result["dry_run"] is False
    assert conn.committed is True

    # Temiz olanlara dokunulmadı
    assert store_dirty.rows[3]["db_type"] == "postgresql"  # zaten öyleydi
    assert store_dirty.rows[5]["db_type"] == "mssql"       # mssql korundu
    assert store_dirty.rows[4]["db_type"] == "db_type"     # inaktif → dokunma

    # Bozuk olanlar normalize
    assert store_dirty.rows[0]["db_type"] == "postgresql"
    assert store_dirty.rows[1]["db_type"] == "postgresql"
    assert store_dirty.rows[2]["db_type"] == "postgresql"


def test_047b_idempotent_second_run(m047b, store_dirty):
    """İkinci çalıştırmada 0 satır UPDATE — idempotent."""
    conn1 = _FakeConn(store_dirty)
    r1 = m047b.run(conn1, dry_run=False)
    assert r1["updated"] == 3

    conn2 = _FakeConn(store_dirty)
    r2 = m047b.run(conn2, dry_run=False)
    assert r2["target_count"] == 0
    assert r2["updated"] == 0


def test_047b_join_engine_info(m047b):
    """Engine hint'inden db_type inference: alias → whitelist → fallback."""
    # Brief'teki "connections.engine'den doğru db_type seçildi" expectation:
    # VYRA şemasında engine sütunu yok, ama inference helper alias normalize
    # garantisini veriyor — bu invariant'i doğruluyoruz.
    assert m047b._infer_db_type_from_engine("Postgres") == "postgresql"
    assert m047b._infer_db_type_from_engine("oracledb") == "oracle"
    assert m047b._infer_db_type_from_engine("SQL_Server") == "mssql"
    assert m047b._infer_db_type_from_engine("MySQL") == "mysql"
    assert m047b._infer_db_type_from_engine(None) == "postgresql"


def test_047b_rollback_on_error(m047b, monkeypatch):
    """UPDATE sırasında exception olursa rollback çağrılıyor + raise propagate ediliyor."""
    store = _FakeRows([{"id": 1, "is_active": True, "db_type": "db_type"}])
    conn = _FakeConn(store)

    # apply_update'i hata fırlatacak şekilde patch et.
    def _boom():
        raise RuntimeError("simulated db error")
    monkeypatch.setattr(store, "apply_update", _boom)

    with pytest.raises(RuntimeError):
        m047b.run(conn, dry_run=False)

    assert conn.rolled_back is True
    assert conn.committed is False


def test_047b_cli_dry_run_flag(m047b):
    """--dry-run CLI argümanı parse ediliyor."""
    parser = m047b._build_parser()
    args = parser.parse_args(["--dry-run"])
    assert args.dry_run is True

    args2 = parser.parse_args([])
    assert args2.dry_run is False
