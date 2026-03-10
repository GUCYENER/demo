"""
VYRA L1 Support API - Web Search Module
========================================
Web araması yaparak ek bilgi sağlar.
RAG'de sonuç bulunamazsa fallback olarak kullanılır.
"""

from __future__ import annotations

import requests
from dataclasses import dataclass
from typing import List, Optional
from app.services.logging_service import log_system_event, log_error, log_warning


@dataclass
class WebSearchResult:
    """Web arama sonucu"""
    title: str
    snippet: str
    url: str
    
    def __str__(self):
        return f"[{self.title}]\n{self.snippet}\nKaynak: {self.url}"


@dataclass
class WebSearchResponse:
    """Web arama yanıtı"""
    results: List[WebSearchResult]
    has_results: bool
    source: str = "web"
    
    def get_context_for_llm(self, max_results: int = 3) -> str:
        """LLM'e gönderilecek context string döndürür"""
        if not self.results:
            return ""
        
        context_parts = []
        for result in self.results[:max_results]:
            context_parts.append(f"--- Web Kaynağı: {result.title} ---\n{result.snippet}")
        
        return "\n\n".join(context_parts)
    
    def get_sources_list(self) -> List[str]:
        """Kaynak URL listesi"""
        return [r.url for r in self.results]


def web_search_snippets(query: str, max_results: int = 3) -> WebSearchResponse:
    """
    DuckDuckGo Instant Answer API kullanarak web araması yapar.
    
    Args:
        query: Arama sorgusu
        max_results: Maksimum sonuç sayısı
    
    Returns:
        WebSearchResponse
    """
    try:
        # DuckDuckGo Instant Answer API (rate limit yok, API key gerektirmez)
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        results = []
        
        # Abstract (ana sonuç)
        if data.get("Abstract"):
            results.append(WebSearchResult(
                title=data.get("Heading", "DuckDuckGo"),
                snippet=data.get("Abstract", ""),
                url=data.get("AbstractURL", "https://duckduckgo.com")
            ))
        
        # RelatedTopics (ilgili konular)
        for topic in data.get("RelatedTopics", [])[:max_results - len(results)]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(WebSearchResult(
                    title=topic.get("FirstURL", "").split("/")[-1].replace("_", " ") or "İlgili Konu",
                    snippet=topic.get("Text", ""),
                    url=topic.get("FirstURL", "https://duckduckgo.com")
                ))
        
        if results:
            log_system_event("INFO", f"Web arama başarılı: '{query[:50]}...' - {len(results)} sonuç", "web_search")
            return WebSearchResponse(results=results, has_results=True)
        else:
            log_warning(f"Web arama sonuç bulunamadı: '{query[:50]}...'", "web_search")
            return WebSearchResponse(results=[], has_results=False)
            
    except requests.exceptions.Timeout:
        log_warning("Web arama zaman aşımı (10s)", "web_search")
        return WebSearchResponse(results=[], has_results=False)
    except requests.exceptions.RequestException as e:
        log_error(f"Web arama bağlantı hatası: {str(e)}", "web_search", error_detail=str(e))
        return WebSearchResponse(results=[], has_results=False)
    except Exception as e:
        log_error(f"Web arama hatası: {str(e)}", "web_search", error_detail=str(e))
        return WebSearchResponse(results=[], has_results=False)


def search_web_fallback(query: str) -> WebSearchResponse:
    """
    Fallback web araması - RAG sonuç vermezse kullanılır.
    """
    # Türkçe arama için sorguyu zenginleştir
    enhanced_query = f"{query} çözüm nasıl"
    return web_search_snippets(enhanced_query, max_results=3)
