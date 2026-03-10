"""
VYRA ML Training - Synthetic Data Generator
=============================================
Chunk'lardan sentetik soru-cevap çiftleri üretir.
CatBoost'un proaktif eğitimi için kullanılır.

v2.32.0: Initial implementation
v2.44.0: LLM destekli soru üretimi, zengin metadata, hard negatives,
         gerçek quality_score/topic/heading kullanımı

Özellikler:
- Chunk'tan anahtar kelime çıkarma
- Intent bazlı soru şablonları (fallback)
- LLM destekli gerçekçi soru üretimi
- Hard negative örnekler (aynı topic farklı dosya)
- Gerçek chunk metadata'sı (heading, quality_score, topic_label)
"""

from __future__ import annotations

import re
import random
from typing import List, Dict, Any, Optional

from app.core.db import get_db_context
from app.services.logging_service import log_system_event, log_error, log_warning


# ============================================
# Soru Şablonları (Intent Bazlı — LLM fallback)
# ============================================

QUESTION_TEMPLATES = {
    "LIST_REQUEST": [
        "{keyword} nelerdir",
        "{keyword} listesi",
        "{keyword} çeşitleri nelerdir",
        "{keyword} komutları neler",
        "tüm {keyword} listele",
        "{keyword} hangileri",
    ],
    "HOW_TO": [
        "{keyword} nasıl yapılır",
        "{keyword} adımları nelerdir",
        "{keyword} kurulumu nasıl",
        "{keyword} ayarları nasıl yapılır",
        "{keyword} nasıl kullanılır",
    ],
    "TROUBLESHOOT": [
        "{keyword} sorunu nasıl çözülür",
        "{keyword} çalışmıyor",
        "{keyword} hata veriyor",
        "{keyword} bağlantı problemi",
        "{keyword} neden çalışmıyor",
    ],
    "SINGLE_ANSWER": [
        "{keyword} nedir",
        "{keyword} ne işe yarar",
        "{keyword} komutu ne yapar",
        "{keyword} açıklaması",
    ],
}

# Türkçe stop words
TURKISH_STOPWORDS = {
    've', 'veya', 'bir', 'bu', 'şu', 'için', 'ile', 'de', 'da',
    'mi', 'mı', 'mu', 'mü', 'nasıl', 'ne', 'neden', 'kim',
    'hangi', 'kaç', 'benim', 'var', 'yok', 'olarak', 'gibi',
    'daha', 'çok', 'az', 'her', 'tüm', 'bazı', 'hiç', 'ise',
    'olan', 'sonra', 'önce', 'arasında', 'üzerinde', 'altında',
}

# LLM soru üretim batch boyutu (her batch'te kaç chunk birden gönderilir)
LLM_BATCH_SIZE = 5


