"""
VYRA L1 Support API - RAG Image Routes
=======================================
Doküman görsellerini sunma endpoint'leri.

Author: VYRA AI Team
Version: 1.0.0
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.db import get_db_conn
from app.services.logging_service import log_error

router = APIRouter()


# ⚠ SIRA ÖNEMLİ: Literal path'ler ({image_id} parametreli) path'lerden ÖNCE!

@router.get("/images/by-file/{file_id}")
async def get_file_images(file_id: int):
    """
    Bir dosyaya ait tüm görsellerin listesini döndürür (binary hariç).
    
    Args:
        file_id: uploaded_files tablosundaki dosya ID
    
    Returns:
        Görsel metadata listesi
    """
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, image_index, image_format, width_px, height_px, 
                   file_size_bytes, context_heading, context_chunk_index, alt_text,
                   LEFT(ocr_text, 200) as ocr_preview,
                   CASE WHEN LENGTH(COALESCE(ocr_text, '')) > 0 THEN true ELSE false END as has_ocr
            FROM document_images 
            WHERE file_id = %s 
            ORDER BY image_index
            """,
            (file_id,)
        )
        rows = cur.fetchall()
        
        return {
            "file_id": file_id,
            "total_images": len(rows),
            "images": [
                {
                    "id": r["id"],
                    "image_index": r["image_index"],
                    "image_format": r["image_format"],
                    "width": r["width_px"],
                    "height": r["height_px"],
                    "file_size_bytes": r["file_size_bytes"],
                    "context_heading": r["context_heading"],
                    "context_chunk_index": r["context_chunk_index"],
                    "alt_text": r["alt_text"],
                    "has_ocr": r["has_ocr"],
                    "ocr_preview": r["ocr_preview"] or "",
                    "url": f"/api/rag/images/{r['id']}"
                }
                for r in rows
            ]
        }
    except Exception as e:
        log_error(f"Dosya görselleri listeleme hatası: {e}", "rag_images")
        raise HTTPException(status_code=500, detail="Görsel listesi yüklenirken hata")
    finally:
        conn.close()


@router.get("/images/{image_id}")
async def get_document_image(image_id: int):
    """
    Doküman görselini binary olarak döndürür.
    
    Args:
        image_id: document_images tablosundaki görsel ID
    
    Returns:
        Görsel binary verisi (Content-Type: image/png, image/jpeg vb.)
    """
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT image_data, image_format, ocr_text FROM document_images WHERE id = %s",
            (image_id,)
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Görsel bulunamadı")
        
        image_data = row["image_data"]
        image_format = row["image_format"]
        
        # Pillow memory view → bytes
        if isinstance(image_data, memoryview):
            image_data = bytes(image_data)
        
        content_type = f"image/{image_format}"
        
        # OCR metin var mı bilgisi header'a ekle
        ocr_text = row.get("ocr_text", "") or ""
        
        return Response(
            content=image_data,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Length": str(len(image_data)),
                "X-Has-OCR": "true" if ocr_text.strip() else "false"
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"Görsel getirme hatası: {e}", "rag_images")
        raise HTTPException(status_code=500, detail="Görsel yüklenirken hata")
    finally:
        conn.close()


@router.get("/images/{image_id}/ocr")
async def get_image_ocr_text(image_id: int):
    """
    Görselin OCR metnini döndürür.
    
    Args:
        image_id: document_images tablosundaki görsel ID
    
    Returns:
        {"image_id": int, "ocr_text": str, "has_text": bool}
    """
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT ocr_text, alt_text, context_heading FROM document_images WHERE id = %s",
            (image_id,)
        )
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Görsel bulunamadı")
        
        ocr_text = (row.get("ocr_text") or "").strip()
        
        return {
            "image_id": image_id,
            "ocr_text": ocr_text,
            "has_text": len(ocr_text) > 0,
            "context_heading": row.get("context_heading", ""),
            "alt_text": row.get("alt_text", "")
        }
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"OCR metin getirme hatası: {e}", "rag_images")
        raise HTTPException(status_code=500, detail="OCR verisi yüklenirken hata")
    finally:
        conn.close()
