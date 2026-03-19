"""
VYRA L1 Support API - RAG Search Routes
=========================================
Semantik arama ve istatistik endpoint'leri.
"""

from __future__ import annotations

from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes.auth import get_current_user
from app.api.schemas.rag_schemas import (
    RAGSearchRequest, RAGSearchResult, RAGSearchResponse, RAGStatsResponse
)
from app.services.logging_service import log_error
from app.services.rag_service import get_rag_service


router = APIRouter()


@router.post("/search", response_model=RAGSearchResponse)
async def search_knowledge_base(
    request: RAGSearchRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Bilgi tabanında semantik arama yapar"""
    try:
        rag_service = get_rag_service()
        response = rag_service.search(
            query=request.query,
            n_results=request.n_results,
            user_id=user["id"]  # 🔒 ORG FILTERING
        )
        
        results = [
            RAGSearchResult(
                content=r.content,
                source_file=r.source_file,
                score=r.score
            )
            for r in response.results
        ]
        
        return RAGSearchResponse(
            query=request.query,
            results=results,
            total_results=len(results)
        )
    except Exception as e:
        log_error(f"RAG arama hatasi: {str(e)}", "rag", error_detail=str(e))
        raise HTTPException(status_code=500, detail="Arama sırasında bir hata oluştu.")


@router.get("/stats", response_model=RAGStatsResponse)
async def get_stats(
    company_id: Optional[int] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """RAG istatistiklerini döndürür"""
    try:
        rag_service = get_rag_service()
        stats = rag_service.get_stats()
        
        return RAGStatsResponse(
            storage=stats["storage"],
            total_chunks=stats["total_chunks"],
            embedded_chunks=stats["embedded_chunks"],
            file_count=stats["file_count"],
            embedding_model=stats["embedding_model"]
        )
    except Exception as e:
        log_error(f"İstatistik hatası: {e}", "rag")
        raise HTTPException(status_code=500, detail="İstatistik alınırken bir hata oluştu.")
