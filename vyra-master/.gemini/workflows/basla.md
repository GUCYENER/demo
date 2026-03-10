---
description: Projenin başlatılması için hazırlık ritüeli
---

# Başlangıç Ritüeli (/basla)

Yeni bir oturum veya görev başlatırken uygulanacak adımlar.

## 1. Ortam Kontrolü
// turbo
```powershell
# Backend sunucusunun çalışıp çalışmadığını kontrol et
try { $r = Invoke-WebRequest -Uri "http://localhost:8002/api/health" -UseBasicParsing -TimeoutSec 5; Write-Host "✅ Backend: $($r.StatusCode)" } catch { Write-Host "❌ Backend çalışmıyor" }
```

## 2. Git Durum Kontrolü
// turbo
```powershell
& 'C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe' status --short
```

## 3. Mevcut Versiyon Kontrolü
// turbo
```powershell
python -c "import sys; sys.path.insert(0, r'd:\VYRA'); from app.core.config import APP_VERSION; print(f'Mevcut versiyon: {APP_VERSION}')"
```

## 4. Log Sağlık Kontrolü
// turbo
```powershell
# Son 1 saatteki ERROR loglarını kontrol et
$cutoff = (Get-Date).AddHours(-1).ToString("yyyy-MM-ddTHH:mm:ss")
$logFile = "D:\VYRA\logs\vyra.log"
if (Test-Path $logFile) {
    $errors = Get-Content $logFile -Tail 500 | ForEach-Object { try { $_ | ConvertFrom-Json } catch { $null } } | Where-Object { $_ -ne $null -and $_.level -eq "ERROR" -and $_.ts -ge $cutoff }
    if ($errors.Count -eq 0) {
        Write-Host "✅ LOG: Son 1 saatte ERROR yok" -ForegroundColor Green
    } else {
        Write-Host "⚠️ LOG: Son 1 saatte $($errors.Count) ERROR var" -ForegroundColor Yellow
        $errors | Select-Object -First 5 | ForEach-Object { Write-Host "  [$($_.module)] $($_.msg)" }
    }
} else {
    Write-Host "⚠️ Log dosyası bulunamadı" -ForegroundColor Yellow
}
```

## 5. 🔒 Güvenlik Denetim Kontrol Listesi (Prod Öncesi)

Güvenlik ekibi prod öncesi uygulamayı aşağıdaki kapsamda inceleyecektir. Her geliştirme döngüsünde bu maddeler kontrol edilmelidir.

### 5.1 SQL Injection Önleme
- [ ] **UI → DB Doğrudan Sorgu Yasağı:** Frontend'den doğrudan veritabanına sorgu atılmamalıdır. Tüm veri erişimi backend API üzerinden yapılmalıdır.
- [ ] **Prepared Statements / Parameterized Query:** Tüm SQL sorgularında `%s` placeholder (psycopg2) veya eşdeğer parametrize yöntem kullanılmalıdır. `f-string` ile VALUES/WHERE değeri **asla** sorguya gömülmemelidir.
- [ ] **Kullanıcı Girdileri Doğrudan Eklenmemeli:** Kullanıcıdan gelen veriler (`request body`, `query params`, `path params`) asla string interpolasyon ile SQL sorgusuna eklenmemelidir.
- [ ] **Dinamik Kolon Adı Güvenliği:** Dinamik `SET`/`WHERE` oluşturan yerlerde kolon adları `ALLOWED_COLUMNS` whitelist ile sınırlandırılmalıdır.

### 5.2 ORM / Veri Erişim Katmanı
- [ ] **ORM Kullanımı:** ORM (SQLAlchemy, Hibernate, Entity Framework, Sequelize vb.) tercih edilmelidir. ORM kullanılmıyorsa, raw SQL'in parametrize edildiği doğrulanmalıdır.
- [ ] **Projede ORM yoksa:** psycopg2 native parameterized query (`%s`) kullanımı tüm dosyalarda tutarlı olmalıdır.

### 5.3 Input Validation
- [ ] **Pydantic Validasyon:** Tüm API endpoint'lerinde giriş verileri Pydantic `BaseModel` + `Field` ile doğrulanmalıdır.
- [ ] **Tip Kontrolü:** Sayısal alanlar `int/float`, metin alanları `str` olarak tip güvenli tanımlanmalıdır.
- [ ] **Uzunluk Kontrolü:** Tüm string alanlarına `min_length` / `max_length` sınırı konmalıdır.
- [ ] **Format Kontrolü:** Kullanıcı adı, e-posta, telefon gibi alanlara `pattern` (regex) veya format validasyonu uygulanmalıdır.
- [ ] **Query Parametreleri:** `page`, `per_page`, `search` gibi query parametrelerine `ge`, `le`, `max_length` sınırları verilmelidir.

### 5.4 Stored Procedure Güvenliği
- [ ] **Parametreli Yazım:** Stored Procedure kullanılıyorsa, tüm parametreler `%s` placeholder ile aktarılmalıdır. SP içinde dinamik SQL (`EXECUTE format(...)`) kullanılmamalıdır.

### 5.5 Least Privilege (En Az Yetki Prensibi)
- [ ] **DB Kullanıcısı:** Uygulama `superuser` (postgres) ile değil, sadece DML yetkili (`SELECT/INSERT/UPDATE/DELETE`) kısıtlı kullanıcı ile bağlanmalıdır.
- [ ] **DDL Yetkisi Yok:** Uygulama DB kullanıcısı `CREATE`, `DROP`, `ALTER` gibi DDL komutları çalıştıramamalıdır.
- [ ] **`.env` Kontrolü:** Üretim ortamında `DB_USER` değeri `postgres` **olmamalıdır**.

### 5.6 Hata Mesajları Gizleme
- [ ] **İç Hata Detayı Sızıntısı Yok:** `HTTPException.detail` içinde `str(e)`, `traceback`, dosya yolu gibi iç bilgiler kullanıcıya döndürülmemelidir.
- [ ] **Genel Mesaj + Backend Log:** Kullanıcıya genel mesaj (`"Bir hata oluştu"`), backend'e detaylı log (`log_error(f"...: {str(e)}")`) yazılmalıdır.
- [ ] **Stack Trace Koruması:** Üretimde `debug=False` olmalı, hata sayfalarında stack trace gösterilmemelidir.

## 6. Hazır
- Ortam kontrolü tamamlandı, görev başlatılabilir.
