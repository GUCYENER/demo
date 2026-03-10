"""
VYRA L1 Support API - Feedback Routes
======================================
Kullanıcı geri bildirim API endpoints.

Author: VYRA AI Team
Version: 1.0.0 (v2.13.0)
"""

from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_user
from app.services.feedback_service import get_feedback_service
from app.services.user_affinity_service import get_user_affinity_service
from app.services.logging_service import log_system_event


router = APIRouter()


# ============================================
# Pydantic Models
# ============================================

class FeedbackRequest(BaseModel):
    """Feedback gönderme isteği"""
    feedback_type: str = Field(..., description="helpful, not_helpful, copied, partial")
    ticket_id: Optional[int] = None
    chunk_ids: Optional[List[int]] = None
    query_text: Optional[str] = None
    response_text: Optional[str] = None


class FeedbackResponse(BaseModel):
    """Feedback yanıtı"""
    success: bool
    message: str


class FeedbackStatsResponse(BaseModel):
    """Feedback istatistikleri"""
    total_feedback: int
    helpful_count: int
    not_helpful_count: int
    helpfulness_rate: float
    recent_feedback: list


class UserAffinityResponse(BaseModel):
    """Kullanıcı affinity profili"""
    user_id: int
    total_queries: int
    total_success: int
    success_rate: float
    topic_count: int
    affinities: list
    top_topics: list


# ============================================
# Feedback Endpoints
# ============================================

@router.post("/feedback", response_model=FeedbackResponse, summary="Kullanıcı geri bildirimi gönder")
async def submit_feedback(
    request: FeedbackRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Kullanıcı geri bildirimi kaydet.
    
    Feedback tipleri:
    - `helpful`: Cevap işe yaradı
    - `not_helpful`: Cevap işe yaramadı
    - `copied`: Cevap kopyalandı
    - `partial`: Kısmen faydalı
    """
    feedback_service = get_feedback_service()
    
    result = feedback_service.record_feedback(
        user_id=current_user["id"],
        feedback_type=request.feedback_type,
        ticket_id=request.ticket_id,
        chunk_ids=request.chunk_ids,
        query_text=request.query_text,
        response_text=request.response_text
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Feedback kaydedilemedi"))
    
    return FeedbackResponse(success=True, message=result.get("message", "Geri bildiriminiz kaydedildi"))


@router.get("/feedback/stats", response_model=FeedbackStatsResponse, summary="Kullanıcı feedback istatistikleri")
async def get_feedback_stats(
    days: int = 30,
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcının son N günlük feedback istatistiklerini getir"""
    feedback_service = get_feedback_service()
    stats = feedback_service.get_user_stats(current_user["id"], days)
    
    return FeedbackStatsResponse(
        total_feedback=stats.total_feedback,
        helpful_count=stats.helpful_count,
        not_helpful_count=stats.not_helpful_count,
        helpfulness_rate=stats.helpfulness_rate,
        recent_feedback=stats.recent_feedback
    )


# ============================================
# User Affinity Endpoints
# ============================================

@router.get("/users/me/affinity", response_model=UserAffinityResponse, summary="Kullanıcı topic affinitesi")
async def get_user_affinity(
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcının topic affinite profilini getir"""
    affinity_service = get_user_affinity_service()
    profile = affinity_service.get_user_profile(current_user["id"])
    
    return UserAffinityResponse(
        user_id=profile.get("user_id", current_user["id"]),
        total_queries=profile.get("total_queries", 0),
        total_success=profile.get("total_success", 0),
        success_rate=profile.get("success_rate", 0.0),
        topic_count=profile.get("topic_count", 0),
        affinities=profile.get("affinities", []),
        top_topics=profile.get("top_topics", [])
    )


@router.get("/users/me/affinity/topics", summary="Kullanıcının en ilgili olduğu konular")
async def get_top_topics(
    limit: int = 5,
    current_user: dict = Depends(get_current_user)
):
    """Kullanıcının en yüksek affiniteye sahip olduğu topic'leri getir"""
    affinity_service = get_user_affinity_service()
    topics = affinity_service.get_top_topics(current_user["id"], limit)
    
    return {"topics": topics}
