"""VYRA v3.32.0 — FK Loop Improvements Unit Tests (G3).

Plan: .agents/plans/2026-05-23_1645_fk_loop_v3320_improvements_v1.md
Ajan-A backend değişiklikleri için unit testler.

Test sınıfları:
    - TestCompositeFKGrouping        : constraint_name + fk_position bazlı gruplama
    - TestRowCountZeroEnforcement    : boş sonuç -> learned_queries'e yazma
    - TestDeclaredInferredDedupe     : aynı (from->to) çiftinde yüksek confidence
    - TestCircuitBreaker             : son 24h failure -> skip
    - TestJunctionIntegration        : is_junction=TRUE bridge -> render_junction_n2m
    - TestSelfRefQuestion            : self-ref question_tr mantıklı metin
    - TestCardinalityAwareSelection  : 1:1 -> AGGREGATE_COUNT atla

Strateji:
    Ajan-A henüz tamamlanmamışsa beklenen API'yi sınayan testler
    `@pytest.mark.xfail(strict=False)` ile işaretlenir; suite kırılmaz.
    `_MockCursor` ve `_MockExecutor` gerçek DB connection açmaz.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning import fk_synthetic_generator as fkgen
from app.services.db_learning import synthetic_templates as tmpl
from app.services.db_learning.synthetic_templates import (
    Relationship,
    render_aggregate_count,
    render_lookup_join,
)


# ============================================================
# Mock helpers
# ============================================================

class _MockCursor:
    """Script-tabanlı cursor mock.

    scripts: list of (sql_substring_pattern, rows). execute() çağrıldığında SQL
    içinde substring eşleşeni bulup fetchall/fetchone için kuyruğa atar.
    Boş kuyruk durumunda fetchall -> [], fetchone -> None.
    """

    def __init__(self, scripts: Optional[Sequence[Tuple[str, List[Any]]]] = None):
        self.scripts: List[Tuple[str, List[Any]]] = list(scripts or [])
        self.executed: List[Tuple[str, Optional[tuple]]] = []
        self._pending_rows: List[Any] = []
        self._last_sql: str = ""

    def execute(self, sql: str, params: Optional[tuple] = None) -> None:
        self.executed.append((sql, params))
        self._last_sql = sql
        self._pending_rows = self._match_rows(sql)

    def _match_rows(self, sql: str) -> List[Any]:
        norm = " ".join(sql.split()).lower()
        for pattern, rows in self.scripts:
            if pattern.lower() in norm:
                return list(rows)
        return []

    def fetchall(self) -> List[Any]:
        rows, self._pending_rows = self._pending_rows, []
        return rows

    def fetchone(self) -> Optional[Any]:
        if not self._pending_rows:
            return None
        row = self._pending_rows[0]
        self._pending_rows = self._pending_rows[1:]
        return row

    def close(self) -> None:
        pass


@dataclass
class _ExecResult:
    success: bool = True
    row_count: int = 1
    error: Optional[str] = None
    rows: List[Any] = field(default_factory=list)


class _MockExecutor:
    """SafeSQLExecutor mock — SQL pattern bazlı _ExecResult döner."""

    def __init__(self, default: Optional[_ExecResult] = None,
                 scripts: Optional[Dict[str, _ExecResult]] = None):
        self.default = default or _ExecResult(success=True, row_count=1)
        self.scripts: Dict[str, _ExecResult] = scripts or {}
        self.calls: List[str] = []

    def execute(self, sql: str, source: Any = None, dialect: str = "postgresql") -> _ExecResult:
        self.calls.append(sql)
        norm = " ".join(sql.split()).lower()
        for pattern, result in self.scripts.items():
            if pattern.lower() in norm:
                return result
        return self.default


def _make_rel(**kwargs) -> Relationship:
    """Default-doldurmalı Relationship factory.

    Ajan-A composite FK gruplaması için `from_columns`/`to_columns`/`constraint_name`
    alanları ekleyebilir. Mevcut dataclass tek-column tutuyor; eğer yeni alanlar
    eklendiyse kwargs ile geçirilebilir.
    """
    defaults: Dict[str, Any] = dict(
        id=1,
        from_schema="public",
        from_table="orders",
        from_column="customer_id",
        to_schema="public",
        to_table="customers",
        to_column="id",
    )
    defaults.update({k: v for k, v in kwargs.items()
                     if k in {"id", "from_schema", "from_table", "from_column",
                              "to_schema", "to_table", "to_column",
                              "cardinality_from", "cardinality_to", "is_junction"}})
    rel = Relationship(**defaults)
    # Ajan-A sonrası attribute'lar dinamik olarak set edilebilir
    for extra in ("from_columns", "to_columns", "constraint_name", "confidence_score"):
        if extra in kwargs:
            setattr(rel, extra, kwargs[extra])
    return rel


# ============================================================
# TestCompositeFKGrouping
# ============================================================

class TestCompositeFKGrouping:
    """Multi-column FK satırlarının `constraint_name` ile gruplanması."""

    def test_single_column_fk_unchanged(self):
        """Tek column FK eskiden olduğu gibi tek Relationship döner."""
        rows = [
            (1, "public", "orders", "customer_id",
             "public", "customers", "id"),
        ]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rows)])
        rels = fkgen._fetch_relationships(cur, source_id=42)
        assert len(rels) == 1
        rel = rels[0]
        assert rel.from_table == "orders"
        assert rel.from_column == "customer_id"
        # from_columns alanı (composite ext) varsa tek-element listesi tutmalı
        if hasattr(rel, "from_columns"):
            assert list(rel.from_columns) == ["customer_id"]
            assert list(rel.to_columns) == ["id"]

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 composite FK grouping", strict=False)
    def test_two_column_composite_groups_by_constraint_name(self):
        """Aynı constraint_name altında 2 satır -> tek composite Relationship.

        Beklenen API (Ajan-A sonrası):
          - `_fetch_relationships` constraint_name + fk_position bazlı groupBy yapar.
          - Dönen Relationship `from_columns=[c1, c2]`, `to_columns=[c1, c2]` taşır.
        """
        # ds_db_relationships satırları (constraint_name + fk_position eklenmiş)
        rows = [
            # (id, from_schema, from_table, from_column, to_schema, to_table,
            #  to_column, constraint_name, fk_position)
            (10, "public", "order_items", "order_id",
             "public", "orders", "id", "fk_order_items_orders", 1),
            (11, "public", "order_items", "tenant_id",
             "public", "orders", "tenant_id", "fk_order_items_orders", 2),
        ]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rows)])
        rels = fkgen._fetch_relationships(cur, source_id=42)
        assert len(rels) == 1
        rel = rels[0]
        assert list(rel.from_columns) == ["order_id", "tenant_id"]
        assert list(rel.to_columns) == ["id", "tenant_id"]

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 composite render", strict=False)
    def test_render_lookup_join_composite_uses_and_clause(self):
        """Composite Relationship -> SQL'de ON a.c1=b.c1 AND a.c2=b.c2."""
        rel = _make_rel(
            from_columns=["order_id", "tenant_id"],
            to_columns=["id", "tenant_id"],
            from_table="order_items",
            to_table="orders",
        )
        rq = render_lookup_join(rel, dialect="postgresql")
        # ON clause iki eşitliği AND ile birleştirmeli
        assert " AND " in rq.sql.upper()
        # her iki kolon adı SQL'de geçmeli
        assert "order_id" in rq.sql
        assert "tenant_id" in rq.sql

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 composite aggregate", strict=False)
    def test_render_aggregate_count_composite(self):
        """GROUP BY tüm to_columns'u içermeli."""
        rel = _make_rel(
            from_columns=["order_id", "tenant_id"],
            to_columns=["id", "tenant_id"],
            from_table="order_items",
            to_table="orders",
        )
        rq = render_aggregate_count(rel, dialect="postgresql")
        upper = rq.sql.upper()
        assert "GROUP BY" in upper
        # both to_columns must appear in GROUP BY tail
        gb_tail = upper.split("GROUP BY", 1)[1]
        assert "ID" in gb_tail
        assert "TENANT_ID" in gb_tail

    def test_null_constraint_name_falls_back_to_id(self):
        """constraint_name IS NULL -> her satır kendi id'siyle ayrı Relationship.

        Bu davranış mevcut implementasyonda zaten geçerli (constraint_name yok),
        Ajan-A sonrasında da fallback olarak korunmalı.
        """
        rows = [
            (1, "public", "t1", "x_id", "public", "t2", "id"),
            (2, "public", "t1", "y_id", "public", "t3", "id"),
        ]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rows)])
        rels = fkgen._fetch_relationships(cur, source_id=1)
        assert len(rels) == 2
        ids = sorted(r.id for r in rels)
        assert ids == [1, 2]


