# ============================================================
# VYRA L1 Support API - Tam Baslatma Scripti
# ============================================================

# Self-relaunch: ExecutionPolicy kisitlamasini bypass et
if ($ExecutionContext.SessionState.LanguageMode -ne 'NoLanguage') {
    $policy = (Get-ExecutionPolicy -Scope Process)
    if ($policy -notin @('Bypass', 'Unrestricted')) {
        powershell.exe -ExecutionPolicy Bypass -File $MyInvocation.MyCommand.Path @args
        exit $LASTEXITCODE
    }
}

$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent (Resolve-Path $MyInvocation.MyCommand.Path) }

# Venv Python yolu
$VenvPython = "$ProjectRoot\python\Scripts\python.exe"

# Versiyonu DB'den oku (system_settings tablosu), fallback: config.py
# DB şifresini .env'den oku (hardcoded password kullanma!)
$envFile = Get-Content "$ProjectRoot\.env" -ErrorAction SilentlyContinue | Where-Object { $_ -match 'DB_PASSWORD=' }
if ($envFile) {
    $envLine = if ($envFile -is [array]) { $envFile[0] } else { $envFile }
    $env:PGPASSWORD = ($envLine -split '=', 2)[1].Trim()
} else {
    $env:PGPASSWORD = 'postgres'  # Fallback (development)
}
$Version = & "$ProjectRoot\pgsql\bin\psql.exe" -U postgres -d vyra -h localhost -p 5005 -t -A -c "SELECT setting_value FROM system_settings WHERE setting_key = 'app_version'" 2>$null
if ($Version -is [array]) { $Version = $Version[0] }
if ($Version) { $Version = ($Version -replace '\s','').Trim() }
if (-not $Version) {
    $Version = & $VenvPython -c "from app.core.config import settings; print(settings.APP_VERSION)" 2>$null
}
if (-not $Version) { $Version = "?.?.?" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "         VYRA L1 Support API v$Version" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. PostgreSQL
Write-Host "[1/7] PostgreSQL baslatiliyor..." -ForegroundColor Yellow
$pgBin = "$ProjectRoot\pgsql\bin"
$pgData = "$ProjectRoot\pgsql\data"
$pgLog = "$pgData\server.log"

Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList "-D", "`"$pgData`"", "-l", "`"$pgLog`"", "start" -WindowStyle Hidden
Start-Sleep -Seconds 8
Write-Host "   [OK] PostgreSQL (port 5005)" -ForegroundColor Green

# 2. Redis Cache
Write-Host "[2/7] Redis baslatiliyor..." -ForegroundColor Yellow
$redisExe = "$ProjectRoot\redis\redis-server.exe"
$redisConf = "$ProjectRoot\redis\redis.windows.conf"
if (Test-Path $redisExe) {
    # Zaten çalışıp çalışmadığını kontrol et
    $redisRunning = $false
    try {
        $response = & "$ProjectRoot\redis\redis-cli.exe" ping 2>$null
        if ($response -eq "PONG") { $redisRunning = $true }
    } catch {}
    
    if ($redisRunning) {
        Write-Host "   [OK] Redis zaten calisiyor (port 6379)" -ForegroundColor Green
    } else {
        Start-Process -FilePath $redisExe -ArgumentList "`"$redisConf`"" -WorkingDirectory "$ProjectRoot\redis" -WindowStyle Hidden
        Start-Sleep -Seconds 2
        # Bellek limiti ve LRU policy ayarla
        & "$ProjectRoot\redis\redis-cli.exe" CONFIG SET maxmemory 128mb 2>$null | Out-Null
        & "$ProjectRoot\redis\redis-cli.exe" CONFIG SET maxmemory-policy allkeys-lru 2>$null | Out-Null
        Write-Host "   [OK] Redis (port 6379, 128MB LRU)" -ForegroundColor Green
    }
} else {
    Write-Host "   [WARN] Redis bulunamadi, in-memory cache kullanilacak" -ForegroundColor DarkYellow
}

# 3. Backend (venv python ile)
Write-Host "[3/7] Backend baslatiliyor..." -ForegroundColor Yellow
$backendCmd = "cd '$ProjectRoot'; & '$VenvPython' -m uvicorn app.api.main:app --host 0.0.0.0 --port 8002 --timeout-keep-alive 300"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd
Start-Sleep -Seconds 3
Write-Host "   [OK] Backend (port 8002)" -ForegroundColor Green

# 4. Nginx (reverse proxy)
Write-Host "[4/7] Nginx baslatiliyor..." -ForegroundColor Yellow
$nginxExe = "$ProjectRoot\nginx\nginx.exe"
if (Test-Path $nginxExe) {
    $nginxRunning = tasklist /fi "imagename eq nginx.exe" 2>$null | Select-String "nginx.exe"
    if ($nginxRunning) {
        Start-Process -FilePath $nginxExe -ArgumentList "-s", "reload" -WorkingDirectory "$ProjectRoot\nginx" -WindowStyle Hidden -Wait
        Write-Host "   [OK] Nginx reload edildi (port 8000)" -ForegroundColor Green
    } else {
        Start-Process -FilePath $nginxExe -WorkingDirectory "$ProjectRoot\nginx" -WindowStyle Hidden
        Start-Sleep -Seconds 1
        Write-Host "   [OK] Nginx baslatildi (port 8000)" -ForegroundColor Green
    }
} else {
    Write-Host "   [WARN] Nginx bulunamadi ($nginxExe)" -ForegroundColor DarkYellow
}

# 5. Oracle Test DB (Docker container — varsa)
$dockerExe = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$composeFile = "$ProjectRoot\oracle_local_test\docker-compose.yml"
if (Test-Path $dockerExe) {
    Write-Host "[5/7] Oracle Test DB kontrol ediliyor..." -ForegroundColor Yellow
    $dockerOk = & $dockerExe info 2>$null | Select-String "Server Version"
    if ($dockerOk) {
        $oraStatus = & $dockerExe ps -a --filter "name=vyra-oracle-test" --format "{{.Status}}" 2>$null
        if ($oraStatus -match "Up") {
            Write-Host "   [OK] Oracle Test DB zaten calisiyor" -ForegroundColor Green
        } elseif ($oraStatus) {
            # Container var ama durmus — start dene, hata verirse sil+yeniden olustur
            $startResult = & $dockerExe start vyra-oracle-test 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "   [OK] Oracle Test DB baslatildi" -ForegroundColor Green
            } elseif (Test-Path $composeFile) {
                Write-Host "   [*] Container hasarli, yeniden olusturuluyor..." -ForegroundColor DarkYellow
                & $dockerExe rm -f vyra-oracle-test 2>$null | Out-Null
                & $dockerExe compose -f $composeFile up -d 2>$null | Out-Null
                Write-Host "   [OK] Oracle Test DB yeniden olusturuldu" -ForegroundColor Green
            }
        } elseif (Test-Path $composeFile) {
            & $dockerExe compose -f $composeFile up -d 2>$null | Out-Null
            Write-Host "   [OK] Oracle Test DB olusturuldu" -ForegroundColor Green
        } else {
            Write-Host "   [--] Oracle compose dosyasi bulunamadi" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "   [--] Docker Desktop calismiyordu, Oracle atlanıyor" -ForegroundColor DarkGray
    }
} else {
    Write-Host "[5/7] Oracle Test DB atlandi (Docker kurulu degil)" -ForegroundColor DarkGray
}

# 6. Frontend (no-cache server ile)
Write-Host "[6/7] Frontend baslatiliyor..." -ForegroundColor Yellow
$frontendCmd = "cd '$ProjectRoot\frontend'; & '$VenvPython' serve.py"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd
Start-Sleep -Seconds 1
Write-Host "   [OK] Frontend (port 5500)" -ForegroundColor Green

# Tarayici
Write-Host ""
if (Test-Path $nginxExe) {
    Start-Process "http://localhost:8000/login.html"
} else {
    Start-Process "http://localhost:5500/login.html"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  VYRA baslatildi! Tarayici acildi.                         " -ForegroundColor Green
Write-Host "  URL:   http://localhost:8000/login.html                  " -ForegroundColor White
Write-Host "  API:   http://localhost:8002                             " -ForegroundColor White
Write-Host "  Durdurmak icin: .\stop.ps1                              " -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
