"""
catboost_inference — Faz 5c
===========================
Aktif CatBoost ranking modelini load eder ve multi_signal_rank içinde
heuristik final_score yerine model predict_proba kullanır.

Cache:
    Modeller (file_path, mtime) anahtarıyla bellek içi singleton cache'lenir.
    Aynı modeli her query'de yeniden disk'ten okumayız.

Cold-start:
    Model yoksa veya CatBoost kurulu değilse → heuristik skor korunur (no-op).

Hibrit yaklaşım:
    Model olsa bile heuristik final_score korunur ve `ml_score` adıyla
    candidate'a eklenir. Sıralama: model varsa ml_score'a göre; aksi halde
    final_score'a göre.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import logging
import os
import threading

logger = logging.getLogger(__name__)

# CatBoost lazy import
try:
    from catboost import CatBoostClassifier  # type: ignore
    _HAS_CATBOOST = True
except Exception:
    _HAS_CATBOOST = False

from .feature_extractor import extract_batch, FEATURE_ORDER


# (file_path, mtime) -> model nesnesi
_MODEL_CACHE: Dict[Tuple[str, float], Any] = {}
_CACHE_LOCK = threading.Lock()


def load_model(file_path: str) -> Optional[Any]:
    """Disk'ten model yükle (mtime cache)."""
    if not _HAS_CATBOOST:
        return None
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        mtime = os.path.getmtime(file_path)
    except OSError:
        return None

    key = (file_path, mtime)
    with _CACHE_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        try:
            clf = CatBoostClassifier()
            clf.load_model(file_path)
            _MODEL_CACHE[key] = clf
            return clf
        except Exception as e:
            logger.warning("[catboost_inference] load hata: %s", e)
            return None


def get_active_model(cur, company_id: Optional[int] = None) -> Optional[Any]:
    """DB'den aktif modeli pick et + load. None → no-op."""
    if cur is None or not _HAS_CATBOOST:
        return None
    try:
        from .catboost_trainer import get_active_model_info
        info = get_active_model_info(cur, model_type="ranking", company_id=company_id)
    except Exception:
        return None
    if not info:
        return None
    return load_model(info["file_path"])


def apply_model_to_candidates(
    state: Dict[str, Any],
    model: Any,
) -> List[Dict[str, Any]]:
    """
    ranked_candidates üzerine model.predict_proba ile ml_score ekler.
    Sıralama ml_score'a göre yapılır.

    Heuristik final_score korunur (debugging/A-B testing için).
    """
    candidates = state.get("ranked_candidates") or []
    if not candidates:
        return candidates

    X, cands = extract_batch(state)
    if not X:
        return candidates

    try:
        probs = model.predict_proba(X)
        # probs shape: (n, 2) - probability for class 1 (was_selected)
        scores = [float(p[1]) for p in probs]
    except Exception as e:
        logger.warning("[catboost_inference] predict hata: %s", e)
        return candidates

    out: List[Dict[str, Any]] = []
    for cand, ml_s in zip(cands, scores):
        c2 = dict(cand)
        c2["ml_score"] = ml_s
        c2["heuristic_score"] = float(cand.get("final_score") or 0.0)
        c2["final_score"] = ml_s  # ML model active iken final_score ML olur
        out.append(c2)
    out.sort(key=lambda x: x.get("ml_score", 0.0), reverse=True)
    return out
