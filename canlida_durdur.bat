@echo off
chcp 65001 >nul 2>&1

:: === Yonetici izni kontrolu (UAC Elevation) ===
net session >nul 2>&1
if errorlevel 1 (
    echo [INFO] Yonetici izni isteniyor...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

title VYRA L1 Support - Production Durdurma
color 0C

:: =============================================================
:: VYRA L1 Support - Tek Tikla Production Durdurma
:: =============================================================

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "PG_BIN=%PROJECT_ROOT%\pgsql\bin"
set "PG_DATA=%PROJECT_ROOT%\pgsql\data"
set "REDIS_CLI=%PROJECT_ROOT%\redis\redis-cli.exe"
set "NGINX_DIR=%PROJECT_ROOT%\nginx"
set "NGINX_EXE=%NGINX_DIR%\nginx.exe"

echo.
echo =============================================================
echo    VYRA L1 Support - Production Durdurma
echo =============================================================
echo.

:: =============================================================
:: 1. Nginx Durdur
:: =============================================================
echo [1/4] Nginx durduruluyor...
tasklist /fi "imagename eq nginx.exe" 2>nul | find /i "nginx.exe" >nul
if errorlevel 1 goto nginx_not_running

if exist "%NGINX_EXE%" (
    pushd "%NGINX_DIR%"
    "%NGINX_EXE%" -s quit >nul 2>&1
    popd
)
timeout /t 2 /nobreak >nul
taskkill /f /im nginx.exe >nul 2>&1
echo    [OK] Nginx durduruldu
goto nginx_done

:nginx_not_running
echo    [--] Nginx zaten calismiyordu
:nginx_done
echo.

:: =============================================================
:: 2. Python / Uvicorn Durdur
:: =============================================================
echo [2/4] Uvicorn durduruluyor...
tasklist /fi "imagename eq python.exe" 2>nul | find /i "python.exe" >nul
if errorlevel 1 goto python_not_running

taskkill /f /im python.exe >nul 2>&1
echo    [OK] Uvicorn durduruldu
goto python_done

:python_not_running
echo    [--] Uvicorn zaten calismiyordu
:python_done
echo.

:: =============================================================
:: 3. Redis Durdur
:: =============================================================
echo [3/4] Redis durduruluyor...

if not exist "%REDIS_CLI%" goto redis_not_found

"%REDIS_CLI%" ping >nul 2>&1
if errorlevel 1 goto redis_not_running

"%REDIS_CLI%" shutdown nosave >nul 2>&1
echo    [OK] Redis durduruldu
goto redis_done

:redis_not_running
echo    [--] Redis zaten calismiyordu
goto redis_done
:redis_not_found
echo    [--] Redis kurulu degil
:redis_done
echo.

:: =============================================================
:: 4. PostgreSQL Durdur
:: =============================================================
echo [4/4] PostgreSQL durduruluyor...
"%PG_BIN%\pg_isready.exe" -h localhost -p 5005 >nul 2>&1
if errorlevel 1 goto pg_not_running

"%PG_BIN%\pg_ctl.exe" -D "%PG_DATA%" stop -m fast >nul 2>&1
echo    [OK] PostgreSQL durduruldu
goto pg_done

:pg_not_running
echo    [--] PostgreSQL zaten calismiyordu
:pg_done
echo.

:: =============================================================
:: SONUC
:: =============================================================
echo =============================================================
echo.
echo    Tum servisler durduruldu!
echo.
echo    Tekrar baslatmak: canlida_calistir.bat
echo.
echo =============================================================
echo.
echo Cikis icin herhangi bir tusa basin...
pause >nul
