"""Migration 033 — metric library seed yapısal doğrulama (v3.30.0 FAZ 1 G1.4).

Bu testler dosya/modül seviyesindedir (DB bağlantısı yok) — Alembic uygulanmadan
çalıştırılabilir. Metrik listesinin §G1.4 hedeflerini karşıladığını doğrular.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "033_v3300_metric_library_seed.py"


@pytest.fixture(scope="module")
def m033():
    spec = importlib.util.spec_from_file_location("m033", str(MIGRATION_PATH))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_chain(m033):
    assert m033.revision == "033_v3300_metric_library_seed"
    assert m033.down_revision == "032_v3300_db_smart_core_tables"


def test_minimum_24_metrics(m033):
    """Plan §G1.4 hedefi: 24+ metrik."""
    assert len(m033.ALL_METRICS) >= 24


def test_three_domains_present(m033):
    assert len(m033.GENERIC_METRICS) == 8
    assert len(m033.HELPDESK_METRICS) == 12
    assert len(m033.SALES_METRICS) == 10


def test_all_metrics_have_4_dialects(m033):
    """Plan §G1.4: her metrik 4 dialect SQL template içermeli."""
    expected = {"postgresql", "oracle", "mssql", "mysql"}
    for m in m033.ALL_METRICS:
        actual = set(m["sql_templates"].keys())
        assert actual == expected, f"{m['metric_key']}: missing dialects {expected - actual}"


def test_metric_keys_unique(m033):
    keys = [m["metric_key"] for m in m033.ALL_METRICS]
    assert len(set(keys)) == len(keys), f"Duplicate metric_key: {set([k for k in keys if keys.count(k) > 1])}"


def test_required_fields_present(m033):
    required = {"metric_key", "name_tr", "category", "description_tr",
                "applicable_when", "sql_templates", "default_viz"}
    for m in m033.ALL_METRICS:
        missing = required - set(m.keys())
        assert not missing, f"{m['metric_key']}: missing fields {missing}"


def test_default_viz_in_check_constraint(m033):
    """Migration 032 ck_dbsmart_metric_viz CHECK constraint ile uyumlu olmalı."""
    valid_viz = {
        "table", "bar", "line", "area", "kpi", "pie", "donut", "heatmap",
        "treemap", "funnel", "cohort", "map", "scatter", "box", "sankey",
        "sunburst", "calendar",
    }
    for m in m033.ALL_METRICS:
        assert m["default_viz"] in valid_viz, f"{m['metric_key']}: bad viz '{m['default_viz']}'"


def test_applicable_when_is_json_serializable(m033):
    for m in m033.ALL_METRICS:
        # JSONB kolon: serialize edilebilmeli
        json.dumps(m["applicable_when"])
        json.dumps(m["sql_templates"])


def test_categories_match_metric_key_prefix(m033):
    """metric_key prefix'i (örn. 'helpdesk.foo') category ile eşleşmeli."""
    for m in m033.ALL_METRICS:
        prefix = m["metric_key"].split(".", 1)[0]
        assert m["category"] == prefix, f"{m['metric_key']}: prefix '{prefix}' != category '{m['category']}'"


def test_sql_templates_non_empty(m033):
    for m in m033.ALL_METRICS:
        for dialect, sql in m["sql_templates"].items():
            assert sql and "SELECT" in sql.upper(), f"{m['metric_key']}[{dialect}]: empty/invalid SQL"


def test_upgrade_and_downgrade_defined(m033):
    assert callable(m033.upgrade)
    assert callable(m033.downgrade)
