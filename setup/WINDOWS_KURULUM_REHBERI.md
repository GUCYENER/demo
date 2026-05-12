# VYRA L1 Support — Windows Server Kurulum Rehberi

> **Hedef:** İnternet bağlantısı olmayan Windows Server (2016/2019/2022)  
> **Yetkim var:** Yönetici (Administrator) yetkili kullanıcı  
> **Süre:** ~20 dakika  

---

## Bu Proje Nasıl Çalışır?

VYRA, **neredeyse taşınabilir (portable)** bir yapıdadır. Sadece Python ve
Visual C++ kütüphanesi sunucuya kurulmalıdır. Geri her şey proje içinde hazır gelir:

| Bileşen | Durum |
|---------|-------|
| Python 3.13.8 | ❗ Sunucuya kurulması gerekir |
| Visual C++ | ❗ Sunucuya kurulması gerekir |
| Python paketleri | ✅ `setup\windows\packages\` içinde hazır |
| PostgreSQL 16 | ✅ `pgsql\` klasöründe hazır |
| Redis | ✅ `redis\` klasöründe hazır |
| Nginx 1.27 | ✅ `nginx\` klasöründe hazır |
| Veritabanı | ✅ `pgsql\data\` içinde hazır |

---

## Taşınacak Dosyalar

Aşağıdaki klasör ve dosyaları USB veya ağ üzerinden sunucuya kopyalayın.
Örnek hedef: `C:\vyra\`

```
demo_vyra\
├── app\                          ← Uygulama kodu (ZORUNLU)
├── frontend\                     ← Web arayüzü (ZORUNLU)
├── migrations\                   ← Veritabanı güncellemeleri (ZORUNLU)
├── ml_models\                    ← Yapay zeka modelleri (ZORUNLU)
├── pgsql\                        ← PostgreSQL 16 + veritabanı (ZORUNLU)
├── redis\                        ← Redis önbellek sunucusu (ZORUNLU)
├── nginx\                        ← Nginx web sunucusu (ZORUNLU)
├── deploy\                       ← Nginx ayar dosyası (ZORUNLU)
├── scripts\                      ← Yardımcı scriptler (ZORUNLU)
├── setup\
│   └── windows\
│       ├── python-3.13.8-amd64.exe   ← Python kurulum dosyası
│       ├── vc_redist.x64.exe         ← Visual C++ kurulum dosyası
│       └── packages\                 ← Offline Python paketleri
├── .env                          ← Ayar dosyası (ZORUNLU)
├── .env.example                  ← Yedek ayar (alın)
├── alembic.ini                   ← Veritabanı ayarı (ZORUNLU)
├── requirements.txt
├── requirements_frozen.txt
└── canlida_calistir.bat          ← BAŞLATMA DOSYASI
```

### Kopyalamayacaklarınız

```
python\             ← Sunucuya kurulacak, taşımaya gerek yok
.git\
tests\
catboost_info\
setup\linux\
setup\linux_wheels\
setup\rpms\
Gecici_Dosyalar_Sil\
Lib\
include\
```

---

## Kurulum Adımları

### ADIM 1 — Visual C++ Kurulumu

1. `setup\windows\vc_redist.x64.exe` dosyasına **çift tıklayın**
2. **"Install"** butonuna tıklayın
3. Bitince **"Close"** deyin

> Zaten kuruluysa "Already installed" yazar, sorun değil, devam edin.

---

### ADIM 2 — Python 3.13.8 Kurulumu

1. `setup\windows\python-3.13.8-amd64.exe` dosyasına **çift tıklayın**

2. Açılan pencerede **çok önemli:**  
   ☑ **"Add python.exe to PATH"** kutucuğunu işaretleyin  
   (Alt soldaki kutucuk — varsayılan olarak işaretli değildir!)

3. **"Install Now"** butonuna tıklayın

4. Kurulum bitince **"Close"** deyin

5. Kurulumu doğrulayın — Başlat menüsünde **cmd** açıp şunu yazın:
   ```cmd
   python --version
   ```
   `Python 3.13.8` çıkmalı ✅

---

### ADIM 3 — Python Sanal Ortamı ve Paket Kurulumu

Başlat menüsünde **cmd** aratın, **sağ tıklayıp "Yönetici olarak çalıştır"** deyin.

Projeyi koyduğunuz klasöre gidin (örnek `C:\vyra`):

```cmd
cd C:\vyra
```

Sanal ortamı oluşturun:
```cmd
python -m venv python
```

> Bu komut `python\` adında bir klasör oluşturur.
> Birkaç saniye sürer, hata çıkmazsa devam edin.

Paketleri offline kurun:
```cmd
python\Scripts\pip install --no-index --find-links setup\windows\packages -r requirements_frozen.txt
```

> Bu işlem 3-5 dakika sürebilir. Sonunda hata çıkmazsa tamamdır ✅

---

### ADIM 4 — Güvenlik Duvarında Port Açma

Kullanıcıların bağlanabilmesi için **8000** portunu açın.

Yönetici cmd'de şu komutu çalıştırın:

```cmd
netsh advfirewall firewall add rule name="VYRA Web" dir=in action=allow protocol=TCP localport=8000
```

`Ok.` yazısı çıkmalı ✅

---

### ADIM 5 — .env Dosyasını Kontrol Edin

Proje klasöründe `.env` dosyası olmalı.

**Eğer `.env` yoksa:**
```cmd
copy .env.example .env
```

Ardından Not Defteri ile açıp şu satırı sunucu IP'nize göre güncelleyin:
```
CORS_ORIGINS=http://192.168.x.x:8000
debug=False
```

---

### ADIM 6 — Uygulamayı Başlatın

`canlida_calistir.bat` dosyasına **çift tıklayın**.

İlk çalıştırmada birkaç işlem yapılır (1-2 dakika sürer).
Başarılı olursa ekranda şunu görürsünüz:

```
   VYRA v3.x.x - PRODUCTION HAZIR!

   URL:   http://localhost:8000/login.html
