from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field, validator


# ----------------- User / Auth -----------------


class UserBase(BaseModel):
    full_name: str
    phone: str = Field(pattern=r"^5\d{9}$")


class UserCreate(UserBase):
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    phone: str = Field(pattern=r"^5\d{9}$")
    password: str = Field(min_length=6)
    remember_me: bool = True


class UserPublic(BaseModel):
    id: int
    full_name: str
    phone: str
    is_admin: bool

    class Config:
        from_attributes = True


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserPublic


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class TokenData(BaseModel):
    sub: int
    phone: str
    full_name: str
    is_admin: bool
    type: str
    exp: int


# ----------------- Tickets / Steps -----------------


class ChatRequest(BaseModel):
    query: str


class TicketCreate(BaseModel):
    title: str
    description: str
    source_type: Optional[str] = None
    source_name: Optional[str] = None


class TicketStep(BaseModel):
    step_order: int
    step_title: str
    step_body: str


class TicketDetail(BaseModel):
    id: int
    user_id: int  # GÜVENLİK: IDOR koruması için ticket sahibi
    title: str
    description: str
    source_type: Optional[str]
    source_name: Optional[str]
    final_solution: Optional[str]
    cym_text: Optional[str]
    cym_portal_url: Optional[str]
    llm_evaluation: Optional[str] = None  # Corpix AI Değerlendirmesi
    rag_results: Optional[List[Dict[str, Any]]] = None  # 🆕 v2.23.0
    interaction_type: Optional[str] = None  # 🆕 v2.23.0: rag_only, user_selection, ai_evaluation
    created_at: datetime
    steps: List[TicketStep] = []


class TicketHistoryItem(BaseModel):
    id: int
    created_at: datetime
    title: str
    description: str
    source_type: Optional[str]
    source_name: Optional[str]
    final_solution: Optional[str]
    llm_evaluation: Optional[str] = None  # Corpix AI Değerlendirmesi
    rag_results: Optional[List[Dict[str, Any]]] = None  # 🆕 v2.23.0
    interaction_type: Optional[str] = None  # 🆕 v2.23.0


class TicketHistoryResponse(BaseModel):
    items: List[TicketDetail]
    page: int
    page_size: int
    total: int


# ----------------- RAG Upload -----------------


class FileUploadInfo(BaseModel):
    file_name: str
    stored_path: str
    file_type: str


class FileUploadResponse(BaseModel):
    message: str
    uploaded_count: int
    files: List[FileUploadInfo]
