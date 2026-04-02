#!/usr/bin/env python
"""
VYRA L1 Support API - CatBoost Model Training Script
=====================================================
LLM destekli sentetik veri + gerçek feedback ile CatBoost reranking modeli eğitir.

Kullanim:
    python scripts/train_model.py --min-samples 30
    python scripts/train_model.py --min-samples 30 --dry-run
    python scripts/train_model.py --min-samples 30 --no-llm

Author: VYRA AI Team
Version: 2.0.0 (v9.7.0 — LLM + FeatureExtractor + Adversarial Protection)
"""

import sys

# Windows cp1252 encoding fix — subprocess olarak çalışırken Türkçe karakter desteği
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import json
import argparse
from datetime import datetime
from pathlib import Path

# Proje root'u path'e ekle
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np

try:
    from catboost import CatBoostClassifier
    CATBOOST_AVAILABLE = True
except ImportError:
    CATBOOST_AVAILABLE = False
    print("[UYARI] CatBoost yuklu degil. 'pip install catboost' ile yukleyin.")

from app.core.db import get_db_context
from app.services.feature_extractor import FeatureExtractor


# Model kayit dizini
MODELS_DIR = PROJECT_ROOT / "ml_models"
MODELS_DIR.mkdir(exist_ok=True)


# ============================================
# Veri Pipeline
# ============================================

def generate_synthetic_data(use_llm: bool = True, max_chunks: int = 200) -> list:
    """
    SyntheticDataGenerator ile LLM destekli sentetik veri üret.
    Halüsinasyon koruması dahil.
    
    Returns:
        [{query, chunk_id, chunk_text, source_file, intent, relevance_label, score,
          quality_score, topic_label, heading}, ...]
    """
    print(f"[INFO] Sentetik veri uretiliyor (LLM={'Aktif' if use_llm else 'Kapalı'})...")
    
    try:
        from app.services.ml_training.synthetic_data import SyntheticDataGenerator
        
        generator = SyntheticDataGenerator(
            max_chunks=max_chunks,
            questions_per_chunk=2,
            use_llm=use_llm
        )
        
        data = generator.generate_training_data()
        stats = generator.get_stats()
        
        print(f"[OK] Sentetik veri: {len(data)} örnek üretildi")
        if use_llm:
            print(f"     LLM soruları: {stats.get('llm_questions', 0)}")
            print(f"     Template soruları: {stats.get('template_questions', 0)}")
            print(f"     Halüsinasyon filtresi: {stats.get('hallucination_filtered', 0)} soru filtrelendi")
        
        return data
        
    except Exception as e:
        print(f"[HATA] Sentetik veri uretimi hatasi: {e}")
        return []


