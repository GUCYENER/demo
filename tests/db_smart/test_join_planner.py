"""v3.42.0 (Faz 2) — deterministik FK join planlayıcı testleri (saf, DB'siz)."""
from app.services.db_smart.join_planner import find_join_path, render_join_hint

# VYRA_TEST gerçek FK grafiği (ds_db_relationships, source 3 — kanıtlı)
EDGES = [
    ("vyra_test.adresler", "musteri_id", "vyra_test.musteriler", "musteri_id"),
    ("vyra_test.siparisler", "musteri_id", "vyra_test.musteriler", "musteri_id"),
    ("vyra_test.faturalar", "siparis_id", "vyra_test.siparisler", "siparis_id"),
    ("vyra_test.odemeler", "fatura_id", "vyra_test.faturalar", "fatura_id"),
]
ALL = lambda t: True  # noqa: E731


class TestFindJoinPath:
    def test_direct_join_siparisler_musteriler(self):
        p = find_join_path(EDGES, "vyra_test.siparisler", ["vyra_test.musteriler"], ALL)
        assert p["ok"] is True
        assert len(p["joins"]) == 1
        j = p["joins"][0]
        assert {j["left"], j["right"]} == {"vyra_test.siparisler", "vyra_test.musteriler"}
        assert j["left_col"] == "musteri_id" and j["right_col"] == "musteri_id"

    def test_two_hop_faturalar_to_musteriler_via_siparisler(self):
        p = find_join_path(EDGES, "vyra_test.faturalar", ["vyra_test.musteriler"], ALL)
        assert p["ok"] is True
        assert "vyra_test.siparisler" in p["tables"]  # köprü tablo yolda
        assert len(p["joins"]) == 2

    def test_out_of_scope_bridge_blocks(self):
        # Kullanıcı FATURALAR + MUSTERILER'e yetkili ama köprü SIPARISLER'e DEĞİL
        scope = {"vyra_test.faturalar", "vyra_test.musteriler", "vyra_test.adresler"}
        p = find_join_path(EDGES, "vyra_test.faturalar", ["vyra_test.musteriler"],
                           lambda t: t in scope)
        assert p["ok"] is False
        assert p["missing_scope"] == ["vyra_test.siparisler"]

    def test_same_table_no_join(self):
        p = find_join_path(EDGES, "vyra_test.musteriler", ["vyra_test.musteriler"], ALL)
        assert p["ok"] is True
        assert p["joins"] == []

    def test_unreachable_target(self):
        # FK grafiğinde hiç bağlı olmayan tablo
        p = find_join_path(EDGES, "vyra_test.siparisler", ["vyra_test.kampanyalar"], ALL)
        assert p["ok"] is False
        assert p["unreachable"] == ["vyra_test.kampanyalar"]

    def test_multi_target_union(self):
        # siparisler → musteriler (direct) + siparisler → faturalar (direct)
        p = find_join_path(EDGES, "vyra_test.siparisler",
                           ["vyra_test.musteriler", "vyra_test.faturalar"], ALL)
        assert p["ok"] is True
        assert {"vyra_test.musteriler", "vyra_test.faturalar"}.issubset(set(p["tables"]))

    def test_bare_name_resolution(self):
        # v3.42.0 Faz 3b: wizard bare tablo adı gönderebilir → qualified düğüme çözülmeli
        p = find_join_path(EDGES, "SIPARISLER", ["MUSTERILER"], ALL)
        assert p["ok"] is True and len(p["joins"]) == 1

    def test_mixed_bare_qualified(self):
        p = find_join_path(EDGES, "faturalar", ["vyra_test.musteriler"], ALL)
        assert p["ok"] is True and len(p["joins"]) == 2


class TestRenderJoinHint:
    def test_hint_contains_on_condition(self):
        p = find_join_path(EDGES, "vyra_test.siparisler", ["vyra_test.musteriler"], ALL)
        hint = render_join_hint(p)
        assert "JOIN" in hint and "musteri_id" in hint and "siparisler" in hint

    def test_empty_when_no_joins(self):
        p = find_join_path(EDGES, "vyra_test.musteriler", ["vyra_test.musteriler"], ALL)
        assert render_join_hint(p) == ""