# ============================================================
# TestRowCountZeroEnforcement
# ============================================================

class TestRowCountZeroEnforcement:
    """Boş sonuç döndüren execute -> learned_queries'e YAZMA, skipped_empty++."""

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 row_count=0 enforcement + summary.skipped_empty",
                       strict=False)
    def test_empty_result_does_not_write_learned_query(self, monkeypatch):
        # Tek FK döndüren cursor
        rel_rows = [(1, "public", "orders", "customer_id",
                     "public", "customers", "id")]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rel_rows)])

        # _build_executor'u patchla
        executor = _MockExecutor(default=_ExecResult(success=True, row_count=0))
        monkeypatch.setattr(
            fkgen, "_build_executor",
            lambda source_id, dialect, company_id: (executor, {"id": source_id})
        )

        # record_successful_query çağrı sayacı
        calls: List[Dict[str, Any]] = []

        def _fake_record(*args, **kwargs):
            calls.append(kwargs)
            return {"status": "inserted", "id": 999}

        monkeypatch.setattr(fkgen, "record_successful_query", _fake_record)

        summary = fkgen.generate_for_source(
            cur, source_id=42, dialect="postgresql",
            template_kinds=["LOOKUP_JOIN"],
        )

        # row_count=0 olduğu için record_successful_query çağrılmamalı
        assert len(calls) == 0
        # summary'de skipped_empty alanı olmalı
        assert getattr(summary, "skipped_empty", 0) == 1
        # audit yazıldı (success=True ama learned_query_id=None)
        audit_executes = [
            sql for sql, _ in cur.executed
            if "ds_synthetic_query_runs" in sql.lower()
        ]
        assert len(audit_executes) >= 1


