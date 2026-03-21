"""
VYRA L1 Support API - RAG Service (PostgreSQL)
===============================================
PostgreSQL tabanlı vektör araması ile RAG sistemi.
Embedding'ler FLOAT[] olarak saklanır, benzerlik Python'da hesaplanır.
Transaction desteği ile güvenli işlemler.

Composition:
- EmbeddingManager: Model yükleme ve embedding üretimi
- scoring: Cosine, BM25, RRF, fuzzy matching fonksiyonları
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import json

from app.core.config import settings
from app.core.db import get_db_conn
from app.services.logging_service import log_system_event, log_error, log_warning
from app.services.rag.embedding import EmbeddingManager
from app.services.rag import scoring


@dataclass
class SearchResult:
    """Arama sonucu"""
    content: str
    source_file: str
    score: float
    chunk_id: int
    metadata: Dict[str, Any] = None


@dataclass
class SearchResponse:
    """Arama yanıtı"""
    results: List[SearchResult]
    total: int


class RAGService:
    """
    PostgreSQL tabanlı RAG Service.
    
    Özellikler:
    - Embedding'ler PostgreSQL FLOAT[] olarak saklanır
    - Cosine similarity Python'da hesaplanır
    - Transaction desteği ile atomik işlemler
    - 🚀 v2.28.0: ONNX backend ile hızlı model yükleme (fallback: PyTorch)
    - 🏗️ v2.30.0: Modüler mimari (EmbeddingManager + scoring)
    """
    
    def __init__(self):
        self._embedding_mgr = EmbeddingManager()
    
    # ── Backward-compatible delegations ──────────────────────────
    
    @property
    def _backend(self):
        return self._embedding_mgr.backend
    
    @_backend.setter
    def _backend(self, value):
        self._embedding_mgr.backend = value
    
    @property
    def _embedding_dim(self):
        return self._embedding_mgr._embedding_dim
    
    @property
    def embedding_model(self):
        """Embedding modelini lazy load eder (ONNX öncelikli, PyTorch fallback)"""
        return self._embedding_mgr.embedding_model
    
    def _get_embedding(self, text: str) -> List[float]:
        """Metin için embedding vektörü üretir (cache destekli)"""
        return self._embedding_mgr.get_embedding(text)
    
    def _get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Birden fazla metin için embedding üretir (batch)"""
        return self._embedding_mgr.get_embeddings_batch(texts)
    
    # ── Scoring delegations (backward-compat) ────────────────────
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        return scoring.cosine_similarity(vec1, vec2)
    
    def _bm25_score(self, query: str, document: str, avg_doc_len: float = 500, k1: float = 1.5, b: float = 0.75) -> float:
        return scoring.bm25_score(query, document, avg_doc_len, k1, b)
    
    def _reciprocal_rank_fusion(self, rankings: List[List[Dict]], k: int = 60) -> List[Dict]:
        return scoring.reciprocal_rank_fusion(rankings, k)
    
    def _normalize_scores(self, results: List[Dict], score_key: str = "score") -> List[Dict]:
        return scoring.normalize_scores(results, score_key)
    
    def _extract_keywords(self, text: str) -> List[str]:
        return scoring.extract_keywords(text)
    
    def _is_technical_term(self, term: str) -> bool:
        return scoring.is_technical_term(term)
    
    def _has_exact_query_match(self, query: str, chunk_text: str) -> bool:
        return scoring.has_exact_query_match(query, chunk_text)
    
    def _calculate_exact_match_bonus(self, query: str, chunk_text: str) -> float:
        return scoring.calculate_exact_match_bonus(query, chunk_text)
    
    def _calculate_fuzzy_boost(self, query_keywords: List[str], chunk_text: str) -> float:
        return scoring.calculate_fuzzy_boost(query_keywords, chunk_text)
    
    def _is_toc_chunk(self, text: str) -> bool:
        """
        🆕 v2.38.3: İçindekiler tablosu chunk'ı mı tespit et.
        
        TOC chunk'ları her anahtar kelimeyi içerdikleri için BM25'te
        aşırı yüksek skor alır ama kullanıcıya faydalı bilgi sağlamaz.
        
        Algılama kriterleri:
        - Yoğun '...' veya '…' deseni (sayfa numarası referansları)
        """
        import re
        if not text:
            return False
        # Yoğun nokta deseni sayısı (..... ile sayfa numaraları)
        dot_patterns = len(re.findall(r'\.{5,}', text))
        # Alternatif: tab veya boşluk ile ayrılmış sayfa numaraları
        page_refs = len(re.findall(r'\. {2,}\d{1,3}', text))
        
        # 5+ nokta deseni → kesinlikle TOC
        if dot_patterns >= 5:
            return True
        # 3+ nokta deseni + metin uzunluğunun büyük kısmı nokta
        if dot_patterns >= 3 and text.count('.') > len(text) * 0.15:
            return True
        # Sayfa referansları çok ise
        if page_refs >= 5:
            return True
        
        return False
    
    def _preprocess_query(self, query: str) -> str:
        """
        🆕 v2.38.3: Sorgu ön işleme — soru eklerini temizle.
        
        Türkçe soru ekleri ('nelerdir', 'nedir', 'nasıl yapılır' vb.)
        embedding benzerliğini bozar çünkü dokümanlarda bu kelimeler
        genellikle bulunmaz. Temizleme ile daha iyi eşleşme sağlanır.
        
        Returns:
            Temizlenmiş sorgu metni
        """
        import re
        if not query or not query.strip():
            return query if query is not None else ""
        
        # Türkçe soru kelimeleri ve ekleri
        question_patterns = [
            r'\b(nelerdir|nedir|nedır|nelerden|nelerde)\b',
            r'\b(nasıl yapılır|nasıl çalışır|nasıl kullanılır)\b',
            r'\b(neden|niçin|ne zaman|ne kadar)\b',
            r'\b(hangi|hangileri|hangisi|hangisini)\b',
            r'\b(kimdir|kimler|kimlere|kimleri)\b',
            r'\b(hakkında bilgi|hakkında|ile ilgili)\b',
            r'[?]',  # Soru işareti
        ]
        
        cleaned = query
        for pattern in question_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Fazla boşlukları temizle
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Eğer temizleme sonrası çok kısa kaldıysa orijinali kullan
        if len(cleaned) < 3:
            return query
        
        return cleaned
    
    def _calculate_quality_score(self, text: str, metadata: dict) -> float:
        """
        Chunk kalite skoru hesaplama (0.0 - 1.0).
        
        Kriterler:
        - Uzunluk: 200-2000 karakter ideal (0-0.5)
        - Heading: başlık varsa +0.15
        - Cümle bütünlüğü: nokta ile bitiyorsa +0.2
        - Tablo: tablo satırı ise +0.15
        - v2.38.3: TOC chunk cezası
        - v2.43.0: Heading hiyerarşi bonusu, dil karışıklığı cezası
        """
        score = 0.0
        text_len = len(text.strip())
        
        # 1. Uzunluk skoru (0-0.5)
        if text_len < 50:
            score += 0.05
        elif text_len < 200:
            score += 0.15
        elif text_len <= 2000:
            # 200-2000 arası ideal → 0.3-0.5 arası lineer
            score += 0.3 + 0.2 * min(1.0, (text_len - 200) / 1800)
        else:
            score += 0.25  # Çok uzun → ideal değil
        
        # 2. Heading varlığı (+0.15)
        heading = metadata.get("heading", "") if isinstance(metadata, dict) else ""
        if heading and heading.strip():
            score += 0.15
        
        # 3. Cümle bütünlüğü (+0.2)
        stripped = text.strip()
        if stripped and stripped[-1] in '.!?:':
            score += 0.2
        elif stripped and stripped[-1] in ',;':
            score += 0.05  # Kısmi bütünlük
        
        # 4. Tablo bonusu (+0.15)
        content_type = metadata.get("type", "") if isinstance(metadata, dict) else ""
        if content_type == "table_row":
            score += 0.15
        elif content_type == "paragraph":
            score += 0.05
        
        # 5. v2.43.0: Heading hiyerarşi bonusu (+0.1)
        heading_path = metadata.get("heading_path", []) if isinstance(metadata, dict) else []
        if len(heading_path) >= 2:
            score += 0.1  # Heading hiyerarşisi korunmuş
        elif len(heading_path) == 1:
            score += 0.05
        
        # 6. v2.38.3 + v2.43.0: TOC cezası (-0.3)
        if content_type == "toc":
            score -= 0.3
        
        # 7. v2.43.0: Dil karışıklığı cezası (-0.1)
        if text_len > 100:
            import re
            tr_chars = len(re.findall(r'[çğıöşüÇĞİÖŞÜ]', text))
            en_words = len(re.findall(r'\b(?:the|and|is|are|was|for|with|this|that)\b', text, re.IGNORECASE))
            # Hem Türkçe karakter hem İngilizce kelime varsa → karışık
            if tr_chars > 5 and en_words > 3:
                score -= 0.1
        
        # 8. v2.43.0: Bilgi yoğunluğu — keyword density + entity sayısı
        if text_len > 50:
            words = stripped.split()
            total_words = len(words)
            if total_words > 5:
                # 8a. Keyword diversity: unique kelime oranı
                unique_words = len(set(w.lower() for w in words if len(w) > 2))
                diversity_ratio = unique_words / total_words
                if diversity_ratio > 0.7:
                    score += 0.1   # Çeşitli kelime dağarcığı → bilgi zengin
                elif diversity_ratio < 0.3:
                    score -= 0.05  # Tekrarlı → düşük bilgi değeri
                
                # 8b. Entity density: büyük harfle başlayan kelimeler (basit NER)
                entities = sum(1 for w in words if w[0].isupper() and len(w) > 2)
                entity_ratio = entities / total_words
                if entity_ratio > 0.15:
                    score += 0.05  # Yüksek entity yoğunluğu
        
        # 9. v2.43.0: Bağlam bütünlüğü — heading ile içerik keyword overlap
        if heading and heading.strip() and text_len > 30:
            heading_words = set(
                w.lower() for w in heading.strip().split()
                if len(w) > 2
            )
            if heading_words:
                text_lower = text.lower()
                matches = sum(1 for hw in heading_words if hw in text_lower)
                overlap_ratio = matches / len(heading_words)
                if overlap_ratio >= 0.5:
                    score += 0.1   # İçerik heading'le güçlü ilişkili
                elif overlap_ratio == 0:
                    score -= 0.05  # İçerik heading'le hiç ilişkisiz
        
        return round(max(0.1, min(1.0, score)), 3)
    
    # v2.43.0: Chunk deduplication — aynı/benzer içerikli chunk tespiti
    DEDUP_SIMILARITY_THRESHOLD = 0.95
    
    def _deduplicate_chunks(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]]
    ) -> set:
        """
        Aynı/benzer içerikli chunk'ları tespit eder.
        
        v2.43.0: Cosine similarity ile duplicate detection.
        Threshold 0.95+ → duplicate olarak işaretle.
        
        Args:
            chunks: Chunk listesi
            embeddings: Embedding vektörleri
            
        Returns:
            set of indices to remove (kaldırılacak chunk index'leri)
        """
        if len(chunks) < 2:
            return set()
        
        import math
        
        def _cosine_sim(a: List[float], b: List[float]) -> float:
            """İki vektör arası cosine similarity."""
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)
        
        to_remove = set()
        
        # O(n²) — dosya içi chunk sayısı genelde <500, bu yeterli
        for i in range(len(chunks)):
            if i in to_remove:
                continue
            for j in range(i + 1, len(chunks)):
                if j in to_remove:
                    continue
                
                # Hızlı ön-filtre: metin uzunluğu çok farklıysa atla
                len_i = len(chunks[i]["text"])
                len_j = len(chunks[j]["text"])
                if abs(len_i - len_j) > max(len_i, len_j) * 0.3:
                    continue
                
                sim = _cosine_sim(embeddings[i], embeddings[j])
                if sim >= self.DEDUP_SIMILARITY_THRESHOLD:
                    # Daha kısa olanı kaldır (daha az bilgi içerir)
                    if len_i >= len_j:
                        to_remove.add(j)
                    else:
                        to_remove.add(i)
                        break  # i kaldırıldı, inner loop'tan çık
        
        return to_remove
    
    # 🆕 v2.43.0: Cross-file duplicate detection — farklı dosyalardaki aynı içerik
    CROSS_FILE_DEDUP_LIMIT = 1000  # Performans limiti
    
    def _cross_file_deduplicate(
        self,
        chunks: List[Dict[str, Any]],
        embeddings: List[List[float]],
        file_id: int
    ) -> set:
        """
        Farklı dosyalardaki duplicate chunk'ları tespit eder.
        
        DB'deki mevcut chunk embedding'leri ile yeni chunk'ları karşılaştırır.
        Performans için son CROSS_FILE_DEDUP_LIMIT chunk ile sınırlıdır.
        
        Args:
            chunks: Yeni chunk listesi
            embeddings: Yeni chunk embedding'leri
            file_id: Mevcut dosya ID (aynı dosya hariç tutulur)
            
        Returns:
            set of indices to skip (atlanacak yeni chunk index'leri)
        """
        if not chunks or not embeddings:
            return set()
        
        try:
            conn = get_db_conn()
            cur = conn.cursor()
            
            # Aynı dosya hariç, en son eklenen N chunk'ın embedding + text length'ini çek
            cur.execute("""
                SELECT rc.id, rc.embedding, LENGTH(rc.chunk_text) as text_len
                FROM rag_chunks rc
                WHERE rc.file_id != %s
                  AND rc.embedding IS NOT NULL
                ORDER BY rc.id DESC
                LIMIT %s
            """, (file_id, self.CROSS_FILE_DEDUP_LIMIT))
            
            existing_rows = cur.fetchall()
            cur.close()
            conn.close()
            
            if not existing_rows:
                return set()
            
            import math
            
            def _cosine_sim(a, b):
                dot = sum(x * y for x, y in zip(a, b))
                norm_a = math.sqrt(sum(x * x for x in a))
                norm_b = math.sqrt(sum(x * x for x in b))
                if norm_a == 0 or norm_b == 0:
                    return 0.0
                return dot / (norm_a * norm_b)
            
            to_skip = set()
            
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                if i in to_skip:
                    continue
                
                new_len = len(chunk["text"])
                
                for row in existing_rows:
                    existing_emb = row["embedding"]
                    existing_len = row["text_len"] or 0
                    
                    # Hızlı ön-filtre: metin uzunluğu çok farklıysa atla
                    if abs(new_len - existing_len) > max(new_len, existing_len) * 0.3:
                        continue
                    
                    # Embedding tipini kontrol et (DB'den string/list gelebilir)
                    if isinstance(existing_emb, str):
                        try:
                            existing_emb = json.loads(existing_emb)
                        except (json.JSONDecodeError, TypeError):
                            continue
                    
                    if not existing_emb or len(existing_emb) != len(emb):
                        continue
                    
                    sim = _cosine_sim(emb, existing_emb)
                    if sim >= self.DEDUP_SIMILARITY_THRESHOLD:
                        to_skip.add(i)
                        break  # Bu chunk zaten duplicate, diğer existing'lerle karşılaştırmaya gerek yok
            
            return to_skip
            
        except Exception as e:
            log_warning(f"Cross-file dedup hatası: {e}", "rag")
            return set()  # Hata durumunda dedup atlansın, chunk'lar yine de eklensin
    
    # ── CRUD operations ──────────────────────────────────────────
    
    # 🆕 v2.42.0: Batch embedding size — büyük dosyalarda memory yönetimi
    EMBEDDING_BATCH_SIZE = 50
    
    def add_chunks_with_embeddings(
        self,
        file_id: int,
        chunks: List[Dict[str, Any]],
        cursor=None
    ) -> int:
        """
        Chunk'ları embedding'leriyle birlikte veritabanına ekler.
        Transaction ile atomik işlem.
        
        v2.42.0: Batch embedding desteği — 50'şerli batch'ler ile memory yönetimi.
        v2.43.0: Chunk deduplication — cosine similarity 0.95+ threshold.
        
        Args:
            file_id: Dosya ID
            chunks: [{"text": "...", "metadata": {...}}, ...]
            cursor: Opsiyonel - dışarıdan connection için cursor (commit yapılmaz)
        
        Returns:
            Eklenen chunk sayısı
        """
        if not chunks:
            return 0
        
        # 🆕 v2.42.0: Embedding'leri batch'ler halinde üret (memory-safe)
        batch_size = self.EMBEDDING_BATCH_SIZE
        all_embeddings: List[List[float]] = []
        
        for i in range(0, len(chunks), batch_size):
            batch_texts = [c["text"] for c in chunks[i:i + batch_size]]
            batch_embeddings = self._get_embeddings_batch(batch_texts)
            all_embeddings.extend(batch_embeddings)
            
            if len(chunks) > batch_size:
                log_system_event(
                    "DEBUG",
                    f"Embedding batch {i // batch_size + 1}/{(len(chunks) + batch_size - 1) // batch_size} "
                    f"tamamlandı (dosya {file_id})",
                    "rag"
                )
        
        embeddings = all_embeddings
        
        # 🆕 v2.43.0 Faz 7: Chunk Deduplication (cosine similarity)
        dedup_indices = self._deduplicate_chunks(chunks, embeddings)
        if dedup_indices:
            original_count = len(chunks)
            chunks = [chunks[i] for i in range(len(chunks)) if i not in dedup_indices]
            embeddings = [embeddings[i] for i in range(len(embeddings)) if i not in dedup_indices]
            log_system_event(
                "INFO",
                f"Dedup: {len(dedup_indices)} duplicate chunk kaldırıldı ({original_count} → {len(chunks)}) dosya {file_id}",
                "rag"
            )
        
        # 🆕 v2.43.0: Cross-file Duplicate Detection
        cross_dedup_indices = self._cross_file_deduplicate(chunks, embeddings, file_id)
        if cross_dedup_indices:
            pre_count = len(chunks)
            chunks = [chunks[i] for i in range(len(chunks)) if i not in cross_dedup_indices]
            embeddings = [embeddings[i] for i in range(len(embeddings)) if i not in cross_dedup_indices]
            log_system_event(
                "INFO",
                f"Cross-file dedup: {len(cross_dedup_indices)} chunk atlandı ({pre_count} → {len(chunks)}) dosya {file_id}",
                "rag"
            )
        
        # Dışarıdan cursor geldi mi kontrol et
        external_cursor = cursor is not None
        conn = None
        
        if not external_cursor:
            conn = get_db_conn()
            cursor = conn.cursor()
        
        try:
            # Önce eski chunk'ları sil
            cursor.execute("DELETE FROM rag_chunks WHERE file_id = %s", (file_id,))
            
            # Yeni chunk'ları ekle
            for idx, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                metadata = chunk.get("metadata", {})
                
                # 🆕 v2.37.1: Quality score hesaplama
                q_score = self._calculate_quality_score(chunk["text"], metadata)
                
                cursor.execute(
                    """
                    INSERT INTO rag_chunks (file_id, chunk_index, chunk_text, embedding, metadata, quality_score)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (file_id, idx, chunk["text"], embedding, json.dumps(metadata), q_score)
                )
            
            # Dosyanın chunk sayısını güncelle
            cursor.execute(
                "UPDATE uploaded_files SET chunk_count = %s WHERE id = %s",
                (len(chunks), file_id)
            )
            
            # Sadece kendi açtığımız connection için commit yap
            if not external_cursor and conn:
                conn.commit()
            
            # 🚀 v2.30.1: Yeni chunk eklenince RAG cache'i temizle
            try:
                from app.core.cache import cache_service
                cache_service.query.clear()
                log_system_event("DEBUG", f"RAG query cache temizlendi (dosya {file_id} güncellendi)", "rag")
            except Exception as e:
                log_warning(f"RAG query cache temizleme hatası: {e}", "rag")
            
            log_system_event("INFO", f"Dosya {file_id} için {len(chunks)} chunk eklendi", "rag")
            return len(chunks)
            
        except Exception as e:
            if not external_cursor and conn:
                conn.rollback()
            log_error(f"Chunk ekleme hatası: {str(e)}", "rag", error_detail=str(e))
            raise
        finally:
            if not external_cursor and conn:
                conn.close()
    
    # ── Search ───────────────────────────────────────────────────
    
    def search(
        self,
        query: str,
        n_results: int = 5,
        min_score: float = 0.3,
        user_id: Optional[int] = None,  # 🔒 ORG FILTERING İÇİN
        use_reranking: bool = True,  # 🚀 CatBoost Reranking
        max_per_file: Optional[int] = 2  # 🆕 v2.28.0: None = sınırsız (liste sorguları için)
    ) -> SearchResponse:
        """
        Semantik arama yapar + CatBoost reranking (hibrit model).
        
        🔒 GÜVENLİK: user_id verilirse, sadece kullanıcının yetkili olduğu 
        organizasyon gruplarındaki dokümanlar aranır.
        
        🚀 RERANKING: CatBoost modeli aktifse, geniş arama yapılıp sonuçlar
        kişiselleştirilmiş şekilde yeniden sıralanır.
        
        Args:
            query: Arama sorgusu
            n_results: Maksimum sonuç sayısı
            min_score: Minimum benzerlik skoru (0-1)
            user_id: Kullanıcı ID (org filtering için)
            use_reranking: CatBoost reranking kullan
            max_per_file: Aynı dosyadan max sonuç (None=sınırsız, liste sorguları için)
        
        Returns:
            SearchResponse
        """
        import time
        import hashlib
        timings = {}
        start_total = time.time()
        
        # 🚀 v2.30.1: Query Result Cache (5 dakika TTL)
        from app.core.cache import cache_service
        cache_key = f"rag_search:{hashlib.md5(f'{query}:{user_id}:{n_results}:{min_score}:{max_per_file}'.encode()).hexdigest()}"
        cached_response = cache_service.query.get(cache_key)
        if cached_response is not None:
            elapsed = round((time.time() - start_total) * 1000, 1)
            log_system_event("DEBUG", f"RAG CACHE HIT: '{query[:30]}' - {cached_response.total} sonuç ({elapsed}ms)", "rag")
            return cached_response
        
        # 🚀 CatBoost reranking için daha geniş arama yap
        search_limit = n_results * 4 if use_reranking else n_results  # 20 vs 5
        
        # 🚀 v2.32.0: Paralel Embedding + DB Query
        # Embedding hesaplama ve DB sorgusu birbirinden bağımsız → concurrent
        from concurrent.futures import ThreadPoolExecutor
        
        def _compute_embedding():
            # 🆕 v2.38.3: Temizlenmiş sorgu ile embedding üret
            cleaned_query = self._preprocess_query(query)
            if cleaned_query != query:
                log_system_event("DEBUG", f"RAG query preprocessed: '{query}' → '{cleaned_query}'", "rag")
            return self._get_embedding(cleaned_query)
        
        def _fetch_db_rows():
            _conn = get_db_conn()
            try:
                _cur = _conn.cursor()
                
                # 🆕 v2.34.0: Dinamik LIMIT — chunk sayısına göre ölçeklenir
                # Max 5000 cap ile tüm chunk havuzu aranabilir
                _cur.execute("SELECT COUNT(*) as cnt FROM rag_chunks WHERE embedding IS NOT NULL")
                _total_chunks = _cur.fetchone()["cnt"]
                _dynamic_limit = min(max(_total_chunks, 500), 5000)  # min 500, max 5000
                
                # 🔒 ORG FILTERING QUERY
                if user_id:
                    _cur.execute("""
                        SELECT uo.org_id 
                        FROM user_organizations uo
                        JOIN organization_groups o ON uo.org_id = o.id
                        JOIN users u ON uo.user_id = u.id
                        WHERE uo.user_id = %s 
                          AND o.is_active = true
                          AND u.is_approved = true
                    """, (user_id,))
                    _user_org_rows = _cur.fetchall()
                    _user_org_ids = [row['org_id'] for row in _user_org_rows]
                    
                    if _user_org_ids:
                        _placeholders = ','.join(['%s'] * len(_user_org_ids))
                        _query_sql = f"""
                            SELECT rc.id, rc.chunk_text, rc.embedding, rc.metadata, uf.file_name, uf.file_type
                            FROM rag_chunks rc
                            JOIN uploaded_files uf ON rc.file_id = uf.id
                            WHERE rc.embedding IS NOT NULL
                            AND (
                                EXISTS (
                                    SELECT 1 FROM document_organizations doc_org
                                    JOIN organization_groups o ON doc_org.org_id = o.id
                                    WHERE doc_org.file_id = uf.id
                                    AND doc_org.org_id IN ({_placeholders})
                                    AND o.is_active = true
                                )
                                OR NOT EXISTS (
                                    SELECT 1 FROM document_organizations doc_org2
                                    WHERE doc_org2.file_id = uf.id
                                )
                            )
                            ORDER BY rc.id
                            LIMIT %s
                        """
                        _cur.execute(_query_sql, _user_org_ids + [_dynamic_limit])
                    else:
                        _cur.execute("""
                            SELECT rc.id, rc.chunk_text, rc.embedding, rc.metadata, uf.file_name, uf.file_type
                            FROM rag_chunks rc
                            JOIN uploaded_files uf ON rc.file_id = uf.id
                            LEFT JOIN document_organizations doc_org ON uf.id = doc_org.file_id
                            WHERE rc.embedding IS NOT NULL
                            AND doc_org.file_id IS NULL
                            ORDER BY rc.id
                            LIMIT %s
                        """, (_dynamic_limit,))
                else:
                    _cur.execute("""
                        SELECT rc.id, rc.chunk_text, rc.embedding, rc.metadata, uf.file_name, uf.file_type
                        FROM rag_chunks rc
                        JOIN uploaded_files uf ON rc.file_id = uf.id
                        WHERE rc.embedding IS NOT NULL
                        ORDER BY rc.id
                        LIMIT %s
                    """, (_dynamic_limit,))
                
                return _cur.fetchall()
            finally:
                _conn.close()
        
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=2) as executor:
            emb_future = executor.submit(_compute_embedding)
            rows_future = executor.submit(_fetch_db_rows)
            query_embedding = emb_future.result()
            rows = rows_future.result()
        timings["embedding"] = time.time() - t0
        
        if not rows:
            # ⏱️ Timing logu (boş sonuç)
            timings["total"] = time.time() - start_total
            log_system_event(
                "DEBUG", 
                f"RAG: '{query[:40]}' - 0 sonuç (DB boş) | ⏱️ emb:{timings['embedding']:.2f}s total:{timings['total']:.2f}s",
                "rag"
            )
            return SearchResponse(results=[], total=0)
        
        # 🆕 v2.25.0 BEST PRACTICE: Hybrid Search (Vector + BM25)
        # =========================================================
        
        # 🚀 v2.32.0: NumPy Vectorized Batch Scoring
        # Tüm embedding'leri tek seferde hesapla (100x hız artışı)
        valid_rows = [r for r in rows if r["embedding"]]
        
        if not valid_rows:
            timings["total"] = time.time() - start_total
            log_system_event("DEBUG", f"RAG: '{query[:40]}' - 0 sonuç (embedding yok) | ⏱️ total:{timings['total']:.2f}s", "rag")
            return SearchResponse(results=[], total=0)
        
        t1 = time.time()
        
        # Batch cosine similarity (tek matris çarpımı)
        all_embeddings = [r["embedding"] for r in valid_rows]
        semantic_scores = scoring.cosine_similarity_batch(query_embedding, all_embeddings)
        
        # BM25 skorları
        all_texts = [r["chunk_text"] for r in valid_rows]
        bm25_scores_list = [scoring.bm25_score(query, text) for text in all_texts]
        
        timings["scoring"] = time.time() - t1
        
        # 1️⃣ Vector Search sonuçları
        vector_results = []
        # 2️⃣ BM25 (Keyword) sonuçları  
        bm25_results = []
        
        for idx, row in enumerate(valid_rows):
            semantic_score = semantic_scores[idx]
            bm25_score_val = bm25_scores_list[idx]
            
            # 🆕 v2.38.3: TOC chunk tespiti — BM25 skoruna %70 ceza
            is_toc = self._is_toc_chunk(row["chunk_text"])
            if is_toc:
                bm25_score_val *= 0.3  # TOC chunk'lar keyword eşleşmesinden ceza alır
            
            base_result = {
                "id": row["id"],
                "content": row["chunk_text"],
                "source_file": row["file_name"],
                "file_type": row.get("file_type", ""),
                "metadata": row["metadata"],
                "is_toc": is_toc  # 🆕 Metadata olarak taşı
            }
            
            # Vector ranking için
            vector_result = {**base_result, "score": semantic_score}
            vector_results.append(vector_result)
            
            # BM25 ranking için
            bm25_result = {**base_result, "score": bm25_score_val, "bm25_score": bm25_score_val}
            bm25_results.append(bm25_result)

        
        # Vector ve BM25 sonuçlarını sırala
        vector_results.sort(key=lambda x: x["score"], reverse=True)
        bm25_results.sort(key=lambda x: x["score"], reverse=True)
        
        # 3️⃣ Reciprocal Rank Fusion (RRF)
        # Best practice: Vector + BM25 ranking'leri birleştir
        fused_results = scoring.reciprocal_rank_fusion([vector_results[:50], bm25_results[:50]])
        
        # 4️⃣ Final skor hesaplama - MULTIPLICATIVE (not additive!)
        # =========================================================
        scored_results = []
        for item in fused_results:
            chunk_id = item["id"]
            
            # Orijinal skorları bul
            v_item = next((v for v in vector_results if v["id"] == chunk_id), None)
            b_item = next((b for b in bm25_results if b["id"] == chunk_id), None)
            
            semantic_score = v_item["score"] if v_item else 0.0
            bm25_score_val = b_item["bm25_score"] if b_item else 0.0
            
            # 🆕 MULTIPLICATIVE FORMULA (Best Practice)
            # Semantic score ana bileşen, BM25 çarpan olarak
            # Bu sayede %100 satürasyonu önlenir
            if semantic_score > 0:
                bm25_boost = 1.0 + (bm25_score_val * 0.3)  # 1.0 - 1.3 arası çarpan
                final_score = semantic_score * bm25_boost
            else:
                final_score = bm25_score_val * 0.5  # Sadece BM25 varsa düşük skor
            
            # 🆕 v2.38.3: TOC chunk cezası — final skora %50 azaltma
            # TOC chunk'lar hem semantic hem BM25'te yüksek skor alır (her kelimeyi içerir)
            # Bu ceza sayesinde asıl içerik chunk'ları öne çıkar
            is_toc = item.get("is_toc", False)
            if is_toc:
                final_score *= 0.5  # %50 ceza
            
            # 🆕 v2.29.1: Exact match bonus - sorgu chunk'ta TAMAMEN geçiyorsa boost ver
            is_exact_match = scoring.has_exact_query_match(query, item["content"])
            if is_exact_match:
                # TOC chunk'lara exact match bonus verme — zaten her kelimeyi içeriyorlar
                if not is_toc:
                    final_score = final_score * 1.4  # %40 bonus
            
            if final_score >= min_score:
                scored_results.append({
                    "id": chunk_id,
                    "content": item["content"],
                    "source_file": item["source_file"],
                    "file_type": item.get("file_type", ""),
                    "score": final_score,
                    "semantic_score": semantic_score,
                    "bm25_score": bm25_score_val,
                    "rrf_score": item.get("rrf_score", 0),
                    "is_exact_match": is_exact_match,  # Metadata olarak
                    "metadata": item.get("metadata")
                })
        
        # 5️⃣ Akıllı Normalizasyon
        # v2.53.1: Tek sonuçta ham skor korunur (eski: 1.0 yapılırdı)
        scored_results = scoring.normalize_scores(scored_results, "score")
        
        # Normalize edilmiş skorla kendi score'u güncelle
        for r in scored_results:
            r["original_score"] = r["score"]
            r["score"] = r.get("score_normalized", r["score"])
        
        # 🆕 v2.53.1: MUTLAK MİNİMUM HAM SKOR FİLTRESİ
        # Normalizasyon sonrasında bile, ham skoru (original_raw_score) düşük olan
        # sonuçları ele. Bu, anlamsız sorgularda sahte yüksek skor gösterilmesini önler.
        ABSOLUTE_MIN_RAW_SCORE = 0.42  # Ham hibrit skor alt sınırı
        pre_filter_count = len(scored_results)
        scored_results = [
            r for r in scored_results 
            if r.get("original_raw_score", r.get("original_score", 0)) >= ABSOLUTE_MIN_RAW_SCORE
        ]
        if len(scored_results) < pre_filter_count:
            log_system_event(
                "INFO", 
                f"Ham skor filtresi: {pre_filter_count - len(scored_results)} sonuç elendi "
                f"(eşik: {ABSOLUTE_MIN_RAW_SCORE}, kalan: {len(scored_results)})",
                "rag"
            )
        
        # 6️⃣ DIVERSITY FILTERING
        # 🆕 v2.28.0: max_per_file=None ise filtreleme atlanır (liste sorguları için)
        if max_per_file is not None:
            file_counts = {}
            diverse_results = []
            
            # Önce skora göre sırala
            scored_results.sort(key=lambda x: x["score"], reverse=True)
            
            for result in scored_results:
                source = result["source_file"]
                current_count = file_counts.get(source, 0)
                
                if current_count < max_per_file:
                    diverse_results.append(result)
                    file_counts[source] = current_count + 1
            
            scored_results = diverse_results
        else:
            # Liste sorguları için - sadece sırala, filtre yok
            scored_results.sort(key=lambda x: x["score"], reverse=True)
        
        # 🚀 CatBoost Reranking
        reranking_applied = False
        if use_reranking and len(scored_results) > 0:
            try:
                from app.services.catboost_service import get_catboost_service
                catboost_service = get_catboost_service()
                
                if catboost_service.is_ready():
                    # CatBoost ile yeniden sırala
                    reranked = catboost_service.rerank_results(
                        scored_results[:search_limit],  # Geniş havuzdan rerank
                        user_id,
                        query
                    )
                    scored_results = reranked
                    reranking_applied = True
                    log_system_event("DEBUG", f"CatBoost reranking uygulandı: {len(reranked)} sonuç", "rag")
            except Exception as e:
                # CatBoost hatası durumunda mevcut davranışa fallback
                log_system_event("WARNING", f"CatBoost reranking atlandı: {e}", "rag")
        
        # Final sonuçları limitle
        top_results = scored_results[:n_results]
        
        # 🎯 Ardışık skor farkı filtreleme: Her seçenek bir öncekiyle max N puan fark olabilir
        # 🔧 v2.38.3: Eşik 10→25 — TOC fix + normalizasyon sonrası daha fazla sonuç geçsin
        SCORE_GAP_THRESHOLD = 25  # Ardışık puan farkı eşiği (yüzde olarak)
        HIGH_SCORE_BYPASS = 0.65  # Bu skorun üzerindeki sonuçlar filtreden muaf
        
        if top_results:
            score_key = "combined_score" if reranking_applied else "score"
            filtered_results = [top_results[0]]  # İlk sonuç her zaman dahil
            
            for i in range(1, len(top_results)):
                curr_score_raw = top_results[i].get(score_key, 0)
                
                # 🔧 v2.21.2: Yüksek skorlu sonuçları filtreden muaf tut
                if curr_score_raw >= HIGH_SCORE_BYPASS:
                    filtered_results.append(top_results[i])
                    continue
                
                # Skorları 100 ile çarparak puan olarak al (0.60 → 60)
                prev_score = filtered_results[-1].get(score_key, 0) * 100
                curr_score = curr_score_raw * 100
                gap = prev_score - curr_score
                
                if gap <= SCORE_GAP_THRESHOLD:
                    filtered_results.append(top_results[i])
                else:
                    # Fark aşıldı, bu ve sonraki sonuçları atla
                    log_system_event("DEBUG", f"Skor farkı: {prev_score:.1f} - {curr_score:.1f} = {gap:.1f} > {SCORE_GAP_THRESHOLD}pt, elendi", "rag")
                    break
            
            # Filtreleme sonucu log
            if len(filtered_results) < len(top_results):
                log_system_event("INFO", f"Skor farkı filtresi: {len(top_results) - len(filtered_results)} sonuç elendi (eşik: {SCORE_GAP_THRESHOLD}pt, bypass: {HIGH_SCORE_BYPASS*100:.0f}%)", "rag")
            
            top_results = filtered_results
        
        results = [
            SearchResult(
                chunk_id=r.get("id") or r.get("chunk_id", 0),
                content=r.get("content") or r.get("chunk_text", ""),
                source_file=r.get("source_file", ""),
                score=r.get("combined_score") if reranking_applied else r.get("score", 0.0),
                metadata={
                    **(r.get("metadata") or {}),
                    "file_type": r.get("file_type", "")  # 📄 Dosya tipi metadata'ya ekle
                }
            )
            for r in top_results
        ]
        
        # ⏱️ Timing logu
        timings["total"] = time.time() - start_total
        
        # Loglama
        rerank_info = " [CatBoost]" if reranking_applied else ""
        if top_results and top_results[0].get("fuzzy_boost", 0) > 0:
            log_msg = f"RAG{rerank_info}: '{query[:30]}' - {len(results)} sonuç | ⏱️ emb:{timings['embedding']:.2f}s score:{timings.get('scoring',0):.2f}s total:{timings['total']:.2f}s"
        else:
            log_msg = f"RAG{rerank_info}: '{query[:40]}' - {len(results)} sonuç | ⏱️ emb:{timings['embedding']:.2f}s score:{timings.get('scoring',0):.2f}s total:{timings['total']:.2f}s"
        
        log_system_event("INFO" if timings["total"] < 2 else "WARNING", log_msg, "rag")
        
        # 🚀 v2.30.1: Sonucu cache'e kaydet (TTL: 300 sn = 5 dk)
        response = SearchResponse(results=results, total=len(results))
        cache_service.query.set(cache_key, response, ttl=300)
        
        return response
    
    # ── Stats & Management ───────────────────────────────────────
    
    def get_stats(self) -> Dict[str, Any]:
        """Veritabanı istatistiklerini döndürür"""
        conn = get_db_conn()
        try:
            cur = conn.cursor()
            
            # Toplam chunk sayısı
            cur.execute("SELECT COUNT(*) as count FROM rag_chunks")
            chunk_count = cur.fetchone()["count"]
            
            # Embedding'li chunk sayısı
            cur.execute("SELECT COUNT(*) as count FROM rag_chunks WHERE embedding IS NOT NULL")
            embedded_count = cur.fetchone()["count"]
            
            # Dosya sayısı
            cur.execute("SELECT COUNT(*) as count FROM uploaded_files")
            file_count = cur.fetchone()["count"]
            
            return {
                "storage": "PostgreSQL",
                "total_chunks": chunk_count,
                "embedded_chunks": embedded_count,
                "file_count": file_count,
                "embedding_model": getattr(settings, 'EMBEDDING_MODEL', 'paraphrase-multilingual-MiniLM-L12-v2'),
                "embedding_dim": self._embedding_dim
            }
        finally:
            conn.close()
    
    def reset(self) -> None:
        """Tüm chunk'ları ve embedding'leri siler"""
        conn = get_db_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM rag_chunks")
            cur.execute("UPDATE uploaded_files SET chunk_count = 0")
            conn.commit()
            # 🚀 v2.30.1: Cache temizle
            try:
                from app.core.cache import cache_service
                cache_service.query.clear()
            except Exception:
                pass
            log_system_event("WARNING", "RAG veritabanı sıfırlandı (cache temizlendi)", "rag")
        except Exception as e:
            conn.rollback()
            log_error(f"RAG reset hatası: {str(e)}", "rag", error_detail=str(e))
            raise
        finally:
            conn.close()
    
    def delete_file_chunks(self, file_id: int) -> None:
        """Belirli bir dosyanın chunk'larını siler"""
        conn = get_db_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM rag_chunks WHERE file_id = %s", (file_id,))
            cur.execute("UPDATE uploaded_files SET chunk_count = 0 WHERE id = %s", (file_id,))
            # 🚀 v2.30.1: Cache temizle
            try:
                from app.core.cache import cache_service
                cache_service.query.clear()
            except Exception as e:
                log_warning(f"RAG cache temizleme hatası (delete_chunks): {e}", "rag")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


# Singleton instance
_rag_service: Optional[RAGService] = None
_is_preloaded: bool = False


def get_rag_service(preload: bool = False) -> RAGService:
    """
    RAG Service singleton instance döndürür.
    
    Args:
        preload: True ise embedding modeli hemen yüklenir (startup için)
    
    Returns:
        RAGService singleton instance
    """
    global _rag_service, _is_preloaded
    
    if _rag_service is None:
        _rag_service = RAGService()
    
    # Preload: Model yükle ve sık kullanılan sorguları cache'le
    if preload and not _is_preloaded:
        try:
            log_system_event("INFO", "🚀 RAG Service preload başlıyor...", "rag")
            
            # 1. Embedding modelini yükle
            _ = _rag_service.embedding_model
            
            # 2. 🚀 v2.32.0: Dinamik warm-up sorguları (DB + statik)
            common_queries = _generate_warmup_queries()
            
            for query in common_queries:
                _rag_service._get_embedding(query)
            
            # 3. 🚀 v2.32.0: Continuous learning başlat
            try:
                from app.services.ml_training.continuous_learning import get_continuous_learning_service
                cl_service = get_continuous_learning_service()
                cl_service.start()
            except Exception as e:
                log_system_event("WARNING", f"Continuous learning başlatılamadı: {e}", "ml_training")
            
            _is_preloaded = True
            log_system_event("INFO", f"✅ RAG Service preload tamamlandı ({len(common_queries)} sorgu cache'lendi)", "rag")
            
        except Exception as e:
            log_error(f"RAG preload hatası: {e}", "rag")
    
    return _rag_service


def preload_rag_service():
    """
    🚀 FastAPI startup event için helper.
    Embedding modelini ve sık kullanılan sorguları önceden yükler.
    """
    return get_rag_service(preload=True)


def _generate_warmup_queries() -> list:
    """
    🚀 v2.32.0: DB'deki dosya isimlerinden + statik listeden warm-up sorguları üretir.
    İlk kullanıcı sorgusunun hızlı olması için embedding cache'ini önceden doldurur.
    """
    from pathlib import Path
    
    static_queries = [
        "switch enable komutu",
        "router konfigürasyonu",
        "vpn bağlantı ayarları",
        "network troubleshooting",
        "firewall kuralları",
        "dns ayarları",
        "port forwarding",
        "ssl sertifika",
    ]
    
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT uf.file_name 
            FROM uploaded_files uf 
            WHERE uf.chunk_count > 0 
            LIMIT 20
        """)
        file_names = [row['file_name'] for row in cur.fetchall()]
        conn.close()
        
        # Dosya isimlerini keyword olarak ekle
        for fn in file_names:
            name = Path(fn).stem.replace('_', ' ').replace('-', ' ')
            if len(name) > 3:
                static_queries.append(name)
    except Exception as e:
        log_warning(f"Statik query oluşturma hatası: {e}", "rag")
    
    return static_queries[:30]  # Max 30 sorgu
