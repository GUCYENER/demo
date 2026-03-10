# Ortam Kurulumu — Geliştirici Rehberi

| Bilgi | Değer |
|-------|-------|
| **Versiyon** | v2.36.1 |
| **Son Güncelleme** | 2026-02-10 |
| **Durum** | ✅ Güncel |

---

## 1. Gereksinimler

| Yazılım | Versiyon | Amaç |
|---------|----------|------|
| Python | 3.13+ | Backend runtime |
| PostgreSQL | 16+ | Veritabanı |
| Git | 2.x+ | Versiyon kontrolü |
| Node.js | – | Gerekli değil (vanilla JS) |

---

## 2. Python Ortamı

### Sanal Ortam Oluşturma
```powershell
cd D:\VYRA
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### Bağımlılık Yükleme
```powershell
pip install -r requirements.txt
```

### Temel Bağımlılıklar
| Paket | Versiyon | Amaç |
|-------|----------|------|
| `fastapi` | 0.115+ | Web framework |
| `uvicorn` | 0.32+ | ASGI server |
| `psycopg2-binary` | 2.9+ | PostgreSQL driver |
| `PyJWT` | 2.9+ | JWT token |
| `bcrypt` | 4.2+ | Şifre hashing |
| `sentence-transformers` | 3.0+ | Embedding modeli |
| `easyocr` | 1.7+ | OCR metin çıkarma |
| `catboost` | 1.2+ | ML ranking |
| `python-docx` | 1.1+ | Word parser |
| `PyPDF2` | 3.0+ | PDF parser |
| `python-pptx` | 1.0+ | PowerPoint parser |
| `openpyxl` | 3.1+ | Excel parser |

---

## 3. PostgreSQL Kurulumu

### Veritabanı Oluşturma
```sql
CREATE DATABASE vyra_db;
CREATE USER vyra_user WITH PASSWORD 'güçlü_şifre';
GRANT ALL PRIVILEGES ON DATABASE vyra_db TO vyra_user;
```

### Bağlantı Bilgileri
| Parametre | Varsayılan |
|-----------|------------|
| Host | `localhost` |
| Port | `5432` |
| Database | `vyra_db` |
| User | `vyra_user` |

---

## 4. Ortam Değişkenleri (.env)

Proje kök dizininde `.env` dosyası oluşturun:

```env
# Database
DB_HOST=localhost
DB_PORT=5432
DB_NAME=vyra_db
DB_USER=vyra_user
DB_PASSWORD=güçlü_şifre

# JWT
JWT_SECRET_KEY=çok_güçlü_ve_uzun_bir_secret_key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_HOURS=12
REFRESH_TOKEN_EXPIRE_DAYS=7

# LLM (Google Gemini)
GOOGLE_API_KEY=your_gemini_api_key

# Server
APP_HOST=0.0.0.0
APP_PORT=8002

# Logging
LOG_LEVEL=INFO
```

---

## 5. Uygulamayı Çalıştırma

### Geliştirme Modu
```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

### Veya baslat.bat ile
```powershell
.\baslat.bat
```

### Erişim
| URL | Açıklama |
|-----|----------|
| `http://localhost:8002` | Ana uygulama |
| `http://localhost:8002/login` | Giriş sayfası |
| `http://localhost:8002/api/docs` | Swagger API dokümantasyonu |
| `http://localhost:8002/api/health` | Sistem sağlığı |

---

## 6. Dosya Yapısı Kılavuzu

### Yeni Backend Endpoint Ekleme
1. `app/api/routes/` altında yeni route dosyası oluştur
2. `app/main.py` içinde router'ı kaydet
3. Gerekirse `app/services/` altında servis dosyası ekle
4. `app/core/schema.py` içinde tablo tanımını ekle (gerekiyorsa)

### Yeni Frontend Modül Ekleme
1. `frontend/assets/js/modules/` altında JS dosyası oluştur
2. `frontend/home.html` içinde `<script>` tag'i ekle (doğru sırada)
3. Gerekirse `frontend/assets/css/` altında CSS dosyası oluştur
4. CSS dosyasını `frontend/home.html` head bölümüne ekle

---

## 7. Git Yapılandırması

### Git Path (Zorunlu)
```powershell
# Proje kuralı: Sistemdeki özel Git yolunu kullan
$GIT = "C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe"
& $GIT status
```

### Commit Öncesi Kontrol Listesi
- [ ] Testler yazıldı mı?
- [ ] Tüm testler geçti mi?
- [ ] Coverage yeterli mi (%80+)?
- [ ] Dokümantasyon güncellendi mi?
- [ ] Versiyon numarası güncellendi mi?
- [ ] Inline CSS yok mu?
- [ ] Lint kontrolü yapıldı mı?

---

> 📌 Kod standartları: [Kod Standartları](coding_standards.md)