class SyntheticDataGenerator:
    """
    CatBoost proaktif eğitimi için sentetik soru-cevap çiftleri üretir.
    
    Pipeline:
    1. DB'den chunk'ları zengin metadata ile oku
    2. Her chunk'tan anahtar kelime çıkar
    3. LLM ile gerçekçi sorular üret (fallback: intent şablonları)
    4. Hard negative örnekler ekle (aynı topic farklı dosya)
    5. Gerçek metadata'yı (heading, quality_score, topic) eğitim verisine aktar

    v2.44.0: LLM desteği, zengin metadata, hard negatives
    """
    
    def __init__(self, max_chunks: int = 200, questions_per_chunk: int = 3,
                 use_llm: bool = True):
        self.max_chunks = max_chunks
        self.questions_per_chunk = questions_per_chunk
        self.use_llm = use_llm
        self._llm_success_count = 0
        self._llm_fallback_count = 0
    
    def generate_training_data(self) -> List[Dict[str, Any]]:
        """
        DB'deki chunk'lardan sentetik eğitim verisi üretir.
        
        Returns:
            [{
                "query": "VPN nasıl yapılır",
                "chunk_id": 42,
                "chunk_text": "VPN bağlantısı için...",
                "source_file": "vpn_guide.xlsx",
                "intent": "HOW_TO",
                "relevance_label": 1,
                "score": 0.82,
                "quality_score": 0.75,
                "topic_label": "vpn",
                "heading": "VPN Bağlantı Adımları"
            }, ...]
        """
        chunks = self._fetch_chunks()
        
        if not chunks:
            log_system_event("WARNING", "Sentetik veri üretimi: DB'de chunk bulunamadı", "ml_training")
            return []
        
        training_data = []
        
        # Topic bazlı chunk grupları oluştur (hard negatives için)
        topic_groups: Dict[str, List[Dict]] = {}
        for chunk in chunks:
            topic = chunk.get("topic_label") or "general"
            if topic not in topic_groups:
                topic_groups[topic] = []
            topic_groups[topic].append(chunk)
        
        # LLM batch üretimi
        llm_questions_map: Dict[int, List[Dict]] = {}
        if self.use_llm:
            llm_questions_map = self._generate_llm_questions_batch(chunks)
        
        for chunk in chunks:
            chunk_id = chunk["id"]
            content = chunk["content"]
            topic = chunk.get("topic_label") or "general"
            heading = chunk.get("heading") or ""
            quality_score = chunk.get("quality_score") or 0.5
            source_file = chunk.get("file_name") or ""
            
            # Soru üretimi: LLM varsa LLM, yoksa template
            if chunk_id in llm_questions_map and llm_questions_map[chunk_id]:
                questions = llm_questions_map[chunk_id]
            else:
                keywords = self._extract_keywords_from_chunk(content)
                if not keywords:
                    continue
                questions = self._generate_template_questions(keywords)
            
            # === POZİTİF ÖRNEKLER ===
            for q in questions[:self.questions_per_chunk]:
                # Gerçekçi skor çeşitlendirmesi: keyword overlap ile orantılı
                estimated_score = self._estimate_relevance_score(q["query"], content)
                
                # v2.52.0: Post-generation grounding — pozitif örnekte bile
                # chunk'la uyumluluğu kontrol et. Düşük uyumluyu negatife çevir.
                # Kök eşleştirme ile Türkçe çekim eki toleransı sağlanır.
                query_grounding = self._estimate_grounding(q["query"], content)
                
                # v2.52.1: Kısa chunk'larda (< 200 char, örn: Excel komut tablosu)
                # grounding doğal olarak düşük çıkar çünkü kelime havuzu küçük.
                # Eşiği chunk uzunluğuna göre dinamik ayarla.
                content_len = len(content)
                if content_len < 200:
                    grounding_threshold = 0.05  # Kısa chunk: çok düşük eşik
                elif content_len < 500:
                    grounding_threshold = 0.10  # Orta chunk
                else:
                    grounding_threshold = 0.15  # Normal chunk
                
                if query_grounding < grounding_threshold:
                    # Soru chunk'la yeterince ilişkili değil → negatif olarak ekle
                    # NOT: Orijinal intent korunuyor (zorla GENERAL yapılmıyor)
                    training_data.append({
                        "query": q["query"],
                        "chunk_id": chunk_id,
                        "chunk_text": content,
                        "source_file": source_file,
                        "intent": q.get("intent", "GENERAL"),
                        "relevance_label": 0,
                        "score": random.uniform(0.05, 0.25),
                        "quality_score": quality_score,
                        "topic_label": topic,
                        "heading": heading,
                    })
                    continue
                
                training_data.append({
                    "query": q["query"],
                    "chunk_id": chunk_id,
                    "chunk_text": content,
                    "source_file": source_file,
                    "intent": q.get("intent", "GENERAL"),
                    "relevance_label": 1,
                    "score": estimated_score,
                    "quality_score": quality_score,
                    "topic_label": topic,
                    "heading": heading,
                })
            
            if not questions:
                continue
            
            # === NEGATİF ÖRNEKLER ===
            query_for_neg = questions[0]["query"]
            
            # 1. Hard negative: Aynı topic, farklı dosyadan chunk
            hard_neg = self._pick_hard_negative(chunk, topic_groups.get(topic, []))
            if hard_neg:
                training_data.append({
                    "query": query_for_neg,
                    "chunk_id": hard_neg["id"],
                    "chunk_text": hard_neg["content"],
                    "source_file": hard_neg.get("file_name", ""),
                    "intent": "GENERAL",
                    "relevance_label": 0,
                    "score": random.uniform(0.05, 0.25),
                    "quality_score": hard_neg.get("quality_score") or 0.5,
                    "topic_label": hard_neg.get("topic_label") or "general",
                    "heading": hard_neg.get("heading") or "",
                })
            
            # 2. Easy negative: Farklı topic'ten chunk
            easy_neg = self._pick_easy_negative(chunk, topic, topic_groups)
            if easy_neg:
                training_data.append({
                    "query": query_for_neg,
                    "chunk_id": easy_neg["id"],
                    "chunk_text": easy_neg["content"],
                    "source_file": easy_neg.get("file_name", ""),
                    "intent": "GENERAL",
                    "relevance_label": 0,
                    "score": random.uniform(0.01, 0.15),
                    "quality_score": easy_neg.get("quality_score") or 0.5,
                    "topic_label": easy_neg.get("topic_label") or "general",
                    "heading": easy_neg.get("heading") or "",
                })
        
        log_system_event(
            "INFO", 
            f"Sentetik veri üretildi: {len(training_data)} örnek ({len(chunks)} chunk, "
            f"LLM: {self._llm_success_count} başarılı, {self._llm_fallback_count} fallback)", 
            "ml_training"
        )
        
        return training_data
    
    # ─────────────────────────────────────────
    # Chunk Fetch (Zengin Metadata)
    # ─────────────────────────────────────────
    
    def _fetch_chunks(self) -> List[Dict[str, Any]]:
        """
        DB'den chunk'ları zengin metadata ile çeker.
        quality_score, topic_label, heading, file_type bilgisi dahil.
        """
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT rc.id, 
                               rc.chunk_text AS content, 
                               uf.file_name,
                               uf.file_type,
                               rc.quality_score,
                               rc.topic_label,
                               rc.metadata->>'heading' AS heading
                        FROM rag_chunks rc
                        JOIN uploaded_files uf ON rc.file_id = uf.id
                        ORDER BY RANDOM()
                        LIMIT %s
                    """, (self.max_chunks,))
                    
                    return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            log_error(f"Sentetik veri: Chunk fetch hatası: {e}", "ml_training")
            return []
    
    # ─────────────────────────────────────────
    # LLM Destekli Soru Üretimi
    # ─────────────────────────────────────────
    
    def _generate_llm_questions_batch(
        self, chunks: List[Dict[str, Any]]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """
        LLM ile batch halinde gerçekçi sorular üretir.
        Her batch'te LLM_BATCH_SIZE chunk birden gönderilir.
        Başarısız olursa boş dict döner (template fallback devreye girer).
        
        Halüinasyon koruması: Üretilen sorular chunk içeriğiyle
        keyword overlap kontrolünden geçirilir.
        """
        result_map: Dict[int, List[Dict]] = {}
        
        # Chunk içeriklerini id bazlı sakla (validasyon için)
        chunk_content_map: Dict[int, str] = {
            c["id"]: (c.get("content") or "").lower()
            for c in chunks
        }
        
        # Chunk'ları batch'lere böl
        batches = []
        for i in range(0, len(chunks), LLM_BATCH_SIZE):
            batches.append(chunks[i:i + LLM_BATCH_SIZE])
        
        hallucination_count = 0
        
        for batch in batches:
            try:
                batch_results = self._call_llm_for_questions(batch)
                if batch_results:
                    # Halüinasyon filtresi: her soruyu chunk içeriğiyle dogrula
                    for chunk_id, questions in batch_results.items():
                        chunk_text = chunk_content_map.get(chunk_id, "")
                        validated = []
                        for q in questions:
                            if self._validate_question_relevance(q["query"], chunk_text):
                                validated.append(q)
                            else:
                                hallucination_count += 1
                        if validated:
                            result_map[chunk_id] = validated
                    
                    self._llm_success_count += len(result_map)
                else:
                    self._llm_fallback_count += len(batch)
            except Exception as e:
                log_warning(f"LLM soru üretimi batch hatası: {e}", "ml_training")
                self._llm_fallback_count += len(batch)
        
        if hallucination_count > 0:
            log_warning(
                f"LLM halüinasyon filtresi: {hallucination_count} soru elenip atıldı",
                "ml_training"
            )
        
        return result_map
    
    def _call_llm_for_questions(
        self, chunks: List[Dict[str, Any]]
    ) -> Optional[Dict[int, List[Dict]]]:
        """
        LLM'e chunk metinlerini gönderip gerçekçi sorular ürettirir.
        
        Returns:
            {chunk_id: [{"query": "...", "intent": "..."}, ...]}
        """
        try:
            from app.core.llm import call_llm_api
        except ImportError:
            log_warning("LLM API import edilemedi, template fallback", "ml_training")
            return None
        
        # Prompt oluştur
        chunk_texts = []
        chunk_id_map = {}
        
        for i, chunk in enumerate(chunks):
            chunk_id = chunk["id"]
            content = (chunk.get("content") or "")[:400]  # 400 char limit per chunk
            heading = chunk.get("heading") or ""
            source_file = chunk.get("file_name") or ""
            label = f"CHUNK_{i+1}"
            chunk_id_map[label] = chunk_id
            
            entry = f"[{label}]"
            if source_file:
                entry += f" Dosya: {source_file}"
            if heading:
                entry += f" | Başlık: {heading}"
            entry += f"\n{content}"
            chunk_texts.append(entry)
        
        chunks_block = "\n---\n".join(chunk_texts)
        
        prompt = f"""Aşağıdaki IT destek dokümanı parçalarını oku. Her parça için bir L1 destek kullanıcısının sorabileceği 2-3 gerçekçi Türkçe soru üret.

