"""v3.40.0 Faz B — merkezi fail-closed tablo-yetki guard'ı testleri (TYCHE).

`app/services/db_smart/table_guard.enforce_sql_scope`:
  - all_tables → kısıt yok (None)
  - restricted + yetkili tablo → ok + whitelist
  - restricted + yetkisiz tablo → DENY (yanlış-tablo adı sızdırmaz)
  - restricted + boş kapsam → DENY (asla allow-all = footgun kapalı)

resolve_scope mock'lanır (DB yok); check_table_whitelist GERÇEK (saf regex).
"""
from unittest.mock import patch

from app.services.data_source_access import AccessScope
from app.services.db_smart import table_guard as tg


def _patch(scope):
    return patch.object(tg, "resolve_scope", lambda *a, **k: scope)


def test_all_tables_no_restriction():
    with _patch(AccessScope(all_tables=True)):
        ok, allowed, deny = tg.enforce_sql_scope("SELECT * FROM x", 3, {"id": 1}, "oracle")
    assert ok is True and allowed is None and deny is None


def test_restricted_authorized_table_passes():
    sc = AccessScope(all_tables=False, tables=frozenset({("vyra_test", "faturalar")}))
    with _patch(sc):
        ok, allowed, deny = tg.enforce_sql_scope(
            'SELECT * FROM "VYRA_TEST"."FATURALAR"', 3, {"id": 1}, "oracle"
        )
    assert ok is True and deny is None
    assert "vyra_test.faturalar" in allowed and "faturalar" in allowed


def test_restricted_unauthorized_table_denied_no_leak():
    sc = AccessScope(all_tables=False, tables=frozenset({("vyra_test", "faturalar")}))
    with _patch(sc):
        ok, allowed, deny = tg.enforce_sql_scope(
            'SELECT * FROM "VYRA_TEST"."MUSTERILER"', 3, {"id": 1}, "oracle"
        )
    assert ok is False and allowed is None
    assert "faturalar" in deny           # yetkili tablo listelenir
    assert "musteriler" not in deny.lower()  # yetkisiz/istenmeyen tablo adı SIZMAZ


def test_restricted_empty_scope_denied_not_allow_all():
    # KRİTİK: boş kapsam → DENY (check_table_whitelist'in boş=allow-all footgun'u KAPALI)
    with _patch(AccessScope(all_tables=False, tables=frozenset())):
        ok, allowed, deny = tg.enforce_sql_scope("SELECT * FROM anything", 3, {"id": 1}, "oracle")
    assert ok is False and allowed is None and deny


def test_cross_schema_same_name_still_passes_whitelist_note():
    # check_table_whitelist şema-agnostiktir (RB-v3.39.0): guard onu sarar, davranış aynı.
    sc = AccessScope(all_tables=False, tables=frozenset({("vyra_test", "faturalar")}))
    with _patch(sc):
        ok, _allowed, _deny = tg.enforce_sql_scope(
            'SELECT * FROM "OTHER"."FATURALAR"', 3, {"id": 1}, "oracle"
        )
    # Aynı tablo adı farklı şema → whitelist short-name match (bilinen sınırlama, backlog RB-v3.39.0)
    assert ok is True
