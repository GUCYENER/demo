"""
VYRA L1 Support API - Address Routes
======================================
Türkiye il/ilçe/mahalle endpoint'leri.
Uygulama başlangıcında turkiyeapi.dev'den DB'ye sync edilir.
v2.53.0
"""

import logging
import threading
from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException
from app.core.db import get_db_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/address", tags=["address"])

# -----------------------------------------------------------
# External API → DB Sync (startup'ta bir kez çalışır)
# -----------------------------------------------------------

TURKEY_API = "https://turkiyeapi.dev/api/v1"


def sync_address_data():
    """
    Uygulama başlangıcında Türkiye adres verilerini
    API'den çekip DB'ye kaydeder. Zaten veri varsa atlar.
    Background thread'de çalışır.
    """
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as cnt FROM address_provinces")
            count = cur.fetchone()["cnt"]
            if count > 0:
                logger.info(f"[Address] DB'de {count} il zaten mevcut, sync atlanıyor.")
                return

        logger.info("[Address] Adres verisi bulunamadı, API'den indiriliyor...")
        _sync_from_api()
        logger.info("[Address] Adres sync tamamlandı.")
    except Exception as e:
        logger.error(f"[Address] Sync hatası: {e}")


def _sync_from_api():
    """Türkiye API'den il/ilçe verisi çekip DB'ye yazar.
    
    API Yapısı:
    - GET /provinces → 81 il (her ilin altında districts array'i var)
    - Districts içinde neighborhoods YOK
    - Mahalleler ayrı endpoint: GET /districts/{id} → neighborhoods array
    
    Not: Mahalle verisi çok büyük (binlerce), startup'ta sadece il+ilçe yüklenir.
         Mahalleler kullanıcı istediğinde lazy-load ile çekilir.
    """
    import httpx

    try:
        # SSL verify=False: kurumsal proxy sertifika sorununu aşmak için
        with httpx.Client(timeout=30.0, verify=False) as client:
            # 1. İlleri çek (ilçeler dahil)
            res = client.get(f"{TURKEY_API}/provinces")
            res.raise_for_status()
            provinces = res.json().get("data", [])

            with get_db_context() as conn:
                cur = conn.cursor()

                for prov in provinces:
                    prov_id = prov.get("id")
                    prov_name = prov.get("name", "")
                    if not prov_id or not prov_name:
                        continue

                    # İl kaydet
                    cur.execute(
                        "INSERT INTO address_provinces (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                        (prov_id, prov_name)
                    )

                    # İlçeleri kaydet (provinces response'unda geliyor)
                    districts = prov.get("districts", [])
                    for dist in districts:
                        dist_id = dist.get("id")
                        dist_name = dist.get("name", "")
                        if not dist_id or not dist_name:
                            continue

                        cur.execute(
                            "INSERT INTO address_districts (id, province_id, name) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
                            (dist_id, prov_id, dist_name)
                        )

                conn.commit()

            logger.info(f"[Address] {len(provinces)} il ve ilçeleri başarıyla kaydedildi.")

    except Exception as e:
        logger.error(f"[Address] API sync hatası: {e}")
        raise


def start_address_sync():
    """Background thread'de adres sync başlatır."""
    thread = threading.Thread(target=sync_address_data, daemon=True)
    thread.start()


# -----------------------------------------------------------
# API Endpoints (DB'den okur)
# -----------------------------------------------------------

@router.get("/provinces")
def get_provinces():
    """Tüm illeri döndürür."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM address_provinces ORDER BY name")
        rows = cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/districts/{province_id}")
def get_districts(province_id: int):
    """Bir ilin ilçelerini döndürür."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM address_districts WHERE province_id = %s ORDER BY name",
            (province_id,)
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


@router.get("/neighborhoods/{district_id}")
def get_neighborhoods(district_id: int):
    """Bir ilçenin mahallelerini döndürür.
    
    Önce DB'de arar. Yoksa turkiyeapi.dev'den çekip DB'ye kaydeder (lazy-load).
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM address_neighborhoods WHERE district_id = %s ORDER BY name",
            (district_id,)
        )
        rows = cur.fetchall()
        if rows:
            return [dict(r) for r in rows]

    # DB'de yok — API'den çek ve kaydet
    try:
        import httpx
        with httpx.Client(timeout=15.0, verify=False) as client:
            res = client.get(f"{TURKEY_API}/districts/{district_id}")
            res.raise_for_status()
            data = res.json().get("data", {})
            neighborhoods = data.get("neighborhoods", [])

            if neighborhoods:
                with get_db_context() as conn:
                    cur = conn.cursor()
                    for neigh in neighborhoods:
                        neigh_name = neigh if isinstance(neigh, str) else neigh.get("name", "")
                        if neigh_name:
                            cur.execute(
                                "INSERT INTO address_neighborhoods (district_id, name) VALUES (%s, %s)",
                                (district_id, neigh_name)
                            )
                    conn.commit()

                # Tekrar DB'den oku (ID'lerle birlikte)
                with get_db_context() as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT id, name FROM address_neighborhoods WHERE district_id = %s ORDER BY name",
                        (district_id,)
                    )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]

    except Exception as e:
        logger.error(f"[Address] Mahalle lazy-load hatası (district_id={district_id}): {e}")

    return []