Kurallar:
- Her soruyu kısa tut (max 15 kelime)
- Gerçek kullanıcıların soracağı şekilde yaz (resmi değil, doğal dil)
- Her soru için intent belirt: HOW_TO, TROUBLESHOOT, LIST_REQUEST veya SINGLE_ANSWER
- KRİTİK: SADECE parçadaki bilgilere dayalı sorular üret. Parçada geçmeyen kavramları, ürünleri veya süreçleri ASLA sormayın.
- Parçada geçen teknik terimleri, komutları ve kavramları sorularda kullan.
- Her parçanın hangi dosyadan geldiği belirtilmiştir. Soruları o dosyanın konusuyla sınırlı tut.
- Dosya adı bir ipucudur: 'Komutlar.xlsx' ise komut soruları, 'VPN Kılavuzu.pdf' ise VPN soruları üret.

Format (her chunk için):
CHUNK_N:
- [INTENT] soru metni

Parçalar:
{chunks_block}"""
        
        messages = [
            {"role": "system", "content": "Sen bir IT destek eğitim verisi üretme asistanısın. Sadece istenen formatta cevap ver."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            response = call_llm_api(messages)
            if not response:
                return None
            
            return self._parse_llm_questions(response, chunk_id_map)
        except Exception as e:
            log_warning(f"LLM soru üretimi çağrı hatası: {e}", "ml_training")
            return None
    
    def _parse_llm_questions(
        self, response: str, chunk_id_map: Dict[str, int]
    ) -> Dict[int, List[Dict]]:
        """LLM cevabını parse ederek chunk_id bazlı soru listesine çevirir."""
        result: Dict[int, List[Dict]] = {}
        
        current_chunk_label = None
        valid_intents = {"HOW_TO", "TROUBLESHOOT", "LIST_REQUEST", "SINGLE_ANSWER", "GENERAL"}
        
        for line in response.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            
            # Chunk label satırı: "CHUNK_1:" veya "CHUNK_1"
            chunk_match = re.match(r'(CHUNK_\d+)\s*:', line)
            if chunk_match:
                current_chunk_label = chunk_match.group(1)
                continue
            
            # Soru satırı: "- [HOW_TO] VPN nasıl bağlanılır"
            if current_chunk_label and line.startswith("-"):
                question_match = re.match(r'-\s*\[(\w+)\]\s*(.+)', line)
                if question_match:
                    intent = question_match.group(1).upper()
                    query = question_match.group(2).strip()
                    
                    if intent not in valid_intents:
                        intent = "GENERAL"
                    
                    chunk_id = chunk_id_map.get(current_chunk_label)
                    if chunk_id is not None and len(query) >= 5:
                        if chunk_id not in result:
                            result[chunk_id] = []
                        result[chunk_id].append({
                            "query": query,
                            "intent": intent,
                        })
        
        return result
    
    def _validate_question_relevance(self, query: str, chunk_text_lower: str) -> bool:
        """
        LLM'in ürettiği sorunun chunk içeriğiyle gerçekten ilişkili olduğunu doğrular.
        Halüsinasyon koruması: soruda geçen anahtar kelimelerin en az %25'i
        chunk metninde geçmelidir.
        
        v2.52.0: Kök eşleştirme (stem matching) ile Türkçe çekim eki toleransı.
        
        Args:
            query: LLM'in ürettiği soru
            chunk_text_lower: Chunk metnin lowercase hali
            
        Returns:
            True = soru geçerli, False = muhtemel halüsinasyon
        """
        if not query or not chunk_text_lower:
            return False
        
        # Uzunluk kontrolü (çok kısa/uzun sorular şüpheli)
        if len(query) < 5 or len(query) > 150:
            return False
        
        # Sorgudan stop words hariç anlamlı kelimeleri çıkar
        query_words = set(query.lower().split())
        query_words -= TURKISH_STOPWORDS
        # Çok kısa kelimeleri de çıkar (< 3 karakter)
        meaningful_words = {w for w in query_words if len(w) >= 3}
        
        if not meaningful_words:
            # Sadece stop words'den oluşan soru — geçerli kabul et (nadir durum)
            return True
        
        # Chunk metninde kaç kelime geçiyor? (kök eşleştirme ile)
        matches = sum(1 for w in meaningful_words if self._stem_match(w, chunk_text_lower))
        overlap_ratio = matches / len(meaningful_words)
        
        # v2.52.0: Eşik %40 → %25 (kök eşleştirme sayesinde daha dengeli)
        return overlap_ratio >= 0.25
    
    # ─────────────────────────────────────────
    # Template Bazlı Soru Üretimi (Fallback)
    # ─────────────────────────────────────────
    
    def _generate_template_questions(self, keywords: List[str]) -> List[Dict[str, Any]]:
        """
        Anahtar kelimelerden intent bazlı sentetik sorular üretir (LLM fallback).
        """
        questions = []
        
        for keyword in keywords[:3]:
            intent = random.choice(list(QUESTION_TEMPLATES.keys()))
            templates = QUESTION_TEMPLATES[intent]
            template = random.choice(templates)
            
            query = template.format(keyword=keyword)
            
            questions.append({
                "query": query,
                "intent": intent,
            })
        
        self._llm_fallback_count += 1
        return questions
    
    # ─────────────────────────────────────────
    # Negatif Örnek Seçimi
    # ─────────────────────────────────────────
    
    def _pick_hard_negative(
        self, source_chunk: Dict, same_topic_chunks: List[Dict]
    ) -> Optional[Dict]:
        """
        Hard negative: Aynı topic ama farklı dosyadan chunk seç.
        Model'in sadece topic eşleşmesine güvenmesini önler.
        """
        source_file = source_chunk.get("file_name", "")
        source_id = source_chunk["id"]
        
        candidates = [
            c for c in same_topic_chunks
            if c["id"] != source_id and c.get("file_name", "") != source_file
        ]
        
        if not candidates:
            # Aynı dosyadan farklı chunk (fallback)
            candidates = [c for c in same_topic_chunks if c["id"] != source_id]
        
        return random.choice(candidates) if candidates else None
    
    def _pick_easy_negative(
        self, source_chunk: Dict, source_topic: str,
        topic_groups: Dict[str, List[Dict]]
    ) -> Optional[Dict]:
        """
        Easy negative: Tamamen farklı topic'ten chunk seç.
        Temel ayrım yeteneğini öğretir.
        """
        other_topics = [t for t in topic_groups if t != source_topic]
        
        if not other_topics:
            return None
        
        target_topic = random.choice(other_topics)
        candidates = topic_groups[target_topic]
        
        return random.choice(candidates) if candidates else None
    
    # ─────────────────────────────────────────
    # Yardımcı Fonksiyonlar
    # ─────────────────────────────────────────
    
    def _estimate_relevance_score(self, query: str, chunk_text: str) -> float:
        """
        Sorgu-chunk arasındaki tahmini benzerlik skoru.
        Keyword overlap'a göre gerçekçi bir skor üretir.
        """
        if not query or not chunk_text:
            return 0.5
        
        query_words = set(query.lower().split())
        chunk_words = set(chunk_text.lower().split())
        
        # Stop words çıkar
        query_words -= TURKISH_STOPWORDS
        
        if not query_words:
            return 0.6
        
        overlap = len(query_words & chunk_words) / len(query_words)
        
        # Skor: 0.55 (düşük overlap) - 0.95 (yüksek overlap) aralığında + noise
        base = 0.55 + (overlap * 0.35)
        noise = random.uniform(-0.05, 0.05)
        
        return round(min(max(base + noise, 0.5), 0.95), 2)
    
    def _estimate_grounding(self, query: str, chunk_text: str) -> float:
        """
        v2.52.0: Pozitif örnek post-generation grounding kontrolü.
        Sorudaki anlamlı kelimelerin chunk metninde geçme oranını ölçer.
        Kök eşleştirme ile Türkçe çekim eki toleransı sağlar.
        
        Returns:
            Grounding oranı (0.0 - 1.0). 0.15 altı = zayıf ilişki.
        """
        if not query or not chunk_text:
            return 0.0
        
        query_words = set(query.lower().split())
        query_words -= TURKISH_STOPWORDS
        meaningful = {w for w in query_words if len(w) >= 3}
        
        if not meaningful:
            return 1.0  # Sadece stop words → geçerli kabul
        
        chunk_lower = chunk_text.lower()
        matches = sum(1 for w in meaningful if self._stem_match(w, chunk_lower))
        
        return matches / len(meaningful)
    
    @staticmethod
    def _stem_match(word: str, text: str) -> bool:
        """
        v2.52.0: Türkçe çekim eki toleranslı kök eşleştirme.
        
        Kelimenin kökünü (ilk 4+ karakter) kullanarak substring araması yapar.
        Böylece 'sorgulama' kelimesi 'sorgula', 'sorgulanır' gibi çekimlerle eşleşir.
        
        Args:
            word: Aranacak kelime
            text: İçinde aranacak metin
            
        Returns:
            True = kelime veya kökü metinde bulundu
        """
        # 1. Tam kelime eşleşmesi
        if word in text:
            return True
        
        # 2. Kök eşleştirme — Türkçe çekim eki toleransı
        # Kelime uzunluğuna göre kök boyutu belirle
        if len(word) >= 7:
            stem = word[:5]  # 7+ char → 5 char kök
        elif len(word) >= 5:
            stem = word[:4]  # 5-6 char → 4 char kök
        else:
            stem = word[:3]  # 3-4 char → 3 char kök
        
        return stem in text
    
    def _extract_keywords_from_chunk(self, text: str) -> List[str]:
        """
        Chunk'tan eğitim için anahtar kelimeleri çıkarır.
        Teknik terimleri ve önemli kavramları önceliklendirir.
        """
        if not text:
            return []
        
        words = re.findall(r'\b\w+\b', text.lower())
        
        filtered = [w for w in words if len(w) >= 3 and w not in TURKISH_STOPWORDS]
        
        technical = []
        general = []
        
        for word in set(filtered):
            original_word = word
            if original_word.upper() in text:
                technical.append(original_word)
            else:
                general.append(original_word)
        
        keywords = technical[:5] + general[:5]
        
        return keywords[:8]
    
    def get_stats(self) -> Dict[str, Any]:
        """Sentetik veri üretim istatistikleri."""
        try:
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) as total FROM rag_chunks")
                    row = cur.fetchone()
                    chunk_count = row["total"] if row else 0
                    
                    return {
                        "total_chunks": chunk_count,
                        "max_chunks_per_run": self.max_chunks,
                        "questions_per_chunk": self.questions_per_chunk,
                        "use_llm": self.use_llm,
                        "estimated_training_samples": min(chunk_count, self.max_chunks) * (self.questions_per_chunk + 2),
                        "intent_types": list(QUESTION_TEMPLATES.keys()),
                        "llm_success_count": self._llm_success_count,
                        "llm_fallback_count": self._llm_fallback_count,
                    }
        except Exception as e:
            log_error(f"Sentetik veri get_stats DB hatası: {e}", "ml_training")
            return {"total_chunks": 0, "error": "DB bağlantı hatası"}
