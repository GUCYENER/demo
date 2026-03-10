# 🚀 VYRA Production Deployment Rehberi

## Deployment Seçenekleri

| Yöntem | Açıklama | Script |
|--------|----------|--------|
| **🆕 Sunucu (Server)** | Sistem Python + Sistem PostgreSQL | `deploy/start_server.ps1` |
| Portable (Offline) | Portable Python + Embedded PostgreSQL | `deploy/start_production.ps1` |
| Docker | Container tabanlı | `docker-compose up -d` |

---

## 🖥️ Yöntem A: Sunucu Kurulumu (GitHub → Canlı)

**Bu yöntem:** GitHub'dan kodu çekip, sunucuda internet üzerinden tüm bağımlılıkları kurar.

### Mimari

```
                          ┌──────────────────────────┐
  Kullanıcı               │     Windows Server       │
  (Tarayıcı)              │                          │
      │                   │  ┌────────────────────┐  │
      │ :80 / :443        │  │     Nginx           │  │
      ├──────────────────▶│  │  (Reverse Proxy)    │  │
      │                   │  │   Port 80/443       │  │
      │                   │  └──┬──────────┬───────┘  │
      │                   │     │          │          │
      │                   │   /api/*    /* (statik)   │
      │                   │     │          │          │
      │                   │  ┌──▼────┐  ┌──▼───────┐  │
      │                   │  │Uvicorn│  │ Frontend │  │
      │                   │  │:8002  │  │ dosyalar │  │
      │                   │  │4 work.│  │ (HTML/JS)│  │
      │                   │  └──┬────┘  └──────────┘  │
      │                   │     │                     │
      │                   │  ┌──▼──────────────────┐  │
      │                   │  │   PostgreSQL        │  │
      │                   │  │   Port 5005         │  │
      │                   │  │   (Windows Service) │  │
      │                   │  └─────────────────────┘  │
      │                   └──────────────────────────┘
```

### Ön Gereksinimler

