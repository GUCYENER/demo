"""custom_metric_parser — NL→SQL + dbsmart_metric_library save (v3.30.0 FAZ 2 P11 G2.2)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.services.db_smart import custom_metric_parser as cmp


# ─────────────────────────────────────────────────────────────
# extract_intent_heuristic
# ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,expected_agg", [
    ("Toplam satış", "SUM"),
    ("Ortalama sipariş tutarı", "AVG"),
    ("Müşteri sayısı", "COUNT"),
    ("Kaç adet sipariş var", "COUNT"),
    ("En yüksek ciro", "MAX"),
    ("En düşük fiyat", "MIN"),
    ("Medyan tepki süresi", "MEDIAN"),
    ("Başarı oranı yüzde", "RATIO"),
])
def test_intent_agg_func_detected(q, expected_agg):
    intent = cmp.extract_intent_heuristic(q)
    assert intent["agg_func"] == expected_agg


def test_intent_empty_query_returns_blank():
    intent = cmp.extract_intent_heuristic("")
    assert intent == {"agg_func": None, "time_window": None, "group_hints": [], "raw": ""}


def test_intent_non_string_safe():
    intent = cmp.extract_intent_heuristic(None)  # type: ignore[arg-type]
    assert intent["agg_func"] is None


def test_intent_time_window_days():
    intent = cmp.extract_intent_heuristic("Son 30 gün toplam satış")
    assert intent["time_window"] == {"kind": "days", "n": 30}


def test_intent_time_window_this_month():
    intent = cmp.extract_intent_heuristic("Bu ay toplam ciro")
    assert intent["time_window"] is not None
    assert intent["time_window"]["kind"] == "this_month"


def test_intent_time_window_last_year():
    intent = cmp.extract_intent_heuristic("Geçen yıl satışlarımız")
    assert intent["time_window"]["kind"] == "last_year"


def test_intent_group_hints():
    intent = cmp.extract_intent_heuristic("Müşteri başına ortalama sipariş")
    assert "group_by_hint" in intent["group_hints"] or "group_by_entity" in intent["group_hints"]


def test_intent_group_by_time():
    intent = cmp.extract_intent_heuristic("Aya göre toplam satış")
    assert "group_by_time" in intent["group_hints"]


# ─────────────────────────────────────────────────────────────
# build_metric_schema_context
# ─────────────────────────────────────────────────────────────

class _SeqCursor:
    """Sıralı SELECT yanıtları döner. execute() çağrıları kategoriye göre cevaplar."""

    def __init__(self, source_name: str = "MyDB",
                 tables: Optional[Dict[int, Dict[str, Any]]] = None):
        self.source_name = source_name
        self.tables = tables or {}
        self._last: Any = None
        self._last_kind: Optional[str] = None
        self._last_rows: List[tuple] = []
        self.executed: List[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql.strip()[:60], params))
        s = sql.lower()
        if "from data_sources" in s:
            self._last_kind = "src"
            self._last = (self.source_name,)
            self._last_rows = []
        elif "from ds_db_objects" in s:
            tid = params[0]
            tbl = self.tables.get(int(tid))
            if tbl:
                self._last_kind = "obj"
                self._last = (int(tid), tbl["object_name"], tbl.get("te_id"))
                self._last_rows = []
            else:
                self._last_kind = "obj"
                self._last = None
                self._last_rows = []
        elif "from ds_column_enrichments" in s:
            tid = params[1]  # source_id, te_id, te_id, limit
            te_id = params[1]
            # Find table by te_id in self.tables
            cols = []
            for tbl in self.tables.values():
                if tbl.get("te_id") == te_id:
                    cols = tbl.get("columns", [])
                    break
            self._last_kind = "cols"
            self._last_rows = list(cols)
            self._last = cols[0] if cols else None
        else:
            self._last_kind = None
            self._last = None
            self._last_rows = []

    def fetchone(self):
        return self._last

    def fetchall(self):
        return list(self._last_rows)


def test_build_schema_context_empty_table_ids():
    cur = _SeqCursor()
    ctx = cmp.build_metric_schema_context(cur, source_id=1, table_ids=[])
    assert ctx == {"source_name": "?", "dialect": "postgresql", "tables": []}


def test_build_schema_context_populates_tables():
    cur = _SeqCursor(
        source_name="ACME",
        tables={
            10: {
                "object_name": "orders",
                "te_id": 100,
                "columns": [
                    ("id", "INT", "Sipariş ID", None, "primary_key"),
                    ("amount", "DECIMAL", "Tutar", None, "currency"),
                ],
            }
        },
    )
    ctx = cmp.build_metric_schema_context(cur, source_id=1, table_ids=[10])
    assert ctx["source_name"] == "ACME"
    assert len(ctx["tables"]) == 1
    t = ctx["tables"][0]
    assert t["name"] == "orders"
    assert len(t["columns"]) == 2
    assert "amount" in t["col_enrichments"]
    assert t["col_enrichments"]["amount"]["business_name_tr"] == "Tutar"


def test_build_schema_context_skips_unknown_table():
    cur = _SeqCursor()
    ctx = cmp.build_metric_schema_context(cur, source_id=1, table_ids=[999])
    assert ctx["tables"] == []


# ─────────────────────────────────────────────────────────────
# parse_to_sql — happy path + failure modes
# ─────────────────────────────────────────────────────────────

def _ok_schema():
    return {
        "source_name": "ACME",
        "dialect": "postgresql",
        "tables": [{"name": "orders", "columns": [{"name": "amount", "data_type": "DECIMAL"}],
                    "col_enrichments": {}}],
    }


def test_parse_empty_query():
    out = cmp.parse_to_sql("", _ok_schema())
    assert out["success"] is False
    assert "Boş" in out["error"]


def test_parse_no_tables():
    out = cmp.parse_to_sql("toplam satış", {"source_name": "X", "dialect": "postgresql", "tables": []})
    assert out["success"] is False
    assert "Tablo seçimi yok" in out["error"]


def test_parse_happy_path():
    def fake_gen(q, ctx, allowed_tables=None):
        return {"success": True, "sql": "SELECT SUM(amount) FROM orders", "explanation": "Toplam", "error": None}
    def fake_validate(sql):
        return True, None
    def fake_wl(sql, allowed, dialect="postgresql"):
        return True, None

    out = cmp.parse_to_sql(
        "Toplam satış", _ok_schema(),
        _generate_sql=fake_gen, _validate_sql=fake_validate, _check_whitelist=fake_wl,
    )
    assert out["success"] is True
    assert "SUM(amount)" in out["sql"]
    assert out["intent"]["agg_func"] == "SUM"


def test_parse_llm_failure_propagates():
    def fake_gen(q, ctx, allowed_tables=None):
        return {"success": False, "sql": None, "error": "LLM boş", "explanation": None}
    out = cmp.parse_to_sql(
        "Toplam satış", _ok_schema(), _generate_sql=fake_gen,
        _validate_sql=lambda s: (True, None), _check_whitelist=lambda s, a, dialect="": (True, None),
    )
    assert out["success"] is False
    assert "LLM boş" in out["error"]


def test_parse_security_validation_rejects():
    def fake_gen(q, ctx, allowed_tables=None):
        return {"success": True, "sql": "DROP TABLE orders", "explanation": None}
    def fake_validate(sql):
        return False, "Yasak SQL komutu: DROP"
    out = cmp.parse_to_sql(
        "drop", _ok_schema(),
        _generate_sql=fake_gen, _validate_sql=fake_validate,
        _check_whitelist=lambda s, a, dialect="": (True, None),
    )
    assert out["success"] is False
    assert "Güvenlik doğrulaması" in out["error"]
    assert "DROP" in out["error"]


def test_parse_whitelist_rejection():
    def fake_gen(q, ctx, allowed_tables=None):
        return {"success": True, "sql": "SELECT * FROM secret_users", "explanation": None}
    def fake_wl(sql, allowed, dialect="postgresql"):
        return False, "Tablo izinli değil: secret_users"
    out = cmp.parse_to_sql(
        "?", _ok_schema(),
        _generate_sql=fake_gen, _validate_sql=lambda s: (True, None), _check_whitelist=fake_wl,
    )
    assert out["success"] is False
    assert "whitelist" in out["error"].lower()


def test_parse_generate_sql_raises_handled():
    def fake_gen(q, ctx, allowed_tables=None):
        raise RuntimeError("network down")
    out = cmp.parse_to_sql(
        "?", _ok_schema(), _generate_sql=fake_gen,
        _validate_sql=lambda s: (True, None), _check_whitelist=lambda *a, **k: (True, None),
    )
    assert out["success"] is False
    assert "LLM çağrısı başarısız" in out["error"]


# ─────────────────────────────────────────────────────────────
# save_custom_metric
# ─────────────────────────────────────────────────────────────

class _RecCursor:
    def __init__(self, insert_id: Optional[int] = 7):
        self.insert_id = insert_id
        self.executed: List[tuple] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))

    def fetchone(self):
        return (self.insert_id,) if self.insert_id is not None else None


def test_save_metric_inserts_returns_id():
    cur = _RecCursor(insert_id=42)
    mid = cmp.save_custom_metric(
        cur,
        user_ctx={"id": 5, "company_id": 1},
        name_tr="Aylık Satış",
        sql="SELECT SUM(amount) FROM orders",
        source_id=10,
        intent={"agg_func": "SUM"},
    )
    assert mid == 42
    assert len(cur.executed) == 1
    sql, params = cur.executed[0]
    assert "INSERT INTO dbsmart_metric_library" in sql
    # metric_key: custom_5_<hash>
    assert params[0].startswith("custom_5_")
    assert params[1] == "Aylık Satış"
    # sql_templates JSON içinde sql var
    sql_templates = json.loads(params[6])
    assert sql_templates["default"] == "SELECT SUM(amount) FROM orders"
    assert sql_templates["intent"]["agg_func"] == "SUM"


def test_save_metric_missing_user_ctx_returns_none():
    cur = _RecCursor()
    mid = cmp.save_custom_metric(
        cur, user_ctx={"id": None, "company_id": None},
        name_tr="X", sql="SELECT 1", source_id=1,
    )
    assert mid is None
    assert cur.executed == []


def test_save_metric_empty_name_returns_none():
    cur = _RecCursor()
    mid = cmp.save_custom_metric(
        cur, user_ctx={"id": 5, "company_id": 1},
        name_tr="   ", sql="SELECT 1", source_id=1,
    )
    assert mid is None


def test_save_metric_empty_sql_returns_none():
    cur = _RecCursor()
    mid = cmp.save_custom_metric(
        cur, user_ctx={"id": 5, "company_id": 1},
        name_tr="X", sql="", source_id=1,
    )
    assert mid is None


def test_save_metric_insert_returning_empty():
    cur = _RecCursor(insert_id=None)
    mid = cmp.save_custom_metric(
        cur, user_ctx={"id": 5, "company_id": 1},
        name_tr="X", sql="SELECT 1", source_id=1,
    )
    assert mid is None


def test_metric_key_deterministic():
    k1 = cmp._make_metric_key("Aylık Satış", 5)
    k2 = cmp._make_metric_key("Aylık Satış", 5)
    k3 = cmp._make_metric_key("Aylık Satış", 6)
    assert k1 == k2
    assert k1 != k3
    assert k1.startswith("custom_5_")