```

Tarayıcı otomatik açılır.  
Ağdan erişmek için: **`http://SUNUCU_IP:8000/login.html`**

---

### Uygulamayı Durdurmak

`canlida_durdur.bat` dosyasına **çift tıklayın**.

---

## Sunucu Açılışında Otomatik Başlatma (Opsiyonel)

1. `canlida_calistir.bat` dosyasına **sağ tıklayın** → **"Kısayol Oluştur"**
2. Kısayolu şu klasöre taşıyın:
   ```
   C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup
   ```
3. Sunucu her açıldığında VYRA otomatik başlar ✅

---

## Sorun Giderme

### Cmd ekranı açılıp kapanıyor

`.env` dosyası eksik veya Visual C++ kurulmamış.  
→ Adım 1 ve Adım 5'i kontrol edin.

### "python is not recognized" hatası

Python kurulurken PATH seçeneği işaretlenmemiş.  
→ Python'u kaldırıp Adım 2'yi **"Add python.exe to PATH" işaretleyerek** tekrarlayın.

### Tarayıcıda sayfa açılmıyor

Güvenlik duvarı 8000 portunu engelliyor.  
→ Adım 4'ü tekrarlayın.

### "No matching distribution" hatası (paket kurulumunda)

Bir paket bulunamadı.  
→ İnternet olan bir makinede projeyi açıp `setup\windows\packages\` klasörünün tam kopyalandığından emin olun.

### İlk açılışta çok yavaş

Yapay zeka modeli belleğe yükleniyor, 1-2 dakika bekleyin. Sonraki açılışlar daha hızlı olur.

### Log dosyaları

```
logs\uvicorn.log         ← Uygulama logları
pgsql\data\server.log   ← Veritabanı logları
nginx\logs\error.log    ← Web sunucusu logları
```

---

## Özet — 6 Adım

```
1. vc_redist.x64.exe         → çift tıkla → Install
2. python-3.13.8-amd64.exe   → çift tıkla → "Add to PATH" işaretle → Install Now
3. cmd (yönetici) → cd C:\vyra
   python -m venv python
   python\Scripts\pip install --no-index --find-links setup\windows\packages -r requirements_frozen.txt
4. netsh ... (8000 portu aç)
5. .env dosyasını kontrol et
6. canlida_calistir.bat       → çift tıkla
```

---

*VYRA L1 Support — Windows Server Kurulum Rehberi*  
*Python 3.13.8 | PostgreSQL 16 | Redis 6 | Nginx 1.27*
