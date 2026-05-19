"""VYRA v3.27.0 — Synthetic Templates Tests (A.END.1).

Pure-function rendering tests. No DB.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning.synthetic_templates import (
    TEMPLATE_KINDS,
    Relationship,
    render,
    render_all,
)


@pytest.fixture
def rel():
    return Relationship(
        id=1,
        from_schema="sales",
        from_table="orders",
        from_column="customer_id",
        to_schema="public",
        to_table="customers",
        to_column="id",
    )


class TestRender:
    @pytest.mark.parametrize("kind", list(TEMPLATE_KINDS))
    def test_each_kind_returns_non_empty_sql(self, rel, kind):
        rq = render(rel, kind, dialect="postgresql")
        assert rq.sql.strip()
        assert rq.template_kind == kind
        assert rq.dialect == "postgresql"

    def test_lookup_join_mentions_both_tables(self, rel):
        rq = render(rel, "LOOKUP_JOIN", dialect="postgresql")
        sql = rq.sql.lower()
        assert "orders" in sql
        assert "customers" in sql
        assert "join" in sql

    def test_aggregate_count_uses_count(self, rel):
        rq = render(rel, "AGGREGATE_COUNT", dialect="postgresql")
        assert "count(" in rq.sql.lower()

    def test_postgres_uses_limit(self, rel):
        rq = render(rel, "LOOKUP_JOIN", dialect="postgresql")
        assert "limit" in rq.sql.lower()

    def test_oracle_uses_fetch_first(self, rel):
        rq = render(rel, "LOOKUP_JOIN", dialect="oracle")
        # Oracle: ROWNUM or FETCH FIRST (we accept either)
        s = rq.sql.lower()
        assert ("fetch first" in s) or ("rownum" in s)

    def test_mssql_uses_top(self, rel):
        rq = render(rel, "LOOKUP_JOIN", dialect="mssql")
        assert "top" in rq.sql.lower()

    def test_unknown_kind_raises(self, rel):
        with pytest.raises(Exception):
            render(rel, "UNKNOWN_KIND", dialect="postgresql")


class TestRenderAll:
    def test_returns_one_per_template_kind(self, rel):
        out = render_all(rel, dialect="postgresql")
        kinds = [r.template_kind for r in out]
        assert set(kinds) == set(TEMPLATE_KINDS)
        assert len(out) == len(TEMPLATE_KINDS)

    def test_renders_question_in_turkish(self, rel):
        out = render_all(rel, dialect="postgresql")
        for rq in out:
            assert rq.question_tr
            assert isinstance(rq.question_tr, str)
