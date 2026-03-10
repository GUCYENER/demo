# =============================================================
# VYRA L1 Support — Sunucu Başlatma Scripti
# =============================================================
# Sistem Python (venv) + Sistem PostgreSQL kullanır.
# Portable yapı GEREKMEZ.
#
# Kullanım:
#   .\deploy\start_server.ps1                 → Tüm servisleri başlat
#   .\deploy\start_server.ps1 -SkipNginx      → Nginx olmadan başlat
#   .\deploy\start_server.ps1 -Workers 8       → 8 worker ile başlat
# =============================================================

param(
    [switch]$SkipNginx,
    [int]$Workers = 4,
    [int]$BackendPort = 8002
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = "D:\VYRA" }

# ── Python yolu (venv) ──
$VenvPython = "$ProjectRoot\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[HATA] Virtual environment bulunamadi!" -ForegroundColor Red
    Write-Host "       Once kurulumu calistirin: .\deploy\setup_server.ps1" -ForegroundColor Yellow
    exit 1
}

# ── .env kontrolü ──
if (-not (Test-Path "$ProjectRoot\.env")) {
    Write-Host "[HATA] .env dosyasi bulunamadi!" -ForegroundColor Red
    Write-Host "       .env.example dosyasini .env olarak kopyalayin ve duzenleyin." -ForegroundColor Yellow
    exit 1
}

# ── .env'den ayarları oku ──
$envContent = Get-Content "$ProjectRoot\.env" -ErrorAction SilentlyContinue
$dbPort = "5005"
$dbPassword = ""
$pgBinDir = ""

foreach ($line in $envContent) {
    if ($line -match '^\s*DB_PORT\s*=\s*(.+)') { $dbPort = $Matches[1].Trim() }
    if ($line -match '^\s*DB_PASSWORD\s*=\s*(.+)') { $dbPassword = $Matches[1].Trim() }
    if ($line -match '^\s*PG_BIN_DIR\s*=\s*(.+)') { $pgBinDir = $Matches[1].Trim() }
}

if ($dbPassword) { $env:PGPASSWORD = $dbPassword }

# ── PostgreSQL bin dizinini bul ──
if (-not $pgBinDir) {
    $psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
    if ($psqlCmd) {
        $pgBinDir = Split-Path $psqlCmd.Source
    } else {
        $pgSearchPaths = @(
            "C:\Program Files\PostgreSQL\17\bin",
            "C:\Program Files\PostgreSQL\16\bin",
            "C:\Program Files\PostgreSQL\15\bin",
            "C:\Program Files\PostgreSQL\14\bin"
        )
        foreach ($p in $pgSearchPaths) {
            if (Test-Path "$p\psql.exe") { $pgBinDir = $p; break }
        }
    }
}

# ── Versiyon oku ──
$Version = ""
try {
    if ($pgBinDir -and (Test-Path "$pgBinDir\psql.exe")) {
        $Version = & "$pgBinDir\psql.exe" -U postgres -d vyra -h localhost -p $dbPort -t -A -c "SELECT setting_value FROM system_settings WHERE setting_key = 'app_version'" 2>$null
        if ($Version -is [array]) { $Version = $Version[0] }
        $Version = ($Version -replace '\s','').Trim()
    }
} catch {}
if (-not $Version) {
    try {
        $env:PYTHONPATH = $ProjectRoot
        $Version = & $VenvPython -c "from app.core.config import settings; print(settings.APP_VERSION)" 2>$null
    } catch {}
}
if (-not $Version) { $Version = "?.?.?" }

# ── Nginx ──
$NginxDir = "$ProjectRoot\nginx"
$NginxExe = "$NginxDir\nginx.exe"

# ── Banner ──
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VYRA L1 Support API v$Version - SERVER MODE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Nginx   : $(if ($SkipNginx) {'ATLANACAK'} elseif (Test-Path $NginxExe) {'AKTIF'} else {'YOK'})" -ForegroundColor Cyan
Write-Host "  Workers : $Workers" -ForegroundColor Cyan
Write-Host "  Port    : $BackendPort" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# =============================================================
# STEP 1: PostgreSQL
# =============================================================
Write-Host "[1/4] PostgreSQL kontrol ediliyor..." -ForegroundColor Yellow

if ($pgBinDir -and (Test-Path "$pgBinDir\pg_isready.exe")) {
    & "$pgBinDir\pg_isready.exe" -h localhost -p $dbPort 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   [OK] PostgreSQL zaten calisiyor (port $dbPort)" -ForegroundColor Green
    } else {
        # Windows Service olarak başlat
        $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pgService) {
            Write-Host "   [INFO] PostgreSQL servisi baslatiliyor: $($pgService.Name)" -ForegroundColor Gray
            Start-Service $pgService.Name -ErrorAction SilentlyContinue

            $attempts = 0
            do {
                Start-Sleep -Seconds 3
                & "$pgBinDir\pg_isready.exe" -h localhost -p $dbPort 2>$null | Out-Null
                $attempts++
            } while ($LASTEXITCODE -ne 0 -and $attempts -lt 10)

            if ($LASTEXITCODE -eq 0) {
                Write-Host "   [OK] PostgreSQL baslatildi (port $dbPort)" -ForegroundColor Green
            } else {
                Write-Host "   [HATA] PostgreSQL baslatilamadi!" -ForegroundColor Red
                Write-Host "   PostgreSQL servisini kontrol edin: services.msc" -ForegroundColor Yellow
                exit 1
            }
        } else {
            Write-Host "   [HATA] PostgreSQL Windows servisi bulunamadi!" -ForegroundColor Red
            Write-Host "   PostgreSQL'in kurulu ve servis olarak kayitli oldugundan emin olun." -ForegroundColor Yellow
            exit 1
        }
    }
} else {
    # psql PATH'te değilse direkt bağlantı ile dene
    Write-Host "   [UYARI] PostgreSQL bin dizini bulunamadi." -ForegroundColor Yellow
    Write-Host "   .env dosyasinda PG_BIN_DIR tanimlayin veya PostgreSQL'i PATH'e ekleyin." -ForegroundColor Yellow
    Write-Host "   PostgreSQL'in port $dbPort'da calistigini varsayarak devam ediliyor..." -ForegroundColor Yellow
}

