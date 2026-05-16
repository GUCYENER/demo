"""
multi_signal_rank — Faz 3b
==========================
Adayları 6 sinyalle yeniden sıralar (master plan §3 weights):

    final = 0.35 * semantic
          + 0.20 * name_fuzzy
          + 0.15 * column_match
          + 0.10 * fk_centrality
          + 0.10 * recency
          + 0.10 * usage_freq

Ağırlıklar `system_settings`'ten override edilebilir (yoksa default).

Sinyal kaynakları:
    - semantic: hybrid_retrieval'dan gelen `hybrid_score` (önceden 0.65 sem + 0.35 lex harmanı)
    - name_fuzzy: token-bazlı SequenceMatcher (Türkçe normalize)
    - column_match: aday tablonun kolonları kullanıcı sorgusunda geçiyor mu
    - fk_centrality: ds_db_relationships'te aday tabloya/dan giden FK sayısı (normalize)
    - recency: tablo son ne zaman query_history'de göründü (decay)
    - usage_freq: son N gün içinde kaç sorguda kullanıldı (log-normalize)

Tüm sinyaller [0..1] aralığında normalize edilir.
"""
from __future__ import annotations

import math
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

# Default weights — master plan §3
DEFAULT_WEIGHTS: Dict[str, float] = {
    "semantic": 0.35,
    "name_fuzzy": 0.20,
    "column_match": 0.15,
    "fk_centrality": 0.10,
    "recency": 0.10,
    "usage_freq": 0.10,
}


def _normalize_tr(text: str) -> str:
    """Türkçe normalize: lowercase + diakritik kaldır + alfanumerik kelime."""
    if not text:
        return ""
    text = text.lower()
    # Türkçe i/İ ı/I korunsun: diakritikleri kaldırmadan önce manuel eşle
    text = text.replace("ı", "i").replace("İ", "i").replace("ş", "s") \
               .replace("ğ", "g").replace("ü", "u").replace("ö", "o").replace("ç", "c")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(_normalize_tr(text))


def _name_fuzzy_score(query: str, candidate: Dict[str, Any]) -> float:
    """Tablo adı + business_name token-bazlı fuzzy benzerlik."""
    if not query:
        return 0.0
    targets = [
        candidate.get("table_name") or "",
        candidate.get("business_name_tr") or "",
    ]
    q_norm = _normalize_tr(query)
    if not q_norm.strip():
        return 0.0
    best = 0.0
    for t in targets:
        if not t:
            continue
        t_norm = _normalize_tr(t)
        if not t_norm:
            continue
        # Token-bazlı: ortalama best-match per query token
        q_tokens = _tokens(query)
        t_tokens = _tokens(t)
        if q_tokens and t_tokens:
            scores = []
            for qt in q_tokens:
                best_qt = max(
                    (SequenceMatcher(None, qt, tt).ratio() for tt in t_tokens),
                    default=0.0,
                )
                scores.append(best_qt)
            tok_score = sum(scores) / len(scores) if scores else 0.0
        else:
            tok_score = 0.0
        # String benzerliği (overall)
        full_score = SequenceMatcher(None, q_norm, t_norm).ratio()
        best = max(best, max(tok_score, full_score))
    return float(min(1.0, best))


def _column_match_score(query: str, candidate: Dict[str, Any],
                        column_index: Optional[Dict[tuple, List[Dict]]] = None) -> float:
    """
    Aday tablonun kolon/iş_adı/eşanlam token'ları kullanıcı sorgusunda geçiyor mu.

    column_index: optional {(schema, table) → [col_dict, ...]} hızlı lookup
                  col_dict: {"column_name", "business_name_tr", "synonyms"}
    """
    if not query:
        return 0.0
    q_tokens = set(_tokens(query))
    if not q_tokens:
        return 0.0

    cols = []
    if column_index is not None:
        cols = column_index.get(
            (candidate.get("schema_name") or "", candidate.get("table_name") or ""),
            [],
        )
    # Fallback: candidate içine gömülü columns
    if not cols and isinstance(candidate.get("columns"), list):
        cols = candidate["columns"]

    if not cols:
        return 0.0

    matches = 0
    total = 0
    for c in cols:
        total += 1
        col_tokens = set(_tokens(c.get("column_name") or ""))
        col_tokens.update(_tokens(c.get("business_name_tr") or ""))
        for s in (c.get("synonyms") or []):
            col_tokens.update(_tokens(s))
        if col_tokens & q_tokens:
            matches += 1

    if total == 0:
        return 0.0
    # Log-normalize: 1 eşleşme zaten anlamlı, 10 eşleşme tavan
    return float(min(1.0, math.log1p(matches) / math.log1p(min(total, 10))))


def _fk_centrality_score(candidate: Dict[str, Any],
                         centrality_index: Optional[Dict[tuple, int]] = None,
                         max_centrality: int = 10) -> float:
    """
    Aday tablonun FK ağırlığı.

    centrality_index: {(schema, table) → fk_count}
                      Hesabı upstream: relationships'te tabloya gelen + giden FK sayısı.
    """
    if centrality_index is None:
        return 0.0
    cnt = centrality_index.get(
        (candidate.get("schema_name") or "", candidate.get("table_name") or ""),
        0,
    )
    return float(min(1.0, cnt / max_centrality))


