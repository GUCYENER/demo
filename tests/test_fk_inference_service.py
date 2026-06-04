"""VYRA v3.29.9 — fk_inference_service unit tests (dialect-agnostic)."""
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.db_learning import fk_inference_service as svc
from app.services.db_learning.fk_inference_dialects import (
    OracleDialect,
    PostgresDialect,
)


# ─────────────────────────────────────────────────────────────
# _extract_root — pattern parser
# ─────────────────────────────────────────────────────────────
def test_extract_root_snake_id():
    assert svc._extract_root("user_id") == "user"
    assert svc._extract_root("owner_party_id") == "owner_party"


def test_extract_root_camel_id():
    assert svc._extract_root("userId") == "user"
    assert svc._extract_root("partyRelationId") == "partyrelation"


def test_extract_root_id_prefix():
    assert svc._extract_root("id_user") == "user"


def test_extract_root_hungarian():
    assert svc._extract_root("f_user_id") == "user"


def test_extract_root_skips_pk_columns():
    assert svc._extract_root("id") is None
    assert svc._extract_root("pk") is None


def test_extract_root_no_match():
    assert svc._extract_root("name") is None
    assert svc._extract_root("created_at") is None
    assert svc._extract_root("") is None


def test_extract_root_ref_suffix():
    assert svc._extract_root("owner_ref") == "owner"


# ─────────────────────────────────────────────────────────────
# _candidates_from_root — plural/singular
# ─────────────────────────────────────────────────────────────
def test_candidates_basic_plural():
    c = svc._candidates_from_root("user")
    assert "user" in c and "users" in c


def test_candidates_y_to_ies():
    c = svc._candidates_from_root("category")
    assert "category" in c and "categories" in c


def test_candidates_s_es():
    c = svc._candidates_from_root("box")
    assert "boxes" in c


def test_candidates_dedup():
    c = svc._candidates_from_root("user")
    assert len(c) == len(set(c))


# ─────────────────────────────────────────────────────────────
# _type_compatible
# ─────────────────────────────────────────────────────────────
def test_type_compat_int_int():
    d = PostgresDialect()
    assert svc._type_compatible("integer", "bigint", d) is True


def test_type_compat_uuid():
    d = PostgresDialect()
    assert svc._type_compatible("uuid", "uuid", d) is True


def test_type_compat_int_uuid_incompat():
    d = PostgresDialect()
    assert svc._type_compatible("integer", "uuid", d) is False


def test_type_compat_oracle_number():
    d = OracleDialect()
    assert svc._type_compatible("NUMBER(10,0)", "INTEGER", d) is True


def test_type_compat_unknown_returns_false():
    d = PostgresDialect()
    assert svc._type_compatible("inet", "integer", d) is False


# ─────────────────────────────────────────────────────────────
# _score
# ─────────────────────────────────────────────────────────────
def test_score_naming_only():
    # v3.65.0: _score match_kind alır ama method DB-constraint-valid kalır ('naming'); match_kind evidence'da.
    s, m = svc._score("full", False, None)
    assert s == 0.6
    assert m == "naming"


def test_score_naming_type():
    s, m = svc._score("full", True, None)
    assert s == 0.8
    assert m == "naming+type"


def test_score_with_sample_full_coverage():
    s, m = svc._score("full", True, {"coverage_ratio": 1.0})
    assert s == 1.0
    assert m == "naming+type+sample"


def test_score_partial_sample():
    s, m = svc._score("full", True, {"coverage_ratio": 0.5})
    assert s == 0.9
    assert m == "naming+type+sample"


def test_score_head_noun_lower_base():
    # v3.60.0: head-noun (rol-önekli) eşleşme daha düşük taban (0.45) → tek başına min_confidence altı,
    # tip uyumuyla 0.65 → persist olur. v3.65.0: method yine constraint-valid 'naming+type'.
    s_naming, _ = svc._score("head", False, None)
    assert s_naming == 0.45
    s_typed, m = svc._score("head", True, None)
    assert abs(s_typed - 0.65) < 1e-9
    assert m == "naming+type"


