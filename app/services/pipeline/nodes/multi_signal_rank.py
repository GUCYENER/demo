"""
multi_signal_rank — Faz 3b + v3.29.7 (G1 glossary_match_score)
==============================================================
Adayları 7 sinyalle yeniden sıralar:

    final = 0.30 * semantic
          + 0.18 * name_fuzzy
          + 0.14 * column_match
          + 0.10 * fk_centrality
          + 0.08 * recency
          + 0.08 * usage_freq
          + 0.12 * glossary_match     # v3.29.7 G1

Ağırlıklar `system_settings`'ten override edilebilir (yoksa default).
Toplam ~1.00. Glossary sinyali eklendiğinde diğer ağırlıklar orantılı
olarak küçültüldü; admin_verified=True ipuçları tam puan, false ipuçları
kısmi puan getirir.

Sinyal kaynakları:
    - semantic: hybrid_retrieval'dan gelen `hybrid_score` (önceden 0.65 sem + 0.35 lex harmanı)
    - name_fuzzy: token-bazlı SequenceMatcher (Türkçe normalize)
    - column_match: aday tablonun kolonları kullanıcı sorgusunda geçiyor mu
    - fk_centrality: ds_db_relationships'te aday tabloya/dan giden FK sayısı (normalize)
    - recency: tablo son ne zaman query_history'de göründü (decay)
    - usage_freq: son N gün içinde kaç sorguda kullanıldı (log-normalize)
    - glossary_match: v3.29.7 G1 — query_expand_node'un ürettiği glossary_hints
                      içinde aday (schema, table) canonical/mapped olarak geçiyor mu

Tüm sinyaller [0..1] aralığında normalize edilir.
"""
from __future__ import annotations

import math
import re
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

# Default weights — v3.29.7 G1: glossary_match eklendi, toplam ~1.00
DEFAULT_WEIGHTS: Dict[str, float] = {
    "semantic": 0.30,
    "name_fuzzy": 0.18,
    "column_match": 0.14,
    "fk_centrality": 0.10,
    "recency": 0.08,
    "usage_freq": 0.08,
    "glossary_match": 0.12,
}

# v3.29.8 L3 — Per-company override cache (TTL bazlı, in-memory)
# Format: {company_id: (weights_dict, expires_at_unix)}
_COMPANY_WEIGHTS_CACHE: Dict[int, tuple] = {}
_COMPANY_WEIGHTS_TTL_SEC = 60.0


def load_company_weights(cur: Any, company_id: Optional[int]) -> Dict[str, float]:
    """
    Şirket bazlı override'ları DB'den yükler ve DEFAULT_WEIGHTS üzerine bindirir.
    60 saniyelik TTL cache; company_id=None → DEFAULT_WEIGHTS döner.

    Best-effort: cursor None/Exception → DEFAULT_WEIGHTS.
    """
    if company_id is None or cur is None:
        return dict(DEFAULT_WEIGHTS)
    now = time.time()
    cached = _COMPANY_WEIGHTS_CACHE.get(company_id)
    if cached and cached[1] > now:
        return dict(cached[0])
    weights = dict(DEFAULT_WEIGHTS)
    try:
        cur.execute(
            "SELECT signal_name, weight FROM signal_weight_overrides WHERE company_id = %s",
            (company_id,),
        )
        rows = cur.fetchall() or []
        for r in rows:
            # RealDictCursor veya tuple
            if isinstance(r, dict):
                name = r.get("signal_name")
                w = r.get("weight")
            else:
                name, w = r[0], r[1]
            if name in DEFAULT_WEIGHTS and w is not None:
                weights[name] = float(w)
    except Exception:
        # Tablo yok (eski deploy) veya RLS hatası → defaults
        return dict(DEFAULT_WEIGHTS)
    _COMPANY_WEIGHTS_CACHE[company_id] = (dict(weights), now + _COMPANY_WEIGHTS_TTL_SEC)
    return weights


