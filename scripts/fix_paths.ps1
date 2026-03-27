# =============================================================
# VYRA - pyvenv.cfg ve vyra.conf Otomatik Yol Duzeltme
# =============================================================
# canlida_calistir.bat tarafindan otomatik cagrilir.
# Proje tasindiktan sonra yollari yeni konuma uyarlar.
# =============================================================
param(
    [Parameter(Mandatory=$true)]
    [string]$ProjectRoot
)

$exitCode = 0

# --- 1. pyvenv.cfg otomatik duzeltme (home + executable + command) ---
$cfgPath = Join-Path $ProjectRoot "python\pyvenv.cfg"
if (Test-Path $cfgPath) {
    $lines = Get-Content $cfgPath
    $changed = $false
    $venvPath = Join-Path $ProjectRoot "python"
    $venvScripts = Join-Path $venvPath "Scripts"

    # home satirindaki mevcut yolu oku
    $currentHome = ''
    foreach ($l in $lines) {
        if ($l -match '^home\s*=\s*(.+)') { $currentHome = $Matches[1].Trim() }
    }

    # home yolunda python.exe var mi kontrol et (ve kendine referans OLMASIN)
    $homeOk = $false
    $isSelfRef = $false
    if ($currentHome -and (Test-Path (Join-Path $currentHome 'python.exe'))) {
        # Kendine referans kontrolu: home == Scripts dizini ise bu YANLIS
        $resolvedHome = (Resolve-Path $currentHome -ErrorAction SilentlyContinue).Path
        $resolvedScripts = (Resolve-Path $venvScripts -ErrorAction SilentlyContinue).Path
        if ($resolvedHome -and $resolvedScripts -and ($resolvedHome.TrimEnd('\') -eq $resolvedScripts.TrimEnd('\'))) {
            $isSelfRef = $true
            Write-Host "   [UYARI] pyvenv.cfg kendine referans veriyor - duzeltiliyor..."
        } else {
            $homeOk = $true
        }
    }

    if (-not $homeOk) {
        # Base Python'u bul - 2 yontem (3. yontem artik kendine referans vermez)
        $basePython = $null
        $baseDir = $null

        # Yontem 1: Sistem PATH'inde ara
        try {
            $found = (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
            # Venv'in kendi python.exe'sini haric tut
            if ($found -and (Test-Path $found) -and $found -ne (Join-Path $venvScripts 'python.exe')) {
                $basePython = $found
                $baseDir = Split-Path $found -Parent
            }
        } catch {}

        # Yontem 2: py launcher ile ara
        if (-not $basePython) {
            try {
                $pyOut = & py -c "import sys; print(sys.executable)" 2>$null
                if ($pyOut -and (Test-Path $pyOut.Trim())) {
                    $basePython = $pyOut.Trim()
                    $baseDir = Split-Path $basePython -Parent
                }
            } catch {}
        }

        # Yontem 3: Bilinen Python kurulum dizinlerini tara (PATH'e eklenmemis olabilir)
        if (-not $basePython) {
            # pyvenv.cfg'deki version'dan major.minor al
            $pyVer = ''
            foreach ($l in $lines) {
                if ($l -match '^version\s*=\s*(\d+)\.(\d+)') { $pyVer = "$($Matches[1])$($Matches[2])" }
            }
            if (-not $pyVer) { $pyVer = '313' }  # fallback

            $searchPaths = @(
                # Kullanici bazli kurulum (varsayilan)
                "$env:LOCALAPPDATA\Programs\Python\Python$pyVer"
                # Tum kullanicilar icin kurulum
                "$env:ProgramFiles\Python$pyVer"
                "${env:ProgramFiles(x86)}\Python$pyVer"
                # Ozel dizin kurulumu
                "C:\Python$pyVer"
                "C:\Python3"
                "D:\Python$pyVer"
            )
            # Tum kullanicilarin AppData'sini da tara
            $usersDir = Split-Path $env:USERPROFILE -Parent
            if (Test-Path $usersDir) {
                Get-ChildItem $usersDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                    $searchPaths += Join-Path $_.FullName "AppData\Local\Programs\Python\Python$pyVer"
                }
            }
            foreach ($sp in $searchPaths) {
                $candidate = Join-Path $sp "python.exe"
                if ((Test-Path $candidate) -and $candidate -ne (Join-Path $venvScripts 'python.exe')) {
                    $basePython = $candidate
                    $baseDir = $sp
                    Write-Host "   [OK] Python bulundu (dizin taramasi): $sp"
                    break
                }
            }
        }

        if ($basePython) {
            # Sistem Python bulundu - pyvenv.cfg'yi guncelle
            $newLines = @()
            foreach ($l in $lines) {
                if ($l -match '^home\s*=') { $newLines += "home = $baseDir" }
                elseif ($l -match '^executable\s*=') { $newLines += "executable = $basePython" }
                elseif ($l -match '^command\s*=') { $newLines += "command = $basePython -m venv $venvPath" }
                else { $newLines += $l }
            }
            $u = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllLines($cfgPath, $newLines, $u)
            Write-Host "   [OK] pyvenv.cfg guncellendi (home: $baseDir)"
        } else {
            # STANDALONE MOD: Sistem Python bulunamadi
            # pyvenv.cfg silmek CALISMAZ (venv wrapper "failed to locate pyvenv.cfg" verir)
            # Kendine referans (home = Scripts) HANG yapar
            # COZUM: python\Scripts'teki python.exe + DLL'leri python\ kok dizinine kopyala
            #         ve home'u python\ dizinine yonlendir (sahte base Python dizini)
            $stdlibCheck = Join-Path $venvPath "Lib\os.py"
            $srcPython = Join-Path $venvScripts "python.exe"
            if ((Test-Path $stdlibCheck) -and (Test-Path $srcPython)) {
                # python.exe ve DLL dosyalarini python\ kok dizinine kopyala
                $destPython = Join-Path $venvPath "python.exe"
                if (-not (Test-Path $destPython)) {
                    Copy-Item $srcPython $destPython -Force
                    Write-Host "   [OK] python.exe -> python\ kok dizinine kopyalandi"
                }
                # python3.dll ve python3XX.dll kopyala (venv launcher bunlara ihtiyac duyar)
                Get-ChildItem $venvScripts -Filter "python3*.dll" | ForEach-Object {
                    $dest = Join-Path $venvPath $_.Name
                    if (-not (Test-Path $dest)) {
                        Copy-Item $_.FullName $dest -Force
                        Write-Host "   [OK] $($_.Name) -> python\ kok dizinine kopyalandi"
                    }
                }

                # pyvenv.cfg'yi guncelle: home = python\ kok dizini (Scripts degil!)
                $newLines = @()
                foreach ($l in $lines) {
                    if ($l -match '^home\s*=') { $newLines += "home = $venvPath" }
                    elseif ($l -match '^executable\s*=') { $newLines += "executable = $destPython" }
                    elseif ($l -match '^command\s*=') { $newLines += "command = $destPython -m venv $venvPath" }
                    else { $newLines += $l }
                }
                $u = New-Object System.Text.UTF8Encoding $false
                [System.IO.File]::WriteAllLines($cfgPath, $newLines, $u)
                Write-Host "   [OK] pyvenv.cfg guncellendi - standalone mod (home: $venvPath)"
            } else {
                Write-Host "   [HATA] Standalone mod kurulamadi!"
                if (-not (Test-Path $stdlibCheck)) { Write-Host "   [HATA] stdlib (python\Lib\os.py) bulunamadi" }
                if (-not (Test-Path $srcPython)) { Write-Host "   [HATA] python\Scripts\python.exe bulunamadi" }
                $exitCode = 1
            }
        }
    } else {
        # home dogru, sadece command satirini kontrol et
        $needsCmd = $false
        foreach ($l in $lines) {
            if ($l -match '^command\s*=' -and $l -notmatch [regex]::Escape($venvPath)) { $needsCmd = $true }
        }
        if ($needsCmd) {
            $basePython = Join-Path $currentHome 'python.exe'
            $newLines = @()
            foreach ($l in $lines) {
                if ($l -match '^command\s*=') { $newLines += "command = $basePython -m venv $venvPath" }
                else { $newLines += $l }
            }
            $u = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllLines($cfgPath, $newLines, $u)
            Write-Host "   [OK] pyvenv.cfg command yolu guncellendi"
            $changed = $true
        }
        if (-not $changed) { Write-Host "   [OK] pyvenv.cfg yolu dogru" }
    }
} else {
    Write-Host "   [UYARI] pyvenv.cfg bulunamadi: $cfgPath"
}

# --- 2. Nginx vyra.conf root yolu otomatik duzeltme ---
$confPath = Join-Path $ProjectRoot "nginx\conf\conf.d\vyra.conf"
if (Test-Path $confPath) {
    $c = Get-Content $confPath -Raw
    $pr = $ProjectRoot -replace '\\','/'
    if ($c -match 'root\s+([^;]+);') {
        $currentRoot = $Matches[1].Trim()
        $expectedRoot = "$pr/frontend"
        if ($currentRoot -ne $expectedRoot) {
            $c = $c -replace ('root\s+' + [regex]::Escape($currentRoot) + ';'), "root    $expectedRoot;"
            $u = New-Object System.Text.UTF8Encoding $false
            [System.IO.File]::WriteAllText($confPath, $c, $u)
            Write-Host "   [OK] vyra.conf root yolu guncellendi: $expectedRoot"
        } else {
            Write-Host "   [OK] vyra.conf root yolu dogru"
        }
    } else {
        Write-Host "   [UYARI] vyra.conf root direktifi bulunamadi"
    }
} else {
    Write-Host "   [--] vyra.conf henuz mevcut degil"
}

exit $exitCode
