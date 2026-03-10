# =============================================================
# VYRA L1 Support — Sunucu İlk Kurulum Scripti
# =============================================================
# GitHub'dan çekilen kodu canlıda ayağa kaldırmak için.
# Sistem Python + Sistem PostgreSQL kullanır.
#
# Kullanım:
#   .\deploy\setup_server.ps1
#   .\deploy\setup_server.ps1 -PgBinDir "C:\Program Files\PostgreSQL\16\bin"
#   .\deploy\setup_server.ps1 -SkipNginx
# =============================================================

param(
    [string]$PgBinDir = "",
    [string]$NginxVersion = "1.27.4",
    [switch]$SkipNginx,
    [switch]$SkipDB
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = "D:\VYRA" }

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VYRA L1 Support - Sunucu Ilk Kurulum" -ForegroundColor Cyan
Write-Host "  Proje: $ProjectRoot" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# =============================================================
# ADIM 1: Python Kontrolü
# =============================================================
Write-Host "[1/6] Python kontrol ediliyor..." -ForegroundColor Yellow
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    Write-Host "   [HATA] Python bulunamadi!" -ForegroundColor Red
    Write-Host "   Python 3.10+ kurulu olmalidir." -ForegroundColor Red
    Write-Host "   Indir: https://www.python.org/downloads/" -ForegroundColor Cyan
    exit 1
}
$pyVersion = & python --version 2>&1
Write-Host "   [OK] $pyVersion" -ForegroundColor Green

# =============================================================
# ADIM 2: Virtual Environment
# =============================================================
Write-Host "[2/6] Virtual Environment olusturuluyor..." -ForegroundColor Yellow
$VenvDir = "$ProjectRoot\.venv"
$VenvPython = "$VenvDir\Scripts\python.exe"
$VenvPip = "$VenvDir\Scripts\pip.exe"

if (-not (Test-Path $VenvPython)) {
    & python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [HATA] venv olusturulamadi!" -ForegroundColor Red
        exit 1
    }
    Write-Host "   [OK] venv olusturuldu: $VenvDir" -ForegroundColor Green
} else {
    Write-Host "   [OK] venv zaten mevcut" -ForegroundColor Green
}

# =============================================================
# ADIM 3: Python Bağımlılıkları (Internet)
# =============================================================
Write-Host "[3/6] Python bagimliliklari yukleniyor (internet)..." -ForegroundColor Yellow
Write-Host "   [INFO] Ilk seferde 10-15 dakika surebilir (ML modelleri buyuk)" -ForegroundColor Cyan

# pip güncelle
Write-Host "   [INFO] pip guncelleniyor..." -ForegroundColor Gray
& $VenvPip install --upgrade pip 2>&1 | Out-Null

# PyTorch CPU-only (GPU olmayan sunucular için, ~200MB vs ~2GB tasarruf)
Write-Host "   [INFO] PyTorch (CPU) yukleniyor..." -ForegroundColor Gray
& $VenvPip install torch torchvision --index-url https://download.pytorch.org/whl/cpu 2>&1 | Out-Null

# Diğer bağımlılıklar
Write-Host "   [INFO] Diger bagimliliklar yukleniyor..." -ForegroundColor Gray
& $VenvPip install -r "$ProjectRoot\requirements.txt" 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "   [HATA] Bagimlilik kurulumu basarisiz!" -ForegroundColor Red
    exit 1
}
Write-Host "   [OK] Tum bagimliliklar yuklendi" -ForegroundColor Green

# =============================================================
# ADIM 4: .env Dosyası
# =============================================================
Write-Host "[4/6] .env dosyasi kontrol ediliyor..." -ForegroundColor Yellow

