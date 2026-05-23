"""Engine-specific cursor streaming (v3.30.0 FAZ 3 P35).

`_configure_engine_cursor()` davranış matrisi:

    | dialect    | beklenen attr/etki                                |
    |------------|---------------------------------------------------|
    | oracle     | cursor.arraysize=500, cursor.prefetchrows=500     |
    | mssql      | cursor.arraysize=500 (pyodbc); pymssql → no-op    |
    | mysql      | preferred_cursorclass="SSCursor" (info-only)      |
    | postgresql | no-op (caller named cursor + itersize)            |

Driver yokluğu (ImportError) yutulmalı; cursor yine çalışmalı (fallback path
zaten generic fetchmany(batch_size) ile mevcut).
"""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any, Dict, List

import pytest

from app.services.db_smart import sql_executor_stream as ses


# ─────────────────────────────────────────────────────────────
# Cursor stubs — engine başına farklı attribute surface
# ─────────────────────────────────────────────────────────────


class _OracleCursorStub:
    """oracledb cursor: arraysize + prefetchrows attribute'ları var."""

    def __init__(self):
        self.arraysize = 100   # oracledb default
        self.prefetchrows = 2  # oracledb default


class _MssqlPyodbcCursorStub:
    """pyodbc cursor: arraysize var (default 1)."""

    def __init__(self):
        self.arraysize = 1


class _MssqlPymssqlCursorStub:
    """pymssql cursor: arraysize yok → no-op beklenir."""

    pass


class _MysqlBufferedCursorStub:
    """pymysql default (buffered) cursor — arraysize taşımaz."""

    pass


class _MysqlSSCursorStub:
    """pymysql SSCursor sınıfı — isinstance kıyası için."""

    pass


class _PgCursorStub:
    """psycopg2 named cursor: itersize destekler ama _configure no-op olmalı."""

    def __init__(self):
        self.itersize = None


# ─────────────────────────────────────────────────────────────
# Oracle path — arraysize + prefetchrows
# ─────────────────────────────────────────────────────────────


def test_oracle_sets_arraysize_and_prefetchrows():
    cur = _OracleCursorStub()
    applied = ses._configure_engine_cursor(cur, "oracle")
    assert cur.arraysize == ses.ENGINE_FETCH_BATCH == 500
    assert cur.prefetchrows == ses.ENGINE_FETCH_BATCH == 500
    assert applied == {"arraysize": 500, "prefetchrows": 500}


def test_oracle_missing_prefetchrows_attr_skipped():
    """Eski oracledb sürümü: yalnızca arraysize var, prefetchrows YOK."""

    class _Old(_OracleCursorStub):
        def __init__(self):
            self.arraysize = 100
            # NOT: prefetchrows attribute'u tanımlanmıyor

    cur = _Old()
    applied = ses._configure_engine_cursor(cur, "oracle")
    assert applied == {"arraysize": 500}
    assert not hasattr(cur, "prefetchrows")


# ─────────────────────────────────────────────────────────────
# MSSQL path — pyodbc arraysize / pymssql no-op
# ─────────────────────────────────────────────────────────────


def test_mssql_pyodbc_sets_arraysize():
    cur = _MssqlPyodbcCursorStub()
    applied = ses._configure_engine_cursor(cur, "mssql")
    assert cur.arraysize == 500
    assert applied == {"arraysize": 500}


def test_mssql_pymssql_noop_when_attr_missing():
    cur = _MssqlPymssqlCursorStub()
    applied = ses._configure_engine_cursor(cur, "mssql")
    assert applied == {}
    assert not hasattr(cur, "arraysize")


# ─────────────────────────────────────────────────────────────
# MySQL path — SSCursor info / driver absence
# ─────────────────────────────────────────────────────────────


def test_mysql_reports_preferred_sscursor_when_driver_present(monkeypatch):
    """pymysql.cursors mevcut + SSCursor sınıfı bulunabiliyor."""
    fake_cursors = ModuleType("pymysql.cursors")
    fake_cursors.SSCursor = _MysqlSSCursorStub
    fake_pkg = ModuleType("pymysql")
    fake_pkg.cursors = fake_cursors
    monkeypatch.setitem(sys.modules, "pymysql", fake_pkg)
    monkeypatch.setitem(sys.modules, "pymysql.cursors", fake_cursors)

    cur = _MysqlBufferedCursorStub()
    applied = ses._configure_engine_cursor(cur, "mysql")
    assert applied.get("preferred_cursorclass") == "SSCursor"


def test_mysql_with_sscursor_instance_no_warning(monkeypatch):
    """Cursor zaten SSCursor instance ise sadece info döner — recommend log atılmaz."""
    fake_cursors = ModuleType("pymysql.cursors")
    fake_cursors.SSCursor = _MysqlSSCursorStub
    fake_pkg = ModuleType("pymysql")
    fake_pkg.cursors = fake_cursors
    monkeypatch.setitem(sys.modules, "pymysql", fake_pkg)
    monkeypatch.setitem(sys.modules, "pymysql.cursors", fake_cursors)

    cur = _MysqlSSCursorStub()
    applied = ses._configure_engine_cursor(cur, "mysql")
    assert applied == {"preferred_cursorclass": "SSCursor"}


