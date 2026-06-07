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


class TestWeightedSelection:
    """v3.78.3 (TEMA-2 Dilim-1) — cardinality-ağırlıklı join seçimi (path_weight 5. eleman)."""

    def test_weighted_prefers_lighter_over_fewer_hops(self):
        # A→B direkt AĞIR (junction, 200) vs A→X→B HAFİF (50+50=100) → hafif-UZUN yol seçilir
        edges = [
            ("s.a", "bid", "s.b", "id", 200),
            ("s.a", "xid", "s.x", "id", 50),
            ("s.x", "bid", "s.b", "id", 50),
        ]
        p = find_join_path(edges, "s.a", ["s.b"], ALL)
        assert p["ok"] is True
        assert len(p["joins"]) == 2          # 2-hop hafif yol (1-hop ağır DEĞİL) — 2.1 çekirdek
        assert "s.x" in p["tables"]          # köprü kullanıldı

    def test_tie_break_prefers_fewer_hops(self):
        # Eşit Σağırlık (100): A→B direkt(100) vs A→X→B(50+50) → AZ-HOP (direkt) kazanır
        edges = [
            ("s.a", "bid", "s.b", "id", 100),
            ("s.a", "xid", "s.x", "id", 50),
            ("s.x", "bid", "s.b", "id", 50),
        ]
        p = find_join_path(edges, "s.a", ["s.b"], ALL)
        assert p["ok"] is True
        assert len(p["joins"]) == 1          # direkt (1 hop) — eşitlikte az-hop

    def test_default_weight_degrades_to_min_hop(self):
        # 4-tuple kenar (path_weight YOK) → _DEFAULT_WEIGHT uniform → BFS-min-hop davranışı
        edges = [
            ("s.a", "bid", "s.b", "id"),       # direkt, ağırlıksız
            ("s.a", "xid", "s.x", "id"),
            ("s.x", "bid", "s.b", "id"),
        ]
        p = find_join_path(edges, "s.a", ["s.b"], ALL)
        assert p["ok"] is True
        assert len(p["joins"]) == 1          # uniform → min-hop = direkt (güvenli degrade)

    def test_scope_aware_prefers_inscope_direct_over_lighter_outofscope(self):
        # REGRESYON FIX (gstack-adversarial F1): hafif yol out-of-scope köprü X'ten geçse de,
        # IN-SCOPE direkt yol VARSA o kullanılır (ağır olsa bile) → ok=True. Weighting,
        # daha-hafif-ama-scope-dışı yolu seçip mevcut join'i REGRESE ETMEZ.
        edges = [
            ("s.a", "bid", "s.b", "id", 200),   # direkt AĞIR ama in-scope
            ("s.a", "xid", "s.x", "id", 50),    # X üzerinden HAFİF ama X scope-dışı
            ("s.x", "bid", "s.b", "id", 50),
        ]
        scope = {"s.a", "s.b"}                  # X kapsam DIŞI
        p = find_join_path(edges, "s.a", ["s.b"], lambda t: t in scope)
        assert p["ok"] is True                  # in-scope direkt yol kullanıldı (regresyon yok)
        assert len(p["joins"]) == 1
        assert "s.x" not in p["tables"]         # out-of-scope köprü KULLANILMADI

    def test_scope_missing_bridge_still_diagnosed(self):
        # SADECE out-of-scope köprüden geçen yol varsa (in-scope alternatif YOK) →
        # missing_scope diagnostic KORUNUR (kullanıcıya "köprü seç" uyarısı).
        edges = [
            ("s.a", "xid", "s.x", "id", 50),    # tek yol X üzerinden
            ("s.x", "bid", "s.b", "id", 50),
        ]
        scope = {"s.a", "s.b"}                  # X kapsam DIŞI, başka yol yok
        p = find_join_path(edges, "s.a", ["s.b"], lambda t: t in scope)
        assert p["ok"] is False
        assert p["missing_scope"] == ["s.x"]    # diagnostic korundu

    def test_weighted_deterministic_across_calls(self):
        # Eşit-maliyet iki alternatif (X ve Y, ikisi 50+50) → tie-sıra stabil, iki çağrı ÖZDEŞ
        edges = [
            ("s.a", "xid", "s.x", "id", 50),
            ("s.x", "bid", "s.b", "id", 50),
            ("s.a", "yid", "s.y", "id", 50),
            ("s.y", "bid", "s.b", "id", 50),
        ]
        p1 = find_join_path(edges, "s.a", ["s.b"], ALL)
        p2 = find_join_path(edges, "s.a", ["s.b"], ALL)
        assert p1["joins"] == p2["joins"]       # deterministik (cache-stable)
        assert len(p1["joins"]) == 2

    def test_weighted_multi_target_independent(self):
        # Çok-hedef: her hedefe AYRI en-hafif yol (B'ye hafif köprü, C'ye direkt)
        edges = [
            ("s.a", "bid", "s.b", "id", 200),
            ("s.a", "xid", "s.x", "id", 50),
            ("s.x", "bid", "s.b", "id", 50),
            ("s.a", "cid", "s.c", "id", 70),
        ]
        p = find_join_path(edges, "s.a", ["s.b", "s.c"], ALL)
        assert p["ok"] is True
        assert "s.x" in p["tables"]             # B'ye hafif köprü
        assert "s.c" in p["tables"]             # C direkt


class TestRenderJoinHint:
    def test_hint_contains_on_condition(self):
        p = find_join_path(EDGES, "vyra_test.siparisler", ["vyra_test.musteriler"], ALL)
        hint = render_join_hint(p)
        assert "JOIN" in hint and "musteri_id" in hint and "siparisler" in hint

    def test_empty_when_no_joins(self):
        p = find_join_path(EDGES, "vyra_test.musteriler", ["vyra_test.musteriler"], ALL)
        assert render_join_hint(p) == ""
