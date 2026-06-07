"""TEMA-2 Dilim-2 (v3.79.0) — metrik belirsizliği clarify testleri (saf/MagicMock, DB'siz)."""
from app.services.pipeline.nodes.metric_ambiguity import (
    detect_metric_ambiguity,
    enumerate_candidate_metrics,
)
from app.services.pipeline.nodes.metric_ambiguity_gate import (
    metric_ambiguity_gate_node,
    route_after_metric_ambiguity,
)
from app.services.pipeline.nodes.metric_clarification import metric_clarification_node

# Aday tablo (selected_tables şekli: table_name + columns[column_name/data_type/business_name_tr/is_pk/is_fk])
TBL_MEASURE = {
    "table_name": "siparisler", "business_name_tr": "Siparişler",
    "columns": [
        {"column_name": "id", "data_type": "integer", "is_pk": True},
        {"column_name": "musteri_id", "data_type": "integer", "is_fk": True},
        {"column_name": "tutar", "data_type": "numeric", "business_name_tr": "Tutar"},
        {"column_name": "siparis_tarihi", "data_type": "timestamp", "business_name_tr": "Sipariş Tarihi"},
    ],
}
TBL_NO_MEASURE = {
    "table_name": "kategoriler", "business_name_tr": "Kategoriler",
    "columns": [
        {"column_name": "id", "data_type": "integer", "is_pk": True},
        {"column_name": "ad", "data_type": "varchar", "business_name_tr": "Ad"},
    ],
}


class TestEnumerate:
    def test_count_sum_max(self):
        cands = enumerate_candidate_metrics([TBL_MEASURE])
        aggs = {(c["agg_func"], c["column"]) for c in cands}
        assert ("COUNT", None) in aggs          # adet
        assert ("SUM", "tutar") in aggs          # ölçü numeric
        assert ("MAX", "siparis_tarihi") in aggs # tarih recency

    def test_pk_fk_skipped(self):
        cands = enumerate_candidate_metrics([TBL_MEASURE])
        cols = {c["column"] for c in cands}
        assert "id" not in cols and "musteri_id" not in cols  # PK/FK ölçü değil

    def test_non_measure_numeric_skipped(self):
        # numeric ama ölçü-keyword yok → SUM adayı OLMAZ
        t = {"table_name": "t", "columns": [{"column_name": "yas", "data_type": "integer"}]}
        cands = enumerate_candidate_metrics([t])
        assert all(c["agg_func"] != "SUM" for c in cands)  # sadece COUNT

    def test_max_candidates_cap(self):
        assert len(enumerate_candidate_metrics([TBL_MEASURE, TBL_NO_MEASURE], max_candidates=2)) == 2


