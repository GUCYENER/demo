"""
VYRA L1 Support API - Learned Q&A Service
==========================================
Öğrenilmiş soru-cevap havuzu.

CL eğitimi sırasında üretilen sentetik sorulara LLM ile
formatlanmış cevap üretip saklar. Kullanıcı benzer soru
sorduğunda, embedding similarity ile ~100ms'de döndürür.

🆕 v2.51.0: Tier 1 — Deep Think Cache ile CatBoost Bypass arasında.
"""

import numpy as np
from typing import Optional, Dict, Any, List
from app.services.logging_service import log_system_event, log_error, log_warning


class LearnedQAService:
    """
    Öğrenilmiş soru-cevap havuzu.
    
    Eğitim zamanı:
        bulk_generate(training_data) → LLM ile cevap üret → DB'ye kaydet
    
    Sorgu zamanı:
        search(query, threshold=0.80) → embedding benzerliği ile en iyi eşleşme
    """
    
    SIMILARITY_THRESHOLD = 0.80  # Minimum cosine similarity
    
    def __init__(self):
        self._embedding_mgr = None
    
    def _get_embedding_mgr(self):
        """Lazy-loaded EmbeddingManager (ONNX/PyTorch destekli)."""
        if self._embedding_mgr is None:
            try:
                from app.services.rag.embedding import EmbeddingManager
                self._embedding_mgr = EmbeddingManager()
            except Exception as e:
                log_error(f"EmbeddingManager yüklenemedi: {e}", "learned_qa")
        return self._embedding_mgr
    
    def _compute_embedding(self, text: str) -> Optional[List[float]]:
        """Metin için embedding hesapla (ONNX/PyTorch uyumlu)."""
        mgr = self._get_embedding_mgr()
        if mgr is None:
            return None
        try:
            embedding = mgr.get_embedding(text)
            return embedding
        except Exception as e:
            log_error(f"Embedding hesaplama hatası: {e}", "learned_qa")
            return None
    
    def search(self, query: str, user_id: int = None, threshold: float = None) -> Optional[Dict[str, Any]]:
        """
        Kullanıcı sorusuna en yakın öğrenilmiş cevabı bul.
        
        Args:
            query: Kullanıcı sorusu
            user_id: Kullanıcı ID (gelecekte kişiselleştirme için)
            threshold: Minimum benzerlik eşiği (default: 0.80)
            
        Returns:
            Eşleşme varsa {"answer": ..., "score": ..., "source_file": ...}
            Yoksa None
        """
        if threshold is None:
            threshold = self.SIMILARITY_THRESHOLD
        
        query_embedding = self._compute_embedding(query)
        if query_embedding is None:
            return None
        
        try:
            from app.core.db import get_db_conn
            conn = get_db_conn()
            cur = conn.cursor()
            
            # learned_answers tablosundan embedding'li tüm kayıtları çek
            cur.execute("""
                SELECT id, question, answer, intent, source_file, embedding, quality_score
                FROM learned_answers
                WHERE embedding IS NOT NULL
            """)
            rows = cur.fetchall()
            
            if not rows:
                cur.close()
                conn.close()
                return None
            
            # Cosine similarity hesapla
            query_vec = np.array(query_embedding, dtype=np.float32)
            best_match = None
            best_score = 0.0
            
            for row in rows:
                db_embedding = row.get("embedding") if isinstance(row, dict) else row[5]
                if not db_embedding:
                    continue
                
                db_vec = np.array(db_embedding, dtype=np.float32)
                
                # Cosine similarity (normalized vectors → dot product)
                similarity = float(np.dot(query_vec, db_vec))
                
                if similarity > best_score:
                    best_score = similarity
                    best_match = row
            
            cur.close()
            conn.close()
            
            if best_match is None or best_score < threshold:
                log_system_event(
                    "DEBUG",
                    f"Learned QA: eşleşme bulunamadı (best={best_score:.2f}, threshold={threshold})",
                    "learned_qa"
                )
                return None
            
            # Hit count güncelle
            try:
                match_id = best_match.get("id") if isinstance(best_match, dict) else best_match[0]
                conn2 = get_db_conn()
                cur2 = conn2.cursor()
                cur2.execute(
                    "UPDATE learned_answers SET hit_count = hit_count + 1, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                    (match_id,)
                )
                conn2.commit()
                cur2.close()
                conn2.close()
            except Exception:
                pass  # Hit count güncelleme hatası kritik değil
            
            # Sonuç döndür
            if isinstance(best_match, dict):
                question = best_match.get("question", "")
                answer = best_match.get("answer", "")
                intent = best_match.get("intent", "")
                source_file = best_match.get("source_file", "")
                quality = best_match.get("quality_score", 0)
            else:
                question = best_match[1]
                answer = best_match[2]
                intent = best_match[3]
                source_file = best_match[4]
                quality = best_match[6]
            
            log_system_event(
                "INFO",
                f"Learned QA HIT: '{query[:40]}' → '{question[:40]}' (score={best_score:.2f})",
                "learned_qa"
            )
            
            return {
                "answer": answer,
                "question": question,
                "score": best_score,
                "intent": intent,
                "source_file": source_file,
                "quality_score": quality
            }
            
        except Exception as e:
            log_error(f"Learned QA search hatası: {e}", "learned_qa")
            return None
    
    def add(self, question: str, answer: str, intent: str = None,
            source_file: str = None, chunk_id: int = None,
            quality_score: float = 0.0) -> bool:
        """
        v2.52.0: UPSERT — Yeni Q&A çifti ekle veya daha kaliteli cevapla güncelle.
        
        Kalite koruma: Yeni cevabın kalite skoru eskiden yüksekse günceller,
        değilse eski (daha iyi) cevabı korur. Kötü cevap üzerine yazılmasını önler.
        """
        embedding = self._compute_embedding(question)
        
        conn = None
        cur = None
        try:
            from app.core.db import get_db_conn
            conn = get_db_conn()
            cur = conn.cursor()
            
            # Mevcut kaydı kontrol et
            cur.execute(
                "SELECT id, answer, quality_score FROM learned_answers WHERE question = %s LIMIT 1",
                (question,)
            )
            existing = cur.fetchone()
            
            if existing:
                # UPSERT: Kalite karşılaştırması yap
                existing_id = existing["id"] if isinstance(existing, dict) else existing[0]
                existing_answer = existing["answer"] if isinstance(existing, dict) else existing[1]
                
                old_quality = self._compute_answer_quality_score(existing_answer)
                new_quality = self._compute_answer_quality_score(answer)
                
                if new_quality > old_quality:
                    # Yeni cevap daha kaliteli → güncelle
                    cur.execute("""
                        UPDATE learned_answers
                        SET answer = %s, intent = %s, source_file = %s, 
                            chunk_id = %s, embedding = %s, quality_score = %s,
                            updated_at = NOW()
                        WHERE id = %s
                    """, (answer, intent, source_file, chunk_id,
                          embedding, quality_score, existing_id))
                    conn.commit()
                    
                    log_system_event(
                        "INFO",
                        f"Learned QA UPSERT: '{question[:40]}' güncellendi "
                        f"(eski_kalite={old_quality:.0f}, yeni_kalite={new_quality:.0f})",
                        "learned_qa"
                    )
                    return True
                else:
                    # Eski cevap daha iyi → koru
                    log_system_event(
                        "DEBUG",
                        f"Learned QA UPSERT SKIP: '{question[:40]}' eski cevap korundu "
                        f"(eski_kalite={old_quality:.0f} >= yeni_kalite={new_quality:.0f})",
                        "learned_qa"
                    )
                    return False
            
            # Yeni kayıt — INSERT
            cur.execute("""
                INSERT INTO learned_answers
                    (question, answer, intent, source_file, chunk_id, embedding, quality_score)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (question, answer, intent, source_file, chunk_id,
                  embedding, quality_score))
            
            conn.commit()
            return True
        except Exception as e:
            log_error(f"Learned QA add hatası: {e}", "learned_qa")
            return False
        finally:
            if cur:
                try:
                    cur.close()
                except Exception:
                    pass
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    
    @staticmethod
    def _compute_answer_quality_score(answer: str) -> float:
        """
        v2.52.0: Cevap kalite skoru (0-100). LLM gerektirmez.
        
        Ölçütler:
        - Uzunluk (detaylılık)
        - Adım adım yapı (numbered list, emoji)
        - Format zenginliği (bold, bullet)
        - Kelime çeşitliliği
        
        Returns:
            0-100 arası kalite skoru
        """
        import re
        
        if not answer or len(answer) < 20:
            return 0.0
        
        score = 0.0
        
        # 1. Uzunluk skoru (max 30 puan, 500+ char = tam puan)
        length_score = min(len(answer) / 500, 1.0) * 30
        score += length_score
        
        # 2. Adım adım yapı (max 25 puan)
        step_patterns = [
            r'\d+[.)\.]',          # 1. 2. 3.
            r'[1-9]️⃣',              # 1️⃣ 2️⃣ 3️⃣
            r'Adım\s*\d',           # Adım 1, Adım 2
        ]
        step_count = 0
        for pattern in step_patterns:
            step_count += len(re.findall(pattern, answer))
        step_score = min(step_count / 3, 1.0) * 25
        score += step_score
        
        # 3. Format zenginliği (max 25 puan)
        format_score = 0.0
        if '**' in answer:        # Bold
            format_score += 8
        if '•' in answer or '↳' in answer:  # Bullet
            format_score += 5
        if '💡' in answer or '⚠️' in answer or '📌' in answer:  # Emoji
            format_score += 5
        if '🎯' in answer or '✅' in answer or '🔍' in answer:  # Daha fazla
            format_score += 4
        if '\n' in answer:        # Çok satırlı
            format_score += 3
        score += min(format_score, 25)
        
        # 4. Kelime çeşitliliği (max 20 puan)
        words = answer.lower().split()
        if len(words) > 10:
            unique_ratio = len(set(words)) / len(words)
            diversity_score = unique_ratio * 20
            score += diversity_score
        
        return min(score, 100.0)
    
    def bulk_generate(self, training_data: list, max_answers: int = None) -> int:
        """
        CL/Scheduled eğitim verilerinden LLM ile cevap üretip kaydet.
        
        Args:
            training_data: Sentetik eğitim verileri (query, chunk_text, intent, source_file, ...)
            max_answers: Maksimum üretilecek cevap sayısı (None = barajı aşan tümü)
            
        Returns:
            Üretilen cevap sayısı
        """
        # Sadece pozitif (ilgili) eşleşmeleri ve yeterli skora sahip olanları seç
        candidates = [
            d for d in training_data
            if d.get("relevance_label", d.get("label", 0)) == 1 and d.get("score", 0) >= 0.70
        ]
        
        if not candidates:
            log_system_event("INFO", "Learned QA: cevap üretilecek aday yok", "learned_qa")
            return 0
        
        # Skoruna göre sırala (en yüksek önce)
        candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
        
        # Limit varsa kırp
        if max_answers is not None:
            candidates = candidates[:max_answers]
        
        # v2.52.0: Duplicate skip kaldırıldı — UPSERT add() içinde yönetilir.
        # Daha kaliteli cevap üretildiyse eski cevap güncellenir.
        
        generated = 0
        batch = []
        
        for item in candidates:
            question = item.get("query", "").strip()
            chunk_text = item.get("chunk_text", "").strip()
            intent = item.get("intent", "")
            source_file = item.get("source_file", "")
            chunk_id = item.get("chunk_id")
            
            if not question or not chunk_text:
                continue
            
            batch.append({
                "question": question,
                "chunk_text": chunk_text,
                "intent": intent,
                "source_file": source_file,
                "chunk_id": chunk_id,
                "score": item.get("score", 0)
            })
        
        if not batch:
            log_system_event("INFO", "Learned QA: cevap üretilecek aday yok", "learned_qa")
            return 0
        
        # LLM ile batch cevap üretimi
        generated = self._generate_answers_batch(batch)
        
        log_system_event(
            "INFO",
            f"Learned QA: {generated}/{len(batch)} cevap üretildi ve kaydedildi",
            "learned_qa"
        )
        
        return generated
    
    
    
    def _generate_answers_batch(self, batch: list) -> int:
        """
        v2.52.0: Per-question task mimarisi ile cevap üret ve kaydet.
        
        İyileştirmeler:
        - Her soru bağımsız işlenir (hata izolasyonu)
        - Intent-bazlı zengin prompt (Deep Think seviye)
        - Tam chunk context (2000 char, bilgi kaybı yok)
        - Post-processing (prompt leak temizleme, format düzeltme)
        - Refinement adımı (2. LLM çağrısıyla kalite artışı)
        - Streaming LLM desteği (timeout azaltma)
        """
        try:
            from app.core.llm import call_llm_api, call_llm_api_stream
        except ImportError:
            log_warning("LLM API import edilemedi", "learned_qa")
            return 0
        
        generated = 0
        
        for idx, item in enumerate(batch):
            try:
                question = item["question"]
                chunk_text = item["chunk_text"]
                intent = (item.get("intent") or "GENERAL").upper()
                source_file = item.get("source_file", "")
                
                log_system_event(
                    "INFO",
                    f"Learned QA [{idx+1}/{len(batch)}]: '{question[:50]}' (intent={intent})",
                    "learned_qa"
                )
                
                # 1️⃣ Intent-bazlı zengin prompt ile LLM çağrısı
                raw_answer = self._generate_single_answer(
                    question=question,
                    chunk_text=chunk_text,
                    intent=intent,
                    source_file=source_file,
                    call_llm_api=call_llm_api,
                    call_llm_api_stream=call_llm_api_stream
                )
                
                if not raw_answer or len(raw_answer) < 50:
                    log_warning(
                        f"Learned QA: Cevap çok kısa veya boş: '{question[:40]}'",
                        "learned_qa"
                    )
                    continue
                
                # 2️⃣ Post-processing
                processed_answer = self._postprocess_qa_answer(raw_answer, intent)
                
                # 3️⃣ Refinement — kalite artışı için 2. LLM çağrısı
                refined_answer = self._refine_answer(
                    raw_answer=processed_answer,
                    question=question,
                    intent=intent,
                    call_llm_api=call_llm_api
                )
                
                final_answer = refined_answer if refined_answer else processed_answer
                
                # 4️⃣ Halüsinasyon kontrolü (3 katmanlı validasyon)
                validation = self._validate_answer(
                    answer=final_answer,
                    source_text=chunk_text,
                    question=question
                )
                if not validation["passed"]:
                    log_warning(
                        f"Learned QA REJECTED: '{question[:40]}' "
                        f"reason={validation['reason']}, "
                        f"faithfulness={validation.get('faithfulness', 0):.2f}, "
                        f"grounding={validation.get('grounding', 0):.1%}, "
                        f"length_ratio={validation.get('length_ratio', 0):.1f}x",
                        "learned_qa"
                    )
                    continue
                
                # 5️⃣ Kaydet
                success = self.add(
                    question=question,
                    answer=final_answer,
                    intent=item.get("intent"),
                    source_file=source_file,
                    chunk_id=item.get("chunk_id"),
                    quality_score=item.get("score", 0)
                )
                if success:
                    generated += 1
                    
            except Exception as e:
                log_warning(
                    f"Learned QA soru atlandı: '{item.get('question', '')[:40]}' hata={e}",
                    "learned_qa"
                )
                continue
        
        return generated
    
    def _generate_single_answer(
        self, question: str, chunk_text: str, intent: str,
        source_file: str, call_llm_api, call_llm_api_stream
    ) -> str:
        """
        v2.52.0: Tek soru için intent-bazlı LLM cevap üretimi.
        Streaming ile timeout riskini azaltır.
        """
        format_instruction = self._get_qa_format_instruction(intent)
        
        # Giriş güvenliği: uzun soru/chunk taşma riski
        question_safe = question[:500]  # Max 500 char (~125 token)
        chunk_content = chunk_text[:2000]  # Max 2000 char (~500 token)
        
        prompt = f"""Aşağıdaki kaynak içeriğe dayanarak soruyu profesyonel ve kapsamlı şekilde cevapla.

📝 SORU: {question_safe}
📄 KAYNAK DOSYA: {source_file}

📖 KAYNAK İÇERİK:
{chunk_content}

{format_instruction}

⚠️ KRİTİK KURALLAR:
1. SADECE kaynak içerikteki bilgilere dayalı cevap ver
2. Kaynak içerikte olmayan bilgileri UYDURMA
3. Teknik terimleri parantez içinde açıkla
4. Türkçe ve profesyonel bir dil kullan
5. Cevap en az 5-6 cümle olsun, detaylı ve kapsamlı yaz"""

        messages = [
            {"role": "system", "content": (
                "Sen kurumsal IT destek ortamında uzmanlaşmış kıdemli bir teknik destek "
                "mühendisisin. Kullanıcılara adım adım, detaylı ve anlaşılır çözümler "
                "sunuyorsun. Her cevabında sorunun ne olduğunu, nasıl çözüleceğini ve "
                "dikkat edilmesi gereken noktaları açıkça belirtirsin."
            )},
            {"role": "user", "content": prompt}
        ]
        
        # Streaming ile cevap al (timeout riski azaltır)
        try:
            full_response = ""
            for token in call_llm_api_stream(messages):
                full_response += token
            
            if full_response and len(full_response) >= 30:
                # Maksimum cevap uzunluğu: 3000 char (~750 token)
                # Daha uzun cevaplar anlam bozukluğuna/tekrar döngüsüne işaret eder
                if len(full_response) > 3000:
                    # Son cümle sonunda kes (temiz sonlanma)
                    truncated = full_response[:3000]
                    last_period = truncated.rfind('.')
                    if last_period > 2000:
                        truncated = truncated[:last_period + 1]
                    return truncated.strip()
                return full_response.strip()
        except Exception as e:
            log_warning(f"Learned QA streaming fallback: {e}", "learned_qa")
        
        # Fallback: senkron çağrı
        try:
            response = call_llm_api(messages)
            return response.strip() if response else ""
        except Exception as e:
            log_warning(f"Learned QA senkron çağrı hatası: {e}", "learned_qa")
            return ""
    
    @staticmethod
    def _get_qa_format_instruction(intent: str) -> str:
        """
        v2.52.0: Intent tipine göre cevap format talimatı.
        Deep Think formatting mixin'den esinlenerek Learned QA için uyarlandı.
        """
        instructions = {
            "HOW_TO": """📌 FORMAT TALİMATI (ADIM ADIM REHBER):
🎯 **Amaç:** [Ne yapılacağını kısaca belirt]

📌 **Adımlar:**

  1️⃣ **[Adım başlığı]**
     ↳ Detaylı açıklama — nereye tıklanacağı, ne yazılacağı açıkça belirt

  2️⃣ **[İkinci adım]**
     ↳ Detaylı açıklama

  3️⃣ **[Üçüncü adım]**
     ↳ Detaylı açıklama

💡 **İpucu:** [Varsa faydalı ipucu]
⚠️ **Dikkat:** [Varsa dikkat edilecek nokta]""",

            "TROUBLESHOOT": """📌 FORMAT TALİMATI (SORUN GİDERME):
🔴 **Sorun:** [Sorunun net açıklaması]

🔍 **Olası Nedenler:**
  • [Neden 1]
  • [Neden 2]

✅ **Çözüm Adımları:**

  1️⃣ **[İlk işlem]**
     ↳ Beklenen sonuç

  2️⃣ **[İkinci işlem]**
     ↳ Beklenen sonuç

⚠️ **Dikkat:** [Kritik uyarılar]
📞 **Çözülmezse:** [Alternatif yöntem veya yönlendirme]""",

            "LIST_REQUEST": """📌 FORMAT TALİMATI (LİSTE):
📋 **[Konu Başlığı]**

1. **[Öğe 1]**
   ↳ Kısa açıklama

2. **[Öğe 2]**
   ↳ Kısa açıklama

3. **[Öğe 3]**
   ↳ Kısa açıklama

💡 **Not:** [Varsa ek bilgi]""",

            "SINGLE_ANSWER": """📌 FORMAT TALİMATI (TEKİL CEVAP):
📖 **[Konu Başlığı]**

**Tanım:** [Net ve öz açıklama — en az 2-3 cümle]

**Kullanım:** [Nasıl/ne zaman kullanılır]

**Örnek:** [Varsa somut örnek]

💡 **İpucu:** [Varsa faydalı bilgi]""",
        }
        
        return instructions.get(intent, """📌 FORMAT TALİMATI (GENEL):
📋 **Özet:** [Konunun kısa özeti]

**Detaylar:**
  • [Madde 1 — detaylı açıklama]
  • [Madde 2 — detaylı açıklama]
  • [Madde 3 — detaylı açıklama]

💡 **Ek Bilgi:** [Varsa faydalı not]""")
    
    @staticmethod
    def _postprocess_qa_answer(answer: str, intent: str) -> str:
        """
        v2.52.0: LLM cevabını post-process eder.
        Prompt leak temizleme, format düzeltme.
        """
        import re
        
        cleaned = answer
        
        # 1. Prompt sızıntısı temizle
        leak_patterns = [
            r'^.*SADECE kaynak içerikteki bilgilere dayalı.*$',
            r'^.*Kaynak içerikte olmayan bilgileri UYDURMA.*$',
            r'^.*Türkçe ve profesyonel bir dil kullan.*$',
            r'^.*FORMAT TALİMATI.*$',
            r'^.*KRİTİK KURALLAR:.*$',
            r'^.*Teknik terimleri parantez içinde açıkla.*$',
            r'^.*Cevap en az \d+-\d+ cümle olsun.*$',
            r'^.*KAYNAK İÇERİK:.*$',
            r'^.*KAYNAK DOSYA:.*$',
        ]
        
        for pattern in leak_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE | re.IGNORECASE)
        
        # 2. Ardışık boş satırları temizle (3+ → 2)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        
        # 3. Başındaki/sonundaki gereksiz boşlukları temizle
        cleaned = cleaned.strip()
        
        return cleaned
    
    def _refine_answer(self, raw_answer: str, question: str, 
                       intent: str, call_llm_api) -> Optional[str]:
        """
        v2.52.0: Ham LLM cevabını iyileştir (kalite artışı).
        2. LLM çağrısı ile daha zengin, düzgün formatlı cevap üretir.
        
        Returns:
            İyileştirilmiş cevap veya None (başarısız ise)
        """
        try:
            # Refinement giriş güvenliği
            question_safe = question[:500]
            answer_safe = raw_answer[:3000]  # Çok uzun cevapları kırp
            
            refinement_prompt = f"""Aşağıdaki teknik destek cevabını iyileştir ve zenginleştir.

SORU: {question_safe}
SORU TİPİ: {intent}

HAM CEVAP:
{answer_safe}

İYİLEŞTİRME KURALLARI:
1. Adım adım yapı ekle veya mevcut yapıyı güçlendir
2. Her adıma emoji numara ekle (1️⃣ 2️⃣ 3️⃣)
3. Teknik terimleri parantez içinde açıkla
4. Eksik bilgi varsa mantıksal çıkarım yap ama kaynak dışına çıkma
5. Okunabilirliği artır — kısa paragraflar, madde işaretleri
6. Profesyonel ve kullanıcı dostu ton kullan
7. Bilgileri ASLA silme veya kısaltma — sadece zenginleştir

İYİLEŞTİRİLMİŞ CEVAP:"""

            messages = [
                {"role": "system", "content": "Sen bir teknik editörsün. Teknik destek cevaplarını daha anlaşılır, detaylı ve profesyonel hale getirirsin."},
                {"role": "user", "content": refinement_prompt}
            ]
            
            response = call_llm_api(messages)
            
            if response and len(response) >= len(raw_answer) * 0.5:
                # Refinement başarılı — iyileştirilmiş cevap daha kısa olmamalı
                refined = self._postprocess_qa_answer(response.strip(), intent)
                return refined
            
            return None
            
        except Exception as e:
            log_warning(f"Learned QA refinement hatası: {e}", "learned_qa")
            return None
    
    def _parse_llm_answers(self, response: str, expected_count: int) -> Dict[int, str]:
        """LLM cevabını parse et."""
        import re
        
        answers = {}
        
        # CEVAP_N: formatını ara
        pattern = r'CEVAP_(\d+):\s*\n(.*?)(?=CEVAP_\d+:|$)'
        matches = re.findall(pattern, response, re.DOTALL)
        
        for num_str, content in matches:
            idx = int(num_str) - 1  # 0-indexed
            if 0 <= idx < expected_count:
                cleaned = content.strip()
                if cleaned:
                    answers[idx] = cleaned
        
        # Eğer pattern bulunamazsa, basit bölme dene
        if not answers and expected_count == 1:
            # Tek soru için tüm response cevap
            cleaned = response.strip()
            if cleaned and len(cleaned) >= 50:
                answers[0] = cleaned
        
        return answers
    
    # =========================================================================
    # 🛡️ HALÜSİNASYON ÖNLEME — 3 Katmanlı Doğrulama
    # =========================================================================
    
    # Eşik değerler
    FAITHFULNESS_THRESHOLD = 0.45   # Cevap-kaynak semantik benzerliği
    GROUNDING_THRESHOLD = 0.30      # Anahtar kelimelerin kaynakta bulunma oranı
    # v2.52.0: Refinement adımı cevabı zenginleştirdiği için oran artırıldı
    MAX_LENGTH_RATIO = 8.0          # Cevap / kaynak uzunluk oranı limiti
    
    # Türkçe stop words (grounding kontrolünde atlanacak)
    _STOP_WORDS = {
        'bir', 'bu', 've', 'de', 'da', 'ile', 'için', 'olan', 'olarak',
        'gibi', 'daha', 'en', 'çok', 'her', 'ya', 'veya', 'ama', 'ancak',
        'hem', 'ne', 'nasıl', 'neden', 'hangi', 'kadar', 'sonra', 'önce',
        'ayrıca', 'den', 'dan', 'nin', 'nın', 'nun', 'nün', 'dir', 'dır',
        'ise', 'olup', 'olan', 'var', 'yok', 'eder', 'yapar', 'olur',
        'the', 'is', 'are', 'and', 'or', 'of', 'to', 'in', 'on', 'at',
        'edilir', 'yapılır', 'sağlar', 'bulunur', 'yer', 'alır', 'şekilde',
        'olarak', 'üzerinden', 'tarafından', 'aracılığıyla', 'durumda'
    }
    
    def _validate_answer(self, answer: str, source_text: str, question: str,
                         lenient: bool = False) -> Dict[str, Any]:
        """
        LLM cevabının kaynağa sadık olup olmadığını 3 katmanlı kontrol ile doğrula.
        
        Katman 1: Semantik Sadakat (Faithfulness)
        Katman 2: Anahtar Kelime Temellendirme (Grounding)
        Katman 3: Uzunluk Oranı Kontrolü (Length Ratio)
        
        Args:
            lenient: True ise Enhance endpoint için düşük eşikler kullanılır.
                     LLM sentezi doğal olarak kaynak metinden farklı kelimeler
                     kullandığı için standart eşikler yanlış pozitif verir.
        
        Returns:
            {"passed": bool, "reason": str, "faithfulness": float, "grounding": float, "length_ratio": float}
        """
        result = {
            "passed": True,
            "reason": "",
            "faithfulness": 0.0,
            "grounding": 0.0,
            "length_ratio": 0.0
        }
        
        # v3.4.0: Enhance vs Learned QA eşik ayrımı
        if lenient:
            grounding_threshold = 0.10       # %10 — LLM sentez doğal parafraz yapar
            faithfulness_threshold = 0.25     # Düşük semantik benzerlik toleransı
            max_length_ratio = 15.0           # Sentez daha uzun olabilir
        else:
            grounding_threshold = self.GROUNDING_THRESHOLD      # 0.30
            faithfulness_threshold = self.FAITHFULNESS_THRESHOLD  # 0.45
            max_length_ratio = self.MAX_LENGTH_RATIO              # 8.0
        
        # === Katman 3: Uzunluk Oranı Kontrolü (en hızlı — ilk kontrol) ===
        source_len = len(source_text.strip())
        answer_len = len(answer.strip())
        
        if source_len > 0:
            length_ratio = answer_len / source_len
            result["length_ratio"] = length_ratio
            
            # v3.1.2: Dinamik eşik — kısa kaynak metinlerde (komut referansları,
            # tablo hücreleri, kısa açıklamalar) LLM doğal olarak daha uzun cevap üretir.
            if source_len < 200:
                effective_ratio = 30.0   # Çok kısa kaynak (komut satırları)
            elif source_len < 500:
                effective_ratio = 15.0   # Orta kaynak (kısa paragraflar)
            else:
                effective_ratio = max_length_ratio
            
            if length_ratio > effective_ratio:
                result["passed"] = False
                result["reason"] = f"length_ratio_exceeded ({length_ratio:.1f}x > {effective_ratio:.0f}x)"
                return result
        
        # === Katman 2: Anahtar Kelime Temellendirme ===
        grounding_score = self._check_keyword_grounding(answer, source_text)
        result["grounding"] = grounding_score
        
        # v3.1.2: Kısa kaynaklarda anahtar kelime havuzu küçük
        if source_len < 200:
            effective_grounding = 0.05   # Çok kısa kaynak
        elif source_len < 500:
            effective_grounding = 0.15   # Orta kaynak
        else:
            effective_grounding = grounding_threshold
        
        if grounding_score < effective_grounding:
            result["passed"] = False
            result["reason"] = f"low_grounding ({grounding_score:.1%} < {effective_grounding:.0%})"
            return result
        
        # === Katman 1: Semantik Sadakat (en pahalı — son kontrol) ===
        faithfulness = self._check_faithfulness(answer, source_text)
        result["faithfulness"] = faithfulness
        
        if faithfulness < faithfulness_threshold:
            result["passed"] = False
            result["reason"] = f"low_faithfulness ({faithfulness:.2f} < {faithfulness_threshold})"
            return result
        
        return result
    
    def _check_keyword_grounding(self, answer: str, source_text: str) -> float:
        """
        Cevaptaki anlamlı kelimelerin kaç tanesinin kaynak metinde geçtiğini kontrol et.
        
        Returns:
            Grounding oranı (0.0 - 1.0)
        """
        import re
        
        # Kelimeleri çıkar ve normalize et
        answer_words = set(
            w.lower() for w in re.findall(r'\b[a-zA-ZçğıöşüÇĞİÖŞÜ]{3,}\b', answer)
            if w.lower() not in self._STOP_WORDS
        )
        
        if not answer_words:
            return 1.0  # Anlamlı kelime yoksa geç
        
        source_lower = source_text.lower()
        
        # v3.4.0 FIX: Türkçe çekim eki toleransı — "sayımlar" → "sayım" kökü
        # Tam kelime eşleşmezse, son 2 karakter atılarak kök kırpma denenir
        def _is_grounded(word: str) -> bool:
            if word in source_lower:
                return True
            # Kök kırpma: 5+ char kelimelerde son 1-2 char atarak dene
            if len(word) >= 5:
                if word[:-1] in source_lower:
                    return True
                if word[:-2] in source_lower:
                    return True
            return False
        
        grounded = sum(1 for w in answer_words if _is_grounded(w))
        
        return grounded / len(answer_words)
    
    def _check_faithfulness(self, answer: str, source_text: str) -> float:
        """
        Cevap ve kaynak metni arasındaki semantik benzerliği ölç.
        
        Returns:
            Cosine similarity (0.0 - 1.0)
        """
        mgr = self._get_embedding_mgr()
        if mgr is None:
            return 1.0  # Model yoksa geç (güvenli taraf)
        
        try:
            answer_emb = mgr.get_embedding(answer[:500])
            source_emb = mgr.get_embedding(source_text[:500])
            similarity = float(np.dot(answer_emb, source_emb))
            return max(0.0, similarity)
        except Exception:
            return 1.0  # Hata varsa geç
    
    def get_stats(self) -> dict:
        """İstatistikler."""
        try:
            from app.core.db import get_db_conn
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    COUNT(*) as total,
                    COUNT(CASE WHEN embedding IS NOT NULL THEN 1 END) as with_embedding,
                    SUM(hit_count) as total_hits,
                    AVG(quality_score) as avg_quality
                FROM learned_answers
            """)
            row = cur.fetchone()
            cur.close()
            conn.close()
            
            if isinstance(row, dict):
                return {
                    "total_answers": row.get("total", 0),
                    "with_embedding": row.get("with_embedding", 0),
                    "total_hits": row.get("total_hits", 0) or 0,
                    "avg_quality": round(float(row.get("avg_quality", 0) or 0), 2)
                }
            else:
                return {
                    "total_answers": row[0] if row else 0,
                    "with_embedding": row[1] if row else 0,
                    "total_hits": row[2] or 0 if row else 0,
                    "avg_quality": round(float(row[3] or 0), 2) if row else 0
                }
        except Exception:
            return {"total_answers": 0, "with_embedding": 0, "total_hits": 0, "avg_quality": 0}


# Singleton
_learned_qa_service = None


def get_learned_qa_service() -> LearnedQAService:
    """Learned QA Service singleton döndürür."""
    global _learned_qa_service
    if _learned_qa_service is None:
        _learned_qa_service = LearnedQAService()
    return _learned_qa_service
