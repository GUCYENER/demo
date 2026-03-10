"""
VYRA L1 Support API - RAG Service (Backward-Compatible Wrapper)
================================================================
Bu dosya geriye uyumluluk için korunmuştur.
Tüm fonksiyonalite app/services/rag/ paketine taşınmıştır.

🏗️ v2.30.0: Modüler mimari — bu dosya sadece re-export yapar.
"""

# Re-export everything from the new modular package
from app.services.rag.service import (  # noqa: F401
    RAGService,
    SearchResult,
    SearchResponse,
    get_rag_service,
    preload_rag_service,
)

__all__ = [
    "RAGService",
    "SearchResult",
    "SearchResponse",
    "get_rag_service",
    "preload_rag_service",
]
