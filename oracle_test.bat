@echo off
chcp 65001 >nul 2>&1
title Oracle Test DB — VYRA
color 0B

echo ============================================================
echo   Oracle Test DB — Hizli Baslatici
echo ============================================================

set "DOCKER=C:\Program Files\Docker\Docker\resources\bin\docker.exe"

:: Docker Desktop calisiyor mu?
"%DOCKER%" info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [*] Docker Desktop baslatiliyor...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo     Bekleniyor...
    :wait_docker
    timeout /t 5 /nobreak >nul
    "%DOCKER%" info >nul 2>&1
    if %ERRORLEVEL% NEQ 0 goto wait_docker
)
echo [OK] Docker Desktop hazir.

:: Container durumu
"%DOCKER%" ps -a --filter "name=vyra-oracle-test" --format "{{.Status}}" 2>nul | findstr /i "Up" >nul
if %ERRORLEVEL% EQU 0 (
    echo [OK] Oracle container zaten calisiyor.
    goto test
)

:: Container var ama durdurulmus mu?
"%DOCKER%" ps -a --filter "name=vyra-oracle-test" --format "{{.Status}}" 2>nul | findstr /i "Exited" >nul
if %ERRORLEVEL% EQU 0 (
    echo [*] Container durdurulmus, yeniden baslatiliyor...
    "%DOCKER%" start vyra-oracle-test
    goto wait_ready
)

:: Container hic yok — docker compose ile olustur
echo [*] Container bulunamadi, olusturuluyor...
"%DOCKER%" compose -f "%~dp0oracle_local_test\docker-compose.yml" up -d
if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Container olusturulamadi!
    pause
    exit /b 1
)

:wait_ready
echo [*] Oracle DB hazir olmasini bekliyoruz...
:wait_loop
timeout /t 5 /nobreak >nul
"%DOCKER%" logs --tail 3 vyra-oracle-test 2>&1 | findstr /i "DATABASE IS READY" >nul
if %ERRORLEVEL% NEQ 0 (
    echo     Bekleniyor...
    goto wait_loop
)

:test
echo [OK] Oracle DB hazir!
echo.
echo     Host:     localhost
echo     Port:     1521
echo     Service:  FREEPDB1
echo     User:     VYRA_TEST
echo     Pass:     VyraTest2026
echo.
echo ============================================================
pause
