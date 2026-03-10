"""
VYRA L1 Support API - Schemas Package
======================================
Pydantic şema modülleri.
"""

from app.api.schemas.rag_schemas import (
    FileUploadInfo,
    FileUploadResponse,
    FileListItem,
    FileListResponse,
    RAGSearchRequest,
    RAGSearchResult,
    RAGSearchResponse,
    RAGStatsResponse,
    RebuildResponse,
    UpdateFileOrgsRequest,
)

from app.api.schemas.user_schemas import (
    UserListItem,
    UserListResponse,
    ApproveUserRequest,
    RejectUserRequest,
    UpdateUserOrgsRequest,
    RoleItem,
    RolesResponse,
    ProfileResponse,
    UpdateProfileRequest,
    UpdateAvatarRequest,
    ChangePasswordRequest,
)

__all__ = [
    # RAG Schemas
    "FileUploadInfo",
    "FileUploadResponse",
    "FileListItem",
    "FileListResponse",
    "RAGSearchRequest",
    "RAGSearchResult",
    "RAGSearchResponse",
    "RAGStatsResponse",
    "RebuildResponse",
    "UpdateFileOrgsRequest",
    # User Schemas
    "UserListItem",
    "UserListResponse",
    "ApproveUserRequest",
    "RejectUserRequest",
    "UpdateUserOrgsRequest",
    "RoleItem",
    "RolesResponse",
    "ProfileResponse",
    "UpdateProfileRequest",
    "UpdateAvatarRequest",
    "ChangePasswordRequest",
]
