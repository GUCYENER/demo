"""signal_weight_analyzer — v3.29.8 L2

Pipeline_events tablosundaki `signal_breakdown` event'lerini son N gün
penceresinde çekip, her sinyalin pipeline_end outcome'ı ile Pearson
korelasyonunu hesaplar; sonra mevcut ağırlıkları yumuşak ayarlayan bir
öneri üretip `signal_weight_suggestions` tablosuna yazar.

Tasarım:
  - **Read-only analyzer:** ağırlıkları kendiliğinden değiştirmez,
    sadece öneri üretir. Layer 3 admin onayı ile uygulanır.
  - **Pearson r:** signal_score (top-1 candidate) vs outcome (1=ok, 0=err).
  - **Sample yetersizse skip:** n < min_sample_size → o sinyal için öneri yok.
  - **Bayesian shrinkage:** confidence = |r| * sqrt(n / (n + 30))
  - **Lambda smoothing:** suggested = current * (1 + lambda * r)
    lambda default 0.3 (yumuşak; tek seferde max %30 drift).
  - **Clip + renormalize:** suggested [current*0.5, current*2.0] aralığına
    sıkıştırılır; tüm sinyaller toplam 1.0 olacak şekilde normalize edilir.

Public API:
    analyze_signal_weights(cur, company_id, days=7, min_sample_size=50,
                           lambda_=0.3) -> List[SuggestionRow]
    persist_suggestions(cur, suggestions, company_id) -> int
    run_full_analysis(cur, company_id=None) -> Dict[str, Any]
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# multi_signal_rank.DEFAULT_WEIGHTS ile aynı 7 sinyal (alan adları "_score" siz)
SIGNAL_NAMES = (
    "semantic", "name_fuzzy", "column_match",
    "fk_centrality", "recency", "usage_freq", "glossary_match",
)

# pipeline_events metadata içindeki top[0].signals key'leri "_score" ekli
_SIGNAL_KEY_MAP = {
    "semantic": "semantic_score",
    "name_fuzzy": "name_fuzzy_score",
    "column_match": "column_match_score",
    "fk_centrality": "fk_centrality_score",
    "recency": "recency_score",
    "usage_freq": "usage_freq_score",
    "glossary_match": "glossary_match_score",
}


def _pearson(xs: List[float], ys: List[float]) -> float:
    """Pearson korelasyon. n<2 veya tek değer → 0.0."""
    n = len(xs)
    if n < 2 or len(ys) != n:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx2 = sum((x - mx) ** 2 for x in xs)
    sy2 = sum((y - my) ** 2 for y in ys)
    denom = math.sqrt(sx2 * sy2)
    if denom <= 0:
        return 0.0
    r = num / denom
    return max(-1.0, min(1.0, r))


def _confidence(r: float, n: int) -> float:
    """Bayesian shrinkage: |r| * sqrt(n / (n + 30))."""
    if n <= 0:
        return 0.0
    return float(abs(r) * math.sqrt(n / (n + 30)))


def _fetch_run_data(
    cur: Any,
    company_id: Optional[int],
    days: int,
) -> List[Tuple[Dict[str, float], int, Dict[str, float], Optional[Any]]]:
    """
    pipeline_events'tan son N gün boyunca her run için
    (top1_signals, outcome, weights_used, sb_created_at) tuple'larını döner.

    outcome: 1 if pipeline_end status='ok' AND row_count>0 AND retry_count==0
             0 otherwise
    sb_created_at: v3.29.9 — signal_breakdown event timestamp'i;
                   per-signal age filter için (örn. fk_centrality deploy banner).
    """
    co_filter = ""
    params: List[Any] = [days]
    if company_id is not None:
        co_filter = "AND e.company_id = %s"
        params.append(company_id)

    cur.execute(
        f"""
        WITH sb AS (
            SELECT e.run_id, e.metadata, e.created_at AS sb_ts
              FROM pipeline_events e
             WHERE e.event_type = 'signal_breakdown'
               AND e.created_at >= NOW() - (%s || ' days')::interval
               {co_filter}
        ),
        pe AS (
            SELECT e.run_id, e.status, e.metadata AS end_meta
              FROM pipeline_events e
             WHERE e.event_type = 'pipeline_end'
               AND e.created_at >= NOW() - (%s || ' days')::interval
               {co_filter}
        )
        SELECT sb.metadata AS sb_meta, pe.status, pe.end_meta, sb.sb_ts
          FROM sb
          JOIN pe ON pe.run_id = sb.run_id
        """,
        params + params,
    )
    rows = cur.fetchall()
    out: List[Tuple[Dict[str, float], int, Dict[str, float], Optional[Any]]] = []
    for row in rows:
        if isinstance(row, dict):
            sb_meta = row.get("sb_meta")
            status = row.get("status")
            end_meta = row.get("end_meta")
            sb_ts = row.get("sb_ts")
        else:
            sb_meta, status, end_meta = row[0], row[1], row[2]
            sb_ts = row[3] if len(row) > 3 else None
        # JSONB → dict (psycopg2 RealDictCursor zaten dict döner)
        if isinstance(sb_meta, str):
            try:
                sb_meta = json.loads(sb_meta)
            except Exception:
                continue
        if isinstance(end_meta, str):
            try:
                end_meta = json.loads(end_meta)
            except Exception:
                end_meta = {}
        if not isinstance(sb_meta, dict):
            continue
        top = sb_meta.get("top") or []
        if not top:
            continue
        top1 = top[0]
        signals = top1.get("signals") or {}
        weights_used = sb_meta.get("weights") or {}
        # Outcome: ok + non-empty + no retry
        retry_count = (end_meta or {}).get("retry_count") or 0
        row_count = (end_meta or {}).get("row_count") or 0
        outcome = 1 if (status == "ok" and row_count > 0 and retry_count == 0) else 0
        out.append((signals, outcome, weights_used, sb_ts))
    return out


def _load_fk_inference_deploy_ts(cur: Any) -> Optional[Any]:
    """v3.29.9 — system_settings'ten FK inference deploy timestamp'ini oku."""
    try:
        cur.execute(
            "SELECT setting_value FROM system_settings WHERE setting_key = %s",
            ("FK_INFERENCE_DEPLOY_TS",),
        )
        row = cur.fetchone()
        if not row:
            return None
        val = row.get("setting_value") if hasattr(row, "get") else row[0]
        if not val:
            return None
        # Parse ISO 8601 if string, else assume datetime
        from datetime import datetime
        if isinstance(val, str):
            try:
                # Postgres TIMESTAMPTZ → ISO
                return datetime.fromisoformat(val.replace("Z", "+00:00"))
            except ValueError:
                return None
        return val
    except Exception as e:
        logger.debug("[signal_weight_analyzer] FK_INFERENCE_DEPLOY_TS load failed: %s", e)
        return None


def _renormalize(weights: Dict[str, float]) -> Dict[str, float]:
    """Tüm değerleri toplam 1.0 olacak şekilde normalize et."""
    total = sum(v for v in weights.values() if v > 0)
    if total <= 0:
        return weights
    return {k: round(v / total, 6) for k, v in weights.items()}


def analyze_signal_weights(
    cur: Any,
    company_id: Optional[int] = None,
    days: int = 7,
    min_sample_size: int = 50,
    lambda_: float = 0.3,
    min_event_age_hours: int = 0,
) -> List[Dict[str, Any]]:
    """
    Son N gün signal_breakdown event'lerinden Pearson korelasyon hesaplar
    ve her sinyal için bir suggestion satırı üretir.

    v3.29.9 — `min_event_age_hours`: fk_centrality için deploy-day spike
    filtresi. system_settings.FK_INFERENCE_DEPLOY_TS + min_event_age_hours
    öncesindeki signal_breakdown örnekleri SADECE fk_centrality Pearson
    hesabından çıkarılır (diğer sinyaller etkilenmez). Default 0 = filtre
    devre dışı.

    Returns:
        List[{
          signal_name, current_weight, suggested_weight,
          confidence, correlation_pearson, sample_size, window_days
        }]
        Sample yetersizse boş liste döner.
    """
    samples = _fetch_run_data(cur, company_id, days)
    n = len(samples)
    if n < min_sample_size:
        logger.info(
            "[signal_weight_analyzer] sample yetersiz: n=%d < min=%d (co=%s, days=%d)",
            n, min_sample_size, company_id, days,
        )
        return []

    # v3.29.9: fk_centrality için deploy_ts cutoff (None ise filtre yok)
    fk_cutoff_ts: Optional[Any] = None
    if min_event_age_hours and min_event_age_hours > 0:
        deploy_ts = _load_fk_inference_deploy_ts(cur)
        if deploy_ts is not None:
            from datetime import timedelta
            try:
                fk_cutoff_ts = deploy_ts + timedelta(hours=min_event_age_hours)
            except Exception:
                fk_cutoff_ts = None

    # Yürürlükteki ağırlıklar (son run'ın weights'ından — analiz anındaki snapshot)
    current_weights: Dict[str, float] = {}
    for _, _, w, _ in samples:
        if w:
            current_weights = {k: float(v) for k, v in w.items() if k in SIGNAL_NAMES}
            break
    if not current_weights:
        # Fallback to module defaults
        from app.services.pipeline.nodes.multi_signal_rank import DEFAULT_WEIGHTS
        current_weights = dict(DEFAULT_WEIGHTS)

    # Outcomes vektörü ortak
    ys = [float(o) for (_, o, _, _) in samples]

    # Pearson per sinyal — clipped + renormalized suggestion
    raw_suggestions: Dict[str, Dict[str, Any]] = {}
    for sig in SIGNAL_NAMES:
        score_key = _SIGNAL_KEY_MAP[sig]
        # v3.29.9: fk_centrality için per-event age filtresi
        if sig == "fk_centrality" and fk_cutoff_ts is not None:
            filtered = [(s, o, sb_ts) for (s, o, _, sb_ts) in samples
                        if sb_ts is not None and sb_ts >= fk_cutoff_ts]
            if len(filtered) < min_sample_size:
                logger.info(
                    "[signal_weight_analyzer] fk_centrality için deploy_ts+%dh sonrası n=%d < min=%d — atlandı",
                    min_event_age_hours, len(filtered), min_sample_size,
                )
                continue
            sig_xs = [float((s or {}).get(score_key) or 0.0) for (s, _, _) in filtered]
            sig_ys = [float(o) for (_, o, _) in filtered]
            sig_n = len(filtered)
        else:
            sig_xs = [float((s or {}).get(score_key) or 0.0) for (s, _, _, _) in samples]
            sig_ys = ys
            sig_n = n
        # Sinyal tamamen sabitse (varyans yok) korelasyon anlamsız
        if len(set(sig_xs)) <= 1:
            continue
        r = _pearson(sig_xs, sig_ys)
        conf = _confidence(r, sig_n)
        cur_w = float(current_weights.get(sig) or 0.0)
        # Yumuşak ayarlama
        proposed = cur_w * (1.0 + lambda_ * r)
        # Drift cap
        lo, hi = max(0.0, cur_w * 0.5), min(1.0, max(cur_w * 2.0, cur_w + 0.05))
        proposed = max(lo, min(hi, proposed))
        raw_suggestions[sig] = {
            "signal_name": sig,
            "current_weight": round(cur_w, 6),
            "_proposed": proposed,
            "confidence": round(conf, 6),
            "correlation_pearson": round(r, 6),
            "sample_size": sig_n,
            "window_days": days,
        }

    if not raw_suggestions:
        return []

    # Renormalize: yalnız değişen sinyallerin değişimini tüm vektöre dağıt
    proposed_vec = {
        s: raw_suggestions.get(s, {}).get("_proposed", current_weights.get(s, 0.0))
        for s in SIGNAL_NAMES
    }
    proposed_vec = _renormalize(proposed_vec)

    out: List[Dict[str, Any]] = []
    for sig, rec in raw_suggestions.items():
        rec["suggested_weight"] = round(proposed_vec.get(sig, rec["_proposed"]), 6)
        rec.pop("_proposed", None)
        out.append(rec)
    return out


def persist_suggestions(
    cur: Any,
    suggestions: List[Dict[str, Any]],
    company_id: Optional[int],
) -> int:
    """signal_weight_suggestions tablosuna toplu insert. Geri: satır sayısı."""
    if not suggestions:
        return 0
    count = 0
    for s in suggestions:
        cur.execute(
            """
            INSERT INTO signal_weight_suggestions
                (company_id, signal_name, current_weight, suggested_weight,
                 confidence, correlation_pearson, sample_size, window_days)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                company_id,
                s["signal_name"],
                s["current_weight"],
                s["suggested_weight"],
                s["confidence"],
                s["correlation_pearson"],
                s["sample_size"],
                s["window_days"],
            ),
        )
        count += 1
    return count


def run_full_analysis(
    cur: Any,
    company_id: Optional[int] = None,
    days: int = 7,
    min_sample_size: int = 50,
    lambda_: float = 0.3,
    min_event_age_hours: int = 0,
) -> Dict[str, Any]:
    """Scheduler/admin endpoint'inden tetiklenir. Analiz + persist."""
    try:
        suggestions = analyze_signal_weights(
            cur, company_id=company_id, days=days,
            min_sample_size=min_sample_size, lambda_=lambda_,
            min_event_age_hours=min_event_age_hours,
        )
        persisted = persist_suggestions(cur, suggestions, company_id)
        return {
            "ok": True,
            "company_id": company_id,
            "suggestions_count": len(suggestions),
            "persisted": persisted,
            "window_days": days,
        }
    except Exception as e:
        logger.exception("[signal_weight_analyzer] run_full_analysis failed: %s", e)
        return {"ok": False, "error": str(e)[:300]}