if (-not (Test-Path "$ProjectRoot\.env")) {
    Copy-Item "$ProjectRoot\.env.example" "$ProjectRoot\.env"
    Write-Host "   [UYARI] .env.example -> .env olarak kopyalandi" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "   *** ZORUNLU: .env dosyasini acip asagidakileri duzenleyin: ***" -ForegroundColor Red
    Write-Host "       JWT_SECRET    = (en az 32 karakter, benzersiz)" -ForegroundColor White
    Write-Host "       DB_PASSWORD   = (PostgreSQL sifresi)" -ForegroundColor White
    Write-Host "       DB_PORT       = 5005 (PostgreSQL portu)" -ForegroundColor White
    Write-Host "       PG_BIN_DIR    = (PostgreSQL bin dizini)" -ForegroundColor White
    Write-Host "       CORS_ORIGINS  = (sunucu IP veya domain)" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "   [OK] .env mevcut" -ForegroundColor Green
}

# =============================================================
# ADIM 5: PostgreSQL Veritabanı Kurulumu
# =============================================================
if ($SkipDB) {
    Write-Host "[5/6] PostgreSQL ATLANDI (-SkipDB)" -ForegroundColor Gray
} else {
    Write-Host "[5/6] PostgreSQL veritabani olusturuluyor..." -ForegroundColor Yellow

    # .env'den ayarları oku
    $envContent = Get-Content "$ProjectRoot\.env" -ErrorAction SilentlyContinue
    $dbPort = "5005"
    $dbName = "vyra"
    $dbUser = "vyra_app"
    $dbPassword = "postgres"
    $envPgBinDir = ""

    foreach ($line in $envContent) {
        if ($line -match '^\s*DB_PORT\s*=\s*(.+)') { $dbPort = $Matches[1].Trim() }
        if ($line -match '^\s*DB_NAME\s*=\s*(.+)') { $dbName = $Matches[1].Trim() }
        if ($line -match '^\s*DB_USER\s*=\s*(.+)') { $dbUser = $Matches[1].Trim() }
        if ($line -match '^\s*DB_PASSWORD\s*=\s*(.+)') { $dbPassword = $Matches[1].Trim() }
        if ($line -match '^\s*PG_BIN_DIR\s*=\s*(.+)') { $envPgBinDir = $Matches[1].Trim() }
    }

    # PostgreSQL bin dizinini bul (öncelik: parametre > .env > PATH > varsayılan)
    $pgBin = ""
    if ($PgBinDir) {
        $pgBin = $PgBinDir
    } elseif ($envPgBinDir) {
        $pgBin = $envPgBinDir
    } else {
        $psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
        if ($psqlCmd) {
            $pgBin = Split-Path $psqlCmd.Source
        } else {
            $pgSearchPaths = @(
                "C:\Program Files\PostgreSQL\17\bin",
                "C:\Program Files\PostgreSQL\16\bin",
                "C:\Program Files\PostgreSQL\15\bin",
                "C:\Program Files\PostgreSQL\14\bin"
            )
            foreach ($p in $pgSearchPaths) {
                if (Test-Path "$p\psql.exe") {
                    $pgBin = $p
                    break
                }
            }
        }
    }

    if (-not $pgBin -or -not (Test-Path "$pgBin\psql.exe")) {
        Write-Host "   [HATA] PostgreSQL bulunamadi!" -ForegroundColor Red
        Write-Host "   Cozumler:" -ForegroundColor Yellow
        Write-Host "     1) PostgreSQL kurun: https://www.postgresql.org/download/windows/" -ForegroundColor White
        Write-Host "     2) -PgBinDir parametresi kullanin" -ForegroundColor White
        Write-Host "     3) .env dosyasinda PG_BIN_DIR ayarlayin" -ForegroundColor White
        exit 1
    }
    Write-Host "   [OK] PostgreSQL: $pgBin" -ForegroundColor Gray

    # PostgreSQL çalışıyor mu kontrol et
    & "$pgBin\pg_isready.exe" -h localhost -p $dbPort 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [UYARI] PostgreSQL calismiyordu, baslatmaya calisiliyor..." -ForegroundColor Yellow
        $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pgService) {
            Start-Service $pgService.Name -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 5
            & "$pgBin\pg_isready.exe" -h localhost -p $dbPort 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-Host "   [HATA] PostgreSQL baslatilamadi! Servisi manuel baslatin." -ForegroundColor Red
                exit 1
            }
        } else {
            Write-Host "   [HATA] PostgreSQL servisi bulunamadi!" -ForegroundColor Red
            Write-Host "   PostgreSQL'in Windows Service olarak calistigini kontrol edin." -ForegroundColor Yellow
            exit 1
        }
    }
    Write-Host "   [OK] PostgreSQL calisiyor (port $dbPort)" -ForegroundColor Green

    # Veritabanı var mı?
    $env:PGPASSWORD = "postgres"
    $dbExists = & "$pgBin\psql.exe" -U postgres -h localhost -p $dbPort -t -A -c "SELECT 1 FROM pg_database WHERE datname='$dbName'" 2>$null
    if ($dbExists -match "1") {
        Write-Host "   [OK] Veritabani '$dbName' zaten mevcut" -ForegroundColor Green
    } else {
        Write-Host "   [INFO] Veritabani olusturuluyor..." -ForegroundColor Gray

        # Kullanıcı oluştur (hata tolere et — zaten var olabilir)
        & "$pgBin\psql.exe" -U postgres -h localhost -p $dbPort -c "DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$dbUser') THEN CREATE ROLE $dbUser WITH LOGIN PASSWORD '$dbPassword'; END IF; END `$`$;" 2>$null

        # Veritabanı oluştur
        & "$pgBin\psql.exe" -U postgres -h localhost -p $dbPort -c "CREATE DATABASE $dbName OWNER $dbUser ENCODING 'UTF8' LC_COLLATE 'Turkish_Turkey.1254' LC_CTYPE 'Turkish_Turkey.1254' TEMPLATE template0" 2>$null
        if ($LASTEXITCODE -ne 0) {
            # Fallback: locale olmadan dene
            & "$pgBin\psql.exe" -U postgres -h localhost -p $dbPort -c "CREATE DATABASE $dbName OWNER $dbUser ENCODING 'UTF8'" 2>$null
        }

        # Yetki ver
        & "$pgBin\psql.exe" -U postgres -h localhost -p $dbPort -c "GRANT ALL PRIVILEGES ON DATABASE $dbName TO $dbUser" 2>$null

        # pgvector extension
        & "$pgBin\psql.exe" -U postgres -h localhost -p $dbPort -d $dbName -c "CREATE EXTENSION IF NOT EXISTS vector" 2>$null

        Write-Host "   [OK] Veritabani '$dbName' olusturuldu (user: $dbUser)" -ForegroundColor Green
    }

    # Alembic migration
    Write-Host "   [INFO] Alembic migration calistiriliyor..." -ForegroundColor Gray
    Push-Location $ProjectRoot
    $env:PYTHONPATH = $ProjectRoot
    try {
        & $VenvPython -m alembic upgrade head 2>&1
        Write-Host "   [OK] Migration tamamlandi" -ForegroundColor Green
    } catch {
        Write-Host "   [UYARI] Migration hatasi: $_" -ForegroundColor Yellow
        Write-Host "   init_db otomatik devreye alacak." -ForegroundColor Gray
    }
    Pop-Location
}

