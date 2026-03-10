# 🚀 VYRA L1 FastAPI - Hızlı Başlangıç Kılavuzu

## Uygulamayı Başlatma

### Yöntem 1: Otomatik Başlatma (Önerilen) ⚡
Tek komutla backend, frontend ve tarayıcıyı aç:

```powershell
.\start_simple.ps1
```

Bu script şunları yapar:
- ✅ Backend'i başlatır (Port 8000)
- ✅ Frontend'i başlatır (Port 5500)
- ✅ Tarayıcıda login sayfasını açar

---

### Yöntem 2: Manuel Başlatma 🔧

#### 1. Backend'i Başlat
```powershell
# Virtual environment'ı aktif et
.\.venv\Scripts\Activate.ps1

# Backend'i başlat
python -m uvicorn app.api.main:app --reload --port 8000
```

#### 2. Frontend'i Başlat (Yeni terminal)
```powershell
cd frontend
python -m http.server 5500
```

#### 3. Tarayıcıda Aç
```
http://localhost:5500/login.html
```

---

## 📌 Önemli URL'ler

| Servis | URL | Açıklama |
|--------|-----|----------|
| 🎨 **Frontend** | http://localhost:5500/login.html | Login sayfası |
| 🎨 **Ana Sayfa** | http://localhost:5500/home.html | Dashboard |
| 🔧 **Backend API** | http://localhost:8000 | FastAPI root |
| 📚 **API Docs** | http://localhost:8000/docs | Swagger UI |
| 📘 **ReDoc** | http://localhost:8000/redoc | Alternative docs |
| ❤️ **Health Check** | http://localhost:8000/api/health | Server durumu |

---

## 👤 Test Kullanıcısı Oluşturma

1. http://localhost:5500/login.html sayfasını aç
2. "Kayıt Ol" sekmesine tıkla
3. Bilgileri doldur:
   - **Ad Soyad:** Test Kullanıcı
   - **Telefon:** 5551112233 (10 haneli, 5 ile başlayan)
   - **Şifre:** test1234 (min 8 karakter)
4. "Kayıt Ol" butonuna tıkla
5. Otomatik olarak giriş yapılacak

---

## 🛑 Uygulamayı Durdurma

### start_simple.ps1 ile başlattıysanız:
- Açılan PowerShell pencerelerinde `CTRL+C` tuşlayın
- Veya pencereleri kapatın

### Manuel başlattıysanız:
- Her iki terminal'de `CTRL+C` tuşlayın

---

## 🔧 Sorun Giderme

### Port zaten kullanılıyor hatası
```powershell
# Port 8000'i kullanan işlemi bul ve kapat
netstat -ano | findstr :8000
taskkill /PID <PID_NUMARASI> /F

# Port 5500 için aynı işlem
netstat -ano | findstr :5500
taskkill /PID <PID_NUMARASI> /F
```

### SQLite veritabanını sıfırlama
```powershell
Remove-Item data\vyra.db
python -m uvicorn app.api.main:app --reload --port 8000
# Veritabanı otomatik oluşturulacak
```

### Vektör veritabanını yeniden oluşturma
```powershell
python -m app.services.vectorstore_build
```

---

## 📚 Kullanım Akışı

1. **Giriş Yap** → Login sayfasından giriş
2. **Sorun Yaz** → Ana sayfada sorununu detaylı anlat
3. **Çözüm Al** → "Çözüm Öner" butonuna tıkla
4. **Adımları İzle** → VYRA'nın önerdiği adımları uygula
5. **ÇYM Metni** → Gerekirse "ÇYM için çağrı içeriği" kısmını aç ve kopyala
6. **Geçmiş** → "Geçmiş Çözümler" sekmesinden eski ticketları gör

---

## 🎯 İlk Kullanım İçin Örnek Sorular

- "Outlook şifremi unuttum, nasıl değiştirebilirim?"
- "VPN bağlantısı kopuyor, ne yapmalıyım?"
- "LDAP hesabım kilitlendi, nasıl açarım?"
- "Mail kutum doldu, nasıl arşivlerim?"

---

## 📖 Daha Fazla Bilgi

- **Backend Kodu:** `app/` klasörü
- **Frontend Kodu:** `frontend/` klasörü
- **Veritabanı:** `data/vyra.db` (SQLite)
- **Yüklü Dokümanlar:** `docs/` klasörü
- **Vektör DB:** `data/chroma_db_v2/`

---

**İyi çalışmalar! 🚀**
