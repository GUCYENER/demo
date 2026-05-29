"""
VYRA Oracle Test DB — Otomatik Kurulum Scripti
===============================================
Bu script:
  1. Docker Desktop + Oracle Free 23ai container'ını kurar (tercih edilen)
     VEYA mevcut Oracle instance'a bağlanır
  2. VYRA_TEST schema'sını oluşturur (tablolar, FK, index)
  3. 50 müşteri, 20 ürün, 30 sipariş, fatura, ödeme verisi ekler

Kullanım:
  cd Gecici_Dosyalar_Sil/oracle_local_test
  python 03_setup_oracle.py                          # Docker ile otomatik
  python 03_setup_oracle.py --host localhost --port 1521 --user VYRA_TEST --password VyraTest2026 --service FREEPDB1
"""

import argparse
import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def check_docker():
    """Docker Desktop erişilebilir mi?"""
    for cmd in ["docker", "docker.exe"]:
        try:
            result = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def start_oracle_container(docker_cmd):
    """Docker Compose ile Oracle Free 23ai container'ını başlat."""
    compose_file = os.path.join(SCRIPT_DIR, "docker-compose.yml")
    if not os.path.exists(compose_file):
        print("[HATA] docker-compose.yml bulunamadı!")
        return False

    print("\n[1/3] Oracle Free 23ai container başlatılıyor...")
    print("      (İlk seferde image indirme ~500MB, container init ~2 dk)")

    result = subprocess.run(
        [docker_cmd, "compose", "-f", compose_file, "up", "-d"],
        capture_output=True, text=True, cwd=SCRIPT_DIR
    )
    if result.returncode != 0:
        print(f"[HATA] Docker Compose hatası:\n{result.stderr}")
        return False

    print("[OK] Container başlatıldı. DB hazır olmasını bekliyoruz...")

    # DB hazır olana kadar bekle (max 3 dk)
    for i in range(36):  # 36 x 5s = 180s
        time.sleep(5)
        try:
            log = subprocess.run(
                [docker_cmd, "logs", "--tail", "5", "vyra-oracle-test"],
                capture_output=True, text=True, timeout=10
            )
            if "DATABASE IS READY TO USE" in log.stdout:
                print(f"[OK] Oracle DB hazır! ({(i+1)*5} saniyede)")
                return True
            print(f"      Bekleniyor... ({(i+1)*5}s)")
        except Exception:
            pass

    print("[UYARI] 3 dakika doldu ama DB henüz hazır değil. Birkaç dakika daha bekleyip tekrar deneyin.")
    return False


def connect_oracle(host, port, user, password, service):
    """Oracle DB'ye oracledb ile bağlan."""
    try:
        import oracledb
    except ImportError:
        print("[HATA] oracledb modülü bulunamadı! pip install oracledb")
        sys.exit(1)

    dsn = f"{host}:{port}/{service}"
    print(f"\n[2/3] Oracle DB'ye bağlanılıyor: {user}@{dsn}")

    try:
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        print(f"[OK] Bağlantı başarılı! Oracle {conn.version}")
        return conn
    except Exception as e:
        print(f"[HATA] Bağlantı hatası: {e}")
        return None


def execute_sql_file(conn, filepath, label):
    """SQL dosyasını çalıştır (statement-by-statement)."""
    if not os.path.exists(filepath):
        print(f"[HATA] {filepath} bulunamadı!")
        return False

    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    cur = conn.cursor()
    # SQL statement'ları ';' ile ayır
    statements = []
    current = []
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        current.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip().rstrip(";")
            if stmt:
                statements.append(stmt)
            current = []

    success = 0
    errors = 0
    for i, stmt in enumerate(statements):
        try:
            cur.execute(stmt)
            success += 1
        except Exception as e:
            err_msg = str(e)
            # Zaten var hatalarını atla
            if "ORA-00955" in err_msg or "already exists" in err_msg.lower():
                success += 1
            elif "ORA-00001" in err_msg:  # unique constraint — veri zaten var
                success += 1
            else:
                errors += 1
                # Sadece ilk hatanın detayını göster
                if errors <= 3:
                    short_stmt = stmt[:80].replace("\n", " ")
                    print(f"  [UYARI] Statement {i+1} hatası: {err_msg[:120]}")
                    print(f"          SQL: {short_stmt}...")

    conn.commit()
    print(f"[OK] {label}: {success} başarılı, {errors} hata")
    return errors == 0


