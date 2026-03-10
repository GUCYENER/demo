"""
VYRA L1 Support - System Assets Seeder
======================================
Mevcut logo ve ikonları veritabanına yükler.
İlk kurulumda veya asset'lerin sıfırlanması gerektiğinde çalıştırılır.
"""

import os
import sys

# Proje kök dizinini path'e ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.db import get_db_conn

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "assets", "images")

# Seed edilecek asset'ler
ASSETS_TO_SEED = [
    {
        "asset_key": "favicon",
        "file_name": "favicon.png",
        "mime_type": "image/png"
    },
    {
        "asset_key": "login_logo",
        "file_name": "vyra_logo_new.png",
        "mime_type": "image/png"
    },
    {
        "asset_key": "sidebar_logo",
        "file_name": "vyra_logo.png",
        "mime_type": "image/png"
    },
    {
        "asset_key": "login_video",
        "file_name": "logo_video.mp4",
        "mime_type": "video/mp4"
    }
]


def seed_assets():
    """Mevcut görselleri veritabanına yükler"""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        seeded_count = 0
        skipped_count = 0
        
        for asset in ASSETS_TO_SEED:
            file_path = os.path.join(ASSETS_DIR, asset["file_name"])
            
            # Dosya var mı kontrol et
            if not os.path.exists(file_path):
                print(f"⚠️  Dosya bulunamadı, atlandı: {asset['file_name']}")
                skipped_count += 1
                continue
            
            # Dosyayı oku
            with open(file_path, "rb") as f:
                file_data = f.read()
            
            # Veritabanına ekle (upsert)
            cur.execute("""
                INSERT INTO system_assets (asset_key, asset_name, mime_type, asset_data, updated_at)
                VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (asset_key) DO UPDATE SET
                    asset_name = EXCLUDED.asset_name,
                    mime_type = EXCLUDED.mime_type,
                    asset_data = EXCLUDED.asset_data,
                    updated_at = CURRENT_TIMESTAMP
            """, (asset["asset_key"], asset["file_name"], asset["mime_type"], file_data))
            
            print(f"✅ Asset yüklendi: {asset['asset_key']} ({asset['file_name']}, {len(file_data)} bytes)")
            seeded_count += 1
        
        conn.commit()
        print(f"\n🎉 Toplam: {seeded_count} asset yüklendi, {skipped_count} atlandı")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Hata: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("=" * 50)
    print("VYRA System Assets Seeder")
    print("=" * 50)
    seed_assets()
