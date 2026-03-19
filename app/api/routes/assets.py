"""
VYRA L1 Support API - System Assets Routes
===========================================
Sistem görselleri (logo, favicon vb.) için API endpoint'leri.
Bu görseller veritabanında BLOB olarak saklanır ve reset'te korunur.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response, FileResponse
from typing import Optional

from app.core.db import get_db_conn
from app.services.logging_service import log_system_event, log_error
from app.api.routes.auth import get_current_user

# Statik dosya fallback dizini
_STATIC_FALLBACK_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "frontend", "assets", "images"
)

router = APIRouter()


# ============================================
# Asset Retrieval (Public - No Auth Required)
# ============================================

@router.get("/{asset_key}")
async def get_asset(asset_key: str):
    """
    Sistem görselini döndürür (favicon, logo vb.)
    
    Bu endpoint authentication gerektirmez - 
    favicon ve logo public olmalı.
    """
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT asset_data, mime_type, asset_name
            FROM system_assets
            WHERE asset_key = %s
        """, (asset_key,))
        
        row = cur.fetchone()
        if not row:
            # DB'de yoksa statik dosyalardan fallback dene
            _FALLBACK_MAP = {
                "favicon": "favicon.png",
                "login_logo": "vyra_logo.png",
                "sidebar_logo": "vyra_logo.png",
            }
            fallback_file = _FALLBACK_MAP.get(asset_key)
            if fallback_file:
                fallback_path = os.path.normpath(
                    os.path.join(_STATIC_FALLBACK_DIR, fallback_file)
                )
                if os.path.isfile(fallback_path):
                    return FileResponse(
                        fallback_path,
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
            raise HTTPException(status_code=404, detail=f"Asset bulunamadı: {asset_key}")
        
        # Binary data döndür
        return Response(
            content=bytes(row["asset_data"]),
            media_type=row["mime_type"],
            headers={
                "Cache-Control": "public, max-age=86400",  # 1 gün cache
                "Content-Disposition": f"inline; filename=\"{row['asset_name']}\""
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        log_error(f"Asset okuma hatası: {e}", "assets")
        raise HTTPException(status_code=500, detail="Asset yüklenirken bir hata oluştu.")
    finally:
        conn.close()


# ============================================
# Asset Management (Admin Only)
# ============================================

@router.get("")
async def list_assets(current_user: dict = Depends(get_current_user)):
    """
    Tüm sistem görsellerini listeler.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, asset_key, asset_name, mime_type, 
                   LENGTH(asset_data) as size_bytes,
                   created_at, updated_at
            FROM system_assets
            ORDER BY asset_key
        """)
        
        assets = [dict(row) for row in cur.fetchall()]
        return {"assets": assets}
        
    finally:
        conn.close()


@router.post("/{asset_key}")
async def upload_asset(
    asset_key: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    Yeni sistem görseli yükler veya mevcut olanı günceller.
    
    Desteklenen asset_key'ler:
    - favicon: Sekme ikonu
    - login_logo: Login sayfası logosu  
    - sidebar_logo: Sidebar logosu
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    
    # Sadece belirli asset key'lere izin ver
    allowed_keys = ["favicon", "login_logo", "sidebar_logo", "header_logo", "login_video"]
    if asset_key not in allowed_keys:
        raise HTTPException(
            status_code=400, 
            detail=f"Geçersiz asset_key. İzin verilenler: {allowed_keys}"
        )
    
    # Dosya tipini kontrol et
    allowed_types = ["image/png", "image/jpeg", "image/svg+xml", "image/x-icon", "image/ico", "video/mp4"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz dosya tipi: {file.content_type}. İzin verilenler: {allowed_types}"
        )
    
    # Dosyayı oku
    file_data = await file.read()
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Upsert (varsa güncelle, yoksa ekle)
        cur.execute("""
            INSERT INTO system_assets (asset_key, asset_name, mime_type, asset_data, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (asset_key) DO UPDATE SET
                asset_name = EXCLUDED.asset_name,
                mime_type = EXCLUDED.mime_type,
                asset_data = EXCLUDED.asset_data,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id
        """, (asset_key, file.filename, file.content_type, file_data))
        
        result = cur.fetchone()
        conn.commit()
        
        log_system_event(
            "INFO",
            f"Asset güncellendi: {asset_key} ({file.filename}, {len(file_data)} bytes). Kullanıcı: {current_user.get('username')}",
            "assets"
        )
        
        return {
            "success": True,
            "message": f"Asset '{asset_key}' başarıyla güncellendi",
            "asset_id": result["id"],
            "size_bytes": len(file_data)
        }
        
    except Exception as e:
        conn.rollback()
        log_error(f"Asset yükleme hatası: {e}", "assets")
        raise HTTPException(status_code=500, detail="Asset yüklenirken bir hata oluştu.")
    finally:
        conn.close()


@router.delete("/{asset_key}")
async def delete_asset(
    asset_key: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Sistem görselini siler.
    """
    if not current_user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin yetkisi gerekli")
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        cur.execute("DELETE FROM system_assets WHERE asset_key = %s RETURNING id", (asset_key,))
        result = cur.fetchone()
        
        if not result:
            raise HTTPException(status_code=404, detail=f"Asset bulunamadı: {asset_key}")
        
        conn.commit()
        
        log_system_event(
            "WARNING",
            f"Asset silindi: {asset_key}. Kullanıcı: {current_user.get('username')}",
            "assets"
        )
        
        return {"success": True, "message": f"Asset '{asset_key}' silindi"}
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        log_error(f"Asset silme hatası: {e}", "assets")
        raise HTTPException(status_code=500, detail="Asset silinirken bir hata oluştu.")
    finally:
        conn.close()
