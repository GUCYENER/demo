"""
VYRA L1 Support API - RAG Routes
=================================
RAG modül router aggregator.
Alt modüllerden router'ları birleştirir.
"""

from fastapi import APIRouter

from app.api.routes.rag_upload import router as upload_router
from app.api.routes.rag_search import router as search_router
from app.api.routes.rag_files import router as files_router
from app.api.routes.rag_rebuild import router as rebuild_router
from app.api.routes.rag_maturity import router as maturity_router
from app.api.routes.rag_enhance import router as enhance_router
from app.api.routes.rag_images import router as images_router


router = APIRouter()

# Alt modül router'larını birleştir
router.include_router(upload_router)
router.include_router(search_router)
router.include_router(files_router)
router.include_router(rebuild_router)
router.include_router(maturity_router)
router.include_router(enhance_router)
router.include_router(images_router)

