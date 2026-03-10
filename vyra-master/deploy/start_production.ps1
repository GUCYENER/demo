# =============================================================
# VYRA L1 Support — Production Deployment Script
# =============================================================
# Bare-Metal: Nginx + Uvicorn + PostgreSQL
#
# Kullanım:
#   .\deploy\start_production.ps1           → Tüm servisleri başlat
#   .\deploy\start_production.ps1 -SkipNginx → Nginx olmadan başlat
# =============================================================

param(
    [switch]$SkipNginx,
    [int]$Workers = 4,
    [int]$BackendPort = 8002
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = "D:\VYRA" }

# ── .env'den DB_PASSWORD oku ──
$envFile = Get-Content "$ProjectRoot\.env" -ErrorAction SilentlyContinue | Where-Object { $_ -match 'DB_PASSWORD=' }
if ($envFile) {
    $env:PGPASSWORD = ($envFile -split '=', 2)[1].Trim()
} else {
    Write-Host "[WARN] .env'de DB_PASSWORD bulunamadi, fallback kullaniliyor" -ForegroundColor Yellow
    $env:PGPASSWORD = 'postgres'
}

# ── Portable Python ──
$VenvPython = "$ProjectRoot\python\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[HATA] Portable Python bulunamadi: $VenvPython" -ForegroundColor Red
    exit 1
}

# ── Nginx yolu ──
$NginxDir = "$ProjectRoot\nginx"
$NginxExe = "$NginxDir\nginx.exe"

# -- Versiyon oku (DB olmayabilir, hata tolere et) --
try {
    $Version = & "$ProjectRoot\pgsql\bin\psql.exe" -U postgres -d vyra -h localhost -p 5005 -t -A -c "SELECT setting_value FROM system_settings WHERE setting_key = 'app_version'" 2>$null
    $Version = ($Version -replace '\s','').Trim()
} catch { $Version = "" }
if (-not $Version) {
    try {
        $Version = & $VenvPython -c "from app.core.config import settings; print(settings.APP_VERSION)" 2>$null
    } catch { $Version = "" }
}
if (-not $Version) { $Version = "?.?.?" }

# -- Banner --
Write-Host ""
Write-Host "=====  VYRA L1 Support API v$Version - PRODUCTION MODE  =====" -ForegroundColor Cyan
Write-Host "  Nginx   : $(if ($SkipNginx) {'ATLANACAK'} else {'AKTIF'})" -ForegroundColor Cyan
Write-Host "  Workers : $Workers" -ForegroundColor Cyan
Write-Host "  Port    : $BackendPort" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""

# =============================================================
# STEP 1: PostgreSQL
# =============================================================
Write-Host "[1/4] PostgreSQL kontrol ediliyor..." -ForegroundColor Yellow

$pgBin = "$ProjectRoot\pgsql\bin"
$pgData = "$ProjectRoot\pgsql\data"
$pgLog = "$pgData\server.log"

# Zaten calisiyor mu?
& "$pgBin\pg_isready.exe" -h localhost -p 5005 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "   [OK] PostgreSQL zaten calisiyor (port 5005)" -ForegroundColor Green
} else {
    Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList "-D", "`"$pgData`"", "-l", "`"$pgLog`"", "start" -WindowStyle Hidden
    
    # PostgreSQL hazir olana kadar bekle (max 30 saniye)
    $attempts = 0
    do {
        Start-Sleep -Seconds 3
        & "$pgBin\pg_isready.exe" -h localhost -p 5005 2>$null | Out-Null
        $attempts++
    } while ($LASTEXITCODE -ne 0 -and $attempts -lt 10)
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   [OK] PostgreSQL baslatildi (port 5005)" -ForegroundColor Green
    } else {
        Write-Host "   [HATA] PostgreSQL baslatilamadi!" -ForegroundColor Red
        exit 1
    }
}

# =============================================================
# STEP 2: Alembic Migration
# =============================================================
Write-Host "[2/4] Veritabani migration kontrol ediliyor..." -ForegroundColor Yellow
try {
    Push-Location $ProjectRoot
    & $VenvPython -m alembic upgrade head 2>&1 | Out-Null
    Pop-Location
    Write-Host "   [OK] Alembic migration tamamlandi" -ForegroundColor Green
} catch {
    Write-Host "   [UYARI] Alembic migration hatasi (init_db fallback kullanilacak)" -ForegroundColor Yellow
}

# =============================================================
# STEP 3: Backend (Uvicorn — Production Mode)
# =============================================================
Write-Host "[3/4] Backend baslatiliyor (Uvicorn x$Workers workers)..." -ForegroundColor Yellow

