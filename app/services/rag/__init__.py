"""
VYRA L1 Support API - RAG Package
===================================
Modüler RAG (Retrieval-Augmented Generation) sistemi.

Bileşenler:
- embedding: ONNX/PyTorch model yönetimi ve embedding üretimi
- scoring: Cosine similarity, BM25, RRF, fuzzy matching
- service: Ana RAGService sınıfı, search ve CRUD

Kullanım:
    from app.services.rag import RAGService, get_rag_service, preload_rag_service
"""

from app.services.rag.service import (
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