# =============================================================
# ADIM 6: Nginx Kurulumu
# =============================================================
if ($SkipNginx) {
    Write-Host "[6/6] Nginx ATLANDI (-SkipNginx)" -ForegroundColor Gray
} else {
    Write-Host "[6/6] Nginx kontrol ediliyor..." -ForegroundColor Yellow

    $NginxDir = "$ProjectRoot\nginx"
    $NginxExe = "$NginxDir\nginx.exe"

    if (-not (Test-Path $NginxExe)) {
        Write-Host "   [INFO] Nginx $NginxVersion indiriliyor..." -ForegroundColor Cyan
        $nginxZip = "$env:TEMP\nginx-$NginxVersion.zip"
        $nginxUrl = "https://nginx.org/download/nginx-$NginxVersion.zip"

        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $nginxUrl -OutFile $nginxZip -UseBasicParsing
            Expand-Archive $nginxZip -DestinationPath $env:TEMP -Force

            if (-not (Test-Path $NginxDir)) { New-Item -ItemType Directory -Path $NginxDir -Force | Out-Null }
            Copy-Item "$env:TEMP\nginx-$NginxVersion\*" $NginxDir -Recurse -Force
            Remove-Item $nginxZip -Force -ErrorAction SilentlyContinue
            Remove-Item "$env:TEMP\nginx-$NginxVersion" -Recurse -Force -ErrorAction SilentlyContinue

            Write-Host "   [OK] Nginx $NginxVersion kuruldu: $NginxDir" -ForegroundColor Green
        } catch {
            Write-Host "   [UYARI] Nginx indirilemedi: $_" -ForegroundColor Yellow
            Write-Host "   Manuel indirme: $nginxUrl" -ForegroundColor Cyan
            Write-Host "   Indirip $NginxDir konumuna acin." -ForegroundColor Cyan
        }
    } else {
        Write-Host "   [OK] Nginx zaten kurulu" -ForegroundColor Green
    }

    # Nginx config oluştur
    if (Test-Path $NginxExe) {
        $confDir = "$NginxDir\conf\conf.d"
        if (-not (Test-Path $confDir)) { New-Item -ItemType Directory -Path $confDir -Force | Out-Null }

        # Template'den config oluştur — path'i proje dizinine göre ayarla
        $confTemplate = Get-Content "$ProjectRoot\deploy\nginx\vyra.conf" -Raw
        $normalizedRoot = $ProjectRoot -replace '\\', '/'
        $confFinal = $confTemplate -replace 'root\s+[A-Za-z]:/[^;]+/frontend', "root    $normalizedRoot/frontend"
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText("$confDir\vyra.conf", $confFinal, $utf8NoBom)
        Write-Host "   [OK] vyra.conf kopyalandi (root: $normalizedRoot/frontend)" -ForegroundColor Gray

        # nginx.conf güncelle
        $nginxConf = Get-Content "$NginxDir\conf\nginx.conf" -Raw -ErrorAction SilentlyContinue
        if ($nginxConf -notmatch 'include\s+conf\.d') {
            $newConf = @"
worker_processes auto;
error_log logs/error.log warn;
pid logs/nginx.pid;

events {
    worker_connections 1024;
}

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
            [System.IO.File]::WriteAllText("$NginxDir\conf\nginx.conf", $newConf, $utf8NoBom)
            Write-Host "   [OK] nginx.conf guncellendi" -ForegroundColor Gray
        }

        # Config test
        Push-Location $NginxDir
        & $NginxExe -t 2>$null
        Pop-Location
        if ($LASTEXITCODE -eq 0) {
            Write-Host "   [OK] Nginx config testi basarili" -ForegroundColor Green
        } else {
            Write-Host "   [UYARI] Nginx config testi basarisiz — kontrol edin" -ForegroundColor Yellow
        }
    }
}

# =============================================================
# SONUÇ
# =============================================================
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  VYRA SUNUCU KURULUMU TAMAMLANDI!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Sonraki adimlar:" -ForegroundColor Yellow
Write-Host "    1. .env dosyasini kontrol edin" -ForegroundColor White
Write-Host "       - JWT_SECRET (en az 32 karakter)" -ForegroundColor Gray
Write-Host "       - DB_PASSWORD" -ForegroundColor Gray
Write-Host "       - CORS_ORIGINS (sunucu IP/domain)" -ForegroundColor Gray
Write-Host "       - PG_BIN_DIR (PostgreSQL bin dizini)" -ForegroundColor Gray
Write-Host ""
Write-Host "    2. Servisleri baslatin:" -ForegroundColor White
Write-Host "       .\deploy\start_server.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
