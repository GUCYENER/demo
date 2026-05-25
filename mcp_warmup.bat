@echo off
REM ============================================================
REM   VYRA MCP On-Isindirma (MemPalace + Graphify)
REM   start.ps1 tarafindan PG den ONCE cagrilir.
REM   Hata olsa bile exit 0 - startup i bloklamaz (HERMES kurali).
REM ============================================================
chcp 65001 >nul 2>&1
setlocal

REM Python stdout/stderr UTF-8 - mempalace wake-up Turkce karakterler (cp1252 fix)
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "MP=C:\Users\EXT02D059293\AppData\Local\Programs\Python\Python313\Scripts\mempalace.exe"
set "GF_DIR=C:\Users\EXT02D059293\Documents\General_Graphify"
set "PY=python"

echo.
echo ============================================================
echo   VYRA MCP On-Isindirma (MemPalace + Graphify)
echo ============================================================
echo.

REM ---- MemPalace (sadece vyra wing) ----
if exist "%MP%" (
    echo [1/3] MemPalace status...
    "%MP%" status
    if errorlevel 1 echo    [WARN] mempalace status hata - devam
    echo.
    echo [2/3] MemPalace vyra wing isindirma...
    "%MP%" wake-up --wing vyra
    if errorlevel 1 echo    [WARN] mempalace wake-up vyra hata - devam
    echo.
) else (
    echo [1-2/3] mempalace.exe bulunamadi: %MP%
    echo         Cozum: pip install mempalace
    echo         MCP fallback devreye girecek - devam.
    echo.
)

REM ---- Graphify (vyra project) ----
if exist "%GF_DIR%\core\cli.py" (
    echo [3/3] Graphify vyra project isindirma...
    pushd "%GF_DIR%"
    %PY% -m core.cli wakeup --project vyra
    if errorlevel 1 echo    [WARN] graphify wakeup hata - devam
    popd
    echo.
) else (
    echo [3/3] Graphify bulunamadi: %GF_DIR%
    echo       Cozum: General_Graphify repo sunu klonla
    echo       MCP fallback devreye girecek - devam.
    echo.
)

echo ============================================================
echo   MCP isindirma tamamlandi.
echo ============================================================
endlocal
REM HERMES: ASLA non-zero ile cikma
exit /b 0
