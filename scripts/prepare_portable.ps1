# ============================================================
# VYRA Portable Hazırlık Scripti
# ============================================================
# Bu scripti İNTERNET OLAN makinede çalıştırın!
# Tüm bağımlılıkları portable hale getirir.
# ============================================================

param(
    [switch]$SkipPython,
    [switch]$SkipPackages,
    [switch]$SkipModel,
    [switch]$SkipNginx,
    [switch]$SkipVcRedist
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "$ProjectRoot\app")) {
    $ProjectRoot = "D:\VYRA"
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  VYRA Portable Hazırlık Scripti" -ForegroundColor Cyan
Write-Host "  Proje: $ProjectRoot" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$VenvPython = "$ProjectRoot\.venv\Scripts\python.exe"
$PortablePython = "$ProjectRoot\python"
$OfflineDir = "$ProjectRoot\offline_packages"
$HfCacheDir = "$ProjectRoot\models\hf_cache"
$NginxDir = "$ProjectRoot\nginx"
$ToolsDir = "$ProjectRoot\tools"

# ============================================================
# ADIM 1: Portable Python Oluştur
# ============================================================
if (-not $SkipPython) {
    Write-Host "[1/5] Portable Python olusturuluyor..." -ForegroundColor Yellow
    
    if (Test-Path $PortablePython) {
        Write-Host "   [UYARI] python/ klasoru zaten mevcut, atlaniyor." -ForegroundColor DarkYellow
        Write-Host "   [INFO] Yeniden olusturmak icin klasoru silin." -ForegroundColor Gray
    } else {
        # Mevcut venv Python'undan yeni bir venv oluştur (--copies ile)
        Write-Host "   Python venv kopyalaniyor (--copies)..." -ForegroundColor Gray
        & $VenvPython -m venv $PortablePython --copies 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "   [HATA] Python venv olusturulamadi!" -ForegroundColor Red
            exit 1
        }
        
        # pip upgrade
        Write-Host "   pip guncelleniyor..." -ForegroundColor Gray
        & "$PortablePython\Scripts\python.exe" -m pip install --upgrade pip 2>&1 | Out-Null
        
        Write-Host "   [OK] Portable Python olusturuldu: $PortablePython" -ForegroundColor Green
    }
} else {
    Write-Host "[1/5] Python olusturma ATLANDI (-SkipPython)" -ForegroundColor DarkYellow
}
Write-Host ""

