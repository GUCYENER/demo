"""VYRA v3.37.0 — LLM Format Suggest Service (B8 / METIS-FORMAT).

Step 4 (Önizleme) sürecinde kullanıcı "Hazır rapor formatı öner" dediğinde
LLM'den 3-5 hazır rapor kartı (chart_type + group_by + order_by) önerir.

Public API:
    suggest_formats(metric: Dict, columns: List[str], user_intent: Optional[str]) -> Dict

Davranış:
- Cache (Redis veya in-memory fallback) — TTL 900 sn.
- Chart type whitelist: line / bar / pie / table / kpi / area.
- LLM çıktısı JSON dışı veya whitelist dışı türler içerirse temizler.

Owner: METIS-FORMAT
Brief: .agents/in_flight/2026-05-25_2242_v3370_llm_format_suggest.md
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.core.llm import call_llm_api, get_active_llm

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# Sabitler
# ──────────────────────────────────────────────────────────────────

CHART_TYPE_WHITELIST = {"line", "bar", "pie", "table", "kpi", "area"}
CACHE_TTL_SECONDS = 900  # 15 dakika
CACHE_KEY_PREFIX = "llm:format"
MIN_CARDS = 3
MAX_CARDS = 5


# ──────────────────────────────────────────────────────────────────
# Yardımcılar
# ──────────────────────────────────────────────────────────────────

def _sha256(payload: Any) -> str:
    """Deterministik sha256 üret (JSON-serialize edilebilir veriler için)."""
    try:
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        raw = str(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_key(metric: Dict[str, Any], columns: List[str], user_intent: Optional[str]) -> str:
    """Cache anahtarı: llm:format:{metric_hash}:{cols_hash}:{intent_hash}."""
    metric_h = _sha256(metric)
    cols_h = _sha256(sorted(columns or []))
    intent_h = _sha256(user_intent or "")
    return f"{CACHE_KEY_PREFIX}:{metric_h}:{cols_h}:{intent_h}"


def _get_cache():
    """Redis cache singleton — yoksa in-memory fallback.

    Hata durumunda None döner (graceful degradation).
    """
    try:
        from app.core.redis_cache import RedisCache  # type: ignore
        return RedisCache(default_ttl=CACHE_TTL_SECONDS, key_prefix="vyra:")
    except Exception as exc:  # pragma: no cover - import veya bağlantı hatası
        logger.warning("LLM format cache başlatılamadı: %s", exc)
        return None


def _safe_cache_get(cache: Any, key: str) -> Optional[Any]:
    if cache is None:
        return None
    try:
        return cache.get(key)
    except Exception as exc:
        logger.warning("Cache GET hatası (%s): %s", key, exc)
        return None


def _safe_cache_set(cache: Any, key: str, value: Any, ttl: int) -> None:
    if cache is None:
        return
    try:
        cache.set(key, value, ttl=ttl)
    except Exception as exc:
        logger.warning("Cache SET hatası (%s): %s", key, exc)


# ──────────────────────────────────────────────────────────────────
# Prompt
# ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "Sen veri görselleştirme uzmanısın. Verilen metrik ve kolon listesi için "
    "3-5 hazır rapor format kartı önerirsin. Her kart için aşağıdaki alanları üret:\n"
    "- title: Türkçe, kısa, açıklayıcı başlık.\n"
    "- chart_type: SADECE şunlardan biri: line, bar, pie, table, kpi, area.\n"
    "- group_by: Liste, SQL kolon/ifadeleri (ör: ['MONTH(tarih)']).\n"
    "- order_by: Liste, SQL ifadeleri (ör: ['SUM(tutar) DESC']).\n"
    "- rationale: Tek cümlelik gerekçe.\n"
    "ÇIKTI: SADECE geçerli JSON döndür, ek açıklama yazma. "
    "Şema: {\"cards\": [{\"title\": \"...\", \"chart_type\": \"...\", "
    "\"group_by\": [...], \"order_by\": [...], \"rationale\": \"...\"}]}"
)


def _build_user_prompt(
    metric: Dict[str, Any],
    columns: List[str],
    user_intent: Optional[str],
) -> str:
    intent_part = f"\nKullanıcı niyeti: {user_intent}" if user_intent else ""
    return (
        f"Metrik: {json.dumps(metric, ensure_ascii=False)}\n"
        f"Kolonlar: {json.dumps(columns, ensure_ascii=False)}"
        f"{intent_part}\n\n"
        "3-5 rapor format kartı öner. SADECE JSON dön."
    )


# ──────────────────────────────────────────────────────────────────
# LLM yanıt parse + sanitize
# ──────────────────────────────────────────────────────────────────

def _extract_json_block(text: str) -> Optional[Dict[str, Any]]:
    """LLM yanıtından JSON gövdesini çıkarır.

    LLM bazen ``` markdown bloğu veya ön/arka metin ekleyebilir.
    """
    if not text:
        return None
    # Önce doğrudan parse dene
    try:
        return json.loads(text)
    except Exception:
        pass
    # Markdown fence temizle
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:
            pass
    # İlk { ... } bloğunu kaba yakala
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        try:
            return json.loads(brace.group(0))
        except Exception:
            pass
    return None


def _sanitize_cards(raw_cards: Any) -> List[Dict[str, Any]]:
    """LLM çıktısını whitelist + zorunlu alanlara göre temizle."""
    if not isinstance(raw_cards, list):
        return []

    cleaned: List[Dict[str, Any]] = []
    for idx, card in enumerate(raw_cards, start=1):
        if not isinstance(card, dict):
            continue
        chart_type = str(card.get("chart_type", "")).strip().lower()
        if chart_type not in CHART_TYPE_WHITELIST:
            logger.info(
                "Format kartı whitelist dışı chart_type='%s' — atlandı", chart_type
            )
            continue
        title = str(card.get("title", "")).strip()
        if not title:
            continue

        group_by = card.get("group_by") or []
        order_by = card.get("order_by") or []
        if not isinstance(group_by, list):
            group_by = [str(group_by)]
        if not isinstance(order_by, list):
            order_by = [str(order_by)]

        cleaned.append({
            "id": f"fmt_{idx}",
            "title": title,
            "chart_type": chart_type,
            "group_by": [str(x) for x in group_by],
            "order_by": [str(x) for x in order_by],
            "rationale": str(card.get("rationale", "")).strip(),
        })

    # ID'leri sıralı tut
    for i, c in enumerate(cleaned, start=1):
        c["id"] = f"fmt_{i}"

    # En fazla MAX_CARDS
    return cleaned[:MAX_CARDS]


# ──────────────────────────────────────────────────────────────────
# Public
# ──────────────────────────────────────────────────────────────────

def suggest_formats(
    metric: Dict[str, Any],
    columns: List[str],
    user_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """3-5 rapor format kartı öner.

    Args:
        metric: {"metric_name": str, "agg": str, "formula": str, ...}
        columns: kolon adları listesi
        user_intent: opsiyonel kullanıcı niyeti

    Returns:
        {
            "format_cards": [...],
            "cache_hit": bool,
            "model": "<provider>/<model>"
        }
    """
    cache = _get_cache()
    key = _cache_key(metric, columns or [], user_intent)

    cached = _safe_cache_get(cache, key)
    if cached and isinstance(cached, dict) and cached.get("format_cards"):
        out = dict(cached)
        out["cache_hit"] = True
        return out

    # LLM çağrısı
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(metric, columns or [], user_intent)},
    ]

    raw_response: str
    try:
        raw_response = call_llm_api(messages, temperature=0.3)
    except Exception as exc:
        logger.error("LLM çağrısı başarısız: %s", exc)
        raise

    parsed = _extract_json_block(raw_response) or {}
    cards = _sanitize_cards(parsed.get("cards", []))

    if len(cards) < MIN_CARDS:
        logger.warning(
            "LLM yetersiz kart üretti (%d < %d) — yine de döndürülüyor",
            len(cards),
            MIN_CARDS,
        )

    # Model bilgisi (best-effort)
    model_label = "unknown/unknown"
    try:
        cfg = get_active_llm() or {}
        provider = cfg.get("provider") or cfg.get("provider_name") or "llm"
        model_name = cfg.get("model_name") or "model"
        model_label = f"{provider}/{model_name}"
    except Exception:  # pragma: no cover
        pass

    result = {
        "format_cards": cards,
        "cache_hit": False,
        "model": model_label,
    }

    # Cache yaz (en az 1 kart varsa)
    if cards:
        _safe_cache_set(cache, key, result, CACHE_TTL_SECONDS)

    return result
