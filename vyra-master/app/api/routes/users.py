"""
VYRA L1 Support API - Users Routes
====================================
User modül router aggregator.
Alt modüllerden router'ları birleştirir.
"""

from fastapi import APIRouter

from app.api.routes.user_admin import router as admin_router
from app.api.routes.user_profile import router as profile_router


router = APIRouter(tags=["users"])

# Alt modül router'larını birleştir
router.include_router(admin_router)
router.include_router(profile_router)
