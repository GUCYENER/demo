"""
VYRA Oracle Test DB — Temizleme Scripti
========================================
Tüm test tablolarını ve verilerini siler.

Kullanım:
  python 04_cleanup.py --host localhost --port 1521 --user VYRA_TEST --password VyraTest2026 --service FREEPDB1
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="VYRA Oracle Test DB Temizleme")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", default="1521")
    parser.add_argument("--user", default="VYRA_TEST")
    parser.add_argument("--password", default="VyraTest2026")
    parser.add_argument("--service", default="FREEPDB1")
    args = parser.parse_args()

    try:
        import oracledb
    except ImportError:
        print("[HATA] oracledb modülü bulunamadı!")
        sys.exit(1)

    dsn = f"{args.host}:{args.port}/{args.service}"
    print(f"Oracle DB'ye bağlanılıyor: {args.user}@{dsn}")

    conn = oracledb.connect(user=args.user, password=args.password, dsn=dsn)
    cur = conn.cursor()

    # Tablolar (FK sırasına göre — önce child tablolar)
    tables = [
        "ODEMELER", "FATURALAR", "SIPARIS_DETAY", "SIPARISLER",
        "DESTEK_TALEPLERI", "ABONELIKLER", "ADRESLER",
        "URUNLER", "URUN_KATEGORILERI", "KAMPANYALAR", "MUSTERILER"
    ]

    print("\nTablolar siliniyor...")
    for t in tables:
        try:
            cur.execute(f"DROP TABLE {t} CASCADE CONSTRAINTS PURGE")
            print(f"  [OK] {t} silindi")
        except Exception as e:
            if "ORA-00942" in str(e):
                print(f"  [--] {t} zaten yok")
            else:
                print(f"  [HATA] {t}: {str(e)[:80]}")

    conn.commit()
    conn.close()
    print("\n[OK] Temizleme tamamlandı!")


if __name__ == "__main__":
    main()