# ============================================================
# TestDeclaredInferredDedupe
# ============================================================

class TestDeclaredInferredDedupe:
    """Aynı (from->to) çifti farklı confidence ile mevcutsa yüksek confidence kalır."""

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 declared+inferred dedupe in _fetch_relationships",
                       strict=False)
    def test_duplicate_pair_keeps_higher_confidence(self):
        rows = [
            # confidence_score sütunu eklendiği varsayımı
            (1, "public", "orders", "customer_id",
             "public", "customers", "id", 1.0),
            (2, "public", "orders", "customer_id",
             "public", "customers", "id", 0.7),
        ]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rows)])
        rels = fkgen._fetch_relationships(cur, source_id=42)
        assert len(rels) == 1
        # yüksek confidence (id=1) kalmalı
        assert rels[0].id == 1
        if hasattr(rels[0], "confidence_score"):
            assert float(rels[0].confidence_score) == pytest.approx(1.0)


# ============================================================
# TestCircuitBreaker
# ============================================================

class TestCircuitBreaker:
    """Son 24h içinde failure varsa skip; 25+ saat önceki failure tekrar denenir."""

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 circuit breaker + summary.skipped_recent_failure",
                       strict=False)
    def test_recent_failure_skipped(self, monkeypatch):
        rel_rows = [(1, "public", "orders", "customer_id",
                     "public", "customers", "id")]
        cur = _MockCursor(scripts=[
            ("from ds_db_relationships", rel_rows),
            # Circuit breaker query: recent failure exists
            ("success = false", [(1,)]),
        ])
        executor = _MockExecutor(default=_ExecResult(success=True, row_count=5))
        monkeypatch.setattr(
            fkgen, "_build_executor",
            lambda source_id, dialect, company_id: (executor, {"id": source_id})
        )
        monkeypatch.setattr(
            fkgen, "record_successful_query",
            lambda *a, **kw: {"status": "inserted", "id": 1}
        )

        summary = fkgen.generate_for_source(
            cur, source_id=42, dialect="postgresql",
            template_kinds=["LOOKUP_JOIN"],
        )
        assert getattr(summary, "skipped_recent_failure", 0) >= 1
        # executor çağrılmamalı (skip happened)
        assert len(executor.calls) == 0

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 circuit breaker time window",
                       strict=False)
    def test_old_failure_retried(self, monkeypatch):
        rel_rows = [(1, "public", "orders", "customer_id",
                     "public", "customers", "id")]
        # Circuit breaker sorgusu boş (eski failure, 24h dışında)
        cur = _MockCursor(scripts=[("from ds_db_relationships", rel_rows)])
        executor = _MockExecutor(default=_ExecResult(success=True, row_count=5))
        monkeypatch.setattr(
            fkgen, "_build_executor",
            lambda source_id, dialect, company_id: (executor, {"id": source_id})
        )
        monkeypatch.setattr(
            fkgen, "record_successful_query",
            lambda *a, **kw: {"status": "inserted", "id": 1}
        )

        summary = fkgen.generate_for_source(
            cur, source_id=42, dialect="postgresql",
            template_kinds=["LOOKUP_JOIN"],
        )
        assert getattr(summary, "skipped_recent_failure", 0) == 0
        assert summary.success == 1


