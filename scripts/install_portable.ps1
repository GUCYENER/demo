# ============================================================
# VYRA Portable Kurulum Scripti (Sunucu Tarafı)
# ============================================================
# Bu scripti İNTERNET OLMAYAN sunucuda çalıştırın!
# Python paketlerini offline_packages/ klasöründen kurar.
# ============================================================

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path "$ProjectRoot\app")) {
    Write-Host "[HATA] Bu script D:\VYRA\scripts\ klasorundan calistirilmali!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VYRA Portable Kurulum (Offline Sunucu)" -ForegroundColor Cyan
Write-Host "  Proje: $ProjectRoot" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$PortablePython = "$ProjectRoot\python\python.exe"
$PortablePip = "$ProjectRoot\python\Scripts\pip.exe"
$OfflineDir = "$ProjectRoot\offline_packages"
$ToolsDir = "$ProjectRoot\tools"

# ============================================================
# ADIM 0: Ön kontroller
# ============================================================
Write-Host "[0/4] On kontroller yapiliyor..." -ForegroundColor Yellow

# Python kontrol
if (-not (Test-Path $PortablePython)) {
    Write-Host "   [HATA] Portable Python bulunamadi: $PortablePython" -ForegroundColor Red
    Write-Host "   [INFO] Oncelikle Python'u python/ klasorune kurun." -ForegroundColor Gray
    exit 1
}
$pyVer = & $PortablePython --version 2>&1
Write-Host "   [OK] Python: $pyVer" -ForegroundColor Green

# Offline paketler kontrol
if (-not (Test-Path $OfflineDir)) {
    Write-Host "   [HATA] Offline paketler bulunamadi: $OfflineDir" -ForegroundColor Red
    exit 1
}
$pkgCount = (Get-ChildItem $OfflineDir -File | Measure-Object).Count
Write-Host "   [OK] Offline paketler: $pkgCount dosya" -ForegroundColor Green
Write-Host ""

# ============================================================
# ADIM 1: VC++ Redistributable Kurulumu
# ============================================================
Write-Host "[1/4] VC++ Redistributable kontrol ediliyor..." -ForegroundColor Yellow

$VcRedistPath = "$ToolsDir\vc_redist.x64.exe"
# Zaten kurulu mu kontrol et
$vcInstalled = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64" -ErrorAction SilentlyContinue
if ($vcInstalled) {
    Write-Host "   [OK] VC++ Redistributable zaten kurulu (v$($vcInstalled.Major).$($vcInstalled.Minor))" -ForegroundColor Green
} elseif (Test-Path $VcRedistPath) {
    Write-Host "   VC++ Redistributable kuruluyor (yonetici yetkisi gerekli)..." -ForegroundColor Gray
    Start-Process -FilePath $VcRedistPath -ArgumentList "/install", "/quiet", "/norestart" -Wait
    Write-Host "   [OK] VC++ Redistributable kuruldu" -ForegroundColor Green
} else {
    Write-Host "   [UYARI] VC++ Redistributable bulunamadi: $VcRedistPath" -ForegroundColor DarkYellow
    Write-Host "   [INFO] Bazi Python paketleri calisma zamani hatalari verebilir!" -ForegroundColor Gray
}
Write-Host ""

# ============================================================
# ADIM 2: Python Paketlerini Kur (Offline)
# ============================================================
Write-Host "[2/4] Python paketleri kuruluyor (offline)..." -ForegroundColor Yellow
Write-Host "   Bu islem 3-5 dakika surebilir..." -ForegroundColor Gray

$FrozenReqs = "$ProjectRoot\requirements_frozen.txt"
if (-not (Test-Path $FrozenReqs)) {
    Write-Host "   [HATA] requirements_frozen.txt bulunamadi!" -ForegroundColor Red
    exit 1
}

# pip upgrade (offline'dan)
$pipWheel = Get-ChildItem $OfflineDir -Filter "pip-*.whl" | Select-Object -First 1
if ($pipWheel) {
    & $PortablePython -m pip install --no-index --find-links $OfflineDir $pipWheel.FullName 2>&1 | Out-Null
}

# Tüm paketleri offline kur
& $PortablePip install --no-index --find-links $OfflineDir -r $FrozenReqs 2>&1 | ForEach-Object {
    if ($_ -match "Successfully installed") {
        Write-Host "   $_" -ForegroundColor Green
    } elseif ($_ -match "ERROR|Could not") {
        Write-Host "   $_" -ForegroundColor Red
    }
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [UYARI] Bazi paketler yuklenemedi. Log'u kontrol edin." -ForegroundColor DarkYellow
} else {
    $installedCount = (& $PortablePip list --format=freeze 2>$null | Measure-Object -Line).Lines
    Write-Host "   [OK] $installedCount paket basariyla kuruldu" -ForegroundColor Green
}
Write-Host ""

# ============================================================
# ADIM 3: Nginx Config Kontrolu
# ============================================================
Write-Host "[3/4] Nginx yapilandiriliyor..." -ForegroundColor Yellow

$NginxDir = "$ProjectRoot\nginx"

if (Test-Path "$NginxDir\nginx.exe") {
    # conf.d klasörünü oluştur
    if (-not (Test-Path "$NginxDir\conf\conf.d")) {
        New-Item -ItemType Directory -Path "$NginxDir\conf\conf.d" -Force | Out-Null
    }
    
    # vyra.conf kopyala
    if (Test-Path "$ProjectRoot\deploy\nginx\vyra.conf") {
        Copy-Item "$ProjectRoot\deploy\nginx\vyra.conf" "$NginxDir\conf\conf.d\vyra.conf" -Force
    }
    
    # nginx.conf kontrol
    $ngConf = Get-Content "$NginxDir\conf\nginx.conf" -Raw -ErrorAction SilentlyContinue
    if ($ngConf -notmatch 'include\s+conf\.d') {
        $newConf = @"
worker_processes auto;
error_log logs/error.log warn;
pid logs/nginx.pid;
events { worker_connections 1024; }
http {
    include mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;
    include conf.d/*.conf;
}
"@
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText("$NginxDir\conf\nginx.conf", $newConf, $utf8NoBom)
        Write-Host "   [OK] nginx.conf guncellendi" -ForegroundColor Green
    } else {
        Write-Host "   [OK] nginx.conf hazir" -ForegroundColor Green
    }
    
    # Config test
    Push-Location $NginxDir
    & "$NginxDir\nginx.exe" -t 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "   [OK] Nginx config testi basarili" -ForegroundColor Green
    } else {
        Write-Host "   [UYARI] Nginx config testi basarisiz" -ForegroundColor DarkYellow
    }
    Pop-Location
} else {
    Write-Host "   [UYARI] Nginx bulunamadi: $NginxDir" -ForegroundColor DarkYellow
}
Write-Host ""

# ============================================================
# ADIM 4: .env Kontrolü
# ============================================================
Write-Host "[4/4] .env dosyasi kontrol ediliyor..." -ForegroundColor Yellow

$envFile = "$ProjectRoot\.env"
if (Test-Path $envFile) {
    $envContent = Get-Content $envFile -Raw
    
    # HF_HOME kontrolü
    if ($envContent -notmatch "HF_HOME") {
        Add-Content $envFile "`n# HuggingFace Offline Mode`nHF_HOME=./models/hf_cache`nHF_HUB_OFFLINE=1`nTRANSFORMERS_OFFLINE=1"
        Write-Host "   [OK] HuggingFace offline ayarlari eklendi" -ForegroundColor Green
    } else {
        Write-Host "   [OK] HuggingFace ayarlari zaten mevcut" -ForegroundColor Green
    }
    
    # JWT_SECRET kontrolü
    if ($envContent -match 'JWT_SECRET\s*=\s*$' -or $envContent -match 'JWT_SECRET\s*=\s*CHANGE_ME') {
        Write-Host "   [UYARI] JWT_SECRET ayarlanmamis! .env dosyasini duzenleyin." -ForegroundColor DarkYellow
    } else {
        Write-Host "   [OK] JWT_SECRET ayarli" -ForegroundColor Green
    }
} else {
    Write-Host "   [UYARI] .env dosyasi bulunamadi!" -ForegroundColor DarkYellow
    Write-Host "   [INFO] .env.example dosyasini .env olarak kopyalayin ve duzenleyin." -ForegroundColor Gray
}
Write-Host ""

# ============================================================
# SONUÇ
# ============================================================
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  KURULUM TAMAMLANDI!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Baslatmak icin:" -ForegroundColor Yellow
Write-Host "    canlida_calistir.bat" -ForegroundColor White
Write-Host ""
Write-Host "  Test URL:" -ForegroundColor Yellow
Write-Host "    http://localhost/login.html" -ForegroundColor White
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