def _recency_score(candidate: Dict[str, Any],
                   recency_index: Optional[Dict[tuple, float]] = None,
                   half_life_days: float = 7.0) -> float:
    """
    Son kullanım zamanına göre exponential decay.

    recency_index: {(schema, table) → last_used_unix_ts}
    half_life_days: 7 gün -> skor 0.5; 14 gün -> 0.25
    """
    if recency_index is None:
        return 0.0
    ts = recency_index.get(
        (candidate.get("schema_name") or "", candidate.get("table_name") or ""),
        None,
    )
    if ts is None:
        return 0.0
    now = time.time()
    days = max(0.0, (now - ts) / 86400.0)
    # decay = 2^(-days/half_life)
    return float(0.5 ** (days / max(half_life_days, 0.1)))


def _usage_freq_score(candidate: Dict[str, Any],
                      freq_index: Optional[Dict[tuple, int]] = None,
                      saturation: int = 50) -> float:
    """
    Son N gün içinde kullanım sayısı (saturation log-normalize).
    """
    if freq_index is None:
        return 0.0
    cnt = freq_index.get(
        (candidate.get("schema_name") or "", candidate.get("table_name") or ""),
        0,
    )
    if cnt <= 0:
        return 0.0
    return float(min(1.0, math.log1p(cnt) / math.log1p(saturation)))


def multi_signal_rank(
    candidates: List[Dict[str, Any]],
    query_text: str,
    column_index: Optional[Dict[tuple, List[Dict]]] = None,
    centrality_index: Optional[Dict[tuple, int]] = None,
    recency_index: Optional[Dict[tuple, float]] = None,
    freq_index: Optional[Dict[tuple, int]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    Adayları 6 sinyalle skorla ve `final_score` ile DESC sırala.

    `candidates` öğesi en az şu alanları taşımalı:
        - schema_name, table_name
        - semantic_score (zaten verilmiş — yoksa 0)
        - opsiyonel: business_name_tr, columns, hybrid_score

    Returns:
        Aynı adaylar + her birine sinyal skorları + final_score ile zenginleştirilmiş,
        final_score DESC sıralı.
    """
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    # Normalize ağırlıklar (toplamı 1.0 olmasa da skor [0..1] kalır)

    ranked: List[Dict[str, Any]] = []
    for c in candidates:
        # Semantic: hybrid_score > semantic_score > 0
        sem = float(c.get("hybrid_score") or c.get("semantic_score") or 0.0)
        # Clamp to [0,1]
        sem = max(0.0, min(1.0, sem))

        name_fz = _name_fuzzy_score(query_text, c)
        col_m = _column_match_score(query_text, c, column_index)
        fk_c = _fk_centrality_score(c, centrality_index)
        rec = _recency_score(c, recency_index)
        freq = _usage_freq_score(c, freq_index)

        final = (
            w["semantic"]      * sem
          + w["name_fuzzy"]    * name_fz
          + w["column_match"]  * col_m
          + w["fk_centrality"] * fk_c
          + w["recency"]       * rec
          + w["usage_freq"]    * freq
        )

        enriched = dict(c)
        enriched["semantic_score"] = sem
        enriched["name_fuzzy_score"] = name_fz
        enriched["column_match_score"] = col_m
        enriched["fk_centrality_score"] = fk_c
        enriched["recency_score"] = rec
        enriched["usage_freq_score"] = freq
        enriched["final_score"] = float(final)
        ranked.append(enriched)

    ranked.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
    return ranked


# LangGraph-uyumlu wrapper (Faz 3f'de graph'a bağlanacak)
def multi_signal_rank_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    LangGraph node fonksiyonu — `QueryState`'i okur ve günceller.
    Pure Python — LangGraph bağımlılığı yok; sadece dict in/out.

    Faz 4e: scoring_weights state'te yoksa user_preferences'tan yükler;
    sonra preferred/blacklisted table filter'ını uygular.
    """
    candidates = state.get("candidates") or []
    query = state.get("question") or ""

    # Faz 4e — user_preferences entegrasyonu (best-effort)
    weights = state.get("scoring_weights")
    user_prefs = state.get("user_preferences")
    if weights is None and user_prefs:
        try:
            from app.services.user_preferences_service import apply_weight_overrides
            weights = apply_weight_overrides(DEFAULT_WEIGHTS, user_prefs)
        except Exception:
            weights = None

    ranked = multi_signal_rank(
        candidates, query,
        column_index=state.get("column_index"),
        centrality_index=state.get("centrality_index"),
        recency_index=state.get("recency_index"),
        freq_index=state.get("freq_index"),
        weights=weights,
    )

    # Faz 4e — preferred/blacklisted filter
    if user_prefs:
        try:
            from app.services.user_preferences_service import apply_table_filters
            ranked = apply_table_filters(ranked, user_prefs)
        except Exception:
            pass

    return {"ranked_candidates": ranked}