| Gereksinim | Kontrol Komutu | Notlar |
|------------|---------------|--------|
| Windows Server 2019+ | `winver` | 64-bit |
| PowerShell 5.1+ | `$PSVersionTable.PSVersion` | Genelde yüklü gelir |
| Python 3.10+ | `python --version` | [python.org](https://www.python.org/downloads/) |
| PostgreSQL 14+ | `psql --version` | [postgresql.org](https://www.postgresql.org/download/windows/) |
| İnternet erişimi | `ping google.com` | pip install ve Nginx indirme için |
| Git (opsiyonel) | `git --version` | GitHub'dan çekmek için |

### ADIM 1: PostgreSQL Kurulumu (Tek Seferlik)

1. [PostgreSQL'i indirin](https://www.postgresql.org/download/windows/) ve kurun.
2. **Kurulum sırasında:**
   - Port: `5005` (varsayılan 5432 yerine)
   - Superuser şifresi: not edin (sonra `.env`'de kullanılacak)
   - pgvector extension'ı da kurun (varsa)
3. **Kurulum sonrası:** PostgreSQL Windows Service olarak otomatik çalışır.

> ⚠️ PostgreSQL kurulumunda port 5005 seçilmezse, kurulum sonrası `postgresql.conf` dosyasında `port = 5005` olarak değiştirin ve servisi restart edin.

```powershell
# postgresql.conf konumu (varsayılan):
# C:\Program Files\PostgreSQL\16\data\postgresql.conf

# Port değişikliği sonrası servisi yeniden başlatın:
Restart-Service postgresql-x64-16
```

### ADIM 2: Proje Dosyalarını Kopyala

```powershell
# Git ile:
cd D:\
git clone https://github.com/YASINF/vyra.git VYRA
cd D:\VYRA

# VEYA: ZIP olarak indirip D:\VYRA klasörüne açın
```

### ADIM 3: İlk Kurulum (Otomatik)

```powershell
cd D:\VYRA

# Tek komutla tüm kurulum:
.\deploy\setup_server.ps1

# PostgreSQL farklı bir dizindeyse:
.\deploy\setup_server.ps1 -PgBinDir "C:\Program Files\PostgreSQL\16\bin"
```

Bu script sırayla:
1. ✅ Python kontrol eder
2. ✅ Virtual environment oluşturur (`.venv/`)
3. ✅ pip ile tüm bağımlılıkları yükler (PyTorch CPU dahil)
4. ✅ `.env` dosyasını hazırlar
5. ✅ PostgreSQL'de veritabanı & kullanıcı oluşturur
6. ✅ Alembic migration çalıştırır
7. ✅ Nginx indirir ve yapılandırır

### ADIM 4: .env Dosyasını Düzenle

Kurulum sonrası `.env` dosyasını mutlaka düzenleyin:

```ini
# ⚠️ ZORUNLU değişiklikler:
debug=False

# JWT Secret (her sunucuda benzersiz, 32+ karakter)
# Üretmek için: python -c "import secrets; print(secrets.token_urlsafe(48))"
JWT_SECRET=BURAYA_GUCLU_BIR_SECRET_YAZ

# PostgreSQL
DB_HOST=localhost
DB_PORT=5005
DB_NAME=vyra
DB_USER=vyra_app
DB_PASSWORD=veritabani_sifresi

# PostgreSQL bin dizini
PG_BIN_DIR=C:\Program Files\PostgreSQL\16\bin

# CORS — Sunucunun IP veya domain'i
CORS_ORIGINS=http://sunucu-ip-adresi,http://vyra.company.com
```

### ADIM 5: 🚀 Servisleri Başlat

```powershell
cd D:\VYRA

# Tüm servisleri başlat
.\deploy\start_server.ps1

# 8 worker ile (yoğun kullanım):
.\deploy\start_server.ps1 -Workers 8

# Nginx olmadan:
.\deploy\start_server.ps1 -SkipNginx
```

### ADIM 6: Doğrulama

| Test | URL | Beklenen |
|------|-----|----------|
| Login sayfası | `http://SUNUCU-IP/login.html` | Login formu görünmeli |
| API sağlık | `http://SUNUCU-IP/api/health` | `{"status":"ok"}` |
| Swagger (kapalı) | `http://SUNUCU-IP/docs` | 404 (production'da kapalı) |

---

## 📁 Klasör Yapısı (Sunucu Kurulumu Sonrası)

```
D:\VYRA\
├── .venv\              # Python venv (setup_server.ps1 oluşturur)
├── app\                # Backend Python kodu
├── frontend\           # Frontend HTML/JS/CSS
├── deploy\             # Deployment scriptleri
│   ├── setup_server.ps1    # İlk kurulum
│   ├── start_server.ps1    # Başlat
│   ├── stop_server.ps1     # Durdur
│   └── nginx\              # Nginx config template
├── migrations\         # Alembic DB migration
├── nginx\              # Nginx (setup_server.ps1 indirir)
├── models\             # ML modelleri (runtime indirilir)
├── .env                # Ortam değişkenleri (GİZLİ!)
├── .env.example        # .env şablonu
├── requirements.txt    # Python bağımlılıkları
└── alembic.ini         # DB migration config
```

> 📌 `python/`, `pgsql/`, `redis/`, `offline_packages/` klasörleri **SADECE** portable kurulumda kullanılır.
> Sunucu kurulumunda bu klasörler **oluşturulmaz**.

---

## 📋 Günlük Operasyonlar

### Servisleri Durdurma
```powershell
.\deploy\stop_server.ps1           # Backend + Nginx durdur
.\deploy\stop_server.ps1 -StopDB   # DB dahil durdur
```

### Sunucu Yeniden Başladığında
PostgreSQL otomatik başlar (Windows Service). Sadece backend ve Nginx'i başlatın:
```powershell
cd D:\VYRA
.\deploy\start_server.ps1
```

> 💡 **Otomatik başlatma için:** Task Scheduler'da bir görev oluşturun:
> - Trigger: "At system startup"
> - Action: `powershell.exe -ExecutionPolicy Bypass -File D:\VYRA\deploy\start_server.ps1`
> - Run as: Administrator

### Güncelleme (Yeni Versiyon Deploy)
```powershell
# 1. Servisleri durdur
.\deploy\stop_server.ps1

# 2. Yeni kodu çek
git pull origin master

# 3. Python bağımlılıkları güncelle (değiştiyse)
.\.venv\Scripts\pip.exe install -r requirements.txt

# 4. Servisleri başlat (migration otomatik çalışır)
.\deploy\start_server.ps1
```

### Log Takibi
```powershell
# Nginx logları
Get-Content D:\VYRA\nginx\logs\vyra_access.log -Tail 20
Get-Content D:\VYRA\nginx\logs\vyra_error.log -Tail 20

# Backend logları
Get-Content D:\VYRA\logs\vyra.log -Tail 20

# PostgreSQL logları (sistem kurulumunda)
Get-Content "C:\Program Files\PostgreSQL\16\data\log\*.log" -Tail 20
```

---

## 🖥️ Yöntem B: Portable Kurulum (Offline)

Bu yöntem internet OLMAYAN sunucular için. Tüm bağımlılıklar projeyle birlikte taşınır.

Detaylı bilgi: Mevcut scriptler (`canlida_calistir.bat`, `deploy/start_production.ps1`) bu yöntemi kullanır.

---

## 🐳 Yöntem C: Docker

```powershell
# Docker Compose ile tek komutla:
docker-compose up -d

# Durdurmak:
docker-compose down
```

---

## 🔧 Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| Port 80 kullanımda | IIS varsa durdurun: `iisreset /stop` |
| PostgreSQL başlamıyor | `services.msc`'den servisi kontrol edin |
| DB bağlantı hatası | `.env`'de DB_PORT=5005, DB_PASSWORD kontrolü |
| Backend başlamıyor | `.env`'deki `JWT_SECRET` kontrolü (32+ karakter) |
| Nginx config hatası | `.\nginx\nginx.exe -t` ile test edin |
| CORS hatası | `.env`'de `CORS_ORIGINS` güncelleyin |
| Sayfa yüklenmiyor | Firewall port 80 açık mı? |
| venv bulunamadı | `.\deploy\setup_server.ps1` çalıştırın |
| pip hata veriyor | Internet bağlantısını kontrol edin |
| ML modeli indiremiyor | Proxy ayarlarını kontrol edin |

### Firewall Ayarları
```powershell
# Port 80 aç (HTTP) — Yönetici PowerShell'de
New-NetFirewallRule -DisplayName "VYRA HTTP" -Direction Inbound -Port 80 -Protocol TCP -Action Allow

# Port 443 aç (HTTPS — SSL kullanacaksanız)
New-NetFirewallRule -DisplayName "VYRA HTTPS" -Direction Inbound -Port 443 -Protocol TCP -Action Allow
```

---

## 🔒 Güvenlik Kontrol Listesi

- [ ] `.env` dosyasında `debug=False`
- [ ] `JWT_SECRET` en az 32 karakter, benzersiz
- [ ] Admin şifresi değiştirildi (DB'de)
- [ ] `CORS_ORIGINS` sadece izin verilen domain'ler
- [ ] Swagger/ReDoc production'da kapalı (`/docs` → 404)
- [ ] Firewall sadece port 80 (ve 443) açık
- [ ] PostgreSQL veritabanı backup planında
- [ ] Windows Update güncel
- [ ] `.env` dosyası Git'e commit edilmemiş (.gitignore'da)
