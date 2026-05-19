"""feature_permissions seed — aki_kesif eklendiğini doğrula (FAZ 0)."""
from __future__ import annotations

from app.api.routes.feature_permissions import (
    FEATURE_LABELS,
    KNOWN_FEATURE_KEYS,
)


def test_aki_kesif_in_known_feature_keys():
    assert "aki_kesif" in KNOWN_FEATURE_KEYS


def test_aki_kesif_has_tr_label():
    assert FEATURE_LABELS.get("aki_kesif") == "Akıllı Veri Keşfi"


def test_existing_features_unchanged():
    # Mevcut 3 modülün anahtarları bozulmamalı
    assert {"kb", "db", "llm"}.issubset(KNOWN_FEATURE_KEYS)
    assert FEATURE_LABELS["kb"] == "Bilgi Tabanında Ara"
    assert FEATURE_LABELS["db"] == "Veritabanında Ara"
    assert FEATURE_LABELS["llm"] == "VYRA ile Sohbet Et"