# ============================================================
# TestJunctionIntegration
# ============================================================

class TestJunctionIntegration:
    """is_junction=TRUE bridge tabloları için render_junction_n2m çağrılır."""

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 junction wiring in fk_synthetic_generator",
                       strict=False)
    def test_junction_table_triggers_n2m_template(self, monkeypatch):
        # Bridge table: user_role (user_id, role_id) — 2 FK satırı, is_junction=TRUE
        rel_rows = [
            (10, "public", "user_role", "user_id",
             "public", "users", "id", True, 0.9),
            (11, "public", "user_role", "role_id",
             "public", "roles", "id", True, 0.9),
        ]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rel_rows)])
        executor = _MockExecutor(default=_ExecResult(success=True, row_count=3))
        monkeypatch.setattr(
            fkgen, "_build_executor",
            lambda source_id, dialect, company_id: (executor, {"id": source_id})
        )
        monkeypatch.setattr(
            fkgen, "record_successful_query",
            lambda *a, **kw: {"status": "inserted", "id": 42}
        )

        summary = fkgen.generate_for_source(
            cur, source_id=1, dialect="postgresql",
        )
        # En az 1 junction success
        assert getattr(summary, "junction_success", 0) >= 1
        # Audit'te JUNCTION_N2M template_kind olmalı
        junction_audit = any(
            "JUNCTION_N2M" in (sql or "")
            for sql, _ in cur.executed
        )
        assert junction_audit

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 junction confidence gating",
                       strict=False)
    def test_low_confidence_junction_skipped(self, monkeypatch):
        rel_rows = [
            (10, "public", "user_role", "user_id",
             "public", "users", "id", True, 0.5),
            (11, "public", "user_role", "role_id",
             "public", "roles", "id", True, 0.5),
        ]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rel_rows)])
        executor = _MockExecutor(default=_ExecResult(success=True, row_count=3))
        monkeypatch.setattr(
            fkgen, "_build_executor",
            lambda source_id, dialect, company_id: (executor, {"id": source_id})
        )
        monkeypatch.setattr(
            fkgen, "record_successful_query",
            lambda *a, **kw: {"status": "inserted", "id": 42}
        )

        summary = fkgen.generate_for_source(
            cur, source_id=1, dialect="postgresql",
        )
        # Düşük confidence -> JUNCTION_N2M render edilmez
        assert getattr(summary, "junction_success", 0) == 0


# ============================================================
# TestSelfRefQuestion
# ============================================================

class TestSelfRefQuestion:
    """rel.from_table == rel.to_table -> mantıklı question_tr."""

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 self-ref question_tr improvement",
                       strict=False)
    def test_self_ref_lookup_join_question(self):
        rel = _make_rel(
            id=99,
            from_schema="public",
            from_table="employee",
            from_column="manager_id",
            to_schema="public",
            to_table="employee",
            to_column="id",
        )
        rq = render_lookup_join(rel, dialect="postgresql")
        q = (rq.question_tr or "").lower()
        # Anlamlı self-ref dili: "parent" veya "hiyerarşik" geçmeli
        assert ("parent" in q) or ("hiyerarşik" in q) or ("üst" in q)
        # YASAK: "X tablosundaki kayıtların ilgili X" cümlesi olmamalı
        bad = "employee tablosundaki kayıtların ilgili employee"
        assert bad not in q


