# -*- coding: utf-8 -*-
"""
v3.37.0 (HEBE-FE 2026-05-25) — Smart Discovery Wizard UX bundle tests
======================================================================

Brief: .agents/in_flight/2026-05-25_2245_v3370_smart_wizard_ux_bundle.md

POSEIDON tavsiyesi: Playwright Windows CI riski → basit string-pattern
assertion'lar (regex / substring) ile JS+CSS+HTML statik içeriği kontrol
ediyoruz. Bu, browser dependency'siz, hızlı, deterministik.

Test edilen davranışlar (9 kapı):
  - B3  : delete handler grid refresh çağrısı (loadSavedReports)
  - B5a : Next butonu disabled mantığı (reportColumns empty guard)
  - B5a : showToast / _notify çağrısı + "kolon" mesajı
  - B6  : sticky footer + textarea#user-intent + .wizard-sticky-footer class
  - B7b : ORDER BY chip toggle (ASC/DESC) fonksiyonu
  - B4  : LLM metric-suggest endpoint çağrısı (fetch + URL)
  - B5b : LLM column-suggest iki kategori (metric-cols + dimensions)
  - B8  : format apply state set (state.format = card pattern)
  - LLM : error catch + buton re-enable (try/catch + _llmSetBusy(btn, false))
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
JS_PATH = REPO_ROOT / "frontend" / "assets" / "js" / "modules" / "db_smart_wizard.js"
CSS_PATH = REPO_ROOT / "frontend" / "assets" / "css" / "modules" / "_db_smart_wizard.css"


@pytest.fixture(scope="module")
def wizard_js() -> str:
    assert JS_PATH.exists(), f"wizard JS bulunamadi: {JS_PATH}"
    return JS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def wizard_css() -> str:
    assert CSS_PATH.exists(), f"wizard CSS bulunamadi: {CSS_PATH}"
    return CSS_PATH.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────
# B3 — delete handler grid refresh
# ──────────────────────────────────────────────────────────────────────

def test_b3_delete_handler_reloads_grid(wizard_js: str) -> None:
    """_confirmDeleteSavedReport DELETE sonrası loadSavedReports() çağırmalı."""
    # Delete fonksiyonu mevcut + DELETE method kullanıyor
    assert "_confirmDeleteSavedReport" in wizard_js
    assert "'DELETE'" in wizard_js or '"DELETE"' in wizard_js
    # Delete handler bloku içinde loadSavedReports() çağrısı olmalı
    # (yeni B3 davranışı — eski inline removeChild yerine).
    m = re.search(
        r"async\s+function\s+_confirmDeleteSavedReport\s*\([^)]*\)\s*\{.*?\n    \}",
        wizard_js,
        re.DOTALL,
    )
    assert m is not None, "_confirmDeleteSavedReport bloku bulunamadi"
    block = m.group(0)
    assert "loadSavedReports()" in block or "_loadSavedReportsList()" in block, (
        "Delete handler grid refresh icin loadSavedReports() cagirmali"
    )


# ──────────────────────────────────────────────────────────────────────
# B5a — empty columns Next disable + toast
# ──────────────────────────────────────────────────────────────────────

def test_b5a_next_button_disabled_attribute(wizard_js: str) -> None:
    """Step 3 Next butonu reportColumns boşken disabled olmalı."""
    assert "_updateNextGuard" in wizard_js, "B5a guard fonksiyonu eksik"
    # Empty kontrol + disabled set
    assert "_state.reportColumns.length === 0" in wizard_js or \
           "reportColumns.length === 0" in wizard_js, "Empty kontrol eksik"
    assert "next.disabled = empty" in wizard_js, "next.disabled set edilmemis"


def test_b5a_toast_called_on_empty_next(wizard_js: str) -> None:
    """Disabled Next click denemesinde toast/notify 'kolon' mesaji ile cikmali."""
    # _notify çağrısı + "kolon" kelimesini içeren mesaj
    assert "_notify('En az bir kolon seçin'" in wizard_js, (
        "Empty Next toast mesaji eksik"
    )
    # Ek olarak mousedown listener (disabled butonda native click fire etmez)
    assert "addEventListener('mousedown'" in wizard_js


# ──────────────────────────────────────────────────────────────────────
# B6 — sticky footer (user_intent + Çalıştır)
# ──────────────────────────────────────────────────────────────────────

def test_b6_sticky_footer_textarea_exists(wizard_js: str, wizard_css: str) -> None:
    """wizard-sticky-footer class + textarea#user-intent + maxlength=500."""
    # JS textarea oluşturuyor
    assert "wizard-sticky-footer" in wizard_js, "wizard-sticky-footer class eksik (JS)"
    assert 'id="user-intent"' in wizard_js, "user-intent textarea id eksik"
    assert "maxlength=\"500\"" in wizard_js or "maxlength='500'" in wizard_js, (
        "maxlength=500 eksik"
    )
    # CSS sticky positioning
    assert ".wizard-sticky-footer" in wizard_css
    assert "position: sticky" in wizard_css or "position:sticky" in wizard_css
    # Çalıştır butonu (B7a) sticky footer içinde sağda
    assert 'id="run-btn"' in wizard_js or "id='run-btn'" in wizard_js
    assert "wizard-run-btn" in wizard_js