def fetch_real_feedback(limit: int = 500) -> list:
    """
    Gerçek kullanıcı feedback'lerini adversarial koruma ile çeker.
    CL servisindeki _fetch_real_feedback() ile aynı mantık.
    
    Returns:
        Eğitim formatında veri listesi
    """
    print("[INFO] Gercek feedback verileri cekiliyor...")
    
    try:
        with get_db_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        uf.query_text,
                        uf.feedback_type,
                        uf.chunk_id,
                        COALESCE(rc.chunk_text, '') AS chunk_text,
                        COALESCE(rc.quality_score, 0.5) AS quality_score,
                        COALESCE(rc.topic_label, 'general') AS topic_label,
                        rc.metadata->>'heading' AS heading,
                        COALESCE(ufl.file_name, '') AS source_file
                    FROM user_feedback uf
                    LEFT JOIN rag_chunks rc ON uf.chunk_id = rc.id
                    LEFT JOIN uploaded_files ufl ON rc.file_id = ufl.id
                    WHERE uf.chunk_id IS NOT NULL
                      AND uf.query_text IS NOT NULL
                      AND uf.query_text != ''
                    ORDER BY uf.created_at DESC
                    LIMIT %s
                """, (limit,))
                
                rows = cur.fetchall()
        
        if not rows:
            print("[INFO] Gercek feedback bulunamadi")
            return []
        
        # Türkçe stop words (adversarial detection)
        stop_words = {
            've', 'veya', 'bir', 'bu', 'için', 'ile', 'de', 'da',
            'mi', 'mı', 'nasıl', 'ne', 'neden', 'var', 'yok',
        }
        
        feedback_data = []
        suspicious_count = 0
        
        for row in rows:
            feedback_type = row["feedback_type"]
            query_text = row["query_text"]
            chunk_text = row["chunk_text"]
            
            # Label mapping
            if feedback_type in ("helpful", "positive"):
                label = 1
                score = 0.85
            elif feedback_type == "copied":
                label = 1
                score = 0.80
            elif feedback_type == "partial":
                label = 0
                score = 0.40
            elif feedback_type in ("not_helpful", "negative"):
                label = 0
                score = 0.15
            else:
                label = 0
                score = 0.30
            
            # ─── Adversarial Feedback Koruması ───
            if label == 0 and chunk_text:
                query_words = set(query_text.lower().split()) - stop_words
                query_words = {w for w in query_words if len(w) >= 3}
                
                if query_words:
                    chunk_lower = chunk_text.lower()
                    matches = sum(1 for w in query_words if w in chunk_lower)
                    overlap = matches / len(query_words)
                    
                    if overlap >= 0.5:
                        suspicious_count += 1
                        continue
            
            feedback_data.append({
                "query": query_text,
                "chunk_id": row["chunk_id"],
                "chunk_text": chunk_text,
                "source_file": row["source_file"],
                "intent": "REAL_FEEDBACK",
                "relevance_label": label,
                "score": score,
                "quality_score": row["quality_score"],
                "topic_label": row["topic_label"],
                "heading": row["heading"] or "",
            })
        
        pos_count = sum(1 for d in feedback_data if d['relevance_label'] == 1)
        neg_count = sum(1 for d in feedback_data if d['relevance_label'] == 0)
        
        print(f"[OK] Gercek feedback: {len(feedback_data)} kayıt "
              f"(pozitif: {pos_count}, negatif: {neg_count}, "
              f"şüpheli atlandı: {suspicious_count})")
        
        return feedback_data
        
    except Exception as e:
        print(f"[HATA] Feedback cekme hatasi: {e}")
        return []


# ============================================
# Feature Extraction (Gerçek)
# ============================================

def extract_features(training_data: list) -> tuple:
    """
    FeatureExtractor ile gerçek feature matrix oluştur.
    Placeholder feature'lar yerine model runtime'daki ile aynı feature'lar.
    
    Returns:
        (features_array, labels_array) veya (None, None) hata durumunda
    """
    print("[INFO] Feature extraction basliyor (FeatureExtractor)...")
    
    extractor = FeatureExtractor()
    
    features_list = []
    labels = []
    skipped = 0
    
    for sample in training_data:
        # source_file'dan file_type çıkar
        source_file = sample.get("source_file", "")
        file_type = ""
        if "." in source_file:
            file_type = f".{source_file.rsplit('.', 1)[-1].lower()}"
        
        # FeatureExtractor'ın beklediği result format
        result = {
            "chunk_id": sample["chunk_id"],
            "content": sample["chunk_text"],
            "score": sample["score"],
            "quality_score": sample.get("quality_score", 0.5),
            "topic_label": sample.get("topic_label", "general"),
            "file_type": file_type,
            "metadata": {
                "file_type": file_type,
                "heading": sample.get("heading", ""),
            },
        }
        
        try:
            matrix, _ = extractor.build_feature_matrix(
                [result], user_id=None, query=sample["query"]
            )
            if matrix.shape[0] > 0:
                features_list.append(matrix[0])
                labels.append(sample["relevance_label"])
        except Exception:
            skipped += 1
            continue
    
    if skipped > 0:
        print(f"[UYARI] {skipped} örnek feature extraction'da atlandı")
    
    if len(features_list) < 10:
        print(f"[HATA] Yeterli feature üretilemedi: {len(features_list)} < 10")
        return None, None
    
    features_arr = np.array(features_list)
    labels_arr = np.array(labels)
    
    print(f"[OK] Feature matrix: {features_arr.shape[0]} örnek, {features_arr.shape[1]} feature")
    
    return features_arr, labels_arr


# ============================================
# Model Eğitimi
# ============================================

def train_model(features: np.ndarray, labels: np.ndarray) -> object:
    """CatBoost Classifier modeli eğit."""
    print("[INFO] CatBoost egitimi basliyor...")
    
    if not CATBOOST_AVAILABLE:
        print("[HATA] CatBoost yuklu degil!")
        return None, {}
    
    from sklearn.model_selection import train_test_split
    
    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(
        features, labels, test_size=0.2, random_state=42, stratify=labels
    )
    
    model = CatBoostClassifier(
        iterations=200,
        learning_rate=0.05,
        depth=5,
        verbose=50,
        random_seed=42,
        auto_class_weights='Balanced',
        task_type='CPU',
        eval_metric='AUC',
    )
    
    model.fit(
        X_train, y_train,
        eval_set=(X_test, y_test),
        early_stopping_rounds=30
    )
    
    # Metrikler
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
    
    y_pred = model.predict(X_test)
    
    metrics = {
        "accuracy": float(accuracy_score(y_test, y_pred)),
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "train_samples": int(X_train.shape[0]),
        "test_samples": int(X_test.shape[0]),
        "total_samples": int(features.shape[0]),
        "features": int(features.shape[1]),
        "training_type": "manual",
    }
    
    print("\n[OK] Egitim tamamlandi!")
    print(f"     Accuracy:  {metrics['accuracy']:.4f}")
    print(f"     Precision: {metrics['precision']:.4f}")
    print(f"     Recall:    {metrics['recall']:.4f}")
    print(f"     F1:        {metrics['f1']:.4f}")
    
    return model, metrics


def save_model(model, metrics: dict) -> str:
    """Modeli diske kaydet ve DB'ye bilgi ekle."""
    
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_name = "catboost_manual"
    model_filename = f"{model_name}_v{version}.cbm"
    model_path = str(MODELS_DIR / model_filename)
    
    # Modeli kaydet
    model.save_model(model_path)
    print(f"[OK] Model kaydedildi: {model_path}")
    
    # Veritabanına kaydet
    with get_db_context() as conn:
        with conn.cursor() as cur:
            # Önceki aktif modeli deaktive et
            cur.execute("""
                UPDATE ml_models SET is_active = FALSE 
                WHERE model_type = 'catboost' AND is_active = TRUE
            """)
            
            # Yeni modeli ekle
            cur.execute("""
                INSERT INTO ml_models 
                (model_name, model_version, model_path, model_type, is_active, 
                 metrics, training_samples)
                VALUES (%s, %s, %s, 'catboost', TRUE, %s, %s)
            """, (
                model_name,
                version,
                model_path,
                json.dumps(metrics),
                metrics.get('total_samples', 0)
            ))
            
            conn.commit()
    
    # Hot-swap: CatBoost servisini sıfırla
    try:
        from app.services.catboost_service import get_catboost_service
        service = get_catboost_service()
        service._model = None
        service._model_loaded = False
        print("[OK] CatBoost servisi hot-swap ile sıfırlandı")
    except Exception:
        pass
    
    print(f"[OK] Model veritabanina kaydedildi: v{version}")
    
    return model_path


