"""Bulgular4 Round 2 (v3.38.1) — B4-1 add_filter flat-args + B4-2 garbage regex (TYCHE).

B4-1: /ast/patch endpoint `fn(ast, **body.args)` ile çağırır; FE filtreyi DÜZ
      {expr, op, value} olarak gönderir. add_filter bunu kabul etmeli (TypeError → 400 değil).
B4-2: _repair_glued_keyword_garbage satır-içi (boşluk sonrası) garbage'ı da onarmalı,
      string-literal / quoted-identifier FP üretmemeli.
"""
import pytest

from app.services.db_smart import ast_renderer
from app.services.db_smart.llm_generate_report import _repair_glued_keyword_garbage


def _base_ast():
    return {"type": "select", "columns": [{"expr": "t.a"}]}


# ───────────────────────── B4-1: add_filter ─────────────────────────

def test_add_filter_flat_kwargs_no_typeerror():
    # FE'nin gönderdiği şekil: fn(ast, **{expr, op, value})
    out = ast_renderer.add_filter(_base_ast(), expr="SIPARIS_ID", op="=", value=1)
    assert out["filters"] == [{"expr": "SIPARIS_ID", "op": "=", "value": 1}]


def test_add_filter_wrapped_backward_compat():
    out = ast_renderer.add_filter(_base_ast(), filt={"expr": "X", "op": ">", "value": 5})
    assert out["filters"] == [{"expr": "X", "op": ">", "value": 5}]


def test_add_filter_positional_dict_backward_compat():
    out = ast_renderer.add_filter(_base_ast(), {"expr": "Y", "op": "=", "value": "z"})
    assert out["filters"][0]["expr"] == "Y"


def test_add_filter_unary_op_no_value():
    # IS NULL gibi unary op'ta value yok → value key eklenmemeli
    out = ast_renderer.add_filter(_base_ast(), expr="COL", op="IS NULL")
    assert out["filters"] == [{"expr": "COL", "op": "IS NULL"}]
    assert "value" not in out["filters"][0]


def test_add_filter_value_zero_preserved():
    # value=0 falsy ama geçerli → korunmalı
    out = ast_renderer.add_filter(_base_ast(), expr="COL", op="=", value=0)
    assert out["filters"][0]["value"] == 0


def test_add_filter_missing_expr_raises():
    with pytest.raises(ValueError):
        ast_renderer.add_filter(_base_ast(), op="=", value=1)


# ───────────────────────── B4-2: garbage repair ─────────────────────────

def test_repair_inline_glued_from():
    # Tek satır LLM çıktısı: W0FROM boşluk sonrası — ESKİ regex kaçırıyordu
    sql = 'W0SELECT "x"."a" W0FROM "S"."T" FETCH FIRST 100 ROWS ONLY'
    out, changed = _repair_glued_keyword_garbage(sql)
    assert changed is True
    assert "W0" not in out
    assert out.startswith("SELECT")
    assert " FROM " in out


def test_repair_linestart_glued():
    sql = 'W0SELECT a, b\nW0FROM tbl'
    out, changed = _repair_glued_keyword_garbage(sql)
    assert "W0" not in out
    assert out == "SELECT a, b\nFROM tbl"


def test_repair_preserves_string_literal():
    # 'fooSELECT' string değeri — quote öncesi, whitespace değil → dokunulmaz
    sql = "SELECT a FROM t WHERE n = 'fooSELECT'"
    out, changed = _repair_glued_keyword_garbage(sql)
    assert changed is False
    assert out == sql


def test_repair_preserves_quoted_identifier():
    sql = 'SELECT "x"."WITHHOLDING" FROM t'
    out, changed = _repair_glued_keyword_garbage(sql)
    assert changed is False
    assert "WITHHOLDING" in out


def test_repair_clean_sql_unchanged():
    sql = 'SELECT a FROM t WHERE x = 1'
    out, changed = _repair_glued_keyword_garbage(sql)
    assert changed is False
    assert out == sql
