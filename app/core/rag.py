"""
VYRA L1 Support API - RAG Core Module
======================================
Bilgi Tabanı arama fonksiyonları.
RAGService'i wrap ederek basit interface sağlar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from app.services.logging_service import log_system_event, log_error


@dataclass
class KnowledgeResult:
    """Bilgi tabanı arama sonucu"""
    content: str
    source_file: str
    score: float
    metadata: dict = None  # 🆕 v2.29.2: Sheet name, heading vb.
    
    def __str__(self):
        return f"[{self.source_file}] (skor: {self.score:.2f})\n{self.content}"


# LLM bypass için eşik değerler
HIGH_CONFIDENCE_THRESHOLD = 0.60  # Bu skorun üzerinde LLM atlanabilir (chunk içeriği direkt gösterilir)
MIN_CONTENT_LENGTH = 80  # Minimum içerik uzunluğu


@dataclass
class KnowledgeSearchResponse:
    """Arama yanıtı"""
    results: List[KnowledgeResult]
    has_results: bool
    best_source: Optional[str] = None
    
    @property
    def can_bypass_llm(self) -> bool:
        """
        RAG sonucu yeterince güvenilir mi? LLM atlanabilir mi?
        
        Kriterler:
        1. En az bir sonuç var
        2. En iyi sonucun skoru >= 0.70
        3. İçerik yeterince uzun (>= 80 karakter)
        """
        if not self.results:
            return False
        
        best = self.results[0]
        return best.score >= HIGH_CONFIDENCE_THRESHOLD and len(best.content) >= MIN_CONTENT_LENGTH
    
    @property
    def best_score(self) -> float:
        """En iyi sonucun skoru"""
        return self.results[0].score if self.results else 0.0
    
    def get_direct_answer(self) -> str:
        """LLM kullanmadan direkt RAG yanıtı"""
        if not self.results:
            return ""
        return self.results[0].content
    
    def get_context_for_llm(self, max_results: int = 3) -> str:
        """LLM'e gönderilecek context string döndürür"""
        if not self.results:
            return ""
        
        context_parts = []
        sources = set()
        
        for result in self.results[:max_results]:
            context_parts.append(f"--- Kaynak: {result.source_file} ---\n{result.content}")
            sources.add(result.source_file)
        
        return "\n\n".join(context_parts)
    
    def get_sources_list(self) -> List[str]:
        """Benzersiz kaynak dosya listesi"""
        return list(set(r.source_file for r in self.results))



def search_knowledge_base(
    query: str, 
    n_results: int = 5, 
    min_score: float = 0.35, 
    user_id: int = None,
    max_per_file: int = 2  # 🆕 v2.28.0: None = sınırsız (liste sorguları için)
) -> KnowledgeSearchResponse:
    """
    Bilgi tabanında semantik arama yapar.
    
    🔒 GÜVENLİK: user_id verilirse, sadece kullanıcının yetkili olduğu 
    organizasyon gruplarındaki dokümanlar aranır.
    
    Args:
        query: Arama sorgusu
        n_results: Maksimum sonuç sayısı
        min_score: Minimum benzerlik skoru (0-1)
        user_id: Kullanıcı ID (org filtering için)
        max_per_file: Aynı dosyadan max sonuç (None=sınırsız)
    
    Returns:
        KnowledgeSearchResponse
    """
    try:
        from app.services.rag_service import RAGService
        
        rag_service = RAGService()
        
        # 🆕 v2.53.1: Kısa/anlamsız sorgularda eşik yükselt
        # 5 karakterden az anlamlı içerik → min_score artır
        meaningful_chars = len(query.strip().replace('.', '').replace('?', '').replace(' ', ''))
        if meaningful_chars < 5:
            min_score = max(min_score, 0.55)
            log_system_event("DEBUG", f"Kısa sorgu tespit: '{query}' ({meaningful_chars} harf) → min_score={min_score}", "rag")
        
        # 🔒 ORG FILTERING + 🆕 DIVERSITY CONTROL
        response = rag_service.search(
            query, 
            n_results=n_results, 
            min_score=min_score, 
            user_id=user_id,
            max_per_file=max_per_file
        )
        
        if not response.results:
            log_system_event("INFO", f"RAG arama sonuç bulunamadı: '{query[:50]}...'", "rag")
            return KnowledgeSearchResponse(results=[], has_results=False)
        
        results = [
            KnowledgeResult(
                content=r.content,
                source_file=r.source_file,
                score=r.score,
                metadata=r.metadata  # 🆕 v2.29.2: Sheet name vb.
            )
            for r in response.results
        ]
        
        best_source = results[0].source_file if results else None
        
        log_system_event(
            "INFO", 
            f"RAG arama başarılı: '{query[:50]}...' - {len(results)} sonuç, en iyi: {best_source}",
            "rag"
        )
        
        return KnowledgeSearchResponse(
            results=results,
            has_results=True,
            best_source=best_source
        )
        
    except Exception as e:
        log_error(f"RAG arama hatası: {str(e)}", "rag", error_detail=str(e))
        return KnowledgeSearchResponse(results=[], has_results=False)
