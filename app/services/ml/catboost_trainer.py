"""
catboost_trainer — Faz 5b
=========================
agentic_query_feedback verisinden CatBoostClassifier (was_selected hedef) eğitir.
Pointwise binary classification kullanıyoruz (CatBoostRanker yerine) — basit,
sample sayısı az olduğunda daha stabil. İlerde CatBoostRanker'a geçiş mümkün.

Pipeline:
    1) load_training_data(): SELECT FROM agentic_query_feedback (filter + min size)
    2) split train/validation (chronological — son %20 validation)
    3) CatBoostClassifier.fit(X, y, eval_set=(Xv, yv))
    4) metrics: auc, accuracy, logloss
    5) save_model(file_path)
    6) DB'ye `catboost_models` kaydı (is_active=False, manuel onaylama beklenir)

CatBoost yoksa (graceful):
    train_ranking_model() NotImplementedError yerine net hata mesajı döner.

Kullanım:
    from app.services.ml.catboost_trainer import train_ranking_model
    res = train_ranking_model(cur, company_id=1, min_samples=50)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import logging
import os
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# CatBoost lazy import (Faz 5 graceful pattern)
try:
    from catboost import CatBoostClassifier, Pool  # type: ignore
    _HAS_CATBOOST = True
except Exception:
    _HAS_CATBOOST = False
    logger.info("[catboost_trainer] CatBoost yüklü değil — training devre dışı")

from .feature_extractor import FEATURE_ORDER


DEFAULT_HYPERPARAMS = {
    "iterations": 500,
    "learning_rate": 0.05,
    "depth": 6,
    "loss_function": "Logloss",
    "eval_metric": "AUC",
    "random_seed": 42,
    "early_stopping_rounds": 50,
    "verbose": False,
}


def load_training_data(
    cur,
    company_id: Optional[int] = None,
    source_id: Optional[int] = None,
    min_samples: int = 50,
    max_samples: int = 100000,
) -> Tuple[List[List[float]], List[int], List[Dict[str, Any]]]:
    """
    agentic_query_feedback'ten X, y, meta yükler.

    Filtre:
        - company_id eşleşmesi (None → tüm şirketler)
        - source_id eşleşmesi (None → tümü)
        - execution_success NOT NULL (yarım kalan run'lar dahil değil)

    Returns:
        X: feature matrix
        y: was_selected (0/1) etiket
        meta: ek bilgi (kayıt id, candidate_table) — analiz için
    """
    where_clauses = ["execution_success IS NOT NULL"]
    params: List[Any] = []
    if company_id is not None:
        where_clauses.append("company_id = %s")
        params.append(company_id)
    if source_id is not None:
        where_clauses.append("source_id = %s")
        params.append(source_id)

    where_sql = " AND ".join(where_clauses)

    select_cols = ", ".join(FEATURE_ORDER + ["was_selected", "id", "candidate_schema", "candidate_table", "created_at"])
    sql = f"""
        SELECT {select_cols}
          FROM agentic_query_feedback
         WHERE {where_sql}
         ORDER BY created_at ASC
         LIMIT %s
    """
    params.append(max_samples)
    cur.execute(sql, params)
    rows = cur.fetchall()

    if len(rows) < min_samples:
        return [], [], []

    n_feats = len(FEATURE_ORDER)
    X: List[List[float]] = []
    y: List[int] = []
    meta: List[Dict[str, Any]] = []
    for r in rows:
        feats = [float(r[i] or 0.0) for i in range(n_feats)]
        label = int(bool(r[n_feats]))
        X.append(feats)
        y.append(label)
        meta.append({
            "id": r[n_feats + 1],
            "candidate_schema": r[n_feats + 2],
            "candidate_table": r[n_feats + 3],
            "created_at": r[n_feats + 4],
        })
    return X, y, meta


def split_chronological(
    X: List[List[float]], y: List[int],
    validation_ratio: float = 0.2,
) -> Tuple[List[List[float]], List[int], List[List[float]], List[int]]:
    """Veri zaten created_at ASC sırasında — son %20 validation."""
    n = len(X)
    cut = int(n * (1.0 - validation_ratio))
    cut = max(min(cut, n - 1), 1)
    return X[:cut], y[:cut], X[cut:], y[cut:]


def train_ranking_model(
    cur,
    company_id: Optional[int] = None,
    source_id: Optional[int] = None,
    min_samples: int = 50,
    hyperparams: Optional[Dict[str, Any]] = None,
    save_dir: str = "models/catboost",
    notes: Optional[str] = None,
    trained_by: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Training entry point. Başarısızsa hata dict döner ({'error': ...}).
    Başarıda model dosyası + DB kaydı oluşturur.
    """
    if not _HAS_CATBOOST:
        return {"error": "catboost_not_installed",
                "message": "pip install catboost gerekli."}

    X, y, meta = load_training_data(cur, company_id, source_id, min_samples=min_samples)
    if len(X) < min_samples:
        return {"error": "insufficient_data",
                "message": f"En az {min_samples} kayıt gerekli, bulunan: {len(X)}",
                "available": len(X)}

    # Class balance check
    pos = sum(y)
    neg = len(y) - pos
    if pos < 5 or neg < 5:
        return {"error": "class_imbalance",
                "message": f"Yeterli pozitif/negatif örnek yok (pos={pos}, neg={neg})"}

    Xt, yt, Xv, yv = split_chronological(X, y, validation_ratio=0.2)

    hp = dict(DEFAULT_HYPERPARAMS)
    if hyperparams:
        hp.update(hyperparams)

    try:
        clf = CatBoostClassifier(**hp)
        clf.fit(Xt, yt, eval_set=(Xv, yv) if Xv else None, plot=False)
    except Exception as e:
        return {"error": "training_failed", "message": str(e)}

    # Metrics
    train_score = clf.score(Xt, yt) if Xt else None
    val_score = clf.score(Xv, yv) if Xv else None
    train_metrics = {"accuracy": train_score, "size": len(Xt), "positive_ratio": sum(yt) / max(len(yt), 1)}
    val_metrics = {"accuracy": val_score, "size": len(Xv), "positive_ratio": sum(yv) / max(len(yv), 1) if Xv else None}
    try:
        eval_res = clf.get_evals_result() if hasattr(clf, "get_evals_result") else {}
        if eval_res:
            train_metrics["best_iter"] = clf.get_best_iteration()
            # Best AUC pick
            for k, v in eval_res.items():
                if "AUC" in v:
                    val_metrics["best_auc"] = max(v["AUC"])
                    break
    except Exception:
        pass

    # Save model
    os.makedirs(save_dir, exist_ok=True)
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"ranking_v{version}.cbm"
    if company_id:
        fname = f"ranking_c{company_id}_v{version}.cbm"
    file_path = os.path.join(save_dir, fname)
    try:
        clf.save_model(file_path)
    except Exception as e:
        return {"error": "save_failed", "message": str(e)}

    # DB record
    try:
        cur.execute("""
            INSERT INTO catboost_models
                (model_type, version, file_path, feature_names, training_size,
                 train_metrics, validation_metrics, hyperparameters, is_active,
                 company_id, trained_by, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s, %s)
            RETURNING id
        """, (
            "ranking", version, file_path, FEATURE_ORDER, len(X),
            json.dumps(train_metrics, default=str),
            json.dumps(val_metrics, default=str),
            json.dumps(hp, default=str),
            company_id, trained_by, notes or f"Trained on {len(X)} samples",
        ))
        row = cur.fetchone()
        model_id = row[0] if row else None
    except Exception as e:
        logger.warning("[catboost_trainer] DB insert hata: %s", e)
        model_id = None

    return {
        "ok": True,
        "model_id": model_id,
        "version": version,
        "file_path": file_path,
        "training_size": len(X),
        "validation_size": len(Xv),
        "train_metrics": train_metrics,
        "validation_metrics": val_metrics,
        "hyperparameters": hp,
    }


def activate_model(cur, model_id: int) -> bool:
    """
    Modeli active olarak işaretler. Aynı (model_type, company_id) çiftindeki
    diğer aktifleri otomatik deactivate eder.
    """
    try:
        # Önce modelin meta bilgisini al
        cur.execute("SELECT model_type, company_id FROM catboost_models WHERE id = %s", (model_id,))
        row = cur.fetchone()
        if not row:
            return False
        model_type, company_id = row

        # Bu (type, company) için aktifleri kapat
        cur.execute("""
            UPDATE catboost_models SET is_active = FALSE
             WHERE model_type = %s
               AND COALESCE(company_id, 0) = COALESCE(%s, 0)
               AND is_active = TRUE
               AND id != %s
        """, (model_type, company_id, model_id))

        # Hedef modeli active yap
        cur.execute("UPDATE catboost_models SET is_active = TRUE WHERE id = %s", (model_id,))
        return True
    except Exception as e:
        logger.error("[catboost_trainer] activate hata: %s", e)
        return False


def get_active_model_info(cur, model_type: str = "ranking", company_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Aktif model metadata'sını döner."""
    try:
        # Önce company-specific, yoksa global
        cur.execute("""
            SELECT id, model_type, version, file_path, feature_names,
                   training_size, train_metrics, validation_metrics, created_at
              FROM catboost_models
             WHERE model_type = %s
               AND is_active = TRUE
               AND (company_id = %s OR company_id IS NULL)
             ORDER BY (company_id IS NULL) ASC, created_at DESC
             LIMIT 1
        """, (model_type, company_id))
        row = cur.fetchone()
    except Exception:
        return None
    if not row:
        return None
    return {
        "id": row[0], "model_type": row[1], "version": row[2], "file_path": row[3],
        "feature_names": row[4], "training_size": row[5],
        "train_metrics": row[6], "validation_metrics": row[7],
        "created_at": row[8],
    }
