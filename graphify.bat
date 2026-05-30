@echo off
REM ============================================================
REM   VYRA Graphify — Ayaga Kaldir + Isindir  (MANUEL)
REM ------------------------------------------------------------
REM   Ne yapar : DB liveness (status) -> yoksa init -> mine -> wakeup
REM   Ne YAPMAZ: MCP server'i daemon olarak baslatmaz. MCP stdio'dur,
REM              istemci (Claude) kendi spawn eder. Bu bat SADECE grafi
REM              tazeler/isindirir; sonra `basla` veya MCP'yi sen baslat.
REM   Kullanim : graphify.bat   (cift tikla veya cmd'den calistir)
REM ============================================================
chcp 65001 >nul 2>&1
setlocal

REM ---- Ortam: UTF-8 + transformers TensorFlow yolunu KAPAT ----
REM   USE_TF=0: transformers TF/keras3 yolunu hic yuklemez. Iki sorunu birden cozer:
REM     1) VYRA venv'deki "cannot import name 'TFPreTrainedModel'" import cakismasi
REM     2) TF kutuphanesi bellege yuklenmedigi icin model load'da "paging file
REM        too small (os error 1455)" riski azalir. Embedding torch ile yapilir.
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "USE_TF=0"
set "USE_TORCH=1"
set "TRANSFORMERS_NO_ADVISORY_WARNINGS=1"

set "GF_DIR=C:\Users\EXT02D059293\Documents\General_Graphify"
set "PROJECT=vyra"

REM ---- Python: sentence-transformers'in TEMIZ import oldugu yorumlayici ----
REM   .mcp.json (MCP server) ile AYNI interpreter: sistem Python313.
REM   VYRA venv (d:\demo_vyra\python\...) KULLANILMAZ -> orada transformers/keras3
REM   cakismasi var, `import sentence_transformers` patliyor.
set "PY=C:\Users\EXT02D059293\AppData\Local\Programs\Python\Python313\python.exe"

echo ============================================================
echo   VYRA Graphify Ayaga Kaldir + Isindir   (project: %PROJECT%)
echo ============================================================
echo.

REM ---- 0) On kosullar ----
if not exist "%GF_DIR%\core\cli.py" (
    echo [HATA] Graphify bulunamadi: %GF_DIR%
    echo        General_Graphify repo klonlu mu?
    goto :end_fail
)
if not exist "%PY%" (
    echo [HATA] Python313 bulunamadi: %PY%
    echo        .mcp.json ile ayni interpreter gerekli.
    goto :end_fail
)
echo [PY] Interpreter: %PY%
echo.

pushd "%GF_DIR%"

REM ---- 1) DB liveness (status); yoksa init ----
echo [1/4] DB durumu kontrol ediliyor (status)...
"%PY%" -u -m core.cli status --project %PROJECT%
if errorlevel 1 (
    echo    [STALE] DB yok / status hata, init calistiriliyor...
    "%PY%" -u -m core.cli init %PROJECT%
    if errorlevel 1 (
        echo    [HATA] init basarisiz.
        popd
        goto :end_fail
    )
    echo    [OK] DB olusturuldu.
) else (
    echo    [OK] DB ayakta.
)
echo.

REM ---- 2) Mine: son commit'leri indexle (+ embedding sweep) ----
echo [2/4] Mine - son commit'ler indexleniyor...
"%PY%" -u -m core.cli mine --project %PROJECT%
if errorlevel 1 echo    [WARN] mine hata - devam ediliyor
echo.

REM ---- 3) Wakeup: oturum ozeti ----
echo [3/4] Wakeup - oturum ozeti hazirlaniyor...
"%PY%" -u -m core.cli wakeup --project %PROJECT%
if errorlevel 1 echo    [WARN] wakeup hata - devam ediliyor
echo.

REM ---- 4) Son durum ----
echo [4/4] Son durum:
"%PY%" -u -m core.cli status --project %PROJECT%
echo.

popd

echo ============================================================
echo   Graphify HAZIR - taze ve isindirildi.
echo   Simdi `basla` veya MCP istemcisini ELLE baslatabilirsin.
echo ============================================================
endlocal
pause
exit /b 0

:end_fail
echo.
echo ============================================================
echo   Graphify isindirma BASARISIZ - yukaridaki hatayi kontrol et.
echo ============================================================
endlocal
pause
exit /b 1
