# ============================================================
# VYRA L1 Support API - Durdurma Scripti
# ============================================================

$ErrorActionPreference = "SilentlyContinue"

$ProjectRoot = $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = "d:\vyra_l1_fastapi" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Red
Write-Host "         VYRA L1 Support API - Durdurma                     " -ForegroundColor Red
Write-Host "============================================================" -ForegroundColor Red
Write-Host ""

# 1. Nginx Durdur
Write-Host "[1/4] Nginx durduruluyor..." -ForegroundColor Yellow

$nginxDir = "$ProjectRoot\nginx"
$nginxExe = "$nginxDir\nginx.exe"
$nginxProcs = Get-Process -Name "nginx" -ErrorAction SilentlyContinue
if ($nginxProcs) {
    if (Test-Path $nginxExe) {
        Push-Location $nginxDir
        & $nginxExe -s quit 2>$null
        Pop-Location
        Start-Sleep -Seconds 2
    }
    # Kalan nginx process'lerini zorla kapat
    Get-Process -Name "nginx" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "   [OK] Nginx durduruldu" -ForegroundColor Green
} else {
    Write-Host "   [--] Nginx zaten calismiyordu" -ForegroundColor Gray
}

# 2. Python islemlerini durdur
Write-Host ""
Write-Host "[2/4] Python islemleri durduruluyor..." -ForegroundColor Yellow

# Tum python.exe'leri durdur
$pythonProcs = Get-Process -Name "python" -ErrorAction SilentlyContinue
if ($pythonProcs) {
    $pythonProcs | ForEach-Object {
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
    Write-Host "   [OK] Python islemleri durduruldu" -ForegroundColor Green
} else {
    Write-Host "   [--] Python islemleri zaten calismiyordu" -ForegroundColor Gray
}

# 3. Redis Durdur
Write-Host ""
Write-Host "[3/4] Redis durduruluyor..." -ForegroundColor Yellow

$redisCli = "$ProjectRoot\redis\redis-cli.exe"
if (Test-Path $redisCli) {
    $response = & $redisCli ping 2>$null
    if ($response -eq "PONG") {
        & $redisCli shutdown nosave 2>$null
        Write-Host "   [OK] Redis durduruldu" -ForegroundColor Green
    } else {
        Write-Host "   [--] Redis zaten calismiyordu" -ForegroundColor Gray
    }
} else {
    Write-Host "   [--] Redis kurulu degil" -ForegroundColor Gray
}

# 4. PostgreSQL Durdur
Write-Host ""
Write-Host "[4/4] PostgreSQL durduruluyor..." -ForegroundColor Yellow

$pgBin = "$ProjectRoot\pgsql\bin"
$pgData = "$ProjectRoot\pgsql\data"

$null = & "$pgBin\pg_isready.exe" -h localhost -p 5005 2>$null
if ($LASTEXITCODE -eq 0) {
    Start-Process -FilePath "$pgBin\pg_ctl.exe" -ArgumentList "-D", "`"$pgData`"", "stop", "-m", "fast" -WindowStyle Hidden -Wait
    Write-Host "   [OK] PostgreSQL durduruldu" -ForegroundColor Green
} else {
    Write-Host "   [--] PostgreSQL zaten calismiyordu" -ForegroundColor Gray
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Baslatmak icin: .\start.ps1                                " -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
