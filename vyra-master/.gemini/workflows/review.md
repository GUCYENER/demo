---
description: Code review ve kalite doğrulama ritüeli
---

# Code Review Ritual (/review)

Tüm değişikliklerin kalite ve güvenlik standartlarına uygun olup olmadığını doğrulamak için sistematik inceleme süreci.

## 1. Değişiklik Kapsamı
// turbo
```powershell
& 'C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe' diff --stat
```

## 2. Python Syntax Kontrolü
// turbo
```powershell
# Değiştirilen Python dosyalarını derle
$files = & 'C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe' diff --name-only --diff-filter=M 2>&1 | Where-Object { $_ -like "*.py" }
$failed = @()
foreach ($f in $files) { $result = python -m py_compile $f 2>&1; if ($LASTEXITCODE -ne 0) { $failed += "$f" } }
if ($failed.Count -eq 0) { Write-Host "✅ Syntax: Tüm dosyalar OK" } else { Write-Host "❌ Syntax HATA:"; $failed | ForEach-Object { Write-Host "  $_" } }
```

## 3. Inline CSS Kontrolü
// turbo
```powershell
# HTML dosyalarda inline style kullanımını tespit et (runtime dinamik değerler hariç)
$htmlFiles = & 'C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe' diff --name-only --diff-filter=M 2>&1 | Where-Object { $_ -like "*.html" }
foreach ($f in $htmlFiles) {
    $inlines = Select-String -Path $f -Pattern 'style="' -ErrorAction SilentlyContinue
    if ($inlines) { Write-Host "⚠️ Inline CSS: $f ($($inlines.Count) satır)" }
}
```

## 4. Exception Handling Kontrolü
// turbo
```powershell
# Silent pass veya log-missing blokları tespit et
$pyFiles = & 'C:\Users\EXT02D059293\AppData\Local\Programs\Git\cmd\git.exe' diff --name-only --diff-filter=M 2>&1 | Where-Object { $_ -like "*.py" }
foreach ($f in $pyFiles) {
    $silentPass = Select-String -Path $f -Pattern 'except.*:\s*$' -ErrorAction SilentlyContinue
    $bareExcept = Select-String -Path $f -Pattern '^\s*except\s*:' -ErrorAction SilentlyContinue
    if ($silentPass) { Write-Host "⚠️ Log-missing except: $f ($($silentPass.Count) blok)" }
    if ($bareExcept) { Write-Host "❌ Bare except: $f ($($bareExcept.Count) blok)" }
}
```

## 5. Log Dosyası Kontrolü
// turbo
```powershell
# Son testlerden kalan ERROR loglarını kontrol et
$logFile = "D:\VYRA\logs\vyra.log"
$cutoff = (Get-Date).AddMinutes(-30).ToString("yyyy-MM-ddTHH:mm:ss")
$errors = Get-Content $logFile -Tail 200 | ForEach-Object { try { $_ | ConvertFrom-Json } catch { $null } } | Where-Object { $_ -ne $null -and $_.level -eq "ERROR" -and $_.ts -ge $cutoff }
if ($errors.Count -eq 0) { Write-Host "✅ Log: Son 30dk ERROR yok" } else { Write-Host "⚠️ $($errors.Count) ERROR bulundu"; $errors | ForEach-Object { Write-Host "  [$($_.module)] $($_.msg)" } }
```

## 6. Sonuç
- ✅ Tüm kontroller geçti → Commit yapılabilir
- ⚠️ Uyarılar var → Gözden geçir ve düzelt
- ❌ Hatalar var → Commit engellendi
