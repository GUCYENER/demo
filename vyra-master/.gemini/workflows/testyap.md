---
description: Test senaryolarını çalıştırma ve log kontrolü ile doğrulama ritüeli
---

# Test Execution Ritual (/testyap)

Bu ritüel, test senaryolarının sistematik çalıştırılmasını ve sonuçların log dosyasından doğrulanmasını kapsar.

## 1. Environment Verification
- **Application State**: Backend API ve Frontend sunucularının aktif olduğunu doğrula.
- **Log Verification**: Test olayının timestamp'ini kullanarak logları kontrol et.
- **CLI Redirect Verification**: Tarayıcı tabanlı UI otomasyonu başarısız olduğunda CLI ile doğrulama yap:
  - **PowerShell**: `$r = Invoke-WebRequest -Uri "$URL" -Method GET -MaximumRedirection 0 -UseBasicParsing; $r.StatusCode; $r.Headers.Location`
  - **Validation**: `302` status + doğru `Location` header = gold standard

## 2. Automated Testing Protocol
// turbo
- **Python**: `python -m pytest tests/ -v --tb=short`
- **Metrics**: `python -m pytest tests/ --cov=app --cov-report=term-missing`

## 3. Manual & E2E Protocol
- **UI Validation**: Tarayıcı tabanlı testleri senaryo adımlarına göre uygula.
- **Evidence Collection**: Kritik milestonelar için screenshot al.
- **API Validation**: Endpoint doğrulaması `curl` veya Postman ile yap.

## 4. 🔍 Log Dosyası Hata Kontrolü (Zorunlu Adım)

> **KRİTİK:** Test tamamlandıktan sonra aşağıdaki adımlar ZORUNLU olarak uygulanır.

### 4.1 Test Öncesi Zaman Damgası Al
Test başlamadan **ÖNCE** zaman damgasını kaydet:
```powershell
$testStart = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
Write-Host "Test Başlangıç: $testStart"
```

### 4.2 Testleri Çalıştır
// turbo
```powershell
python -m pytest tests/ -v --tb=short 2>&1 | Select-Object -Last 30
```

### 4.3 ERROR Seviyesindeki Logları Kontrol Et
Test tamamlandıktan sonra log dosyasını tara:
// turbo
```powershell
# ERROR ve CRITICAL seviyesindeki logları filtrele
$logFile = "D:\VYRA\logs\vyra.log"
$errors = Get-Content $logFile | ForEach-Object {
    try { $_ | ConvertFrom-Json } catch { $null }
} | Where-Object {
    $_ -ne $null -and
    ($_.level -eq "ERROR" -or $_.level -eq "CRITICAL") -and
    $_.ts -ge $testStart
}

if ($errors.Count -eq 0) {
    Write-Host "✅ LOG KONTROLÜ: Test süresince ERROR/CRITICAL log yok" -ForegroundColor Green
} else {
    Write-Host "❌ LOG KONTROLÜ: $($errors.Count) hata bulundu!" -ForegroundColor Red
    $errors | ForEach-Object {
        Write-Host "  [$($_.level)] [$($_.module)] $($_.msg)" -ForegroundColor Yellow
    }
}
```

### 4.4 WARNING Seviyesindeki Logları İncele
// turbo
```powershell
$warnings = Get-Content $logFile | ForEach-Object {
    try { $_ | ConvertFrom-Json } catch { $null }
} | Where-Object {
    $_ -ne $null -and
    $_.level -eq "WARNING" -and
    $_.ts -ge $testStart
}

if ($warnings.Count -eq 0) {
    Write-Host "✅ WARNING KONTROLÜ: Uyarı yok" -ForegroundColor Green
} else {
    Write-Host "⚠️ WARNING KONTROLÜ: $($warnings.Count) uyarı bulundu" -ForegroundColor Yellow
    $warnings | ForEach-Object {
        Write-Host "  [WARNING] [$($_.module)] $($_.msg)" -ForegroundColor DarkYellow
    }
}
```

### 4.5 stderr Çıktısını Kontrol Et
Test çalıştırma sırasında stderr'e yazılan print mesajlarını da kontrol et (circular import fallback logları):
```powershell
python -m pytest tests/ -v --tb=short 2>$env:TEMP\pytest_stderr.log
$stderrContent = Get-Content "$env:TEMP\pytest_stderr.log" -ErrorAction SilentlyContinue
if ($stderrContent) {
    Write-Host "⚠️ STDERR ÇIKTISI:" -ForegroundColor Yellow
    $stderrContent | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkYellow }
} else {
    Write-Host "✅ STDERR: Temiz" -ForegroundColor Green
}
```

### 4.6 Sonuç Değerlendirmesi

| Durum | Aksiyon |
|-------|---------|
| ✅ Tüm testler PASS + Log temiz | → `/confirm` workflow'una geç |
| ✅ Testler PASS + ⚠️ WARNING var | → WARNING'leri incele, gerekirse düzelt |
| ❌ Testler FAIL | → Hataları düzelt, tekrar test et |
| ❌ Log'da ERROR/CRITICAL var | → **Deployment engellendi!** Hataları çöz |

## 5. Reporting Structure
| Test ID | Description | Result | Log Status | Notes |
|---------|-------------|--------|------------|-------|
| TEST-XX | [Description] | ✅/❌ | ✅/⚠️/❌ | [Details] |

## 6. Failure Management
- **Logging**: ❌ FAIL durumlarını detaylı log ve hata mesajları ile belgele.
- **Correction**: Uygulanabilir otomatik düzeltmeleri öner veya uygula.
- **Communication**: Kritik engelleyiciler için paydaşları bilgilendir.

## 7. Regression & Hygiene
- Mevcut özelliklerde regresyon olmadığını doğrula.
- Performans düşüşü kontrolü yap.
- Konsol çıktısında beklenmeyen uyarı veya hata olup olmadığını izle.

## 8. Sign-off Criteria
- ✅ **ALL PASS + LOG TEMİZ**: → `/confirm` workflow'una geç
- ⚠️ **MINOR FAILURES veya WARNING**: Düzeltme gerekli
- ❌ **CRITICAL FAILURES veya ERROR LOG**: Deployment engellendi
