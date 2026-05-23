"""sql_executor_stream — SSE-compatible streaming executor (v3.30.0 FAZ 3 P15 G3.2)."""
from __future__ import annotations

import sys
from types import ModuleType
from typing import Any, Dict, Iterator, List

import pytest

from app.services.db_smart import sql_executor_stream as ses


# ─────────────────────────────────────────────────────────────
# Fake DB connector — _get_db_connector monkeypatch'i
# ─────────────────────────────────────────────────────────────

class _FakeCursor:
    def __init__(self, columns: List[str], rows: List[List[Any]],
                 raise_on_execute: bool = False):
        self._cols = columns
        self._rows = list(rows)
        self.itersize = None
        self._executed = None
        self._pos = 0
        self._raise = raise_on_execute
        self.closed = False

    @property
    def description(self):
        return [(c,) for c in self._cols]

    def execute(self, sql, params=None):
        self._executed = sql
        if self._raise:
            raise RuntimeError("execute failed")

    def fetchmany(self, n):
        chunk = self._rows[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def close(self):
        self.closed = True


class _FakeConn:
    def __init__(self, cur: _FakeCursor, supports_named: bool = True):
        self._cur = cur
        self._supports_named = supports_named
        self.closed = False
        self.last_cursor_name = None

    def cursor(self, name=None):
        if name is not None:
            if not self._supports_named:
                raise TypeError("named cursor not supported")
            self.last_cursor_name = name
        return self._cur

    def close(self):
        self.closed = True


def _install_fake_connector(monkeypatch, conn):
    """ds_learning_service._get_db_connector → (conn, dialect_str) tuple döndürsün.

    Real signature: _get_db_connector(source: dict, password: str) -> (conn, dialect).
    """
    fake_mod = ModuleType("app.services.ds_learning_service")
    fake_mod._get_db_connector = lambda src, password: (conn, "postgresql") if conn is not None else (None, None)
    monkeypatch.setitem(sys.modules, "app.services.ds_learning_service", fake_mod)


# ─────────────────────────────────────────────────────────────
# Pre-flight guards (validate_sql + whitelist + dialect)
# ─────────────────────────────────────────────────────────────

def test_empty_sql_emits_error():
    events = list(ses.stream_safe_sql("", {"id": 1}, "postgresql"))
    assert events == [{"type": "error", "message": "SQL boş."}]


def test_unsupported_dialect_emits_error():
    events = list(ses.stream_safe_sql(
        "SELECT 1", {"id": 1}, "snowflake",
    ))
    assert any(e["type"] == "error" and "dialect" in e["message"].lower() for e in events)


def test_invalid_sql_security_rejection():
    events = list(ses.stream_safe_sql(
        "DROP TABLE users", {"id": 1}, "postgresql",
    ))
    assert any(e["type"] == "error" and "Güvenlik" in e["message"] for e in events)


def test_empty_source_dict_rejected():
    events = list(ses.stream_safe_sql("SELECT 1", {}, "postgresql"))
    assert any(e["type"] == "error" and "data_source" in e["message"] for e in events)


def test_whitelist_blocks_unknown_table(monkeypatch):
    cur = _FakeCursor(["id"], [[1]])
    conn = _FakeConn(cur)
    _install_fake_connector(monkeypatch, conn)
    events = list(ses.stream_safe_sql(
        "SELECT * FROM orders",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
        allowed_tables=["users"],  # 'orders' yok
    ))
    assert any(e["type"] == "error" and ("Whitelist" in e["message"] or "whitelist" in e["message"].lower()) for e in events)


# ─────────────────────────────────────────────────────────────
# PG streaming path — named cursor + fetchmany batching
# ─────────────────────────────────────────────────────────────

def test_postgresql_uses_named_cursor(monkeypatch):
    cur = _FakeCursor(["id", "name"], [[1, "a"], [2, "b"]])
    conn = _FakeConn(cur, supports_named=True)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT id, name FROM users",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
        batch_size=10,
    ))
    # Named cursor adı verilmiş olmalı
    assert conn.last_cursor_name is not None
    assert conn.last_cursor_name.startswith("vyra_dbsmart_")
    # cur.itersize batch_size ile set edildi
    assert cur.itersize == 10


