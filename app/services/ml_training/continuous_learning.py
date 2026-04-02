"""
VYRA ML Training - Continuous Learning Service
================================================
CatBoost'u arka planda sürekli iyileştiren servis.
Sentetik veri üretimi + periyodik yeniden eğitim.

v2.32.0: Initial implementation

Özellikler:
- Arka plan thread ile sürekli öğrenme
- Sentetik veri üretimi (SyntheticDataGenerator)
- Warm-start CatBoost eğitimi
- Feedback bazlı tetikleme
"""

from __future__ import annotations

import time
import threading
from typing import Dict, Any, Optional

from app.services.logging_service import log_system_event, log_error, log_warning


class ContinuousLearningService:
    """
    CatBoost'u arka planda sürekli iyileştiren servis.
    
    Çalışma mantığı:
    1. Her N dakikada bir yeni feedback kontrol et
    2. Yeterli veri varsa sentetik veri üret
    3. CatBoost'u yeniden eğit (warm-start ile incremental)
    4. Yeni modeli hot-swap ile yükle
    """
    
    def __init__(self, interval_minutes: int = 30, min_feedback_threshold: int = 10):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval_minutes = interval_minutes
        self._min_feedback_threshold = min_feedback_threshold
        self._last_training_time: Optional[float] = None
        self._thread_start_time: Optional[float] = None  # Thread başlama zamanı
        self._training_count = 0
        self._training_history: list = []  # In-memory eğitim geçmişi
        self._lock = threading.Lock()
    
    def start(self) -> bool:
        """Arka plan öğrenme döngüsünü başlat."""
        if self._running:
            log_system_event("WARNING", "Continuous learning zaten çalışıyor", "ml_training")
            return False
        
        self._running = True
        self._thread_start_time = time.time()
        self._thread = threading.Thread(
            target=self._learning_loop, 
            daemon=True,
            name="CatBoost-ContinuousLearning"
        )
        self._thread.start()
        
        log_system_event(
            "INFO", 
            f"Continuous learning başlatıldı (interval: {self._interval_minutes}dk)",
            "ml_training"
        )
        return True
    
    def stop(self) -> bool:
        """Döngüyü durdur."""
        if not self._running:
            return False
        
        self._running = False
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        
        log_system_event("INFO", "Continuous learning durduruldu", "ml_training")
        return True
    
    @property
    def is_running(self) -> bool:
        """Servis çalışıyor mu?"""
        return self._running
    
    def update_config(self, interval_minutes: int = None, is_active: bool = None) -> Dict[str, Any]:
        """
        CL servis konfigürasyonunu runtime'da güncelle.
        
        Args:
            interval_minutes: Yeni çalışma aralığı (dakika)
            is_active: True ise başlat, False ise durdur
        """
        result = {"success": True, "changes": []}
        
        if interval_minutes is not None and interval_minutes != self._interval_minutes:
            old = self._interval_minutes
            self._interval_minutes = interval_minutes
            result["changes"].append(f"interval: {old}dk → {interval_minutes}dk")
            log_system_event(
                "INFO",
                f"CL interval güncellendi: {old}dk → {interval_minutes}dk",
                "ml_training"
            )
        
        if is_active is not None:
            if is_active and not self._running:
                self.start()
                result["changes"].append("servis başlatıldı")
            elif not is_active and self._running:
                self.stop()
                result["changes"].append("servis durduruldu")
        
        return result
    
    def _learning_loop(self):
        """Ana öğrenme döngüsü."""
        log_system_event("DEBUG", "Continuous learning thread başladı", "ml_training")
        
        # İlk çalıştırmada 5 dakika bekle (startup settle)
        wait_seconds = 300
        while wait_seconds > 0 and self._running:
            time.sleep(1)
            wait_seconds -= 1
        
        while self._running:
            try:
                self._check_and_train()
            except Exception as e:
                log_error(f"Continuous learning döngü hatası: {e}", "ml_training")
            
            # Interval kadar bekle (saniye bazında kontrol ile durdurmayı yakala)
            wait_seconds = self._interval_minutes * 60
            while wait_seconds > 0 and self._running:
                time.sleep(1)
                wait_seconds -= 1
    
    def _check_and_train(self):
        """Eğitim gerekli mi kontrol et ve gerekiyorsa eğit."""
        # Feedback sayısını bilgilendirme amaçlı logla (artık gate değil)
        feedback_count = self._check_new_feedback_count()
        
        log_system_event(
            "INFO", 
            f"Continuous learning: Eğitim tetiklendi (mevcut feedback: {feedback_count})",
            "ml_training"
        )
        
        # Sentetik veri üret + eğit  (chunk varsa çalışır)
        self._generate_and_train()
    
    def _check_new_feedback_count(self) -> int:
        """Son eğitimden beri eklenen feedback sayısı."""
        try:
            from app.core.db import get_db_context
            
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    if self._last_training_time:
                        from datetime import datetime
                        last_dt = datetime.fromtimestamp(self._last_training_time)
                        cur.execute("""
                            SELECT COUNT(*) as cnt 
                            FROM user_feedback 
                            WHERE created_at > %s
                        """, (last_dt,))
                    else:
                        cur.execute("SELECT COUNT(*) as cnt FROM user_feedback")
                    
                    row = cur.fetchone()
                    return row["cnt"] if row else 0
        except Exception as e:
            log_error(f"Feedback count hatası: {e}", "ml_training")
            return 0
    
    def _generate_and_train(self):
        """Sentetik veri üret + CatBoost eğit + sonucu DB'ye kaydet."""
        with self._lock:
            job_id = None
            start_time = None
            
            try:
                from datetime import datetime
                from app.services.ml_training.synthetic_data import SyntheticDataGenerator
                
                start_time = datetime.now()
                
                # 0. DB'ye job kaydı oluştur
                job_id = self._create_cl_job(start_time)
                
                # 1. Sentetik veri üret (LLM destekli)
                generator = SyntheticDataGenerator(
                    max_chunks=100,
                    questions_per_chunk=2,
                    use_llm=True
                )
                training_data = generator.generate_training_data()
                
                # 2. Gerçek feedback verilerini ekle (sentetik veriden öncelikli)
                real_feedback = self._fetch_real_feedback()
                if real_feedback:
                    log_system_event(
                        "INFO",
                        f"Gerçek feedback: {len(real_feedback)} örnek eğitime eklendi",
                        "ml_training"
                    )
                    training_data = real_feedback + training_data
                
                if not training_data:
                    self._update_cl_job(job_id, "failed", start_time, error="Eğitim verisi üretilemedi")
                    log_system_event("WARNING", "Eğitim verisi üretilemedi", "ml_training")
                    return
                
                # 2. Feature çıkar ve eğit
                train_result = self._train_catboost(training_data)
                
                # 3. Son eğitim zamanı güncelle
                self._last_training_time = time.time()
                self._training_count += 1
                
                end_time = datetime.now()
                duration = int((end_time - start_time).total_seconds())
                samples = train_result.get("samples", len(training_data)) if train_result else len(training_data)
                
                # 4. DB job kaydını güncelle
                if train_result and train_result.get("success"):
                    self._update_cl_job(
                        job_id, "completed", start_time,
                        end_time=end_time, duration=duration, samples=samples
                    )
                else:
                    error_msg = train_result.get("error", "Bilinmeyen hata") if train_result else "Eğitim sonuç yok"
                    self._update_cl_job(
                        job_id, "failed", start_time,
                        end_time=end_time, duration=duration, samples=samples, error=error_msg
                    )
                
                # 5. In-memory geçmişe ekle
                self._training_history.append({
                    "job_id": job_id,
                    "timestamp": time.time(),
                    "samples": samples,
                    "duration": duration,
                    "status": "completed" if (train_result and train_result.get("success")) else "failed",
                })
                
                # 6. Eğitim örneklerini DB'ye kaydet (kullanıcı görebilsin)
                if job_id and training_data:
                    self._save_training_samples(job_id, training_data)
                
                # 7. 🆕 v2.34.0: Topic refinement — eğitim verilerinden topic keyword iyileştir
                try:
                    from app.services.rag.topic_extraction import refine_topics_from_training
                    refined_count = refine_topics_from_training(training_data)
                    if refined_count > 0:
                        log_system_event(
                            "INFO",
                            f"CL Eğitim #{self._training_count}: {refined_count} topic keyword güncellendi",
                            "ml_training"
                        )
                except Exception as topic_err:
                    # Topic refinement hatası eğitimi bozmaz
                    log_error(f"Topic refinement hatası: {topic_err}", "ml_training")
                
                # 8. 🆕 v2.51.0: Learned Q&A — eğitim verilerinden LLM cevapları üret
                try:
                    from app.services.learned_qa_service import get_learned_qa_service
                    qa_service = get_learned_qa_service()
                    qa_count = qa_service.bulk_generate(training_data)
                    if qa_count > 0:
                        log_system_event(
                            "INFO",
                            f"CL Eğitim #{self._training_count}: {qa_count} learned Q&A üretildi",
                            "ml_training"
                        )
                except Exception as qa_err:
                    # Q&A üretim hatası eğitimi bozmaz
                    log_error(f"Learned Q&A üretim hatası: {qa_err}", "ml_training")
                
                log_system_event(
                    "INFO",
                    f"Continuous learning: Eğitim #{self._training_count} tamamlandı ({samples} örnek, {duration}s)",
                    "ml_training"
                )
                
            except Exception as e:
                if job_id:
                    from datetime import datetime
                    self._update_cl_job(job_id, "failed", start_time, error=str(e)[:500])
                log_error(f"Continuous learning eğitim hatası: {e}", "ml_training")
    
    def _create_cl_job(self, start_time) -> Optional[int]:
        """Continuous learning job kaydı oluştur."""
        try:
            from app.core.db import get_db_context
            from datetime import datetime
            _ = datetime  # suppress pyflakes: used below
            
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    job_name = f"cl_auto_{start_time.strftime('%Y%m%d_%H%M%S')}"
                    cur.execute("""
                        INSERT INTO ml_training_jobs 
                        (job_name, job_type, status, trigger_condition, start_time)
                        VALUES (%s, 'continuous', 'running', 'continuous_learning', %s)
                        RETURNING id
                    """, (job_name, start_time))
                    
                    job_id = cur.fetchone()["id"]
                    conn.commit()
                    return job_id
        except Exception as e:
            log_error(f"CL job oluşturma hatası: {e}", "ml_training")
            return None
    
    def _update_cl_job(
        self, job_id: Optional[int], status: str, start_time,
        end_time=None, duration: Optional[int] = None, samples: Optional[int] = None, error: str = None
    ):
        """Continuous learning job kaydını güncelle."""
        if not job_id:
            return
        
        try:
            from app.core.db import get_db_context
            from datetime import datetime
            
            if not end_time:
                end_time = datetime.now()
            if duration is None and start_time:
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
            log_error(f"CL job güncelleme hatası: {e}", "ml_training")
    
    def _save_training_samples(self, job_id: int, training_data: list):
        """Eğitim örneklerini ml_training_samples tablosuna kaydet."""
        try:
            from app.core.db import get_db_context
            
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    rows = []
                    for sample in training_data:
                        rows.append((
                            job_id,
                            sample.get("query", ""),
                            (sample.get("chunk_text", "") or "")[:500],  # 500 char limit
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
                    
            log_system_event(
                "INFO",
                f"Eğitim örnekleri kaydedildi: job #{job_id}, {len(training_data)} örnek",
                "ml_training"
            )
        except Exception as e:
            log_error(f"Eğitim örnekleri kayıt hatası: {e}", "ml_training")
    
    def _train_catboost(self, training_data: list) -> Dict[str, Any]:
        """CatBoost'u sentetik veri ile eğit. Sonuçları dict olarak döndürür."""
        try:
            import numpy as np
            
            # Feature matrix hazırla
            from app.services.feature_extractor import FeatureExtractor
            extractor = FeatureExtractor()
            
            # Sentetik veriden RAG-benzeri sonuç oluştur
            features_list = []
            labels = []
            
            for sample in training_data:
                # 🆕 v2.34.0: file_type'ı source_file'dan çıkar
                source_file = sample.get("source_file", "")
                file_type = ""
                if "." in source_file:
                    file_type = f".{source_file.rsplit('.', 1)[-1].lower()}"
                
                # v2.44.0: Gerçek metadata'yı kullan (sentetik veride artık mevcut)
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
                except Exception as fe:
                    log_error(f"Feature matrix oluşturma hatası (chunk_id={sample.get('chunk_id')}): {fe}", "ml_training")
                    continue
            
            if len(features_list) < 10:
                return {"success": False, "error": "Yeterli feature üretilemedi", "samples": len(features_list)}
            
            X = np.array(features_list)
            y = np.array(labels)
            
            # CatBoost eğitimi
            try:
                from catboost import CatBoostClassifier, Pool
                
                train_pool = Pool(X, y)
                
                model = CatBoostClassifier(
                    iterations=100,
                    learning_rate=0.05,
                    depth=4,
                    verbose=0,
                    random_seed=42,
                    auto_class_weights='Balanced',
                )
                
                model.fit(train_pool)
                
                # Modeli diske kaydet
                import os
                import json
                from datetime import datetime as _dt
                
                model_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "ml_models")
                os.makedirs(model_dir, exist_ok=True)
                
                version = _dt.now().strftime("%Y%m%d_%H%M%S")
                model_filename = f"catboost_cl_v{version}.cbm"
                model_path = os.path.join(model_dir, model_filename)
                model.save_model(model_path)
                
                # ml_models tablosuna kaydet (CatBoost servisi buradan yükler)
                try:
                    from app.core.db import get_db_context
                    
                    metrics = {
                        "samples": int(X.shape[0]),
                        "features": int(X.shape[1]),
                        "training_type": "continuous_learning"
                    }
                    
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
                                "catboost_cl",
                                version,
                                model_path,
                                json.dumps(metrics),
                                int(X.shape[0])
                            ))
                            conn.commit()
                    
                    log_system_event(
                        "INFO",
                        f"CatBoost modeli ml_models tablosuna kaydedildi: v{version}",
                        "ml_training"
                    )
                except Exception as db_err:
                    log_error(f"Model DB kayıt hatası: {db_err}", "ml_training")
                
                # Hot-swap: Mevcut singleton'ı sıfırla (bir sonraki çağrıda yeniden yüklenecek)
                try:
                    from app.services.catboost_service import get_catboost_service
                    service = get_catboost_service()
                    service._model = None
                    service._model_loaded = False
                    log_system_event("INFO", "CatBoost servisi hot-swap ile sıfırlandı", "ml_training")
                except Exception as hs_err:
                    log_error(f"Hot-swap hatası: {hs_err}", "ml_training")
                
                log_system_event(
                    "INFO",
                    f"CatBoost modeli güncellendi: {X.shape[0]} örnek, {X.shape[1]} feature",
                    "ml_training"
                )
                
                return {"success": True, "samples": X.shape[0], "features": X.shape[1]}
                
            except ImportError as e:
                log_error(f"catboost import hatası: {e}", "ml_training")
                return {"success": False, "error": "catboost kütüphanesi yüklü değil", "samples": 0}
                
        except Exception as e:
            log_error(f"CatBoost eğitim hatası: {e}", "ml_training")
            return {"success": False, "error": str(e)[:300], "samples": 0}
    
    def _fetch_real_feedback(self) -> list:
        """
        user_feedback tablosundan gerçek kullanıcı geri bildirimlerini çeker
        ve eğitim verisine dönüştürür.
        
        v2.44.0: Gerçek feedback'ler sentetik veriye eklenerek
        modelin gerçek kullanıcı tercihlerini öğrenmesi sağlanır.
        
        Adversarial feedback koruması: Sorgu-chunk arasındaki benzerlik
        yüksekken negatif oy verilmişse → şüpheli olarak eğitimden çıkarılır.
        
        Returns:
            Eğitim formatında veri listesi (query, chunk_text, label, ...)
        """
        try:
            from app.core.db import get_db_context
            
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
                        LIMIT 500
                    """)
                    
                    rows = cur.fetchall()
            
            if not rows:
                return []
            
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
                # Negatif oylama + yüksek benzerlik = şüpheli
                if label == 0 and chunk_text:
                    overlap = self._compute_query_chunk_overlap(query_text, chunk_text)
                    if overlap >= 0.5:
                        # Sorgu ve chunk açıkça ilişkili ama negatif oy verilmiş
                        # → Muhtemel adversarial feedback, eğitimden çıkar
                        suspicious_count += 1
                        log_warning(
                            f"Şüpheli feedback atlandı: query='{query_text[:50]}' "
                            f"overlap={overlap:.2f} feedback={feedback_type} "
                            f"chunk_id={row['chunk_id']}",
                            "ml_training"
                        )
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
            
            log_system_event(
                "INFO",
                f"Gerçek feedback çekildi: {len(feedback_data)} kayıt "
                f"(pos: {pos_count}, neg: {neg_count}, "
                f"şüpheli atlandı: {suspicious_count})",
                "ml_training"
            )
            
            return feedback_data
            
        except Exception as e:
            log_error(f"Gerçek feedback çekme hatası: {e}", "ml_training")
            return []
    
    @staticmethod
    def _compute_query_chunk_overlap(query: str, chunk_text: str) -> float:
        """
        Sorgu ve chunk metni arasındaki keyword overlap oranını hesaplar.
        Adversarial feedback tespitinde kullanılır.
        
        Returns:
            0.0-1.0 arası overlap oranı (sorgu kelimelerinin chunk'ta geçme yüzdesi)
        """
        if not query or not chunk_text:
            return 0.0
        
        # Basit Türkçe stop words
        stop_words = {
            've', 'veya', 'bir', 'bu', 'için', 'ile', 'de', 'da',
            'mi', 'mı', 'nasıl', 'ne', 'neden', 'var', 'yok',
        }
        
        query_words = set(query.lower().split()) - stop_words
        query_words = {w for w in query_words if len(w) >= 3}
        
        if not query_words:
            return 0.0
        
        chunk_lower = chunk_text.lower()
        matches = sum(1 for w in query_words if w in chunk_lower)
        
        return matches / len(query_words)
    
    def get_status(self) -> Dict[str, Any]:
        """Servis durumu, istatistikler ve son eğitim geçmişi."""
        from datetime import datetime
        
        next_run = None
        if self._running and self._last_training_time:
            next_ts = self._last_training_time + (self._interval_minutes * 60)
            next_run = datetime.fromtimestamp(next_ts).isoformat()
        elif self._running and self._thread_start_time:
            # İlk çalıştırma: startup settle (5dk) sonrası ilk eğitim
            first_run_ts = self._thread_start_time + 300  # 5dk startup settle
            next_run = datetime.fromtimestamp(first_run_ts).isoformat()
        elif self._running:
            next_run = "Yakında..."
        
        return {
            "is_running": self._running,
            "interval_minutes": self._interval_minutes,
            "min_feedback_threshold": self._min_feedback_threshold,
            "last_training_time": datetime.fromtimestamp(self._last_training_time).isoformat() if self._last_training_time else None,
            "next_scheduled_run": next_run,
            "total_trainings": self._training_count,
            "thread_alive": self._thread.is_alive() if self._thread else False,
            "recent_trainings": self._training_history[-10:],  # Son 10
        }


# ============================================
# Singleton Instance
# ============================================

_continuous_learning_service: Optional[ContinuousLearningService] = None


def get_continuous_learning_service() -> ContinuousLearningService:
    """Continuous learning singleton'ı döndürür."""
    global _continuous_learning_service
    if _continuous_learning_service is None:
        # DB'den kaydedilmiş interval'ı oku (restart sonrası korunsun)
        interval = 30  # default
        try:
            from app.core.db import get_db_conn
            conn = get_db_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT setting_value FROM system_settings WHERE setting_key = 'cl_interval_minutes'"
                    )
                    row = cur.fetchone()
                    if row:
                        interval = int(row['setting_value'])
                        log_system_event(
                            "INFO",
                            f"CL interval DB'den okundu: {interval}dk",
                            "ml_training"
                        )
            finally:
                conn.close()
        except Exception as e:
            log_system_event(
                "WARNING",
                f"CL interval DB'den okunamadı, default kullanılıyor ({interval}dk): {e}",
                "ml_training"
            )
        _continuous_learning_service = ContinuousLearningService(interval_minutes=interval)
    return _continuous_learning_service