def invalidate_company_weights_cache(company_id: Optional[int] = None) -> None:
    """Apply endpoint'i bunu çağırır. None → tüm cache temizlenir."""
    if company_id is None:
        _COMPANY_WEIGHTS_CACHE.clear()
    else:
        _COMPANY_WEIGHTS_CACHE.pop(company_id, None)


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
                         centrality_index: Optional[Dict[tuple, float]] = None,
                         max_centrality: float = 10.0) -> float:
    """
    Aday tablonun FK ağırlığı.

    centrality_index: {(schema, table) → weighted_fk_sum}  (v3.29.9)
        Per-edge weight rules (declared+inferred birleşik graph):
          - declared FK                            → 1.0
          - inferred, admin_verified=TRUE          → 1.0
          - inferred, admin_verified=FALSE, NOT rejected → 0.5 × confidence_score
          - rejected_at IS NOT NULL                → 0.0  (atlanır)

    Backward-compat: int input (eski "raw count" dict) hala kabul edilir;
    skor normalize edilirken max_centrality'a bölünür.
    """
    if centrality_index is None:
        return 0.0
    raw = centrality_index.get(
        (candidate.get("schema_name") or "", candidate.get("table_name") or ""),
        0.0,
    )
    return float(min(1.0, float(raw) / float(max_centrality)))


def build_centrality_index(cur: Any, source_id: int) -> Dict[tuple, float]:
    """v3.29.9: ds_db_relationships'ten confidence-weighted centrality index.

    Hem from_table hem to_table'a edge atfedilir (undirected centrality).
    Rejected ilişkiler dahil edilmez (rejected_at IS NOT NULL → 0).
    """
    cur.execute(
        """
        SELECT from_schema, from_table, to_schema, to_table,
               is_inferred, admin_verified, confidence_score
          FROM ds_db_relationships
         WHERE source_id = %s
           AND rejected_at IS NULL
        """,
        (source_id,),
    )
    rows = cur.fetchall() or []
    idx: Dict[tuple, float] = {}
    for r in rows:
        if hasattr(r, "get"):
            fs = r.get("from_schema") or ""
            ft = r.get("from_table") or ""
            ts = r.get("to_schema") or ""
            tt = r.get("to_table") or ""
            is_inf = bool(r.get("is_inferred"))
            verified = bool(r.get("admin_verified"))
            conf = r.get("confidence_score")
        else:
            fs, ft, ts, tt = r[0] or "", r[1] or "", r[2] or "", r[3] or ""
            is_inf, verified = bool(r[4]), bool(r[5])
            conf = r[6]
        if not is_inf or verified:
            w = 1.0
        else:
            try:
                w = 0.5 * float(conf or 0.0)
            except (TypeError, ValueError):
                w = 0.0
        if w <= 0.0:
            continue
        idx[(fs, ft)] = idx.get((fs, ft), 0.0) + w
        idx[(ts, tt)] = idx.get((ts, tt), 0.0) + w
    return idx


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


def _glossary_match_score(candidate: Dict[str, Any],
                          glossary_hints: Optional[List[Dict[str, Any]]] = None) -> float:
    """
    v3.29.7 G1 — Aday tablonun query_expand'in ürettiği business_glossary
    ipuçlarında geçip geçmediğini ölçer.

    Eşleşme kuralları:
      - canonical_table veya mapped_table tam eşleşmesi → +1.0
      - canonical_schema eşleşirse fakat tablo farklıysa → +0.3 (zayıf sinyal)
      - Birden fazla hint eşleşirse log-normalize (3 eşleşme tavan)
      - admin_verified=True hint → tam ağırlık, false → 0.6× azaltım
        (admin_verified hint'ler G5 synonym_learner döngüsünden geçmiş olur)

    Şema-bilinmez eşleşme: hint.schema None ise (cross-schema canonical)
    sadece tablo adına bakılır.
    """
    if not glossary_hints:
        return 0.0

    cand_schema = (candidate.get("schema_name") or "").lower()
    cand_table = (candidate.get("table_name") or "").lower()
    if not cand_table:
        return 0.0

    score_sum = 0.0
    hits = 0
    for hint in glossary_hints:
        if not isinstance(hint, dict):
            continue
        h_schema = (hint.get("schema") or "").lower()
        h_table = (hint.get("table") or "").lower()
        h_mapped_table = (hint.get("mapped_table") or "").lower()
        admin_verified = bool(hint.get("admin_verified", False))
        # Verified hint full weight; unverified 0.6×
        weight_factor = 1.0 if admin_verified else 0.6

        matched = 0.0
        if h_table and h_table == cand_table:
            # Tablo eşleşti
            if not h_schema or h_schema == cand_schema:
                matched = 1.0
            else:
                # Tablo aynı, schema farklı → orta sinyal
                matched = 0.5
        elif h_mapped_table and h_mapped_table == cand_table:
            matched = 1.0
        elif h_schema and h_schema == cand_schema and not h_table:
            # Sadece schema canonical — zayıf sinyal
            matched = 0.3

        if matched > 0:
            score_sum += matched * weight_factor
            hits += 1

    if hits == 0:
        return 0.0
    # Tek güçlü eşleşme zaten anlamlı; çoklu eşleşme log-doygunluk (tavan 3)
    raw = score_sum / max(1, hits)  # ortalama eşleşme kalitesi
    boost = math.log1p(hits) / math.log1p(3)  # 1 hit=0.5, 3+ hit=1.0
    return float(min(1.0, raw * (0.7 + 0.3 * boost)))


