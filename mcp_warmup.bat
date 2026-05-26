@echo off
REM ============================================================
REM   VYRA Graphify MCP On-Isindirma (tek hafiza katmani)
REM   start.ps1 tarafindan PG den ONCE cagrilir.
REM   Hata olsa bile exit 0 - startup i bloklamaz (HERMES kurali).
REM ============================================================
chcp 65001 >nul 2>&1
setlocal

REM Python stdout/stderr UTF-8 - graphify wakeup Turkce karakterler (cp1252 fix)
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

set "GF_DIR=C:\Users\EXT02D059293\Documents\General_Graphify"
set "PY=python"

echo.
echo ============================================================
echo   VYRA Graphify MCP On-Isindirma
echo ============================================================
echo.

REM ---- Graphify (vyra project) ----
if exist "%GF_DIR%\core\cli.py" (
    echo [1/1] Graphify vyra project isindirma...
    pushd "%GF_DIR%"
    %PY% -m core.cli wakeup --project vyra
    if errorlevel 1 echo    [WARN] graphify wakeup hata - devam
    popd
    echo.
) else (
    echo [1/1] Graphify bulunamadi: %GF_DIR%
    echo       Cozum: General_Graphify repo sunu klonla
    echo       MCP fallback devreye girecek - devam.
    echo.
)

echo ============================================================
echo   Graphify MCP isindirma tamamlandi.
echo ============================================================
endlocal
REM HERMES: ASLA non-zero ile cikma
exit /b 0
