"""VYRA v3.37.0 — LLM Metrik Oneri Servisi (METIS).

Smart Discovery Wizard Step 2 (Metrik) icin dinamik metrik onerisi uretir.

Sorumluluklar:
    - suggest_metrics(source_id, table, columns, user_intent) -> Dict
    - Merkezi LLM client (app.core.llm.call_llm_api) ile cagri yapar.
    - JSON response'unu parse + Pydantic validation.
    - Redis L1 cache (TTL 15 dk) — Redis dustugunde uncached passthrough.

Tasarim notlari:
    - Yeni LLM provider client KURULMAZ — DB'deki aktif config kullanilir.
    - Cache key: llm:metric:{source_id}:{table}:{sha256(columns_json)}:{sha256(user_intent or '')}
    - Cache backend: app.core.redis_cache.RedisCache (lazy singleton).
    - LLM cagrisi LLMConnectionError firlatabilir; caller (API layer) 503'e cevirir.
    - Bos columns listesi caller (API) tarafindan reddedilir (400).
    - Token budget: 30 kolon ile sinirli (RedisCache prompt size guard).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from typing import Any, Dict, List, Optional

from app.core.llm import (
    LLMConfigError,
    LLMConnectionError,
    LLMResponseError,
    call_llm_api,
    extract_json_obj,
    get_active_llm,
)
from app.services._llm_cache_util import LlmRedisCache, sha256_short

logger = logging.getLogger(__name__)

# Cache parametreleri
_CACHE_TTL_SECONDS = 900  # 15 dk
_CACHE_KEY_PREFIX = "vyra:llm:metric:"
MAX_COLUMNS_FOR_PROMPT = 30
MAX_SUGGESTIONS = 5

# Izin verilen agregasyon enum'lari
ALLOWED_AGGS = {"SUM", "AVG", "COUNT", "MIN", "MAX", "COUNT_DISTINCT"}


# Bulgular3 / Review fix #5: shared LlmRedisCache facade (DRY)
_CACHE = LlmRedisCache(prefix=_CACHE_KEY_PREFIX, ttl_seconds=_CACHE_TTL_SECONDS)


def _make_cache_key(
    source_id: int,
    table: str,
    columns: List[Dict[str, Any]],
    user_intent: Optional[str],
    table_label: Optional[str] = None,
) -> str:
    """llm:metric:{source_id}:{table}:{sha256(columns)}:{sha256(intent+label)} formatinda key.

    Bulgular3 / Bulgu 4: table_label hash'e dahil edilir — TR ad degisirse
    eski cache yanlis rationale dondurmesin.
    """
    cols_canonical = json.dumps(
        [{"name": c.get("name"), "type": c.get("type")} for c in columns],
        sort_keys=True,
        ensure_ascii=False,
    )
    intent_norm = (user_intent or "").strip()
    label_norm = (table_label or "").strip()
    return (
        f"{int(source_id)}:{table}:"
        f"{sha256_short(cols_canonical)}:{sha256_short(intent_norm + '|' + label_norm)}"
    )


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    return _CACHE.get(key)


def _cache_set(key: str, payload: Dict[str, Any]) -> None:
    _CACHE.set(key, payload)


# -------------------------------------------------------------
# Prompt builder
# -------------------------------------------------------------

def _build_prompt(
    table: str,
    columns: List[Dict[str, Any]],
    user_intent: Optional[str],
    table_label: Optional[str] = None,
) -> List[Dict[str, str]]:
    """Sistem + user mesajlarini olusturur.

    Bulgular3 / Bulgu 4: table_label (TR ad) verilirse promptta "Tablo (TR adi):
    X (SQL adi: Y)" formatinda gosterilir; LLM rationale icinde TR adi kullanmasi
    icin sistem prompt'una talimat eklenir. formula SQL adlarini kullanmaya devam
    eder (calistirilabilir).
    """
    cols_lines: List[str] = []
    for c in columns[:MAX_COLUMNS_FOR_PROMPT]:
        name = (c.get("name") or "").strip()
        ctype = (c.get("type") or "?").strip()
        if name:
            cols_lines.append(f"- {name} ({ctype})")
    cols_block = "\n".join(cols_lines) if cols_lines else "(kolon yok)"

    intent_block = ""
    if user_intent and user_intent.strip():
        intent_block = f"\n\nKullanici niyeti: {user_intent.strip()}"

    label_norm = (table_label or "").strip()
    use_tr_label = bool(label_norm) and label_norm.upper() != table.upper()

    system_prompt = (
        "Sen veri analisti METIS'sin. Verilen kolonlar uzerinden BI metrikleri "
        "onerirsin. Cevabin SADECE JSON olmali, baska metin EKLEME. "
        "Maksimum 5 metrik oner. Her metrik icin: "
        "metric_name (kisa Turkce isim), agg (SUM/AVG/COUNT/MIN/MAX/COUNT_DISTINCT), "
        "formula (SQL ifadesi), rationale (kisa Turkce gerekce), "
        "confidence (0-1 arasi float)."
    )
    if use_tr_label:
        system_prompt += (
            " rationale icinde tablo adini ANARKEN Turkce ogrenilmis adi "
            "(table_label) kullan. formula icindeki tablo/kolon adlarini "
            "SQL identifier'i ile (orijinal isimler) yaz, calistirilabilir kalsin."
        )

    if use_tr_label:
        table_line = f"Tablo (TR adi): {label_norm} (SQL adi: {table})"
    else:
        table_line = f"Tablo: {table}"

    user_prompt = (
        f"{table_line}\n"
        f"Kolonlar:\n{cols_block}"
        f"{intent_block}\n\n"
        "Cikti SADECE su JSON formatinda olsun:\n"
        "{\n"
        "  \"suggestions\": [\n"
        "    {\n"
        "      \"metric_name\": \"...\",\n"
        "      \"agg\": \"SUM\",\n"
        "      \"formula\": \"SUM(kolon_adi)\",\n"
        "      \"rationale\": \"...\",\n"
        "      \"confidence\": 0.9\n"
        "    }\n"
        "  ]\n"
        "}"
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# -------------------------------------------------------------
# LLM JSON parsing — Bulgular3 Review fix #3: app.core.llm.extract_json_obj
# delegated (balanced-brace, string-aware) — greedy regex kaldirildi.
# -------------------------------------------------------------

_extract_json_obj = extract_json_obj


def _validate_suggestions(raw_suggestions: Any) -> List[Dict[str, Any]]:
    """LLM cevabindaki suggestions listesini validate eder. Bozuk item'lar atilir."""
    if not isinstance(raw_suggestions, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw_suggestions[:MAX_SUGGESTIONS]:
        if not isinstance(item, dict):
            continue
        metric_name = (item.get("metric_name") or "").strip()
        agg_raw = (item.get("agg") or "").strip().upper()
        formula = (item.get("formula") or "").strip()
        rationale = (item.get("rationale") or "").strip()
        confidence = item.get("confidence")
        if not metric_name or not formula:
            continue
        if agg_raw not in ALLOWED_AGGS:
            # Bilinmeyen agg'i bypass: COUNT'a normalize etmek riskli, atla.
            continue
        try:
            conf_f = float(confidence) if confidence is not None else 0.5
        except (TypeError, ValueError):
            conf_f = 0.5
        # Confidence clamp [0,1]
        if conf_f < 0.0:
            conf_f = 0.0
        elif conf_f > 1.0:
            conf_f = 1.0
        out.append({
            "metric_name": metric_name[:200],
            "agg": agg_raw,
            "formula": formula[:500],
            "rationale": rationale[:500],
            "confidence": round(conf_f, 3),
        })
    return out


# -------------------------------------------------------------
# Public API
# -------------------------------------------------------------

def suggest_metrics(
    source_id: int,
    table: str,
    columns: List[Dict[str, Any]],
    user_intent: Optional[str] = None,
    table_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Verilen kolonlar icin maks 5 metrik onerisi uretir.

    Returns:
        {
            "suggestions": [{metric_name, agg, formula, rationale, confidence}, ...],
            "cache_hit": bool,
            "model": "provider/model_name"  (best-effort, hata olursa "unknown")
        }

    Raises:
        LLMConnectionError: LLM ulasilamaz / timeout — caller 503 doner.
        LLMConfigError: Aktif LLM yapilandirilmamis — caller 503 doner.
        LLMResponseError: LLM JSON parse edilemedi — caller 502 doner.
    """
    if not columns:
        # Defensive — caller (API) zaten 400 firlatir; servis seviyesinde bos liste = bos cevap.
        return {"suggestions": [], "cache_hit": False, "model": "unknown"}

    cache_key = _make_cache_key(source_id, table, columns, user_intent, table_label=table_label)

    # 1) Cache lookup (Redis dustugunde sessizce gec)
    cached = _cache_get(cache_key)
    if cached and isinstance(cached.get("suggestions"), list):
        logger.info("[llm_metric] cache HIT key=%s", cache_key)
        cached_sugs = cached.get("suggestions", [])
        # Bulgular3 / Bulgu 4: eski cache item'larinda table_name_tr/object_name
        # alanlari olmayabilir — defansif enrich.
        label_norm_cached = (table_label or "").strip()
        tr_label_cached = label_norm_cached if (label_norm_cached and label_norm_cached.upper() != table.upper()) else None
        for s in cached_sugs:
            if isinstance(s, dict):
                s.setdefault("table_object_name", table)
                if "table_name_tr" not in s:
                    s["table_name_tr"] = tr_label_cached
        return {
            "suggestions": cached_sugs,
            "cache_hit": True,
            "model": cached.get("model", "unknown"),
        }

    # 2) Model adi (best-effort; LLM cagrisi oncesi)
    model_label = "unknown"
    try:
        cfg = get_active_llm()
        if cfg:
            provider = cfg.get("provider") or "?"
            model_name = cfg.get("model_name") or "?"
            model_label = f"{provider}/{model_name}"
    except Exception:
        # Model labeling kritik degil
        pass

    # 3) LLM cagrisi
    messages = _build_prompt(
        table=table, columns=columns, user_intent=user_intent, table_label=table_label,
    )
    try:
        raw_response = call_llm_api(messages, temperature=0.2)
    except (LLMConnectionError, LLMConfigError):
        # Caller (API) bunu 503'e cevirir
        raise
    except Exception as e:
        # Beklenmeyen hata — LLMConnectionError'a wrap et
        logger.error("[llm_metric] unexpected LLM error: %s", e)
        raise LLMConnectionError(f"LLM cagrisi sirasinda beklenmeyen hata: {e}")

    # 4) JSON parse + validation
    parsed = _extract_json_obj(raw_response or "")
    if not parsed:
        logger.warning("[llm_metric] LLM JSON parse edilemedi, response=%r", (raw_response or "")[:200])
        raise LLMResponseError("LLM cevabi JSON formatinda degil.")

    suggestions = _validate_suggestions(parsed.get("suggestions"))

    # Bulgular3 / Bulgu 4: her oneriye TR + SQL tablo adi propagate et.
    # Frontend chip ust kismina table_name_tr basar, tooltip'e table_object_name.
    label_norm = (table_label or "").strip()
    tr_label = label_norm if (label_norm and label_norm.upper() != table.upper()) else None
    for s in suggestions:
        s["table_object_name"] = table
        s["table_name_tr"] = tr_label

    payload = {
        "suggestions": suggestions,
        "model": model_label,
    }

    # 5) Cache yaz (Redis dustugunde sessizce gec)
    _cache_set(cache_key, payload)

    return {
        "suggestions": suggestions,
        "cache_hit": False,
        "model": model_label,
    }