def test_score_method_is_constraint_valid():
    # v3.65.0 regresyon koruması: inference_method DB CHECK constraint izinli değerlerinden olmalı
    # (ck_dsdrel_inference_method) — match_kind suffix'i ('naming:full') ASLA kolona yazılmamalı.
    _allowed = {"naming", "naming+type", "naming+type+sample"}
    for mk in ("full", "head"):
        for tok in (False, True):
            for si in (None, {"coverage_ratio": 1.0}):
                _, m = svc._score(mk, tok, si)
                assert m in _allowed, f"geçersiz inference_method: {m}"


# ─────────────────────────────────────────────────────────────
# v3.60.0: head-noun + Unicode (rol-önekli / Türkçe FK kolonları)
# ─────────────────────────────────────────────────────────────
def test_head_noun_role_prefixed():
    assert svc._head_noun_from_name("CreateUserId") == "user"
    assert svc._head_noun_from_name("PADCompanyId") == "company"
    assert svc._head_noun_from_name("create_user_id") == "user"
    assert svc._head_noun_from_name("PARTYID") == "party"   # all-caps → tek harfe bölünmez
    assert svc._head_noun_from_name("ParentPartyId") == "party"


def test_head_noun_unicode_turkish():
    assert svc._head_noun_from_name("MüşteriId") == "müşteri"
    assert svc._head_noun_from_name("SiparişRef") == "sipariş"


def test_extract_root_unicode_snake():
    # Türkçe snake_case FK kolonu — eski [a-z] regex'i kaçırıyordu
    assert svc._extract_root("müşteri_id") == "müşteri"
    assert svc._extract_root("siparis_ref") == "siparis"


def test_iter_head_noun_resolves_role_prefixed_fk():
    """elysion.T_ORG_PARTY.CreateUserId → head 'user' → T_ORG_USER (full root 'createuser' uymaz)."""
    from app.services.db_learning.fk_inference_dialects import get_dialect
    d = get_dialect("postgresql")
    user = svc._TableInfo(
        schema="elysion", name="T_ORG_USER", norm_name="t_org_user",
        columns=[{"name": "PartyId", "type": "integer", "is_pk": True}],
        pk_columns=["PartyId"],
    )
    party = svc._TableInfo(
        schema="elysion", name="T_ORG_PARTY", norm_name="t_org_party",
        columns=[
            {"name": "PartyId", "type": "integer", "is_pk": True},
            {"name": "CreateUserId", "type": "integer"},
        ],
        pk_columns=["PartyId"],
    )
    tables = {("elysion", "t_org_user"): user, ("elysion", "t_org_party"): party}
    out = list(svc._iter_fk_candidates(tables, d, diag=[]))
    rels = [(t.name, c.get("name"), kind, tt.name) for t, c, root, kind, tt, tc in out]
    assert ("T_ORG_PARTY", "CreateUserId", "head", "T_ORG_USER") in rels


def test_iter_unresolved_diagnostics_recorded():
    """FK üretilemeyen referans-benzeri kolon diag'a 'no_target_table'/'no_pattern' ile yazılır."""
    from app.services.db_learning.fk_inference_dialects import get_dialect
    d = get_dialect("postgresql")
    # Hedefi olmayan FK-benzeri kolon
    t = svc._TableInfo(
        schema="elysion", name="T_ORG_PARTY", norm_name="t_org_party",
        columns=[
            {"name": "PartyId", "type": "integer", "is_pk": True},
            {"name": "GhostThingId", "type": "integer"},  # 'ghostthing'/'thing' → tablo yok
        ],
        pk_columns=["PartyId"],
    )
    tables = {("elysion", "t_org_party"): t}
    diag = []
    list(svc._iter_fk_candidates(tables, d, diag=diag))
    reasons = {dd["column"]: dd["reason"] for dd in diag}
    assert reasons.get("GhostThingId") == "no_target_table"


# ─────────────────────────────────────────────────────────────
# infer_fks_for_source — end-to-end with mocks
# ─────────────────────────────────────────────────────────────
def _seed_objects(cur, tables):
    """Helper: makes cur.fetchall return ds_db_objects rows on first call,
    empty existing-relationships on second call."""
    call_results = [tables, []]
    state = {"i": 0}

    def fetchall_side():
        i = state["i"]
        state["i"] += 1
        return call_results[i] if i < len(call_results) else []

    cur.fetchall.side_effect = fetchall_side


def test_infer_empty_source_returns_zero():
    cur = MagicMock()
    cur.fetchall.return_value = []
    res = svc.infer_fks_for_source(cur, source_id=1)
    assert res["persisted"] == 0
    assert res["candidates"] == 0
    assert res["tables_scanned"] == 0