$backendCmd = @"
cd '$ProjectRoot'
`$env:PYTHONPATH = '$ProjectRoot'
& '$VenvPython' -m uvicorn app.api.main:app ``
    --host 0.0.0.0 ``
    --port $BackendPort ``
    --workers $Workers ``
    --limit-concurrency 100 ``
    --timeout-keep-alive 30 ``
    --access-log ``
    --no-server-header ``
    --log-level warning
"@

Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd -WindowStyle Minimized

# Backend hazır olana kadar bekle
$attempts = 0
do {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        $ready = $resp.StatusCode -eq 200
    } catch { $ready = $false }
    $attempts++
} while (-not $ready -and $attempts -lt 20)

if ($ready) {
    Write-Host "   [OK] Backend hazir (port $BackendPort, $Workers worker)" -ForegroundColor Green
} else {
    Write-Host "   [UYARI] Backend henuz hazir degil, devam ediliyor..." -ForegroundColor Yellow
}

# =============================================================
# STEP 4: Nginx (Reverse Proxy — Frontend + API)
# =============================================================
if (-not $SkipNginx) {
    Write-Host "[4/4] Nginx baslatiliyor..." -ForegroundColor Yellow

    if (-not (Test-Path $NginxExe)) {
        Write-Host "   [UYARI] Nginx bulunamadi: $NginxExe" -ForegroundColor Yellow
        Write-Host '   [INFO] Nginx''i indirmek icin: .\deploy\setup_nginx.ps1' -ForegroundColor Cyan
        Write-Host "   [INFO] Nginx olmadan devam ediliyor (frontend: serve.py)" -ForegroundColor Cyan
        
        # Fallback: Python serve.py ile frontend sun
        $frontendCmd = "cd '$ProjectRoot\frontend'; & '$VenvPython' serve.py"
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd -WindowStyle Minimized
        Start-Sleep -Seconds 1
        Write-Host "   [OK] Frontend baslatildi (serve.py, port 5500)" -ForegroundColor Green
    } else {
        # Nginx config'i kontrol et
        $confSource = "$ProjectRoot\deploy\nginx\vyra.conf"
        $confTarget = "$NginxDir\conf\conf.d\vyra.conf"
        
        # conf.d dizini yoksa oluştur
        $confDir = "$NginxDir\conf\conf.d"
        if (-not (Test-Path $confDir)) {
            New-Item -ItemType Directory -Path $confDir -Force | Out-Null
        }
        
        # Config kopyala/güncelle
        Copy-Item $confSource $confTarget -Force
        Write-Host "   [OK] vyra.conf kopyalandi" -ForegroundColor Gray
        
        # Nginx config test
        Push-Location $NginxDir
        & $NginxExe -t 2>$null
        $testExitCode = $LASTEXITCODE
        Pop-Location
        if ($testExitCode -eq 0) {
            Write-Host "   [OK] Nginx config testi basarili" -ForegroundColor Gray
        } else {
            Write-Host "   [HATA] Nginx config hatasi! nginx -t ile kontrol edin." -ForegroundColor Red
            exit 1
        }

        # Nginx zaten çalışıyor mu?
        $nginxProc = Get-Process -Name "nginx" -ErrorAction SilentlyContinue
        if ($nginxProc) {
            # Reload
            Push-Location $NginxDir
            & $NginxExe -s reload 2>$null
            Pop-Location
            Write-Host "   [OK] Nginx reload edildi (port 80)" -ForegroundColor Green
        } else {
            # Başlat
            Push-Location $NginxDir
            Start-Process $NginxExe -WindowStyle Hidden
            Pop-Location
            Start-Sleep -Seconds 1
            Write-Host "   [OK] Nginx baslatildi (port 80)" -ForegroundColor Green
        }
    }
} else {
    Write-Host "[4/4] Nginx ATLANDI (-SkipNginx)" -ForegroundColor Gray
    
    # Fallback: Python serve.py
    $frontendCmd = "cd '$ProjectRoot\frontend'; & '$VenvPython' serve.py"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd -WindowStyle Minimized
    Start-Sleep -Seconds 1
    Write-Host "   [OK] Frontend baslatildi (serve.py, port 5500)" -ForegroundColor Green
}

# =============================================================
# SONUÇ
# =============================================================
Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "  VYRA v$Version - PRODUCTION HAZIR" -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green

if (-not $SkipNginx -and (Test-Path $NginxExe)) {
    Write-Host "  URL: http://localhost (Nginx -> Uvicorn)" -ForegroundColor Green
    Write-Host "  API: http://localhost/api/health" -ForegroundColor Green
} else {
    Write-Host "  URL: http://localhost:5500/login.html" -ForegroundColor Green
    Write-Host "  API: http://localhost:${BackendPort}/api/health" -ForegroundColor Green
}

Write-Host "  DB:  localhost:5005/vyra" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host '  Durdurmak: .\deploy\stop_production.ps1' -ForegroundColor Yellow
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""
