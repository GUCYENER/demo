# ============================================================
# VYRA L1 Support API - Veritabanı Yedekleme Scripti
# ============================================================
# Kullanım: .\scripts\backup_db.ps1
# ============================================================

param(
    [switch]$Restore,          # -Restore ile geri yükleme modu
    [string]$BackupFile = ""   # -BackupFile ile belirli bir yedek dosyası
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $ProjectRoot) { $ProjectRoot = "d:\VYRA" }

# PostgreSQL ayarları
$pgBin = "$ProjectRoot\pgsql\bin"
$BackupDir = "$ProjectRoot\backups"
$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

# Veritabanı bilgileri (.env'den veya varsayılan)
$DB_HOST = "localhost"
$DB_PORT = "5005"
$DB_NAME = "vyra"
$DB_USER = "postgres"

# .env dosyasından oku (varsa)
$envFile = "$ProjectRoot\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match "^(DB_HOST|DB_PORT|DB_NAME|DB_USER)=(.+)$") {
            Set-Variable -Name $matches[1] -Value $matches[2]
        }
    }
}

# Backup dizinini oluştur
if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VYRA Veritabanı Yedekleme Aracı" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($Restore) {
    # === RESTORE MODU ===
    
    if (-not $BackupFile) {
        # En son yedeği bul
        $latestBackup = Get-ChildItem -Path $BackupDir -Filter "*.sql" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $latestBackup) {
            Write-Host "  [HATA] Yedek dosyası bulunamadı: $BackupDir" -ForegroundColor Red
            exit 1
        }
        $BackupFile = $latestBackup.FullName
    }
    
    if (-not (Test-Path $BackupFile)) {
        Write-Host "  [HATA] Dosya bulunamadı: $BackupFile" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "  [!] GERİ YÜKLEME MODU" -ForegroundColor Yellow
    Write-Host "  Kaynak: $BackupFile" -ForegroundColor White
    Write-Host ""
    $confirm = Read-Host "  Devam etmek istiyor musunuz? (evet/hayir)"
    
    if ($confirm -ne "evet") {
        Write-Host "  İşlem iptal edildi." -ForegroundColor Yellow
        exit 0
    }
    
    Write-Host ""
    Write-Host "  Geri yükleniyor..." -ForegroundColor Yellow
    
    $env:PGPASSWORD = "postgres"
    & "$pgBin\psql.exe" -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -f $BackupFile 2>&1 | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] Geri yükleme tamamlandı!" -ForegroundColor Green
    } else {
        Write-Host "  [HATA] Geri yükleme başarısız!" -ForegroundColor Red
    }
    
} else {
    # === BACKUP MODU ===
    
    $backupFile = "$BackupDir\vyra_backup_$Timestamp.sql"
    
    Write-Host "  Hedef: $backupFile" -ForegroundColor White
    Write-Host "  Yedekleniyor..." -ForegroundColor Yellow
    
    $env:PGPASSWORD = "postgres"
    & "$pgBin\pg_dump.exe" -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME --clean --if-exists -f $backupFile 2>&1 | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        $size = (Get-Item $backupFile).Length / 1KB
        Write-Host "  [OK] Yedekleme tamamlandı! ($([math]::Round($size, 1)) KB)" -ForegroundColor Green
        
        # Eski yedekleri temizle (30 günden eski)
        $oldBackups = Get-ChildItem -Path $BackupDir -Filter "*.sql" | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) }
        if ($oldBackups) {
            $oldBackups | Remove-Item -Force
            Write-Host "  [OK] $($oldBackups.Count) eski yedek silindi (30+ gün)" -ForegroundColor DarkGray
        }
    } else {
        Write-Host "  [HATA] Yedekleme başarısız!" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