# ──────────────────────────────────────────────────────────────────────
# B7b — ORDER BY editable chips toggle
# ──────────────────────────────────────────────────────────────────────

def test_b7b_order_by_chip_toggle_function(wizard_js: str) -> None:
    """ORDER BY chip ASC ↔ DESC toggle handler + draggable + remove."""
    assert "_renderOrderByChips" in wizard_js, "_renderOrderByChips fonksiyonu eksik"
    assert "order-chip" in wizard_js, "order-chip class eksik"
    # ASC/DESC toggle (ternary'yi `===` ile arıyoruz; tek-tırnak çift-tırnak fark etmez)
    assert "=== 'ASC'" in wizard_js or '=== "ASC"' in wizard_js, (
        "ASC/DESC toggle handler bulunamadi"
    )
    # Drag-reorder (HTML5 native)
    assert "draggable=\"true\"" in wizard_js or "draggable='true'" in wizard_js
    # Remove handler
    assert "data-order-remove" in wizard_js
    # state.order_by
    assert "_state.order_by" in wizard_js


# ──────────────────────────────────────────────────────────────────────
# B4 — Metrik Öner LLM endpoint
# ──────────────────────────────────────────────────────────────────────

def test_llm_metric_button_calls_endpoint(wizard_js: str) -> None:
    """B4 click → POST /db-smart/llm/metric-suggest."""
    assert "_onMetricSuggestClick" in wizard_js
    # Endpoint path
    assert "/llm/metric-suggest" in wizard_js, "metric-suggest endpoint eksik"
    # POST method
    metric_section = wizard_js.split("_onMetricSuggestClick", 1)[1].split(
        "_renderMetricSuggestions", 1
    )[0]
    assert "'POST'" in metric_section or '"POST"' in metric_section
    # Payload alanları
    assert "user_intent" in metric_section
    assert "source_id" in metric_section


# ──────────────────────────────────────────────────────────────────────
# B5b — Kolon Öner iki kategori render
# ──────────────────────────────────────────────────────────────────────

def test_llm_column_two_category_render(wizard_js: str) -> None:
    """Kolon öneri render'ı 'Metriğe Bağlı Kolonlar' + 'İlgili Boyutlar' bölümleri."""
    assert "_renderColumnSuggestions" in wizard_js
    assert "Metriğe Bağlı Kolonlar" in wizard_js, "Metric-cols başlığı eksik"
    assert "İlgili Boyutlar" in wizard_js, "Dimensions başlığı eksik"
    # İki ayrı data-section container
    assert 'data-section="metric-cols"' in wizard_js
    assert 'data-section="dimensions"' in wizard_js
    # Endpoint
    assert "/llm/column-suggest" in wizard_js


# ──────────────────────────────────────────────────────────────────────
# B8 — Format Öner apply → state.format
# ──────────────────────────────────────────────────────────────────────

def test_llm_format_apply_sets_state(wizard_js: str) -> None:
    """Format kartı Uygula → _state.format = card."""
    assert "_renderFormatSuggestions" in wizard_js
    assert "/llm/format-suggest" in wizard_js
    # Apply handler içinde state.format = card
    assert "_state.format = card" in wizard_js, (
        "_state.format = card atamasi eksik"
    )
    # Format kartı UI
    assert "dsw-format-card" in wizard_js
    assert "data-format-apply" in wizard_js


# ──────────────────────────────────────────────────────────────────────
# LLM — error toast + buton re-enable
# ──────────────────────────────────────────────────────────────────────

def test_llm_error_toast_and_reenable(wizard_js: str) -> None:
    """LLM fetch fail → 'AI önerisi alınamadı' toast + buton re-enable."""
    # _llmError helper buton state'i resetliyor
    assert "_llmError" in wizard_js
    # Error mesajı
    assert "AI önerisi alınamadı" in wizard_js, (
        "Hata toast mesajı eksik"
    )
    # _llmSetBusy(btn, false) buton re-enable pattern
    assert "_llmSetBusy(btn, false)" in wizard_js, (
        "Buton re-enable çağrısı eksik"
    )
    # try/catch bloku — her LLM click handler'ında olmalı (üç tane: metric/column/format)
    assert wizard_js.count("} catch (e) {") >= 3, (
        "Her LLM handler için try/catch beklenir"
    )
