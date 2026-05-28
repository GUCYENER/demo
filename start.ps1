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

# UTF-8 console encoding — child process (node/npm/python) ciktilari UTF-8 verir.
# Aksi halde npm build report kutu cizimleri ve TR karakterleri CP850 olarak bozuk gozukur.
$OutputEncoding = [System.Text.UTF8Encoding]::new()
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

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

# 0. Graphify MCP On-Isindirma (tek hafiza katmani) — PG'den ONCE
#    Bat HER ZAMAN exit 0 doner; failure servisleri bloklamaz.
#    OPTIMIZASYON: Graphify zaten ayaktaysa warmup'i atla (gereksiz I/O yok).
Write-Host "[0/7] Graphify MCP on-isindirma..." -ForegroundColor Yellow

# Liveness check — hizli, sessiz, hatayi yutar.
$graphifyDir  = "C:\Users\EXT02D059293\Documents\General_Graphify"
$venvPy       = $VenvPython  # PG bloku oncesi tanimli; system python yoksa burada da kullaniriz
$sysPy        = (Get-Command python -ErrorAction SilentlyContinue).Source

$graphifyAlive = $false
$gfCli = Join-Path $graphifyDir "core\cli.py"
if (Test-Path $gfCli) {
    $pyForGf = if ($sysPy) { $sysPy } else { $venvPy }
    if (Test-Path $pyForGf) {
        try {
            Push-Location $graphifyDir
            & $pyForGf -m core.cli status --project vyra *> $null
            if ($LASTEXITCODE -eq 0) { $graphifyAlive = $true }
            Pop-Location
        } catch { try { Pop-Location } catch {} }
    }
}

if ($graphifyAlive) {
    Write-Host "   [SKIP] Graphify zaten ayakta - warmup atlandi" -ForegroundColor DarkGreen
} else {
    $mcpBat = "$ProjectRoot\mcp_warmup.bat"
    if (Test-Path $mcpBat) {
        Write-Host "   [WARM] Graphify isindirma gerekli..." -ForegroundColor Yellow
        & cmd.exe /c "`"$mcpBat`"" *> $null
        Write-Host "   [OK] Graphify isindirma tamamlandi (detay: mcp_warmup.bat ciktisi gizli)" -ForegroundColor Green
    } else {
        Write-Host "   [--] mcp_warmup.bat yok - atlandi (MCP fallback devreye girecek)" -ForegroundColor DarkGray
    }
}

# 0.5 Frontend bundle rebuild (esbuild, hem Windows hem WSL uyumlu)
#     `frontend/package.json` postinstall hook ile platform-spesifik esbuild
#     binary'sini garanti eder; build idempotent (esbuild cache).
Write-Host "[0.5/7] Frontend bundle rebuild..." -ForegroundColor Yellow
$frontendDir = "$ProjectRoot\frontend"
$buildScript = "$frontendDir\build.mjs"
$nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
if ($nodeExe -and (Test-Path $buildScript)) {
    Push-Location $frontendDir
    try {
        # `npm run build` postinstall + ensure-esbuild + build zincirini calistirir.
        # node_modules yoksa `npm install` once cagrilir.
        if (-not (Test-Path "$frontendDir\node_modules\esbuild")) {
            Write-Host "   [INSTALL] node_modules eksik, npm install calistiriliyor..." -ForegroundColor DarkYellow
            & npm install --silent 2>$null | Out-Null
        }
        & npm run build 2>&1 | Select-Object -Last 12
        if ($LASTEXITCODE -eq 0) {
            Write-Host "   [OK] dist/bundle.min.js + bundle.min.css guncellendi" -ForegroundColor Green
        } else {
            Write-Host "   [WARN] Bundle rebuild basarisiz (exit=$LASTEXITCODE) - mevcut dist kullanilacak" -ForegroundColor DarkYellow
        }
    } catch {
        Write-Host "   [WARN] Bundle rebuild hata: $_" -ForegroundColor DarkYellow
    } finally {
        Pop-Location
    }
} else {
    Write-Host "   [--] node bulunamadi veya build.mjs yok - bundle rebuild atlandi" -ForegroundColor DarkGray
}

# 1. PostgreSQL
Write-Host "[1/7] PostgreSQL baslatiliyor..." -ForegroundColor Yellow
$pgBin = "$ProjectRoot\pgsql\bin"
$pgData = "$ProjectRoot\pgsql\data"
$pgLog = "$pgData\server.log"

Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList "-D", "`"$pgData`"", "-l", "`"$pgLog`"", "start" -WindowStyle Hidden
Start-Sleep -Seconds 8
Write-Host "   [OK] PostgreSQL (port 5005)" -ForegroundColor Green

# 1.5. DB Migration (Alembic bypass — psycopg2 direkt, idempotent)
#      head'deyse hicbir sey yapmaz. Cikis kodlari: 0=OK, 1-99=hata.
$migScript = "$ProjectRoot\run_migrations.py"
if (Test-Path $migScript) {
    Write-Host "   [ADIM] DB migration kontrol ediliyor..." -ForegroundColor Yellow
    & $VenvPython $migScript
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [HATA] Migration basarisiz (exit=$LASTEXITCODE)" -ForegroundColor Red
        $migLog = "$ProjectRoot\migration_run.log"
        if (Test-Path $migLog) {
            Write-Host "   [HATA] Son 20 satir ($migLog):" -ForegroundColor Red
            Get-Content $migLog -Tail 20
        }
        exit 1
    }
    Write-Host "   [OK] Migration tamamlandi (detay: migration_run.log)" -ForegroundColor Green
} else {
    Write-Host "   [--] run_migrations.py bulunamadi - migration atlandi" -ForegroundColor DarkGray
}

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