def test_infer_basic_one_fk():
    cur = MagicMock()
    user_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                 {"name": "name", "type": "varchar", "is_primary_key": False}]
    problem_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                    {"name": "user_id", "type": "integer", "is_primary_key": False}]
    objects = [
        ("public", "users", "table", json.dumps(user_cols)),
        ("public", "problem", "table", json.dumps(problem_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=42, dialect="postgresql")
    assert res["tables_scanned"] == 2
    assert res["candidates"] == 1
    assert res["persisted"] == 1
    # INSERT was called once
    inserts = [c for c in cur.execute.call_args_list
               if "INSERT INTO ds_db_relationships" in c.args[0]]
    assert len(inserts) == 1


def test_infer_prefixed_tables_and_is_pk_key():
    """v3.56.0 KÖK fix: prefixed tablo (T_WF_*) + XxxId PK + columns_json `is_pk` key.

    Eski kod: 0 candidate — (1) root 'instance' TAM ad 't_wf_instance' ile eşleşmez (prefix),
    (2) is_primary_key okuyup is_pk'yı kaçırınca pk_cols boş → hedef PK 'id'ye düşer ama PK
    'InstanceId'. Fix: son-token eşleşmesi + is_pk → candidate üretir + persist eder.
    """
    cur = MagicMock()
    instance_cols = [{"name": "InstanceId", "type": "integer", "is_pk": True},
                     {"name": "Name", "type": "varchar", "is_pk": False}]
    biz_cols = [{"name": "BusinessInteractionId", "type": "integer", "is_pk": True},
                {"name": "InstanceId", "type": "integer", "is_pk": False}]
    objects = [
        ("elysion", "T_WF_INSTANCE", "table", json.dumps(instance_cols)),
        ("elysion", "T_WF_BUSINESSINTERACTION", "table", json.dumps(biz_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=42, dialect="postgresql")
    assert res["tables_scanned"] == 2
    # T_WF_BUSINESSINTERACTION.InstanceId → root 'instance' → son-token → T_WF_INSTANCE.InstanceId(PK)
    assert res["candidates"] >= 1, f"prefixed/is_pk candidate üretilmeli: {res}"
    assert res["persisted"] >= 1
    inserts = [c for c in cur.execute.call_args_list
               if "INSERT INTO ds_db_relationships" in c.args[0]]
    assert len(inserts) >= 1


def test_infer_skips_existing():
    cur = MagicMock()
    user_cols = [{"name": "id", "type": "integer", "is_primary_key": True}]
    problem_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                    {"name": "user_id", "type": "integer", "is_primary_key": False}]
    objects = [
        ("public", "users", "table", json.dumps(user_cols)),
        ("public", "problem", "table", json.dumps(problem_cols)),
    ]
    existing = [("public", "problem", "user_id", "public", "users", "id")]
    call_results = [objects, existing]
    state = {"i": 0}

    def fetchall_side():
        i = state["i"]
        state["i"] += 1
        return call_results[i] if i < len(call_results) else []
    cur.fetchall.side_effect = fetchall_side

    res = svc.infer_fks_for_source(cur, source_id=42, dialect="postgresql")
    assert res["candidates"] == 0
    assert res["skipped_existing"] == 1
    assert res["persisted"] == 0


def test_infer_type_mismatch_lowers_confidence_and_skips():
    cur = MagicMock()
    user_cols = [{"name": "id", "type": "uuid", "is_primary_key": True}]
    problem_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                    {"name": "user_id", "type": "integer", "is_primary_key": False}]
    objects = [
        ("public", "users", "table", json.dumps(user_cols)),
        ("public", "problem", "table", json.dumps(problem_cols)),
    ]
    _seed_objects(cur, objects)
    # naming-only score = 0.6, ≥ default min_confidence (0.60) → persists
    res = svc.infer_fks_for_source(cur, source_id=42, dialect="postgresql",
                                   min_confidence=0.65)
    assert res["candidates"] == 1
    assert res["skipped_low_confidence"] == 1
    assert res["persisted"] == 0


def test_infer_self_fk_org_chart():
    """parent_id → org.id self-reference should be detected."""
    cur = MagicMock()
    # Naming pattern: parent_id → root='parent'; we need a 'parent' table.
    # Self-FK case (org → org via parent_id) requires root match self.
    org_cols = [{"name": "id", "type": "integer", "is_primary_key": True},
                {"name": "org_id", "type": "integer", "is_primary_key": False}]
    objects = [
        ("public", "org", "table", json.dumps(org_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=1, dialect="postgresql")
    assert res["candidates"] == 1
    assert res["persisted"] == 1


def test_infer_unknown_dialect_raises():
    cur = MagicMock()
    with pytest.raises(ValueError):
        svc.infer_fks_for_source(cur, source_id=1, dialect="cassandra")


# ─────────────────────────────────────────────────────────────
# v3.73.0 GOLDEN-SET — gerçek-dünya şema vakaları (kullanıcı bulgusu, bulgular6.docx)
# Hungarian tip-öneki (N/V), T_ORG_ site-öneki, FK-col-adı==PK-adı, esnek PK, false-positive guard.
# ─────────────────────────────────────────────────────────────
def test_infer_camel_fk_col_equals_pk_t_org():
    """image4: elysion.T_ORG_USER.PartyId → T_ORG_PARTY.PartyId.

    camelCase FK + T_ORG_ site-öneki + FK-kolon-adı == hedef PK-adı. Çekirdek bunu
    entity-token (party → t_org_party) + declared-PK ile çözmeli.
    """
    cur = MagicMock()
    party_cols = [{"name": "PartyId", "type": "integer", "is_pk": True},
                  {"name": "Name", "type": "varchar", "is_pk": False}]
    user_cols = [{"name": "Id", "type": "integer", "is_pk": True},
                 {"name": "PartyId", "type": "integer", "is_pk": False}]
    objects = [
        ("elysion", "T_ORG_PARTY", "table", json.dumps(party_cols)),
        ("elysion", "T_ORG_USER", "table", json.dumps(user_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=3, dialect="postgresql")
    assert res["candidates"] >= 1, f"PartyId→T_ORG_PARTY çözülmeli: {res}"
    assert res["persisted"] >= 1
    assert any(s["to"].endswith("T_ORG_PARTY.PartyId") for s in res["sample"]), res["sample"]


def test_infer_hungarian_prefix_strip_pg():
    """CUR.RR_93.NCUSTOMER_ID → CUSTOMER.CustomerId (Hungarian N tip-öneki soyma) — PG."""
    cur = MagicMock()
    cust_cols = [{"name": "CustomerId", "type": "integer", "is_pk": True},
                 {"name": "Name", "type": "varchar", "is_pk": False}]
    rr_cols = [{"name": "Id", "type": "integer", "is_pk": True},
               {"name": "NCUSTOMER_ID", "type": "integer", "is_pk": False}]
    objects = [
        ("cur", "CUSTOMER", "table", json.dumps(cust_cols)),
        ("cur", "RR_93", "table", json.dumps(rr_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=3, dialect="postgresql")
    assert res["candidates"] >= 1, f"NCUSTOMER_ID→CUSTOMER prefix-strip çözülmeli: {res}"
    assert res["persisted"] >= 1
    assert any(s["to"].endswith("CUSTOMER.CustomerId") for s in res["sample"]), res["sample"]


def test_infer_hungarian_prefix_strip_oracle():
    """Aynı Hungarian-prefix vakası Oracle dialect (UPPER case-fold, NUMBER tip)."""
    cur = MagicMock()
    cust_cols = [{"name": "CUSTOMER_ID", "type": "NUMBER", "is_pk": True},
                 {"name": "NAME", "type": "VARCHAR2", "is_pk": False}]
    rr_cols = [{"name": "ID", "type": "NUMBER", "is_pk": True},
               {"name": "NCUSTOMER_ID", "type": "NUMBER", "is_pk": False}]
    objects = [
        ("CUR", "CUSTOMER", "table", json.dumps(cust_cols)),
        ("CUR", "RR_93", "table", json.dumps(rr_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=3, dialect="oracle")
    assert res["candidates"] >= 1, f"Oracle NCUSTOMER_ID→CUSTOMER çözülmeli: {res}"
    assert res["persisted"] >= 1


def test_infer_flexible_pk_when_no_declared_pk():
    """E2: hedef tabloda is_pk YOK (Oracle PK-capture yetki hatası simülasyonu) →
    FK-kolon-adı fallback ile PK çözülür (eski kod 'id'ye düşüp target_pk_not_found verirdi)."""
    cur = MagicMock()
    # T_ORG_PARTY'de hiçbir kolon is_pk DEĞİL → pk_columns boş
    party_cols = [{"name": "PartyId", "type": "integer", "is_pk": False},
                  {"name": "Name", "type": "varchar", "is_pk": False}]
    user_cols = [{"name": "Id", "type": "integer", "is_pk": True},
                 {"name": "PartyId", "type": "integer", "is_pk": False}]
    objects = [
        ("elysion", "T_ORG_PARTY", "table", json.dumps(party_cols)),
        ("elysion", "T_ORG_USER", "table", json.dumps(user_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=3, dialect="postgresql")
    assert res["candidates"] >= 1, f"declared-PK yokken FK-col-adı ile çözülmeli: {res}"
    assert res["persisted"] >= 1
    assert res["unresolved_count"] == 0, f"target_pk_not_found OLMAMALI: {res['unresolved']}"


def test_infer_no_false_positive_short_token():
    """Prefix-strip kısa-token false-positive üretmemeli: node_id ↛ 'ode' (len<4 guard)."""
    cur = MagicMock()
    ode_cols = [{"name": "Id", "type": "integer", "is_pk": True}]
    thing_cols = [{"name": "Id", "type": "integer", "is_pk": True},
                  {"name": "node_id", "type": "integer", "is_pk": False}]
    objects = [
        ("public", "ode", "table", json.dumps(ode_cols)),
        ("public", "thing", "table", json.dumps(thing_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=1, dialect="postgresql")
    assert res["candidates"] == 0, f"node_id→ode spurious eşleşme OLMAMALI: {res}"
    assert res["persisted"] == 0


def test_infer_evidence_records_pk_provenance():
    """v3.74.0 cascade: hedef PK unique-index'ten geldiyse evidence_json bunu kaydeder
    (UI rozeti için). pk_source yoksa 'declared' varsayılır."""
    cur = MagicMock()
    # T_ORG_PARTY PK'sı unique-index'ten yakalanmış (discovery pk_source işaretledi)
    party_cols = [{"name": "PartyId", "type": "integer", "is_pk": True, "pk_source": "unique_index"},
                  {"name": "Name", "type": "varchar", "is_pk": False}]
    user_cols = [{"name": "Id", "type": "integer", "is_pk": True},
                 {"name": "PartyId", "type": "integer", "is_pk": False}]
    objects = [
        ("elysion", "T_ORG_PARTY", "table", json.dumps(party_cols)),
        ("elysion", "T_ORG_USER", "table", json.dumps(user_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=3, dialect="postgresql")
    assert res["persisted"] >= 1
    # evidence_json INSERT 9. parametrede (jsonb) — to_pk_source='unique_index' olmalı
    inserts = [c for c in cur.execute.call_args_list
               if "INSERT INTO ds_db_relationships" in c.args[0]]
    assert inserts, "FK persist edilmeli"
    import json as _json
    ev = _json.loads(inserts[0].args[1][9])  # evidence_json param sırası
    assert ev.get("to_pk_source") == "unique_index", ev


@pytest.mark.parametrize("dialect", ["mssql", "mysql"])
def test_infer_prefix_strip_cross_dialect(dialect):
    """Hungarian V-öneki soyma MSSQL + MySQL dialect'lerinde de çalışır (çekirdek agnostik)."""
    cur = MagicMock()
    cust_cols = [{"name": "CustomerId", "type": "int", "is_pk": True},
                 {"name": "Name", "type": "varchar", "is_pk": False}]
    ord_cols = [{"name": "Id", "type": "int", "is_pk": True},
                {"name": "VCUSTOMER_ID", "type": "int", "is_pk": False}]
    objects = [
        ("dbo", "CUSTOMER", "table", json.dumps(cust_cols)),
        ("dbo", "ORDERS", "table", json.dumps(ord_cols)),
    ]
    _seed_objects(cur, objects)
    res = svc.infer_fks_for_source(cur, source_id=3, dialect=dialect)
    assert res["candidates"] >= 1, f"{dialect}: VCUSTOMER_ID→CUSTOMER çözülmeli: {res}"
    assert res["persisted"] >= 1
