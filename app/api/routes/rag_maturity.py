"""
VYRA L1 Support API - RAG Maturity Routes
==========================================
Dosya olgunluk skoru analiz endpoint'i.
"""

from typing import List
from fastapi import APIRouter, File, UploadFile, Depends, HTTPException
import io

from app.api.routes.auth import get_current_user
from app.services.logging_service import log_error
from app.services.maturity_analyzer import analyze_file


router = APIRouter()


@router.post("/analyze-maturity")
async def analyze_maturity(
    files: List[UploadFile] = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Yüklenmeden önce dosyaların RAG olgunluk skorunu hesaplar.
    Her dosya için kategorik analiz ve ihlal raporu döndürür.
    """
    results = []
    
    for f in files:
        try:
            content = await f.read()
            file_obj = io.BytesIO(content)
            result = analyze_file(file_obj, f.filename)
            results.append(result)
        except Exception as e:
            log_error(f"Maturity analiz hatası ({f.filename})", "rag", error_detail=str(e))
            results.append({
                "file_name": f.filename,
                "file_type": f.filename.rsplit('.', 1)[-1].upper() if '.' in f.filename else "?",
                "total_score": 50,
                "categories": [],
                "violations": [],
                "detail_count": 0,
                "message": "Dosya analizi sırasında bir hata oluştu."
            })
    
    return {"results": results}
