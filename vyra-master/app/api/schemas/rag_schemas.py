"""
VYRA L1 Support API - RAG Schemas
==================================
RAG modülleri için Pydantic şemaları.
"""

from typing import List, Optional
from pydantic import BaseModel


# ---------------------------------------------------------
#  File Upload Schemas
# ---------------------------------------------------------

class FileUploadInfo(BaseModel):
    """Yüklenen dosya bilgisi"""
    file_name: str
    file_type: str
    file_size_bytes: int


class FileUploadResponse(BaseModel):
    """Dosya yükleme yanıtı"""
    message: str
    uploaded_count: int
    files: List[FileUploadInfo]
    embeddings_created: bool


# ---------------------------------------------------------
#  File List Schemas
# ---------------------------------------------------------

class FileListItem(BaseModel):
    """Dosya listesi öğesi"""
    id: int
    file_name: str
    file_type: str
    file_size_bytes: Optional[int]
    chunk_count: int
    uploaded_at: str
    uploaded_by: Optional[int]
    uploaded_by_name: Optional[str] = None
    org_groups: List[str] = []  # Organizasyon kodları listesi
    maturity_score: Optional[float] = None  # Dosya olgunluk skoru (0-100)
    status: str = "completed"  # v2.39.0: Dosya işleme durumu (processing, completed, failed)


class FileListResponse(BaseModel):
    """Dosya listesi yanıtı"""
    files: List[FileListItem]
    total: int
    supported_extensions: List[str]


# ---------------------------------------------------------
#  RAG Search Schemas
# ---------------------------------------------------------

class RAGSearchRequest(BaseModel):
    """RAG arama isteği"""
    query: str
    n_results: int = 5


class RAGSearchResult(BaseModel):
    """RAG arama sonucu"""
    content: str
    source_file: str
    score: float


class RAGSearchResponse(BaseModel):
    """RAG arama yanıtı"""
    query: str
    results: List[RAGSearchResult]
    total_results: int


# ---------------------------------------------------------
#  RAG Stats Schemas
# ---------------------------------------------------------

class RAGStatsResponse(BaseModel):
    """RAG istatistikleri yanıtı"""
    storage: str
    total_chunks: int
    embedded_chunks: int
    file_count: int
    embedding_model: str


# ---------------------------------------------------------
#  Rebuild Schemas
# ---------------------------------------------------------

class RebuildResponse(BaseModel):
    """Rebuild işlemi yanıtı"""
    success: bool
    processed_files: int
    total_chunks: int
    failed_files: List[str]
    errors: List[str]


# ---------------------------------------------------------
#  Update Schemas
# ---------------------------------------------------------

class UpdateFileOrgsRequest(BaseModel):
    """Dosya org güncelleme isteği"""
    org_ids: List[int]