def test_postgresql_named_cursor_fallback_when_unsupported(monkeypatch):
    cur = _FakeCursor(["x"], [[1]])
    conn = _FakeConn(cur, supports_named=False)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT x FROM t",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
    ))
    # Named cursor reddedildi → standart cursor; sorgu yine de çalışmalı
    assert any(e["type"] == "rows" for e in events)


def test_event_sequence_complete(monkeypatch):
    cur = _FakeCursor(["id"], [[i] for i in range(5)])
    conn = _FakeConn(cur)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT id FROM t",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
        batch_size=2,
    ))
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert "columns" in types
    assert types.count("rows") >= 2  # 5 satır / 2 batch = 3 batch
    assert types[-1] == "end"


def test_rows_payload_is_lists(monkeypatch):
    """Row tuple'larının list'e dönüştürüldüğünü doğrula (JSON-serializable)."""
    cur = _FakeCursor(["id"], [(1,), (2,)])  # tuple input
    conn = _FakeConn(cur)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT id FROM t",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
    ))
    row_events = [e for e in events if e["type"] == "rows"]
    assert row_events
    for re in row_events:
        for r in re["rows"]:
            assert isinstance(r, list)


def test_end_event_has_row_count(monkeypatch):
    cur = _FakeCursor(["id"], [[i] for i in range(7)])
    conn = _FakeConn(cur)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT id FROM t",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
        batch_size=3,
    ))
    end = next(e for e in events if e["type"] == "end")
    assert end["row_count"] == 7
    assert "elapsed_ms" in end


def test_max_rows_truncation(monkeypatch):
    cur = _FakeCursor(["id"], [[i] for i in range(50)])
    conn = _FakeConn(cur)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT id FROM t",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
        batch_size=10,
        max_rows=15,
    ))
    end = next(e for e in events if e["type"] == "end")
    assert end["truncated"] is True
    assert end["row_count"] <= 15


# ─────────────────────────────────────────────────────────────
# Non-PG dialect — standart cursor, name=None
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dialect", ["mysql", "mssql", "oracle"])
def test_non_pg_uses_standard_cursor(dialect, monkeypatch):
    cur = _FakeCursor(["c"], [[1]])
    conn = _FakeConn(cur)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT c FROM t",
        {"id": 1, "db_type": dialect},
        dialect,
    ))
    # Named cursor talep edilmemiş olmalı (cursor() name kwarg'ı None ile çağrılır)
    assert conn.last_cursor_name is None
    assert any(e["type"] == "rows" for e in events)


# ─────────────────────────────────────────────────────────────
# Exception → error event (cursor sızıntısı yok)
# ─────────────────────────────────────────────────────────────

def test_execute_exception_emits_error_and_closes_cursor(monkeypatch):
    cur = _FakeCursor(["id"], [], raise_on_execute=True)
    conn = _FakeConn(cur)
    _install_fake_connector(monkeypatch, conn)

    events = list(ses.stream_safe_sql(
        "SELECT id FROM t",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
    ))
    assert any(e["type"] == "error" for e in events)
    assert cur.closed is True
    assert conn.closed is True


def test_connector_returns_none_emits_empty_safely(monkeypatch):
    _install_fake_connector(monkeypatch, None)  # conn=None
    events = list(ses.stream_safe_sql(
        "SELECT 1",
        {"id": 1, "db_type": "postgresql"},
        "postgresql",
    ))
    # start + end (boş sonuç) — error YOK çünkü generic protokol "no columns/rows" tolere eder
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert types[-1] == "end"
