# =============================================================
# VYRA L1 Support — Production Stop Script
# =============================================================
# Tüm servisleri güvenli şekilde durdurur.
#
# Kullanım:
#   .\deploy\stop_production.ps1           → Tümünü durdur
#   .\deploy\stop_production.ps1 -KeepDB   → DB hariç durdur
# =============================================================

param(
    [switch]$KeepDB
)

$ErrorActionPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = "D:\VYRA" }

$NginxDir = "$ProjectRoot\nginx"
$NginxExe = "$NginxDir\nginx.exe"

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Red
Write-Host "  VYRA L1 Support - Production Durdurma" -ForegroundColor Red
Write-Host "=============================================================" -ForegroundColor Red
Write-Host ""

# =============================================================
# 1. Nginx Durdur
# =============================================================
Write-Host "[1/3] Nginx durduruluyor..." -ForegroundColor Yellow

$nginxProc = Get-Process -Name "nginx" -ErrorAction SilentlyContinue
if ($nginxProc) {
    if (Test-Path $NginxExe) {
        & $NginxExe -s quit 2>&1 | Out-Null
    }
    # Nginx graceful shutdown için bekle
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

$pythonProcs = Get-Process -Name "python" -ErrorAction SilentlyContinue
if ($pythonProcs) {
    $pythonProcs | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "   [OK] Uvicorn worker'lari durduruldu ($($pythonProcs.Count) process)" -ForegroundColor Green
} else {
    Write-Host "   [--] Python islemleri zaten calismiyordu" -ForegroundColor Gray
}

# =============================================================
# 3. PostgreSQL Durdur
# =============================================================
if ($KeepDB) {
    Write-Host "[3/3] PostgreSQL ATLANDI (-KeepDB)" -ForegroundColor Gray
} else {
    Write-Host "[3/3] PostgreSQL durduruluyor..." -ForegroundColor Yellow

    $pgBin = "$ProjectRoot\pgsql\bin"
    $pgData = "$ProjectRoot\pgsql\data"

    $null = & "$pgBin\pg_isready.exe" -h localhost -p 5005 2>$null
    if ($LASTEXITCODE -eq 0) {
        Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList "-D", "`"$pgData`"", "stop", "-m", "fast" -WindowStyle Hidden -Wait
        Write-Host "   [OK] PostgreSQL durduruldu" -ForegroundColor Green
    } else {
        Write-Host "   [--] PostgreSQL zaten calismiyordu" -ForegroundColor Gray
    }
}

# =============================================================
# SONUÇ
# =============================================================
Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "  Tum servisler durduruldu!" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host '  Tekrar baslatmak: .\deploy\start_production.ps1' -ForegroundColor Yellow
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""
