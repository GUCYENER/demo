"""few_shot_store unit tests (v3.30.0 FAZ 4 P50).

Cursor-mock based — no real DB / no real embedding model. The embedding
service is monkey-patched via ``few_shot_store._embed`` to return a
deterministic 384-dim vector (or None for the failure path).

Coverage:
    - _vector_literal / _build_distance_query shape
    - record_example user-personal insert
    - record_example as_company_baseline → user_id=None bound
    - record_example missing/invalid feedback rejected
    - record_example embedding failure → None (no INSERT)
    - record_example dim mismatch → None
    - top_k_examples merges user + baseline by distance ASC, returns ≤k
    - top_k_examples k=3 → 3 rows sorted by distance
    - top_k_examples empty cursor → []
    - top_k_examples include_company_baseline=False skips baseline query
    - top_k_examples embedding failure → []
    - top_k_examples cross-tenant simulated by raising on user-scope (RLS
      reject) → returns [] gracefully
    - delete_example sets was_correct=FALSE and returns True
    - delete_example unknown id (rowcount=0) → False
    - delete_example DB error → False
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from app.services.text_to_sql_store import few_shot_store as fss


USER_CTX: Dict[str, Any] = {"id": 7, "company_id": 42}
SRC_ID = 11


def _det_vec(seed: float = 0.01) -> List[float]:
    """Deterministic 384-dim vector (linearly spaced floats)."""
    return [seed * (i + 1) / fss.EMBEDDING_DIM for i in range(fss.EMBEDDING_DIM)]


# ─────────────────────────────────────────────────────────────
# Cursor mock
# ─────────────────────────────────────────────────────────────


class _RecCursor:
    """Records executed (sql, params) and replays fetch responses by call order.

    fetchone_seq / fetchall_seq are consumed left-to-right per execute().
    """

    def __init__(
        self,
        fetchone_seq: Optional[List[Any]] = None,
        fetchall_seq: Optional[List[List[Any]]] = None,
        rowcount: int = 1,
        raise_on: Optional[int] = None,
    ):
        self.calls: List[Tuple[str, Any]] = []
        self._fetchone_seq = list(fetchone_seq or [])
        self._fetchall_seq = list(fetchall_seq or [])
        self.rowcount = rowcount
        self._raise_on = raise_on  # zero-based execute() index to raise on

    def execute(self, sql: str, params: Any = None) -> None:
        idx = len(self.calls)
        self.calls.append((sql, params))
        if self._raise_on is not None and idx == self._raise_on:
            raise RuntimeError("simulated db error")

    def fetchone(self) -> Any:
        if self._fetchone_seq:
            return self._fetchone_seq.pop(0)
        return None

    def fetchall(self) -> Any:
        if self._fetchall_seq:
            return self._fetchall_seq.pop(0)
        return []


@pytest.fixture(autouse=True)
def _patch_embedding(monkeypatch: pytest.MonkeyPatch):
    """Default: embedding returns deterministic vector. Tests can override."""
    monkeypatch.setattr(fss, "_embed", lambda q: _det_vec(0.01))
    # Reset module-level manager cache so test isolation holds.
    monkeypatch.setattr(fss, "_EMB_MGR", None, raising=False)


# ─────────────────────────────────────────────────────────────
# _vector_literal & _build_distance_query
# ─────────────────────────────────────────────────────────────


def test_vector_literal_shape():
    lit = fss._vector_literal([0.1, 0.2, -0.3])
    assert lit.startswith("[") and lit.endswith("]")
    parts = lit[1:-1].split(",")
    assert len(parts) == 3
    assert parts[0].startswith("0.")


def test_build_distance_query_user_scope_contains_user_id():
    sql = fss._build_distance_query(scope="user", k=5)
    assert "user_id = %s" in sql
    assert "source_id = %s" in sql
    assert "ORDER BY embedding <=> %s::vector" in sql
    assert "LIMIT %s" in sql


def test_build_distance_query_baseline_scope_contains_user_null():
    sql = fss._build_distance_query(scope="baseline", k=5)
    assert "user_id IS NULL" in sql
    assert "company_id = %s" in sql


def test_build_distance_query_rejects_unknown_scope():
    with pytest.raises(ValueError):
        fss._build_distance_query(scope="bogus", k=5)


# ─────────────────────────────────────────────────────────────
# _require_user_ctx
# ─────────────────────────────────────────────────────────────


def test_require_user_ctx_ok():
    assert fss._require_user_ctx({"id": 1, "company_id": 2}) == (1, 2)


def test_require_user_ctx_missing_raises():
    with pytest.raises(ValueError):
        fss._require_user_ctx({"id": 1})
    with pytest.raises(ValueError):
        fss._require_user_ctx({})


# ─────────────────────────────────────────────────────────────
# record_example
# ─────────────────────────────────────────────────────────────


def test_record_example_user_personal_inserts_and_returns_id():
    cur = _RecCursor(fetchone_seq=[(101,)])
    rid = fss.record_example(
        cur, USER_CTX,
        source_id=SRC_ID, db_engine="postgresql",
        question="kaç açık talep var?",
        generated_sql="SELECT count(*) FROM tickets WHERE status='open'",
    )
    assert rid == 101
    assert len(cur.calls) == 1
    sql, params = cur.calls[0]
    assert "INSERT INTO query_examples" in sql
    # user_id is first positional, must equal 7 (not None).
    assert params[0] == 7
    assert params[1] == 42  # company_id
    assert params[2] == SRC_ID
    assert params[3] == "postgresql"
    # vector literal at index 8
    assert isinstance(params[8], str) and params[8].startswith("[")


def test_record_example_as_company_baseline_user_id_null():
    cur = _RecCursor(fetchone_seq=[(202,)])
    rid = fss.record_example(
        cur, USER_CTX,
        source_id=SRC_ID, db_engine="postgresql",
        question="synthetic Q",
        generated_sql="SELECT 1",
        as_company_baseline=True,
        user_feedback="synthetic",
    )
    assert rid == 202
    _, params = cur.calls[0]
    assert params[0] is None      # user_id NULL
    assert params[1] == 42         # company_id still bound
    assert params[7] == "synthetic"  # user_feedback


def test_record_example_invalid_feedback_rejected():
    cur = _RecCursor()
    with pytest.raises(ValueError):
        fss.record_example(
            cur, USER_CTX,
            source_id=SRC_ID, db_engine="postgresql",
            question="q", generated_sql="SELECT 1",
            user_feedback="not_a_valid_value",
        )


def test_record_example_empty_question_raises():
    cur = _RecCursor()
    with pytest.raises(ValueError):
        fss.record_example(
            cur, USER_CTX, source_id=SRC_ID, db_engine="pg",
            question="   ", generated_sql="SELECT 1",
        )


def test_record_example_embedding_failure_returns_none(monkeypatch):
    monkeypatch.setattr(fss, "_embed", lambda q: None)
    cur = _RecCursor()
    rid = fss.record_example(
        cur, USER_CTX,
        source_id=SRC_ID, db_engine="postgresql",
        question="q", generated_sql="SELECT 1",
    )
    assert rid is None
    assert cur.calls == []  # no INSERT attempted


def test_record_example_dim_mismatch_returns_none(monkeypatch):
    monkeypatch.setattr(fss, "_embed", lambda q: [0.1, 0.2])  # wrong dim
    cur = _RecCursor()
    rid = fss.record_example(
        cur, USER_CTX,
        source_id=SRC_ID, db_engine="postgresql",
        question="q", generated_sql="SELECT 1",
    )
    assert rid is None
    assert cur.calls == []


def test_record_example_db_error_returns_none():
    cur = _RecCursor(raise_on=0)
    rid = fss.record_example(
        cur, USER_CTX,
        source_id=SRC_ID, db_engine="postgresql",
        question="q", generated_sql="SELECT 1",
    )
    assert rid is None


def test_record_example_missing_user_ctx_raises():
    cur = _RecCursor()
    with pytest.raises(ValueError):
        fss.record_example(
            cur, {"id": 1},  # company_id missing
            source_id=SRC_ID, db_engine="pg",
            question="q", generated_sql="SELECT 1",
        )


# ─────────────────────────────────────────────────────────────
# top_k_examples
# ─────────────────────────────────────────────────────────────


def _row(rid: int, dist: float, q: str = "q", sql: str = "S") -> tuple:
    return (rid, q, sql, dist, ["t1"], ["c1"], True)


def test_top_k_merges_user_and_baseline_by_distance():
    cur = _RecCursor(fetchall_seq=[
        [_row(1, 0.30), _row(2, 0.50)],          # user-scope
        [_row(10, 0.10), _row(11, 0.40)],        # baseline-scope
    ])
    out = fss.top_k_examples(
        cur, USER_CTX, source_id=SRC_ID, question="kaç talep?", k=3,
    )
    assert len(out) == 3
    # Sorted by distance ASC: 0.10 → 0.30 → 0.40
    assert [r["id"] for r in out] == [10, 1, 11]
    assert out[0]["source"] == "baseline"
    assert out[1]["source"] == "user"
    assert out[2]["source"] == "baseline"


def test_top_k_k_equals_3_returns_3():
    cur = _RecCursor(fetchall_seq=[
        [_row(i, 0.1 * i) for i in range(1, 6)],  # 5 user rows
        [],                                        # baseline empty
    ])
    out = fss.top_k_examples(
        cur, USER_CTX, source_id=SRC_ID, question="q", k=3,
    )
    assert len(out) == 3
    dists = [r["distance"] for r in out]
    assert dists == sorted(dists)


def test_top_k_empty_returns_empty_list():
    cur = _RecCursor(fetchall_seq=[[], []])
    out = fss.top_k_examples(cur, USER_CTX, source_id=SRC_ID, question="q")
    assert out == []


def test_top_k_baseline_disabled_runs_only_user_query():
    cur = _RecCursor(fetchall_seq=[[_row(1, 0.2)]])
    out = fss.top_k_examples(
        cur, USER_CTX, source_id=SRC_ID, question="q",
        include_company_baseline=False,
    )
    assert len(cur.calls) == 1  # only one SELECT
    assert out[0]["source"] == "user"


def test_top_k_embedding_failure_returns_empty(monkeypatch):
    monkeypatch.setattr(fss, "_embed", lambda q: None)
    cur = _RecCursor()
    out = fss.top_k_examples(cur, USER_CTX, source_id=SRC_ID, question="q")
    assert out == []
    assert cur.calls == []


def test_top_k_user_scope_query_failure_falls_back_to_baseline():
    """Simulates RLS reject or transient DB error on user-scope query.

    The function logs WARNING and still attempts baseline; result is whatever
    baseline returns.
    """
    cur = _RecCursor(
        fetchall_seq=[[_row(99, 0.05)]],  # one baseline row (after user raises)
        raise_on=0,                         # raise on first execute (user-scope)
    )
    out = fss.top_k_examples(cur, USER_CTX, source_id=SRC_ID, question="q")
    assert len(out) == 1
    assert out[0]["id"] == 99
    assert out[0]["source"] == "baseline"


def test_top_k_question_blank_returns_empty():
    cur = _RecCursor()
    out = fss.top_k_examples(cur, USER_CTX, source_id=SRC_ID, question="   ")
    assert out == []
    assert cur.calls == []


def test_top_k_k_clamped_to_max():
    cur = _RecCursor(fetchall_seq=[[], []])
    fss.top_k_examples(cur, USER_CTX, source_id=SRC_ID, question="q", k=9999)
    # k bound — last param of the SELECT — must be ≤ _MAX_K (50).
    _, params = cur.calls[0]
    assert params[-1] == fss._MAX_K


def test_top_k_distance_query_uses_parameter_binding():
    cur = _RecCursor(fetchall_seq=[[], []])
    fss.top_k_examples(cur, USER_CTX, source_id=SRC_ID, question="injection'; DROP TABLE")
    sql, params = cur.calls[0]
    # Vector literal must be a PARAM, not interpolated.
    assert "::vector" in sql
    assert isinstance(params[0], str) and params[0].startswith("[")
    # No SQL keyword leaked into the SQL body from `question`.
    assert "DROP" not in sql.upper()


# ─────────────────────────────────────────────────────────────
# delete_example (soft-delete)
# ─────────────────────────────────────────────────────────────


def test_delete_example_soft_deletes_and_returns_true():
    cur = _RecCursor(rowcount=1)
    ok = fss.delete_example(cur, 42, USER_CTX)
    assert ok is True
    sql, params = cur.calls[0]
    assert "UPDATE query_examples" in sql
    assert "was_correct = FALSE" in sql
    assert params == (42, 7)


def test_delete_example_unknown_id_returns_false():
    cur = _RecCursor(rowcount=0)
    ok = fss.delete_example(cur, 999, USER_CTX)
    assert ok is False


def test_delete_example_db_error_returns_false():
    cur = _RecCursor(raise_on=0)
    ok = fss.delete_example(cur, 1, USER_CTX)
    assert ok is False


def test_delete_example_requires_user_ctx():
    cur = _RecCursor()
    with pytest.raises(ValueError):
        fss.delete_example(cur, 1, {})
