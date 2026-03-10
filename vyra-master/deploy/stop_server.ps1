# =============================================================
# VYRA L1 Support — Sunucu Durdurma Scripti
# =============================================================
# Tüm servisleri güvenli şekilde durdurur.
# PostgreSQL Windows Service olarak çalıştığı için
# varsayılan olarak DURDURULMAZ (diğer uygulamalar kullanıyor olabilir).
#
# Kullanım:
#   .\deploy\stop_server.ps1           → Backend + Nginx durdur
#   .\deploy\stop_server.ps1 -StopDB   → DB dahil durdur
# =============================================================

param(
    [switch]$StopDB
)

$ErrorActionPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = "D:\VYRA" }

$NginxDir = "$ProjectRoot\nginx"
$NginxExe = "$NginxDir\nginx.exe"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Red
Write-Host "  VYRA L1 Support - Sunucu Durdurma" -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Red
Write-Host ""

# =============================================================
# 1. Nginx Durdur
# =============================================================
Write-Host "[1/3] Nginx durduruluyor..." -ForegroundColor Yellow

$nginxProc = Get-Process -Name "nginx" -ErrorAction SilentlyContinue
if ($nginxProc) {
    if (Test-Path $NginxExe) {
        Push-Location $NginxDir
        & $NginxExe -s quit 2>&1 | Out-Null
        Pop-Location
    }
    # Graceful shutdown için bekle
    Start-Sleep -Seconds 2
    # Hala çalışıyorsa zorla durdur
    Get-Process -Name "nginx" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "   [OK] Nginx durduruldu" -ForegroundColor Green
} else {
    Write-Host "   [--] Nginx zaten calismiyordu" -ForegroundColor Gray
}

# =============================================================
# 2. Python/Uvicorn Durdur
# =============================================================
Write-Host "[2/3] Uvicorn (Python) durduruluyor..." -ForegroundColor Yellow

# Sadece bu proje ile ilişkili python süreçlerini bul
$pythonProcs = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId=$($_.Id)" -ErrorAction SilentlyContinue).CommandLine
        $cmdLine -match "uvicorn" -and $cmdLine -match "vyra|app\.api\.main"
    } catch { $false }
}

if ($pythonProcs) {
    $pythonProcs | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "   [OK] Uvicorn worker'lari durduruldu ($($pythonProcs.Count) process)" -ForegroundColor Green
} else {
    # Fallback: uvicorn ile ilişkili tüm python süreçlerini durdur
    $fallbackProcs = Get-Process -Name "python" -ErrorAction SilentlyContinue
    if ($fallbackProcs) {
        Write-Host "   [UYARI] $($fallbackProcs.Count) Python sureci bulundu." -ForegroundColor Yellow
        Write-Host "   VYRA'ya ait olanlari durdurmak istiyor musunuz? (E/H): " -ForegroundColor Yellow -NoNewline
        $confirm = Read-Host
        if ($confirm -eq "E" -or $confirm -eq "e") {
            $fallbackProcs | ForEach-Object {
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            }
            Write-Host "   [OK] Python surecleri durduruldu" -ForegroundColor Green
        } else {
            Write-Host "   [--] Python surecleri korundu" -ForegroundColor Gray
        }
    } else {
        Write-Host "   [--] Uvicorn zaten calismiyordu" -ForegroundColor Gray
    }
}

# =============================================================
# 3. PostgreSQL Durdur (opsiyonel)
# =============================================================
if ($StopDB) {
    Write-Host "[3/3] PostgreSQL durduruluyor..." -ForegroundColor Yellow

    $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pgService -and $pgService.Status -eq "Running") {
        Stop-Service $pgService.Name -Force -ErrorAction SilentlyContinue
        Write-Host "   [OK] PostgreSQL servisi durduruldu: $($pgService.Name)" -ForegroundColor Green
    } elseif ($pgService) {
        Write-Host "   [--] PostgreSQL zaten calismiyordu" -ForegroundColor Gray
    } else {
        Write-Host "   [--] PostgreSQL servisi bulunamadi" -ForegroundColor Gray
    }
} else {
    Write-Host "[3/3] PostgreSQL ATLANDI (Servis olarak calismaya devam eder)" -ForegroundColor Gray
    Write-Host "       DB'yi de durdurmak icin: .\deploy\stop_server.ps1 -StopDB" -ForegroundColor Gray
}

# =============================================================
# SONUÇ
# =============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Servisler durduruldu!" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  Tekrar baslatmak: .\deploy\start_server.ps1" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