class TestDetect:
    def test_ambiguous(self):
        d = detect_metric_ambiguity("top 10 müşteri", [TBL_MEASURE])
        assert d["needs_clarification"] is True
        assert d["reason"] == "metric_ambiguous"
        assert len(d["candidates"]) >= 2

    def test_explicit_metric_not_ambiguous(self):
        # "toplam" → agg_func=SUM (explicit) → belirsiz değil
        d = detect_metric_ambiguity("toplam ciroya göre en çok müşteri", [TBL_MEASURE])
        assert d["needs_clarification"] is False and d["reason"] == "explicit_metric"

    def test_no_ranking_not_ambiguous(self):
        d = detect_metric_ambiguity("müşterileri göster", [TBL_MEASURE])
        assert d["needs_clarification"] is False and d["reason"] == "no_ranking_intent"

    def test_single_candidate_not_ambiguous(self):
        d = detect_metric_ambiguity("en çok kategori", [TBL_NO_MEASURE])
        assert d["needs_clarification"] is False and d["reason"] == "single_candidate"

    def test_tr_ranking_keywords(self):
        for q in ("en çok müşteri", "en fazla sipariş", "müşterileri sırala", "top 5 sipariş", "ilk 10 müşteri"):
            d = detect_metric_ambiguity(q, [TBL_MEASURE])
            assert d["needs_clarification"] is True, q

    def test_ascii_ranking_keywords(self):
        # adversarial-fix #4: diakritiksiz "en cok/fazla" da ranking yakalanır + belirsiz
        # (explicit metrik yok). NOT: "en yuksek ciro" = MAX(ciro) explicit → ayrı dal.
        for q in ("en cok musteri", "en fazla musteri"):
            d = detect_metric_ambiguity(q, [TBL_MEASURE])
            assert d["needs_clarification"] is True, q
        # ASCII ranking YAKALANDI ama explicit (MAX) → no_ranking_intent DEĞİL
        assert detect_metric_ambiguity("en yuksek ciro", [TBL_MEASURE])["reason"] != "no_ranking_intent"

    def test_recency_not_ambiguous(self):
        # adversarial-fix #5: salt-yenilik → metrik değil (MAX tarih ima), soru sorma
        for q in ("en son siparişler", "en son 10 müşteri", "son 5 sipariş"):
            d = detect_metric_ambiguity(q, [TBL_MEASURE])
            assert d["needs_clarification"] is False and d["reason"] == "recency_intent", q

    def test_deep_think_shape_flexible(self):
        # deep_think/text_to_sql şekli: {name, columns:[{name, data_type}]} (agentic'ten farklı)
        dt_tbl = {"name": "siparisler", "business_name_tr": "Siparişler", "columns": [
            {"name": "id", "data_type": "int", "is_pk": True},
            {"name": "tutar", "data_type": "numeric"},
            {"name": "tarih", "data_type": "date"},
        ]}
        d = detect_metric_ambiguity("top 10 müşteri", [dt_tbl])
        assert d["needs_clarification"] is True
        cols = {c["column"] for c in d["candidates"]}
        assert "tutar" in cols and "id" not in cols  # SUM(tutar), PK eleme

    def test_count_only_not_ambiguous(self):
        # adversarial-fix #6: hepsi COUNT → tablo/grain sorusu, metrik belirsizliği değil
        t2 = {"table_name": "etiketler", "columns": [{"column_name": "id", "data_type": "int", "is_pk": True}]}
        d = detect_metric_ambiguity("en çok kategori", [TBL_NO_MEASURE, t2])
        assert d["needs_clarification"] is False and d["reason"] == "count_only"


class TestGateNode:
    def test_ambiguous_sets_payload(self):
        out = metric_ambiguity_gate_node({"question": "top 10 müşteri", "selected_tables": [TBL_MEASURE]})
        assert out["metric_ambiguity"]["needs_clarification"] is True
        assert out["clarification_payload"]["kind"] == "metric"
        assert route_after_metric_ambiguity(out) == "metric_clarification"

    def test_table_clarify_active_skips(self):
        # GÜVENLİ guard: table belirsizdiyse metrik-clarify ATLA (iki-interrupt yok)
        out = metric_ambiguity_gate_node({
            "question": "top 10 müşteri", "selected_tables": [TBL_MEASURE],
            "ambiguity": {"needs_clarification": True},
        })
        assert out["metric_ambiguity"]["needs_clarification"] is False
        assert out["metric_ambiguity"]["reason"] == "table_clarify_active"
        assert "clarification_payload" not in out
        assert route_after_metric_ambiguity(out) == "sql_generate"

    def test_already_chosen_skips(self):
        out = metric_ambiguity_gate_node({
            "question": "top 10 müşteri", "selected_tables": [TBL_MEASURE],
            "chosen_metric": {"expr": "SUM(tutar)"},
        })
        assert out["metric_ambiguity"]["reason"] == "already_chosen"


class TestClarificationNode:
    def test_resume_chosen_metric_object(self):
        cm = {"agg_func": "SUM", "expr": "SUM(tutar)", "label_tr": "toplam Tutar'e göre"}
        out = metric_clarification_node({"user_choice": {"chosen_metric": cm}})
        assert out["chosen_metric"] == cm

    def test_resume_metric_index(self):
        c0 = {"expr": "COUNT(*)"}; c1 = {"expr": "SUM(tutar)"}
        out = metric_clarification_node({
            "user_choice": {"metric_index": 1},
            "clarification_payload": {"candidates": [c0, c1]},
        })
        assert out["chosen_metric"] == c1

    def test_pre_interrupt(self):
        out = metric_clarification_node({})
        assert out.get("_interrupt") is True and "chosen_metric" not in out

    def test_stale_table_choice_does_not_consume(self):
        # GÜVENLİ: tablo-seçimi user_choice'u (metrik anahtarı yok) → tüketme, interrupt
        out = metric_clarification_node({"user_choice": {"selected_tables": [TBL_MEASURE]}})
        assert out.get("_interrupt") is True and "chosen_metric" not in out
