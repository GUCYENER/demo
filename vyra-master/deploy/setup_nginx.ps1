# =============================================================
# VYRA L1 Support - Nginx Setup Script (Windows)
# =============================================================

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = "D:\VYRA" }

$NginxVersion = "1.27.4"
$NginxDir = "D:\nginx"
$NginxZip = "$env:TEMP\nginx-$NginxVersion.zip"
$NginxUrl = "https://nginx.org/download/nginx-$NginxVersion.zip"

Write-Host ""
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host "  VYRA - Nginx Setup ($NginxVersion)" -ForegroundColor Cyan
Write-Host "=============================================================" -ForegroundColor Cyan
Write-Host ""

# =============================================================
# 1. Nginx Indir
# =============================================================
if (Test-Path "$NginxDir\nginx.exe") {
    Write-Host "[1/4] Nginx zaten kurulu: $NginxDir" -ForegroundColor Green
} else {
    Write-Host "[1/4] Nginx indiriliyor..." -ForegroundColor Yellow
    Write-Host "   URL: $NginxUrl" -ForegroundColor Gray

    try {
        Invoke-WebRequest -Uri $NginxUrl -OutFile $NginxZip -UseBasicParsing
        Write-Host "   [OK] Indirildi: $NginxZip" -ForegroundColor Green
    } catch {
        Write-Host "   [HATA] Nginx indirilemedi!" -ForegroundColor Red
        Write-Host "   Manuel indirme: $NginxUrl" -ForegroundColor Yellow
        exit 1
    }

    # =============================================================
    # 2. Zip Ac
    # =============================================================
    Write-Host "[2/4] Nginx cikartiliyor..." -ForegroundColor Yellow

    $tempExtract = "$env:TEMP\nginx-extract"
    if (Test-Path $tempExtract) { Remove-Item $tempExtract -Recurse -Force }

    Expand-Archive -Path $NginxZip -DestinationPath $tempExtract -Force

    # nginx-X.Y.Z klasorunu D:\nginx e tasi
    $extractedDir = Get-ChildItem $tempExtract -Directory | Select-Object -First 1
    
    if (Test-Path $NginxDir) { Remove-Item $NginxDir -Recurse -Force }
    Move-Item $extractedDir.FullName $NginxDir -Force

    # Temizlik
    Remove-Item $NginxZip -Force -ErrorAction SilentlyContinue
    Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue

    Write-Host "   [OK] Nginx kuruldu: $NginxDir" -ForegroundColor Green
}

# =============================================================
# 3. conf.d Dizini + VYRA Config
# =============================================================
Write-Host "[3/4] Nginx yapilandiriliyor..." -ForegroundColor Yellow

$confDir = "$NginxDir\conf\conf.d"
if (-not (Test-Path $confDir)) {
    New-Item -ItemType Directory -Path $confDir -Force | Out-Null
}

# VYRA config kopyala
$confSource = "$ProjectRoot\deploy\nginx\vyra.conf"
$confTarget = "$confDir\vyra.conf"
Copy-Item $confSource $confTarget -Force
Write-Host "   [OK] vyra.conf kopyalandi" -ForegroundColor Green

# nginx.conf a include ekle (yoksa)
$mainConf = "$NginxDir\conf\nginx.conf"
$mainContent = Get-Content $mainConf -Raw

if ($mainContent -notmatch "include\s+conf\.d") {
    # http blogunun icine include ekle
    $includeDirective = "    include conf.d/*.conf;`n"
    
    $mainContent = $mainContent -replace '(http\s*\{[^}]*server\s*\{[^}]*\}[^}]*)', "`$1`n$includeDirective"
    
    # BOM'suz UTF8 ile yaz (Nginx BOM'u parse edemez)
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($mainConf, $mainContent, $utf8NoBom)
    Write-Host "   [OK] nginx.conf include eklendi" -ForegroundColor Green
} else {
    Write-Host "   [OK] nginx.conf zaten conf.d include ediyor" -ForegroundColor Gray
}

# =============================================================
# 4. Config Test
# =============================================================
Write-Host "[4/4] Nginx config testi..." -ForegroundColor Yellow

Push-Location $NginxDir
$testResult = & "$NginxDir\nginx.exe" -t 2>&1
Pop-Location

if ($testResult -match "test is successful") {
    Write-Host "   [OK] Nginx config testi BASARILI" -ForegroundColor Green
} else {
    Write-Host "   [UYARI] Config testi sonucu:" -ForegroundColor Yellow
    Write-Host "   $testResult" -ForegroundColor Yellow
    Write-Host "   [INFO] Manuel duzeltme gerekebilir: $mainConf" -ForegroundColor Cyan
}

# =============================================================
# SONUC
# =============================================================
Write-Host ""
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "  Nginx kurulumu tamamlandi!" -ForegroundColor Green
Write-Host "=============================================================" -ForegroundColor Green
Write-Host "  Dizin:  $NginxDir" -ForegroundColor Green
Write-Host "  Config: $confTarget" -ForegroundColor Green
Write-Host ""
Write-Host "  Production baslatmak:" -ForegroundColor Yellow
Write-Host "    deploy\start_production.ps1" -ForegroundColor Yellow
Write-Host "=============================================================" -ForegroundColor Green
Write-Host ""
