"""v3.55.0 — generate-report LLM kolon grounding (halüsinasyon önleme).

_build_prompt'a GERÇEK kolon envanteri (columns_json) verince prompt'a "Tablo kolonları"
bloğu + "UYDURMA" talimatı girer; verilmeyince eski davranış (backward compat).
"""
from app.services.db_smart import llm_generate_report as L


def _user_msg(messages):
    for m in messages:
        if m.get("role") == "user":
            return m.get("content", "")
    return ""


def test_build_prompt_includes_real_columns_and_guard():
    tc = {
        "elysion.T_WF_BUSINESSINTERACTION": [
            ("BusinessInteractionId", "integer"),
            ("CreateDate", "timestamp"),
        ],
    }
    msgs = L._build_prompt(
        dialect="postgresql",
        primary_table_name="elysion.T_WF_BUSINESSINTERACTION",
        join_table_names=[],
        fk_lines=[],
        report_columns=[{"name": "BusinessInteractionId",
                         "table_name": "elysion.T_WF_BUSINESSINTERACTION"}],
        metric=None,
        user_note="en uzun süre",
        limit=100,
        table_columns=tc,
    )
    u = _user_msg(msgs)
    assert "Tablo kolonları (GERÇEK şema" in u          # grounding bloğu
    assert "CreateDate" in u and "timestamp" in u       # gerçek kolon + tip
    assert "UYDURMA" in u                               # halüsinasyon guard talimatı


def test_build_prompt_no_columns_backward_compat():
    msgs = L._build_prompt(
        dialect="postgresql",
        primary_table_name="t",
        join_table_names=[],
        fk_lines=[],
        report_columns=[{"name": "x"}],
        metric=None,
        user_note="",
        limit=100,
    )
    u = _user_msg(msgs)
    assert "Tablo kolonları (GERÇEK şema" not in u       # table_columns yoksa blok yok


def test_fetch_table_columns_parses_columns_json():
    class _FakeCur:
        def __init__(self):
            self._rows = None
        def execute(self, sql, params=None):
            self._rows = [{
                "schema_name": "elysion", "object_name": "T_X",
                "columns_json": [
                    {"name": "Id", "data_type": "integer"},
                    {"name": "CreateDate", "data_type": "timestamp"},
                    {"name": ""},  # boş ad → atlanmalı
                ],
            }]
        def fetchall(self):
            return self._rows

    out = L._fetch_table_columns(_FakeCur(), 1, [5])
    assert "elysion.T_X" in out
    assert ("Id", "integer") in out["elysion.T_X"]
    assert ("CreateDate", "timestamp") in out["elysion.T_X"]
    assert len(out["elysion.T_X"]) == 2  # boş-adlı kolon elendi


def test_fetch_table_columns_json_string_fallback():
    # columns_json str gelirse (auto-decode olmazsa) json.loads ile çözülür
    import json as _json
    class _FakeCur:
        def __init__(self):
            self._rows = None
        def execute(self, sql, params=None):
            self._rows = [(
                "elysion", "T_Y",
                _json.dumps([{"name": "A", "data_type": "text"}]),
            )]
        def fetchall(self):
            return self._rows
    out = L._fetch_table_columns(_FakeCur(), 1, [9])
    assert out.get("elysion.T_Y") == [("A", "text")]