# =============================================================
# STEP 2: Alembic Migration
# =============================================================
Write-Host "[2/4] Veritabani migration kontrol ediliyor..." -ForegroundColor Yellow
try {
    Push-Location $ProjectRoot
    $env:PYTHONPATH = $ProjectRoot
    & $VenvPython -m alembic upgrade head 2>&1 | Out-Null
    Pop-Location
    Write-Host "   [OK] Alembic migration tamamlandi" -ForegroundColor Green
} catch {
    Pop-Location
    Write-Host "   [UYARI] Alembic migration hatasi (init_db fallback kullanilacak)" -ForegroundColor Yellow
}

# =============================================================
# STEP 3: Backend (Uvicorn — Production Mode)
# =============================================================
Write-Host "[3/4] Backend baslatiliyor (Uvicorn x$Workers workers)..." -ForegroundColor Yellow

# Zaten çalışıyor mu?
$backendReady = $false
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($resp.StatusCode -eq 200) {
        Write-Host "   [OK] Backend zaten calisiyor (port $BackendPort)" -ForegroundColor Green
        $backendReady = $true
    }
} catch {}

if (-not $backendReady) {
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

    # Health check bekle
    $attempts = 0
    do {
        Start-Sleep -Seconds 3
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
            $ready = $resp.StatusCode -eq 200
        } catch { $ready = $false }
        $attempts++
    } while (-not $ready -and $attempts -lt 30)

    if ($ready) {
        Write-Host "   [OK] Backend hazir (port $BackendPort, $Workers worker)" -ForegroundColor Green
    } else {
        Write-Host "   [UYARI] Backend henuz hazir degil, devam ediliyor..." -ForegroundColor Yellow
        Write-Host "   ML modelleri ilk seferde indiriliyordur (5-10 dk surebilir)" -ForegroundColor Gray
    }
}

# =============================================================
# STEP 4: Nginx (Reverse Proxy)
# =============================================================
if (-not $SkipNginx) {
    Write-Host "[4/4] Nginx baslatiliyor..." -ForegroundColor Yellow

    if (-not (Test-Path $NginxExe)) {
        Write-Host "   [UYARI] Nginx bulunamadi: $NginxExe" -ForegroundColor Yellow
        Write-Host "   [INFO] Nginx kurmak icin: .\deploy\setup_server.ps1" -ForegroundColor Cyan
        Write-Host "   [INFO] Nginx olmadan devam ediliyor..." -ForegroundColor Cyan
    } else {
        # Config kopyala (path replace ile)
        $confDir = "$NginxDir\conf\conf.d"
        if (-not (Test-Path $confDir)) { New-Item -ItemType Directory -Path $confDir -Force | Out-Null }

        $confSource = "$ProjectRoot\deploy\nginx\vyra.conf"
        if (Test-Path $confSource) {
            $confTemplate = Get-Content $confSource -Raw
            $normalizedRoot = $ProjectRoot -replace '\\', '/'
            $confFinal = $confTemplate -replace 'root\s+[A-Za-z]:/[^;]+/frontend', "root    $normalizedRoot/frontend"
            $utf8NoBom = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText("$confDir\vyra.conf", $confFinal, $utf8NoBom)
        }

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
            Push-Location $NginxDir
            & $NginxExe -s reload 2>$null
            Pop-Location
            Write-Host "   [OK] Nginx reload edildi (port 80)" -ForegroundColor Green
        } else {
            Push-Location $NginxDir
            Start-Process $NginxExe -WindowStyle Hidden
            Pop-Location
            Start-Sleep -Seconds 1
            Write-Host "   [OK] Nginx baslatildi (port 80)" -ForegroundColor Green
        }
    }
} else {
    Write-Host "[4/4] Nginx ATLANDI (-SkipNginx)" -ForegroundColor Gray
}

# =============================================================
# SONUÇ
# =============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  VYRA v$Version - SERVER HAZIR!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green

if (-not $SkipNginx -and (Test-Path $NginxExe)) {
    Write-Host "  URL:  http://localhost (Nginx -> Uvicorn)" -ForegroundColor Green
    Write-Host "  API:  http://localhost/api/health" -ForegroundColor Green
} else {
    Write-Host "  API:  http://localhost:${BackendPort}/api/health" -ForegroundColor Green
}

Write-Host "  DB:   localhost:$dbPort/vyra" -ForegroundColor Green
Write-Host "" -ForegroundColor Green
Write-Host "  Durdurmak: .\deploy\stop_server.ps1" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