def test_mysql_driver_absent_swallowed(monkeypatch):
    """pymysql import edilemezse ImportError swallow + boş applied döner."""
    # `pymysql` ve alt modüllerini import edilemez yap
    monkeypatch.setitem(sys.modules, "pymysql", None)
    monkeypatch.setitem(sys.modules, "pymysql.cursors", None)

    cur = _MysqlBufferedCursorStub()
    applied = ses._configure_engine_cursor(cur, "mysql")
    assert applied == {}  # ImportError swallowed


# ─────────────────────────────────────────────────────────────
# PostgreSQL path — no-op (caller already configured)
# ─────────────────────────────────────────────────────────────


def test_postgresql_is_noop():
    cur = _PgCursorStub()
    applied = ses._configure_engine_cursor(cur, "postgresql")
    assert applied == {}
    # itersize'a dokunulmamış olmalı (caller sets it)
    assert cur.itersize is None


# ─────────────────────────────────────────────────────────────
# Unknown / empty dialect → no-op (defensive)
# ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("d", ["", None, "snowflake", "redshift", "UNKNOWN"])
def test_unknown_dialect_noop(d):
    cur = SimpleNamespace(arraysize=99)
    applied = ses._configure_engine_cursor(cur, d)  # type: ignore[arg-type]
    assert applied == {}
    assert cur.arraysize == 99  # unchanged


# ─────────────────────────────────────────────────────────────
# Snapshot / matrix — 4 dialect default expectation
# ─────────────────────────────────────────────────────────────


def test_dialect_snapshot_matrix(monkeypatch):
    """4 dialect için _configure_engine_cursor çıkış sözleşmesi."""
    # pymysql sahte modül yükle (mysql path için)
    fake_cursors = ModuleType("pymysql.cursors")
    fake_cursors.SSCursor = _MysqlSSCursorStub
    fake_pkg = ModuleType("pymysql")
    fake_pkg.cursors = fake_cursors
    monkeypatch.setitem(sys.modules, "pymysql", fake_pkg)
    monkeypatch.setitem(sys.modules, "pymysql.cursors", fake_cursors)

    matrix: Dict[str, Dict[str, Any]] = {
        "oracle": ses._configure_engine_cursor(_OracleCursorStub(), "oracle"),
        "mssql": ses._configure_engine_cursor(_MssqlPyodbcCursorStub(), "mssql"),
        "mysql": ses._configure_engine_cursor(_MysqlBufferedCursorStub(), "mysql"),
        "postgresql": ses._configure_engine_cursor(_PgCursorStub(), "postgresql"),
    }
    assert matrix["oracle"] == {"arraysize": 500, "prefetchrows": 500}
    assert matrix["mssql"] == {"arraysize": 500}
    assert matrix["mysql"] == {"preferred_cursorclass": "SSCursor"}
    assert matrix["postgresql"] == {}


# ─────────────────────────────────────────────────────────────
# Integration: stream_safe_sql still works with engine cursor wired in
# ─────────────────────────────────────────────────────────────


class _FakeCursor:
    """Generic fetchmany cursor for integration smoke (mirrors existing test stub)."""

    def __init__(self, columns: List[str], rows: List[List[Any]]):
        self._cols = columns
        self._rows = list(rows)
        self.arraysize = 1
        self.prefetchrows = 1
        self._pos = 0
        self.closed = False

    @property
    def description(self):
        return [(c,) for c in self._cols]

    def execute(self, sql, params=None):
        self._executed = sql

    def fetchmany(self, n):
        chunk = self._rows[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, cur):
        self._cur = cur
        self.closed = False
        self.last_cursor_name = None

    def cursor(self, name=None):
        if name is not None:
            self.last_cursor_name = name
        return self._cur

    def close(self):
        self.closed = True


def _install_fake_connector(monkeypatch, conn):
    fake_mod = ModuleType("app.services.ds_learning_service")
    fake_mod._get_db_connector = lambda src, password: (conn, "oracle")
    monkeypatch.setitem(sys.modules, "app.services.ds_learning_service", fake_mod)


def test_oracle_stream_applies_cursor_tuning_end_to_end(monkeypatch):
    cur = _FakeCursor(["id"], [[i] for i in range(3)])
    conn = _FakeConn(cur)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT id FROM t",
        {"id": 1, "db_type": "oracle"},
        "oracle",
        batch_size=10,
    ))
    # arraysize/prefetchrows ENGINE_FETCH_BATCH'e set edilmiş olmalı
    assert cur.arraysize == ses.ENGINE_FETCH_BATCH
    assert cur.prefetchrows == ses.ENGINE_FETCH_BATCH
    assert any(e["type"] == "rows" for e in events)
    assert events[-1]["type"] == "end"
    assert cur.closed and conn.closed