def verify_data(conn):
    """Oluşturulan verileri doğrula."""
    cur = conn.cursor()
    tables = [
        "MUSTERILER", "ADRESLER", "URUN_KATEGORILERI", "URUNLER",
        "SIPARISLER", "SIPARIS_DETAY", "FATURALAR", "ODEMELER",
        "ABONELIKLER", "DESTEK_TALEPLERI", "KAMPANYALAR"
    ]

    print("\n" + "=" * 55)
    print("  TABLO ADI                  KAYIT SAYISI")
    print("=" * 55)

    total = 0
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            count = cur.fetchone()[0]
            total += count
            print(f"  {t:<28} {count:>6}")
        except Exception as e:
            print(f"  {t:<28} HATA: {str(e)[:40]}")

    print("-" * 55)
    print(f"  {'TOPLAM':<28} {total:>6}")
    print("=" * 55)

    # FK ilişki kontrolü
    cur.execute("""
        SELECT COUNT(*) FROM all_constraints
        WHERE owner = USER AND constraint_type = 'R'
    """)
    fk_count = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM all_indexes
        WHERE owner = USER
    """)
    idx_count = cur.fetchone()[0]

    print(f"\n  FK İlişkiler: {fk_count}")
    print(f"  Indexler:     {idx_count}")

    return total > 0


def print_vyra_config(host, port, user, password, service):
    """VYRA'ya eklenecek bağlantı bilgilerini göster."""
    print("\n" + "=" * 60)
    print("  VYRA Kaynak Ekleme Bilgileri")
    print("=" * 60)
    print(f"""
  Kaynak Adı:     ORACLE-LOCAL-TEST
  DB Tipi:        Oracle
  Host:           {host}
  Port:           {port}
  Service Name:   {service}
  Kullanıcı:      {user}
  Şifre:          {password}

  VYRA UI → Sistem Parametreleri → Bağlı Kaynaklar → Yeni Kaynak Ekle
  Bağlantı testi yapıp kaydedin, ardından DB Keşif çalıştırın.
""")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="VYRA Oracle Test DB Kurulumu")
    parser.add_argument("--host", default="localhost", help="Oracle host (default: localhost)")
    parser.add_argument("--port", default="1521", help="Oracle port (default: 1521)")
    parser.add_argument("--user", default="VYRA_TEST", help="Oracle user (default: VYRA_TEST)")
    parser.add_argument("--password", default="VyraTest2026", help="Oracle password")
    parser.add_argument("--service", default="FREEPDB1", help="Oracle service name (default: FREEPDB1)")
    parser.add_argument("--skip-docker", action="store_true", help="Docker adımını atla, direkt bağlan")
    parser.add_argument("--schema-only", action="store_true", help="Sadece schema oluştur (veri ekleme)")
    parser.add_argument("--data-only", action="store_true", help="Sadece veri ekle (schema zaten var)")
    args = parser.parse_args()

    print("=" * 60)
    print("  VYRA Oracle Test DB — Otomatik Kurulum")
    print("=" * 60)

    # Adım 1: Docker ile Oracle başlat (opsiyonel)
    if not args.skip_docker:
        docker_cmd = check_docker()
        if docker_cmd:
            print(f"\n[OK] Docker bulundu: {docker_cmd}")
            start_oracle_container(docker_cmd)
        else:
            print("\n[BİLGİ] Docker bulunamadı.")
            print("  Seçenekler:")
            print("    1. Docker Desktop kurun: https://www.docker.com/products/docker-desktop/")
            print("    2. Oracle Database Free 23ai kurun: https://www.oracle.com/database/free/")
            print("    3. Mevcut Oracle instance varsa --skip-docker --host <ip> ile çalıştırın")
            print()

    # Adım 2: Oracle'a bağlan
    conn = connect_oracle(args.host, args.port, args.user, args.password, args.service)
    if not conn:
        print("\n[HATA] Oracle DB'ye bağlanılamadı. Bağlantı bilgilerini kontrol edin.")
        print("  Örnek: python 03_setup_oracle.py --skip-docker --host 192.168.1.100 --port 1521 --user MYUSER --password MYPASS --service ORCL")
        sys.exit(1)

    # Adım 3: Schema ve veri oluştur
    schema_file = os.path.join(SCRIPT_DIR, "01_create_schema.sql")
    data_file = os.path.join(SCRIPT_DIR, "02_insert_sample_data.sql")

    if not args.data_only:
        print(f"\n[3/3] Schema oluşturuluyor...")
        execute_sql_file(conn, schema_file, "Schema (DDL)")

    if not args.schema_only:
        print(f"      Örnek veriler ekleniyor...")
        execute_sql_file(conn, data_file, "Örnek Veri (DML)")

    # Doğrulama
    verify_data(conn)

    # VYRA bağlantı bilgileri
    print_vyra_config(args.host, args.port, args.user, args.password, args.service)

    conn.close()
    print("[OK] Kurulum tamamlandı!\n")


if __name__ == "__main__":
    main()