def multi_signal_rank(
    candidates: List[Dict[str, Any]],
    query_text: str,
    column_index: Optional[Dict[tuple, List[Dict]]] = None,
    centrality_index: Optional[Dict[tuple, float]] = None,
    recency_index: Optional[Dict[tuple, float]] = None,
    freq_index: Optional[Dict[tuple, int]] = None,
    weights: Optional[Dict[str, float]] = None,
    glossary_hints: Optional[List[Dict[str, Any]]] = None,
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
        gloss = _glossary_match_score(c, glossary_hints)

        final = (
            w["semantic"]        * sem
          + w["name_fuzzy"]      * name_fz
          + w["column_match"]    * col_m
          + w["fk_centrality"]   * fk_c
          + w["recency"]         * rec
          + w["usage_freq"]      * freq
          + w.get("glossary_match", 0.0) * gloss
        )

        enriched = dict(c)
        enriched["semantic_score"] = sem
        enriched["name_fuzzy_score"] = name_fz
        enriched["column_match_score"] = col_m
        enriched["fk_centrality_score"] = fk_c
        enriched["recency_score"] = rec
        enriched["usage_freq_score"] = freq
        enriched["glossary_match_score"] = gloss
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

    # v3.29.8 L3 — Şirket-bazlı DB override (signal_weight_overrides)
    # user_preferences gibi explicit state weights varsa onu dokunmuyoruz.
    if weights is None:
        co_id = state.get("company_id")
        if co_id is not None:
            try:
                weights = load_company_weights(state.get("_cursor"), co_id)
            except Exception:
                weights = None

    ranked = multi_signal_rank(
        candidates, query,
        column_index=state.get("column_index"),
        centrality_index=state.get("centrality_index"),
        recency_index=state.get("recency_index"),
        freq_index=state.get("freq_index"),
        weights=weights,
        glossary_hints=state.get("glossary_hints"),  # v3.29.7 G1
    )

    # Faz 4e — preferred/blacklisted filter
    if user_prefs:
        try:
            from app.services.user_preferences_service import apply_table_filters
            ranked = apply_table_filters(ranked, user_prefs)
        except Exception:
            pass

    # v3.29.8 L1 — signal_breakdown event: top-3 candidate'ın sinyal kırılımı +
    # kullanılan ağırlıklar. Layer 2 analyzer bu event'leri pipeline_end ile
    # eşleyip Pearson korelasyonu hesaplar. Best-effort (emit_event silent).
    try:
        from app.services.pipeline.observability import emit_event
        active_weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        signal_keys = (
            "semantic_score", "name_fuzzy_score", "column_match_score",
            "fk_centrality_score", "recency_score", "usage_freq_score",
            "glossary_match_score",
        )
        breakdown = []
        for c in ranked[:3]:
            breakdown.append({
                "schema": c.get("schema_name"),
                "table": c.get("table_name"),
                "final_score": round(float(c.get("final_score") or 0.0), 4),
                "signals": {k: round(float(c.get(k) or 0.0), 4) for k in signal_keys},
            })
        emit_event(
            state, "signal_breakdown",
            node_name="multi_signal_rank",
            metadata={
                "weights": {k: round(float(v), 4) for k, v in active_weights.items()},
                "top": breakdown,
                "candidate_count": len(ranked),
            },
        )
    except Exception:
        pass

    # Faz 5c — CatBoost inference (varsa final_score'u model skoruna swap'lar)
    # Heuristik final_score ml öncesi `heuristic_score` adıyla korunur
    try:
        from app.services.ml.catboost_inference import get_active_model, apply_model_to_candidates
        model = get_active_model(state.get("_cursor"), company_id=state.get("company_id"))
        if model is not None:
            tmp_state = dict(state)
            tmp_state["ranked_candidates"] = ranked
            ranked = apply_model_to_candidates(tmp_state, model)
    except Exception:
        pass

    return {"ranked_candidates": ranked}