def save_training_samples(job_id: int, training_data: list):
    """Eğitim örneklerini ml_training_samples tablosuna kaydet."""
    if not job_id or not training_data:
        return
    
    try:
        with get_db_context() as conn:
            with conn.cursor() as cur:
                rows = []
                for sample in training_data:
                    rows.append((
                        job_id,
                        sample.get("query", ""),
                        (sample.get("chunk_text", "") or "")[:500],
                        sample.get("source_file", ""),
                        sample.get("intent", ""),
                        sample.get("relevance_label", 1),
                        sample.get("score", 0),
                    ))
                
                cur.executemany("""
                    INSERT INTO ml_training_samples 
                    (job_id, query, chunk_text, source_file, intent, relevance_label, score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, rows)
                conn.commit()
        
        print(f"[OK] {len(training_data)} eğitim örneği DB'ye kaydedildi (job #{job_id})")
    except Exception as e:
        print(f"[UYARI] Eğitim örnekleri kayıt hatası: {e}")


# ============================================
# Ana Akış
# ============================================

def main():
    parser = argparse.ArgumentParser(description='CatBoost Reranker Model Eğitimi (v2.0 — LLM Destekli)')
    parser.add_argument('--min-samples', type=int, default=30, 
                        help='Minimum egitim ornegi sayisi (default: 30)')
    parser.add_argument('--max-chunks', type=int, default=200,
                        help='Sentetik veri icin maksimum chunk sayisi (default: 200)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Sadece veri kontrolu yap, egitme')
    parser.add_argument('--no-llm', action='store_true',
                        help='LLM kullanma, sadece template sorular')
    parser.add_argument('--job-id', type=int, default=None,
                        help='Mevcut job ID (job_runner tarafından çağrıldığında yeni job oluşturmaz)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("  VYRA CatBoost Model Eğitimi v2.0 (LLM Destekli)")
    print("=" * 60)
    
    start_time = datetime.now()
    
    # ─── 1. Sentetik veri üret ───
    synthetic_data = generate_synthetic_data(
        use_llm=not args.no_llm,
        max_chunks=args.max_chunks
    )
    
    # ─── 2. Gerçek feedback çek ───
    real_feedback = fetch_real_feedback()
    
    # ─── 3. Birleştir (gerçek feedback öncelikli) ───
    training_data = real_feedback + synthetic_data
    
    if len(training_data) < args.min_samples:
        print(f"\n[HATA] Yeterli veri yok: {len(training_data)} < {args.min_samples}")
        sys.exit(1)
    
    print(f"\n[INFO] Toplam eğitim verisi: {len(training_data)} "
          f"(sentetik: {len(synthetic_data)}, gerçek: {len(real_feedback)})")
    
    # ─── 4. Feature extraction ───
    features, labels = extract_features(training_data)
    
    if features is None:
        print("[HATA] Feature extraction basarisiz.")
        sys.exit(1)
    
    if args.dry_run:
        print(f"\n[OK] Dry run tamamlandi. {features.shape[0]} örnek, {features.shape[1]} feature hazır.")
        sys.exit(0)
    
    # ─── 5. Job kaydı: dışarıdan geldiyse kullan, yoksa oluştur ───
    job_id = args.job_id  # job_runner'dan geldiyse mevcut ID
    _standalone = job_id is None  # Standalone mı çalışıyor?
    
    if job_id:
        print(f"[INFO] Harici Job #{job_id} kullanılıyor (job_runner üzerinden)")
    else:
        # Standalone çalışma — kendi job kaydımızı oluştur
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    job_name = f"manual_{start_time.strftime('%Y%m%d_%H%M%S')}"
                    cur.execute("""
                        INSERT INTO ml_training_jobs 
                        (job_name, job_type, status, trigger_condition, start_time)
                        VALUES (%s, 'manual', 'running', 'manual', %s)
                        RETURNING id
                    """, (job_name, start_time))
                    job_id = cur.fetchone()["id"]
                    conn.commit()
            print(f"[INFO] Job #{job_id} oluşturuldu (standalone)")
        except Exception as e:
            print(f"[UYARI] Job kaydi olusturulamadi: {e}")
    
    # ─── 6. Model eğit ───
    model, metrics = train_model(features, labels)
    
    if model is None:
        if job_id and _standalone:
            _update_job(job_id, "failed", start_time, error="Model eğitilemedi")
        print("[HATA] Model egitilelemedi.")
        sys.exit(1)
    
    # ─── 7. Kaydet ───
    model_path = save_model(model, metrics)
    
    # ─── 8. Eğitim örneklerini kaydet ───
    save_training_samples(job_id, training_data)
    
    # ─── 9. Job kaydını güncelle (sadece standalone modda) ───
    end_time = datetime.now()
    duration = int((end_time - start_time).total_seconds())
    if job_id and _standalone:
        _update_job(job_id, "completed", start_time, 
                    end_time=end_time, duration=duration, 
                    samples=metrics.get("total_samples", 0))
    
    # ─── 10. Topic refinement ───
    try:
        from app.services.rag.topic_extraction import refine_topics_from_training
        refined = refine_topics_from_training(training_data)
        if refined > 0:
            print(f"[OK] {refined} topic keyword güncellendi")
    except Exception as e:
        print(f"[UYARI] Topic refinement hatası: {e}")
    
    # ─── 11. Learned Q&A — eğitim verilerinden LLM cevapları üret ───
    try:
        from app.services.learned_qa_service import get_learned_qa_service
        qa_service = get_learned_qa_service()
        qa_count = qa_service.bulk_generate(training_data)
        if qa_count > 0:
            print(f"[OK] {qa_count} learned Q&A cevabı üretildi")
        else:
            print("[INFO] Learned Q&A: Üretilecek aday bulunamadı veya tümü zaten mevcut")
    except Exception as e:
        print(f"[UYARI] Learned Q&A üretim hatası: {e}")
    
    print("\n" + "=" * 60)
    print("  Eğitim tamamlandı!")
    print(f"  Model:    {model_path}")
    print(f"  Örnekler: {metrics.get('total_samples', 0)}")
    print(f"  Süre:     {duration}s")
    print(f"  F1:       {metrics.get('f1', 0):.4f}")
    print("=" * 60)


def _update_job(job_id: int, status: str, start_time, 
                end_time=None, duration=None, samples=None, error=None):
    """Job kaydını güncelle (yardımcı fonksiyon)."""
    try:
        if not end_time:
            end_time = datetime.now()
        if duration is None:
            duration = int((end_time - start_time).total_seconds())
        
        with get_db_context() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ml_training_jobs
                    SET status = %s, end_time = %s, duration_seconds = %s,
                        training_samples = %s, error_message = %s
                    WHERE id = %s
                """, (status, end_time, duration, samples, error, job_id))
                conn.commit()
    except Exception as e:
        print(f"[UYARI] Job güncelleme hatasi: {e}")


if __name__ == "__main__":
    main()
