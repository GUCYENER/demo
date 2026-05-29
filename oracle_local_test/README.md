# VYRA Oracle Test DB — Local Kurulum

## Hizli Baslangic

### Yontem 1: Docker Desktop (Onerilen)

```bash
# 1. Docker Desktop kur (yoksa 05_docker_install.bat calistir)
# 2. Container baslat
cd Gecici_Dosyalar_Sil/oracle_local_test
docker compose up -d

# 3. Hazir olmasini bekle (~2 dk)
docker compose logs -f oracle-db | grep "DATABASE IS READY"

# 4. Schema + veri olustur
python 03_setup_oracle.py
```

### Yontem 2: Mevcut Oracle Instance

```bash
# Direkt baglan (Docker atlaniyor)
python 03_setup_oracle.py --skip-docker --host 192.168.1.100 --port 1521 --user MYUSER --password MYPASS --service ORCL
```

### Yontem 3: Oracle Database Free 23ai (Windows)

1. https://www.oracle.com/database/free/ adresinden indir
2. Installer'i calistir, sifre olarak `VyraTest2026` belirle
3. sqlplus ile VYRA_TEST kullanici olustur:
   ```sql
   sqlplus sys/VyraTest2026@localhost:1521/FREEPDB1 as sysdba
   CREATE USER VYRA_TEST IDENTIFIED BY VyraTest2026;
   GRANT CONNECT, RESOURCE, UNLIMITED TABLESPACE TO VYRA_TEST;
   ```
4. Schema + veri olustur:
   ```bash
   python 03_setup_oracle.py --skip-docker
   ```

---

## Baglanti Bilgileri

| Alan           | Deger              |
|----------------|--------------------|
| Host           | localhost          |
| Port           | 1521               |
| Service Name   | FREEPDB1           |
| Kullanici      | VYRA_TEST          |
| Sifre          | VyraTest2026       |

## Schema (11 Tablo)

```
MUSTERILER (50 kayit) ─┬─ ADRESLER (10 kayit)
                        ├─ SIPARISLER (20 kayit) ── SIPARIS_DETAY (20 kayit)
                        │       └── FATURALAR (10 kayit) ── ODEMELER (9 kayit)
                        ├─ ABONELIKLER (20 kayit)
                        └─ DESTEK_TALEPLERI (10 kayit)

URUN_KATEGORILERI (6) ── URUNLER (20)
KAMPANYALAR (4)
```

## VYRA'ya Kaynak Ekleme

1. VYRA UI → Sistem Parametreleri → Bagli Kaynaklar
2. "Yeni Kaynak Ekle" → Oracle sec
3. Baglanti bilgilerini gir (yukaridaki tablo)
4. "Baglanti Testi" → Basarili
5. Kaydet → DB Kesif calistir

## Dosyalar

| Dosya                    | Aciklama                                  |
|--------------------------|-------------------------------------------|
| docker-compose.yml       | Oracle Free 23ai container tanimlamasi    |
| 01_create_schema.sql     | 11 tablo DDL (FK, index dahil)            |
| 02_insert_sample_data.sql| 50 musteri, 20 urun, siparis, fatura vb.  |
| 03_setup_oracle.py       | Otomatik kurulum scripti                  |
| 04_cleanup.py            | Tum tablolari siler                       |
| 05_docker_install.bat    | Docker Desktop kurulum rehberi            |

## Temizleme

```bash
# Tablolari sil
python 04_cleanup.py

# Docker container'i durdur ve sil
docker compose down -v
```
