"""learning_recorder — dbsmart_interactions event store (v3.30.0 FAZ 2 P10 G2.4)."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import pytest

from app.services.db_smart import learning_recorder as lr


# ─────────────────────────────────────────────────────────────
# Fake cursor — psycopg2 contract
# ─────────────────────────────────────────────────────────────

class _FakeCursor:
    """Minimum psycopg2 cursor uyumu: execute / fetchone / fetchall.

    pii_rows verilirse SELECT ds_column_enrichments için döner.
    insert_id INSERT RETURNING'in döneceği id.
    `executed`: (sql, params) tuple log'u — assertion için.
    """

    def __init__(
        self,
        *,
        pii_rows: Optional[List[tuple]] = None,
        insert_id: Optional[int] = 1,
        raise_on_select: bool = False,
        raise_on_insert: bool = False,
    ):
        self.pii_rows = pii_rows or []
        self.insert_id = insert_id
        self.raise_on_select = raise_on_select
        self.raise_on_insert = raise_on_insert
        self.executed: List[tuple] = []
        self._last: Optional[tuple] = None
        self._last_kind: Optional[str] = None
        self._last_rows: Optional[List[tuple]] = None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.executed.append((sql, params))
        if "ds_column_enrichments" in sql:
            if self.raise_on_select:
                raise RuntimeError("simulated SELECT failure")
            self._last_kind = "select"
            self._last_rows = list(self.pii_rows)
            self._last = None
        elif "INSERT INTO dbsmart_interactions" in sql:
            if self.raise_on_insert:
                raise RuntimeError("simulated INSERT failure")
            self._last_kind = "insert"
            self._last = (self.insert_id,) if self.insert_id is not None else None
            self._last_rows = None
        else:
            self._last_kind = None
            self._last = None

    def fetchone(self):
        if self._last_kind == "insert":
            return self._last
        if self._last_kind == "select" and self._last_rows:
            return self._last_rows[0]
        return None

    def fetchall(self):
        if self._last_kind == "select":
            return list(self._last_rows or [])
        return []


@pytest.fixture(autouse=True)
def _reset_pii_cache():
    lr.invalidate_pii_cache()
    yield
    lr.invalidate_pii_cache()


# ─────────────────────────────────────────────────────────────
# Action whitelist
# ─────────────────────────────────────────────────────────────

def test_known_actions_includes_main_events():
    must_have = {
        "SessionStarted", "DomainSelected", "TableSelected",
        "MetricChosen", "QueryExecuted", "WizardCompleted",
        "WizardAbandoned", "ExplicitFeedback",
    }
    assert must_have.issubset(lr.KNOWN_ACTIONS)


def test_unknown_action_returns_none_no_insert(fake_user_ctx):
    cur = _FakeCursor()
    result = lr.record(cur, "BogusAction", fake_user_ctx)
    assert result is None
    assert not any("INSERT INTO dbsmart_interactions" in sql for sql, _ in cur.executed)


def test_missing_user_ctx_returns_none():
    cur = _FakeCursor()
    result = lr.record(cur, "SessionStarted", {"id": None, "company_id": None})
    assert result is None
    assert not any("INSERT" in sql for sql, _ in cur.executed)


def test_known_action_inserts_and_returns_id(fake_user_ctx):
    cur = _FakeCursor(insert_id=99)
    rid = lr.record(cur, "SessionStarted", fake_user_ctx, session_id=7, step=0)
    assert rid == 99
    insert_calls = [c for c in cur.executed if "INSERT" in c[0]]
    assert len(insert_calls) == 1


def test_insert_params_order_and_types(fake_user_ctx):
    cur = _FakeCursor(insert_id=1)
    lr.record(
        cur, "QueryExecuted", fake_user_ctx,
        session_id=7, step=4,
        suggestion_shown={"viz": "line"},
        satisfaction=3, duration_ms=120,
    )
    sql, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    # (session_id, user_id, company_id, step, action, sug_shown, sug_acc, user_ov, sat, dur)
    assert params[0] == 7
    assert params[1] == 42  # user_id from fake_user_ctx
    assert params[2] == 1   # company_id from fake_user_ctx
    assert params[3] == 4
    assert params[4] == "QueryExecuted"
    assert json.loads(params[5]) == {"viz": "line"}
    assert params[6] is None
    assert params[7] is None
    assert params[8] == 3
    assert params[9] == 120


# ─────────────────────────────────────────────────────────────
# Validation clamps
# ─────────────────────────────────────────────────────────────

def test_satisfaction_out_of_range_becomes_none(fake_user_ctx):
    cur = _FakeCursor()
    lr.record(cur, "ExplicitFeedback", fake_user_ctx, satisfaction=99)
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    assert params[8] is None


def test_satisfaction_negative_one_allowed(fake_user_ctx):
    cur = _FakeCursor()
    lr.record(cur, "ExplicitFeedback", fake_user_ctx, satisfaction=-1)
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    assert params[8] == -1


def test_satisfaction_non_int_becomes_none(fake_user_ctx):
    cur = _FakeCursor()
    lr.record(cur, "ExplicitFeedback", fake_user_ctx, satisfaction="bad")
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    assert params[8] is None


def test_duration_negative_clamped_to_zero(fake_user_ctx):
    cur = _FakeCursor()
    lr.record(cur, "QueryExecuted", fake_user_ctx, duration_ms=-100)
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    assert params[9] == 0


def test_duration_overflow_clamped_to_max(fake_user_ctx):
    cur = _FakeCursor()
    lr.record(cur, "QueryExecuted", fake_user_ctx, duration_ms=10 ** 12)
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    assert params[9] == 2_147_483_647


# ─────────────────────────────────────────────────────────────
# PII masking
# ─────────────────────────────────────────────────────────────

def test_pii_masking_replaces_known_columns(fake_user_ctx):
    cur = _FakeCursor(pii_rows=[("phone",), ("email",)], insert_id=1)
    lr.record(
        cur, "FilterApplied", fake_user_ctx,
        source_id=5,
        suggestion_shown={"phone": "5551234", "name": "Ali"},
    )
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    sug = json.loads(params[5])
    assert sug["phone"] == "***MASKED***"
    assert sug["name"] == "Ali"


def test_pii_masking_recursive_nested(fake_user_ctx):
    cur = _FakeCursor(pii_rows=[("ssn",)], insert_id=1)
    lr.record(
        cur, "FilterApplied", fake_user_ctx,
        source_id=5,
        suggestion_shown={"filters": [{"col": "x", "ssn": "123-45"}]},
    )
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    sug = json.loads(params[5])
    assert sug["filters"][0]["ssn"] == "***MASKED***"
    assert sug["filters"][0]["col"] == "x"


def test_pii_masking_skipped_when_no_source_id(fake_user_ctx):
    cur = _FakeCursor(pii_rows=[("phone",)])
    lr.record(
        cur, "FilterApplied", fake_user_ctx,
        suggestion_shown={"phone": "5551234"},
    )
    # SELECT ds_column_enrichments çağrılmamalı
    assert not any("ds_column_enrichments" in sql for sql, _ in cur.executed)
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    sug = json.loads(params[5])
    assert sug["phone"] == "5551234"  # not masked


def test_pii_lookup_failure_masks_off_but_inserts(fake_user_ctx):
    cur = _FakeCursor(raise_on_select=True, insert_id=1)
    rid = lr.record(
        cur, "FilterApplied", fake_user_ctx,
        source_id=5,
        suggestion_shown={"phone": "5551234"},
    )
    assert rid == 1
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    sug = json.loads(params[5])
    assert sug["phone"] == "5551234"  # not masked on failure


def test_pii_cache_hit_avoids_second_lookup(fake_user_ctx):
    cur = _FakeCursor(pii_rows=[("email",)], insert_id=1)
    lr.record(cur, "FilterApplied", fake_user_ctx, source_id=5, suggestion_shown={"email": "a"})
    lr.record(cur, "FilterApplied", fake_user_ctx, source_id=5, suggestion_shown={"email": "b"})
    selects = [c for c in cur.executed if "ds_column_enrichments" in c[0]]
    assert len(selects) == 1  # cached


def test_invalidate_pii_cache_forces_reload(fake_user_ctx):
    cur = _FakeCursor(pii_rows=[("email",)], insert_id=1)
    lr.record(cur, "FilterApplied", fake_user_ctx, source_id=5, suggestion_shown={"x": 1})
    lr.invalidate_pii_cache(source_id=5)
    lr.record(cur, "FilterApplied", fake_user_ctx, source_id=5, suggestion_shown={"x": 1})
    selects = [c for c in cur.executed if "ds_column_enrichments" in c[0]]
    assert len(selects) == 2


# ─────────────────────────────────────────────────────────────
# Graceful failure
# ─────────────────────────────────────────────────────────────

def test_insert_failure_returns_none_no_raise(fake_user_ctx):
    cur = _FakeCursor(raise_on_insert=True)
    # Wizard akışı kırılmamalı
    rid = lr.record(cur, "SessionStarted", fake_user_ctx)
    assert rid is None


def test_insert_returning_empty_returns_none(fake_user_ctx):
    cur = _FakeCursor(insert_id=None)
    rid = lr.record(cur, "SessionStarted", fake_user_ctx)
    assert rid is None


# ─────────────────────────────────────────────────────────────
# track() context manager
# ─────────────────────────────────────────────────────────────

def test_track_measures_duration_and_records(fake_user_ctx):
    cur = _FakeCursor(insert_id=11)
    with lr.track(cur, "QueryExecuted", fake_user_ctx, session_id=3) as ev:
        ev["suggestion_accepted"] = {"row_count": 5}
    insert = [c for c in cur.executed if "INSERT" in c[0]]
    assert len(insert) == 1
    _, params = insert[0]
    assert params[6] is not None  # suggestion_accepted JSON populated
    assert json.loads(params[6]) == {"row_count": 5}
    assert params[9] is not None and params[9] >= 0  # duration_ms measured


def test_track_records_on_exception(fake_user_ctx):
    cur = _FakeCursor(insert_id=11)
    with pytest.raises(ValueError):
        with lr.track(cur, "QueryExecuted", fake_user_ctx, session_id=3):
            raise ValueError("boom")
    # Exception olsa bile event kaydedilmiş olmalı
    insert = [c for c in cur.executed if "INSERT" in c[0]]
    assert len(insert) == 1


def test_track_explicit_duration_overrides_measured(fake_user_ctx):
    cur = _FakeCursor(insert_id=11)
    with lr.track(cur, "QueryExecuted", fake_user_ctx) as ev:
        ev["duration_ms"] = 999
    _, params = [c for c in cur.executed if "INSERT" in c[0]][0]
    assert params[9] == 999


# ---------- F-009 / F-010 fix dogrulama ----------

def test_mask_payload_case_insensitive_key_match(fake_user_ctx):
    """F-010 fix: PII key match case-insensitive olmali.
    pii_cols = {'email'} ; payload key 'Email' / 'EMAIL' → maskelenmeli."""
    cur = _FakeCursor(pii_rows=[("email",)], insert_id=99)
    lr.record(
        cur, "FilterApplied", fake_user_ctx,
        suggestion_shown={"Email": "ali@x.com", "EMAIL": "veli@x.com", "other": "x"},
        source_id=10,
    )
    insert_calls = [c for c in cur.executed if "INSERT" in c[0]]
    assert insert_calls
    params = insert_calls[0][1]
    payload = json.loads(params[5])
    assert payload["Email"] == "***MASKED***"
    assert payload["EMAIL"] == "***MASKED***"
    assert payload["other"] == "x"


def test_mask_payload_sql_bearing_key_hash_redacted(fake_user_ctx):
    """F-009 fix: 'sql'/'query' key altindaki uzun string hash-redact edilir
    (literal PII payload sizintisi kapali). PII liste boş olsa bile aktif."""
    cur = _FakeCursor(pii_rows=[], insert_id=99)
    long_sql = "SELECT * FROM customers WHERE email='ali@x.com' AND tc='12345678901'"
    lr.record(
        cur, "SQLGenerated", fake_user_ctx,
        suggestion_shown={"sql": long_sql, "short": "ok"},
        source_id=10,
    )
    params = [c for c in cur.executed if "INSERT" in c[0]][0][1]
    payload = json.loads(params[5])
    assert isinstance(payload["sql"], dict)
    assert payload["sql"].get("_redacted") is True
    assert payload["sql"].get("value_hash", "").startswith("sql:")
    assert payload["short"] == "ok"  # kisa string dokunulmadi
    assert "ali@x.com" not in json.dumps(payload)  # literal PII gitmedi


def test_mask_payload_short_sql_not_hashed(fake_user_ctx):
    """F-009 boundary: <=32 char SQL string hash edilmez (debugging icin)."""
    cur = _FakeCursor(pii_rows=[], insert_id=99)
    lr.record(
        cur, "SQLGenerated", fake_user_ctx,
        suggestion_shown={"sql": "SELECT 1"},  # <=32 char
        source_id=10,
    )
    params = [c for c in cur.executed if "INSERT" in c[0]][0][1]
    payload = json.loads(params[5])
    assert payload["sql"] == "SELECT 1"