# ============================================================
# ADIM 2: Offline Paket İndirme
# ============================================================
if (-not $SkipPackages) {
    Write-Host "[2/5] Offline paketler indiriliyor..." -ForegroundColor Yellow
    
    if (-not (Test-Path $OfflineDir)) {
        New-Item -ItemType Directory -Path $OfflineDir -Force | Out-Null
    }
    
    $FrozenReqs = "$ProjectRoot\requirements_frozen.txt"
    if (-not (Test-Path $FrozenReqs)) {
        Write-Host "   requirements_frozen.txt olusturuluyor..." -ForegroundColor Gray
        & "$ProjectRoot\.venv\Scripts\pip.exe" freeze > $FrozenReqs
    }
    
    # ── torch ve torchvision'ı requirements_frozen.txt'den ayır ──
    # CPU-only versiyonları ayrı index'ten indireceğiz
    $ReqsContent = Get-Content $FrozenReqs
    $ReqsNoTorch = $ReqsContent | Where-Object { $_ -notmatch "^torch==" -and $_ -notmatch "^torchvision==" }
    $TorchReqs = $ReqsContent | Where-Object { $_ -match "^torch==" -or $_ -match "^torchvision==" }
    
    $ReqsNoTorchFile = "$ProjectRoot\requirements_no_torch.txt"
    $ReqsNoTorch | Set-Content $ReqsNoTorchFile -Encoding UTF8
    
    # 2a: torch/torchvision CPU-only indirme (~300 MB vs ~2.5 GB)
    if ($TorchReqs) {
        Write-Host "   [2a] torch CPU-only indiriliyor (GPU yok - ~2 GB tasarruf)..." -ForegroundColor Gray
        
        foreach ($pkg in $TorchReqs) {
            $pkgName = ($pkg -split "==")[0]
            $pkgVer = ($pkg -split "==")[1]
            Write-Host "      -> $pkgName==$pkgVer (CPU-only)" -ForegroundColor Gray
        }
        
        # PyTorch CPU-only index
        & "$ProjectRoot\.venv\Scripts\pip.exe" download `
            torch torchvision `
            --index-url https://download.pytorch.org/whl/cpu `
            -d $OfflineDir `
            --python-version 3.13 `
            --platform win_amd64 `
            --only-binary=:all: 2>&1 | ForEach-Object {
                if ($_ -match "Saved|Downloading|Successfully") { Write-Host "      $_" -ForegroundColor Gray }
            }
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "   [OK] torch CPU-only indirildi" -ForegroundColor Green
        } else {
            Write-Host "   [UYARI] torch CPU-only indirilemedi, tam surumu denenecek..." -ForegroundColor DarkYellow
            # Fallback: tam sürüm indir
            & "$ProjectRoot\.venv\Scripts\pip.exe" download torch torchvision -d $OfflineDir --python-version 3.13 --platform win_amd64 --only-binary=:all: 2>&1 | Out-Null
        }
    }
    
    # 2b: Diger paketleri indir
    Write-Host "   [2b] Diger paketler indiriliyor (138 paket)..." -ForegroundColor Gray
    
    & "$ProjectRoot\.venv\Scripts\pip.exe" download `
        -r $ReqsNoTorchFile `
        -d $OfflineDir `
        --python-version 3.13 `
        --platform win_amd64 `
        --only-binary=:all: 2>&1 | ForEach-Object {
            if ($_ -match "Saved|already") { Write-Host "      $_" -ForegroundColor Gray }
        }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "   [UYARI] Bazi paketler binary bulunamadi, source ile deneniyor..." -ForegroundColor DarkYellow
        & "$ProjectRoot\.venv\Scripts\pip.exe" download `
            -r $ReqsNoTorchFile `
            -d $OfflineDir 2>&1 | Out-Null
    }
    
    $pkgCount = (Get-ChildItem $OfflineDir -Filter "*.whl" -ErrorAction SilentlyContinue).Count
    $tarCount = (Get-ChildItem $OfflineDir -Filter "*.tar.gz" -ErrorAction SilentlyContinue).Count
    $totalSize = [math]::Round((Get-ChildItem $OfflineDir -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
    
    Write-Host "   [OK] $pkgCount wheel + $tarCount source paketi indirildi ($totalSize MB)" -ForegroundColor Green
    
    # Temizlik
    Remove-Item $ReqsNoTorchFile -ErrorAction SilentlyContinue
    
} else {
    Write-Host "[2/5] Paket indirme ATLANDI (-SkipPackages)" -ForegroundColor DarkYellow
}
Write-Host ""

# ============================================================
# ADIM 3: HuggingFace Model Cache Taşıma
# ============================================================
if (-not $SkipModel) {
    Write-Host "[3/5] HuggingFace model cache kopyalaniyor..." -ForegroundColor Yellow
    
    $HfSource = "$env:USERPROFILE\.cache\huggingface\hub\models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    $HfTarget = "$HfCacheDir\hub\models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
    
    if (Test-Path $HfTarget) {
        Write-Host "   [OK] HF model cache zaten mevcut" -ForegroundColor Green
    } elseif (Test-Path $HfSource) {
        Write-Host "   Kopyalaniyor (~458 MB)..." -ForegroundColor Gray
        
        # Hub klasör yapısını oluştur
        New-Item -ItemType Directory -Path "$HfCacheDir\hub" -Force | Out-Null
        
        # Model klasörünü kopyala
        Copy-Item -Path $HfSource -Destination $HfTarget -Recurse -Force
        
        # HuggingFace version.txt dosyası (hub dizininde gerekli)
        if (Test-Path "$env:USERPROFILE\.cache\huggingface\hub\version.txt") {
            Copy-Item "$env:USERPROFILE\.cache\huggingface\hub\version.txt" "$HfCacheDir\hub\version.txt" -Force
        }
        
        $modelSize = [math]::Round((Get-ChildItem $HfTarget -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB, 1)
        Write-Host "   [OK] HF model cache kopyalandi ($modelSize MB)" -ForegroundColor Green
    } else {
        Write-Host "   [HATA] HF model cache bulunamadi: $HfSource" -ForegroundColor Red
        Write-Host "   [INFO] Modeli once indirin: python -c `"from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')`"" -ForegroundColor Gray
    }
} else {
    Write-Host "[3/5] Model tasima ATLANDI (-SkipModel)" -ForegroundColor DarkYellow
}
Write-Host ""

# ============================================================
# ADIM 4: Nginx Portable Kurulumu
# ============================================================
if (-not $SkipNginx) {
    Write-Host "[4/5] Nginx portable hazirlaniyor..." -ForegroundColor Yellow
    
    if (Test-Path "$NginxDir\nginx.exe") {
        Write-Host "   [OK] Nginx zaten mevcut: $NginxDir" -ForegroundColor Green
    } else {
        # Önce D:\nginx'ten kopyalamayı dene
        if (Test-Path "D:\nginx\nginx.exe") {
            Write-Host "   D:\nginx konumundan kopyalaniyor..." -ForegroundColor Gray
            if (-not (Test-Path $NginxDir)) { New-Item -ItemType Directory -Path $NginxDir -Force | Out-Null }
            Copy-Item -Path "D:\nginx\*" -Destination $NginxDir -Recurse -Force
            Write-Host "   [OK] Nginx kopyalandi" -ForegroundColor Green
        } else {
            # İnternetten indir
            $NginxVersion = "1.27.4"
            $NginxUrl = "https://nginx.org/download/nginx-$NginxVersion.zip"
            $NginxZip = "$env:TEMP\nginx-$NginxVersion.zip"
            
            Write-Host "   Nginx $NginxVersion indiriliyor..." -ForegroundColor Gray
            try {
                Invoke-WebRequest -Uri $NginxUrl -OutFile $NginxZip -UseBasicParsing
                Expand-Archive -Path $NginxZip -DestinationPath "$env:TEMP\nginx-extract" -Force
                
                if (-not (Test-Path $NginxDir)) { New-Item -ItemType Directory -Path $NginxDir -Force | Out-Null }
                $extractedDir = Get-ChildItem "$env:TEMP\nginx-extract" -Directory | Select-Object -First 1
                Copy-Item -Path "$($extractedDir.FullName)\*" -Destination $NginxDir -Recurse -Force
                
                Remove-Item $NginxZip -Force -ErrorAction SilentlyContinue
                Remove-Item "$env:TEMP\nginx-extract" -Recurse -Force -ErrorAction SilentlyContinue
                
                Write-Host "   [OK] Nginx indirildi ve kuruldu" -ForegroundColor Green
            } catch {
                Write-Host "   [HATA] Nginx indirilemedi: $_" -ForegroundColor Red
            }
        }
        
        # Nginx config kopyala
        if (Test-Path "$ProjectRoot\deploy\nginx\vyra.conf") {
            if (-not (Test-Path "$NginxDir\conf\conf.d")) {
                New-Item -ItemType Directory -Path "$NginxDir\conf\conf.d" -Force | Out-Null
            }
            Copy-Item "$ProjectRoot\deploy\nginx\vyra.conf" "$NginxDir\conf\conf.d\vyra.conf" -Force
            Write-Host "   [OK] Nginx config kopyalandi" -ForegroundColor Green
        }
    }
} else {
    Write-Host "[4/5] Nginx ATLANDI (-SkipNginx)" -ForegroundColor DarkYellow
}
Write-Host ""

# ============================================================
# ADIM 5: VC++ Redistributable & Tools
# ============================================================
if (-not $SkipVcRedist) {
    Write-Host "[5/5] VC++ Redistributable indiriliyor..." -ForegroundColor Yellow
    
    if (-not (Test-Path $ToolsDir)) {
        New-Item -ItemType Directory -Path $ToolsDir -Force | Out-Null
    }
    
    $VcRedistPath = "$ToolsDir\vc_redist.x64.exe"
    if (Test-Path $VcRedistPath) {
        Write-Host "   [OK] VC++ Redistributable zaten mevcut" -ForegroundColor Green
    } else {
        $VcRedistUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
        Write-Host "   VC++ Redistributable (x64) indiriliyor..." -ForegroundColor Gray
        try {
            Invoke-WebRequest -Uri $VcRedistUrl -OutFile $VcRedistPath -UseBasicParsing
            Write-Host "   [OK] VC++ Redistributable indirildi: $VcRedistPath" -ForegroundColor Green
        } catch {
            Write-Host "   [UYARI] VC++ Redistributable indirilemedi: $_" -ForegroundColor DarkYellow
            Write-Host "   [INFO] Manuel indir: https://aka.ms/vs/17/release/vc_redist.x64.exe" -ForegroundColor Gray
        }
    }
} else {
    Write-Host "[5/5] VC++ Redistributable ATLANDI (-SkipVcRedist)" -ForegroundColor DarkYellow
}
Write-Host ""

# ============================================================
# SONUÇ
# ============================================================
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  PORTABLE HAZIRLIK TAMAMLANDI!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""

# Boyut raporu
$sizes = @()
if (Test-Path $PortablePython) {
    $s = [math]::Round((Get-ChildItem $PortablePython -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 0)
    $sizes += "  python/            : $s MB"
}
if (Test-Path $OfflineDir) {
    $s = [math]::Round((Get-ChildItem $OfflineDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 0)
    $sizes += "  offline_packages/  : $s MB"
}
if (Test-Path $HfCacheDir) {
    $s = [math]::Round((Get-ChildItem $HfCacheDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 0)
    $sizes += "  models/hf_cache/   : $s MB"
}
if (Test-Path $NginxDir) {
    $s = [math]::Round((Get-ChildItem $NginxDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 0)
    $sizes += "  nginx/             : $s MB"
}
if (Test-Path $ToolsDir) {
    $s = [math]::Round((Get-ChildItem $ToolsDir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1MB, 0)
    $sizes += "  tools/             : $s MB"
}

Write-Host "  Boyut Raporu:" -ForegroundColor Cyan
$sizes | ForEach-Object { Write-Host $_ -ForegroundColor White }
Write-Host ""
Write-Host "  Sonraki Adimlar:" -ForegroundColor Yellow
Write-Host "  1. Sunucuda VC++ Redistributable kur: tools\vc_redist.x64.exe /install /quiet" -ForegroundColor White
Write-Host "  2. Tum VYRA klasorunu USB'ye kopyala" -ForegroundColor White
Write-Host "  3. Sunucuda: scripts\install_portable.ps1 calistir" -ForegroundColor White
Write-Host "  4. Sunucuda: canlida_calistir.bat ile baslat" -ForegroundColor White
Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
