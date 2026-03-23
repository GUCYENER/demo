"""
VYRA L1 Support API - User Schemas
===================================
User modülleri için Pydantic şemaları.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------
#  User List Schemas
# ---------------------------------------------------------

class UserListItem(BaseModel):
    """Kullanıcı listesi öğesi"""
    id: int
    full_name: str
    username: str
    email: str
    phone: str
    role_id: int
    role_name: str
    is_admin: bool
    is_approved: bool
    approved_at: Optional[str]
    created_at: str


class UserListResponse(BaseModel):
    """Kullanıcı listesi yanıtı"""
    users: List[UserListItem]
    total: int
    pending_count: int


# ---------------------------------------------------------
#  User Approval Schemas
# ---------------------------------------------------------

class ApproveUserRequest(BaseModel):
    """Kullanıcı onay isteği"""
    user_id: int
    role_id: int
    is_admin: bool = False
    org_ids: List[int] = Field(default=[], max_length=50)


class RejectUserRequest(BaseModel):
    """Kullanıcı red isteği"""
    user_id: int


class UpdateUserOrgsRequest(BaseModel):
    """Kullanıcı org güncelleme isteği"""
    org_ids: List[int] = Field(..., max_length=50)


# ---------------------------------------------------------
#  Role Schemas
# ---------------------------------------------------------

class RoleItem(BaseModel):
    """Rol öğesi"""
    id: int
    name: str
    description: Optional[str]


class RolesResponse(BaseModel):
    """Roller yanıtı"""
    roles: List[RoleItem]


# ---------------------------------------------------------
#  Profile Schemas
# ---------------------------------------------------------

class ProfileResponse(BaseModel):
    """Profil yanıtı"""
    id: int
    full_name: str
    username: str
    email: str
    phone: str
    avatar: Optional[str] = None
    role_name: str
    is_admin: bool
    is_approved: bool
    created_at: str
    auth_type: Optional[str] = "local"
    domain: Optional[str] = None
    department: Optional[str] = None
    title: Optional[str] = None
    organization: Optional[str] = None
    company_id: Optional[int] = None


class UpdateProfileRequest(BaseModel):
    """Profil güncelleme isteği"""
    full_name: Optional[str] = Field(None, min_length=2, max_length=150)
    email: Optional[str] = Field(None, max_length=254)
    phone: Optional[str] = Field(None, max_length=20)


class UpdateAvatarRequest(BaseModel):
    """Avatar güncelleme isteği"""
    avatar: str = Field(..., max_length=2_000_000)  # Base64 ~1.5MB limit


class ChangePasswordRequest(BaseModel):
    """Şifre değiştirme isteği"""
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=6, max_length=256)
