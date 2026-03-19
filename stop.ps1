# ============================================================
# VYRA L1 Support API - Durdurma Scripti
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
if (-not $ProjectRoot) { $ProjectRoot = "d:\demo_vyra" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "         VYRA L1 Support API - Durdurma" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Frontend (Python serve.py) durdur
Write-Host "[1/4] Frontend durduruluyor..." -ForegroundColor Yellow
$frontendProcs = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    try {
        $_.CommandLine -match "serve\.py"
    } catch { $false }
}
if ($frontendProcs) {
    $frontendProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "   [OK] Frontend durduruldu" -ForegroundColor Green
} else {
    # Port bazli durdurma (fallback)
    $frontendPid = (Get-NetTCPConnection -LocalPort 5500 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
    if ($frontendPid -and $frontendPid -ne 0) {
        Stop-Process -Id $frontendPid -Force -ErrorAction SilentlyContinue
        Write-Host "   [OK] Frontend durduruldu (PID: $frontendPid)" -ForegroundColor Green
    } else {
        Write-Host "   [--] Frontend zaten calismiyordu" -ForegroundColor DarkGray
    }
}

# 2. Backend (Uvicorn) durdur
Write-Host "[2/4] Backend durduruluyor..." -ForegroundColor Yellow
$backendProcs = Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object {
    try {
        $_.CommandLine -match "uvicorn"
    } catch { $false }
}
if ($backendProcs) {
    $backendProcs | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "   [OK] Backend durduruldu" -ForegroundColor Green
} else {
    # Port bazli durdurma (fallback)
    $backendPid = (Get-NetTCPConnection -LocalPort 8002 -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
    if ($backendPid -and $backendPid -ne 0) {
        Stop-Process -Id $backendPid -Force -ErrorAction SilentlyContinue
        Write-Host "   [OK] Backend durduruldu (PID: $backendPid)" -ForegroundColor Green
    } else {
        Write-Host "   [--] Backend zaten calismiyordu" -ForegroundColor DarkGray
    }
}

# 3. Redis durdur
Write-Host "[3/4] Redis durduruluyor..." -ForegroundColor Yellow
$redisCli = "$ProjectRoot\redis\redis-cli.exe"
if (Test-Path $redisCli) {
    try {
        $pong = & $redisCli ping 2>$null
        if ($pong -eq "PONG") {
            & $redisCli shutdown nosave 2>$null | Out-Null
            Start-Sleep -Seconds 1
            Write-Host "   [OK] Redis durduruldu" -ForegroundColor Green
        } else {
            Write-Host "   [--] Redis zaten calismiyordu" -ForegroundColor DarkGray
        }
    } catch {
        Write-Host "   [--] Redis zaten calismiyordu" -ForegroundColor DarkGray
    }
} else {
    $redisProc = Get-Process -Name "redis-server" -ErrorAction SilentlyContinue
    if ($redisProc) {
        $redisProc | Stop-Process -Force -ErrorAction SilentlyContinue
        Write-Host "   [OK] Redis durduruldu (force)" -ForegroundColor Green
    } else {
        Write-Host "   [--] Redis bulunamadi/calismiyordu" -ForegroundColor DarkGray
    }
}

# 4. PostgreSQL durdur
Write-Host "[4/4] PostgreSQL durduruluyor..." -ForegroundColor Yellow
$pgCtl = "$ProjectRoot\pgsql\bin\pg_ctl.exe"
$pgData = "$ProjectRoot\pgsql\data"
if (Test-Path $pgCtl) {
    & $pgCtl -D "$pgData" stop -m fast 2>$null | Out-Null
    Start-Sleep -Seconds 2
    Write-Host "   [OK] PostgreSQL durduruldu" -ForegroundColor Green
} else {
    Write-Host "   [--] PostgreSQL binary bulunamadi" -ForegroundColor DarkGray
}

# Tum powershell pencerelerini temizle (backend/frontend child process'ler)
$childWindows = Get-Process -Name "powershell" -ErrorAction SilentlyContinue | Where-Object {
    $_.Id -ne $PID -and $_.MainWindowTitle -match "python|uvicorn|serve"
}
if ($childWindows) {
    $childWindows | Stop-Process -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  VYRA tamamen durduruldu.                                  " -ForegroundColor Green
Write-Host "  Tekrar baslatmak icin: .\start.ps1                       " -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