# ============================================================
# TestCardinalityAwareSelection
# ============================================================

class TestCardinalityAwareSelection:
    """1:1 -> AGGREGATE_COUNT atla, NULL cardinality -> her iki template."""

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 cardinality-aware template selection",
                       strict=False)
    def test_one_to_one_skips_aggregate_count(self, monkeypatch):
        rel_rows = [
            # cardinality_from='1', cardinality_to='1'
            (1, "public", "user_profile", "user_id",
             "public", "users", "id", "1", "1"),
        ]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rel_rows)])
        executor = _MockExecutor(default=_ExecResult(success=True, row_count=2))
        monkeypatch.setattr(
            fkgen, "_build_executor",
            lambda source_id, dialect, company_id: (executor, {"id": source_id})
        )
        monkeypatch.setattr(
            fkgen, "record_successful_query",
            lambda *a, **kw: {"status": "inserted", "id": 1}
        )

        summary = fkgen.generate_for_source(
            cur, source_id=1, dialect="postgresql",
        )
        # AGGREGATE_COUNT execute edilmemeli
        assert all("COUNT(" not in sql.upper() for sql in executor.calls)

    @pytest.mark.xfail(reason="awaiting Ajan-A G1 cardinality-aware template selection",
                       strict=False)
    def test_unknown_cardinality_uses_both(self, monkeypatch):
        rel_rows = [
            # cardinality NULL -> default davranış (her iki template)
            (1, "public", "orders", "customer_id",
             "public", "customers", "id", None, None),
        ]
        cur = _MockCursor(scripts=[("from ds_db_relationships", rel_rows)])
        executor = _MockExecutor(default=_ExecResult(success=True, row_count=2))
        monkeypatch.setattr(
            fkgen, "_build_executor",
            lambda source_id, dialect, company_id: (executor, {"id": source_id})
        )
        monkeypatch.setattr(
            fkgen, "record_successful_query",
            lambda *a, **kw: {"status": "inserted", "id": 1}
        )

        summary = fkgen.generate_for_source(
            cur, source_id=1, dialect="postgresql",
        )
        # Hem LOOKUP_JOIN hem AGGREGATE_COUNT execute edilmeli
        assert any("COUNT(" in sql.upper() for sql in executor.calls)
        assert any("JOIN" in sql.upper() and "COUNT(" not in sql.upper()
                   for sql in executor.calls)


# ============================================================
# Smoke: mock helpers'ın kendisi
# ============================================================

class TestMockHelpers:
    """Mock infrastructure'ın doğru çalıştığını kontrol et."""

    def test_mock_cursor_returns_scripted_rows(self):
        cur = _MockCursor(scripts=[("select foo", [(1, "a"), (2, "b")])])
        cur.execute("SELECT foo FROM bar")
        assert cur.fetchall() == [(1, "a"), (2, "b")]

    def test_mock_cursor_empty_when_no_pattern_match(self):
        cur = _MockCursor(scripts=[("select foo", [(1,)])])
        cur.execute("SELECT baz FROM other")
        assert cur.fetchall() == []
        assert cur.fetchone() is None

    def test_mock_executor_returns_default(self):
        ex = _MockExecutor(default=_ExecResult(success=True, row_count=7))
        r = ex.execute("SELECT 1", source={}, dialect="postgresql")
        assert r.success is True
        assert r.row_count == 7

    def test_mock_executor_pattern_override(self):
        ex = _MockExecutor(
            default=_ExecResult(success=True, row_count=1),
            scripts={"count(": _ExecResult(success=True, row_count=0)},
        )
        r1 = ex.execute("SELECT * FROM t", source={}, dialect="postgresql")
        r2 = ex.execute("SELECT COUNT(*) FROM t", source={}, dialect="postgresql")
        assert r1.row_count == 1
        assert r2.row_count == 0
