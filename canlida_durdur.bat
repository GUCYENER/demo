@echo off
chcp 65001 >nul 2>&1

setlocal EnableDelayedExpansion
title VYRA L1 Support - Production Durdurma
color 0C

:: =============================================================
:: VYRA L1 Support - Tek Tikla Production Durdurma
:: =============================================================
:: Tum servisleri guvenli bir sekilde durdurur:
::   1. Nginx (reverse proxy)
::   2. Uvicorn / Python (backend API)
::   3. Redis (cache)
::   4. PostgreSQL (veritabani)
:: =============================================================

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "PG_BIN=%PROJECT_ROOT%\pgsql\bin"
set "PG_DATA=%PROJECT_ROOT%\pgsql\data"
set "REDIS_CLI=%PROJECT_ROOT%\redis\redis-cli.exe"
set "REDIS_PORT=6380"
set "REDIS_PASS=VyraR3d1s_Sec2026"
set "NGINX_DIR=%PROJECT_ROOT%\nginx"
set "NGINX_EXE=%NGINX_DIR%\nginx.exe"
set "VENV_PYTHON=%PROJECT_ROOT%\python\Scripts\python.exe"

echo.
echo =============================================================
echo    VYRA L1 Support - Production Durdurma
echo =============================================================
echo    Proje: %PROJECT_ROOT%
echo =============================================================
echo.

:: =============================================================
:: 1. Nginx Durdur
:: =============================================================
echo [1/4] Nginx durduruluyor...
tasklist /fi "imagename eq nginx.exe" 2>nul | find /i "nginx.exe" >nul
if errorlevel 1 goto nginx_not_running

:: Graceful shutdown dene
if exist "%NGINX_EXE%" (
    pushd "%NGINX_DIR%"
    "%NGINX_EXE%" -s quit >nul 2>&1
    popd
)
timeout /t 2 /nobreak >nul

:: Hala calisiyorsa zorla durdur
tasklist /fi "imagename eq nginx.exe" 2>nul | find /i "nginx.exe" >nul
if not errorlevel 1 (
    taskkill /f /im nginx.exe >nul 2>&1
    echo    [OK] Nginx zorla durduruldu
) else (
    echo    [OK] Nginx graceful durduruldu
)
goto nginx_done

:nginx_not_running
echo    [--] Nginx zaten calismiyordu
:nginx_done
echo.

:: =============================================================
:: 2. Python / Uvicorn Durdur (Sadece VYRA backend)
:: =============================================================
echo [2/4] Uvicorn durduruluyor...

:: VYRA Backend pencere basligina gore bul ve durdur
set "KILLED_PYTHON=0"

:: Yontem 1: VYRA python.exe process'lerini bul (proje dizinindeki python)
for /f "tokens=2" %%p in ('wmic process where "ExecutablePath like '%%python\\Scripts\\python.exe'" get ProcessId /format:list 2^>nul ^| findstr ProcessId') do (
    taskkill /f /pid %%p >nul 2>&1
    if not errorlevel 1 set "KILLED_PYTHON=1"
)

:: Yontem 2: Yukaridaki islemediyse, uvicorn iceren python process'leri ara
if "!KILLED_PYTHON!"=="0" (
    for /f "tokens=2" %%p in ('wmic process where "CommandLine like '%%uvicorn%%app.api.main%%'" get ProcessId /format:list 2^>nul ^| findstr ProcessId') do (
        taskkill /f /pid %%p >nul 2>&1
        if not errorlevel 1 set "KILLED_PYTHON=1"
    )
)

if "!KILLED_PYTHON!"=="1" (
    echo    [OK] Uvicorn durduruldu
) else (
    echo    [--] Uvicorn zaten calismiyordu
)
echo.

:: =============================================================
:: 3. Redis Durdur
:: =============================================================
echo [3/4] Redis durduruluyor (port %REDIS_PORT%)...

if not exist "%REDIS_CLI%" goto redis_not_found

:: Ping ile kontrol (auth ile)
"%REDIS_CLI%" -p %REDIS_PORT% -a %REDIS_PASS% ping >nul 2>&1
if errorlevel 1 goto redis_try_noauth

:: Auth ile graceful shutdown
"%REDIS_CLI%" -p %REDIS_PORT% -a %REDIS_PASS% shutdown nosave >nul 2>&1
echo    [OK] Redis durduruldu (port %REDIS_PORT%)
goto redis_done

:redis_try_noauth
:: Auth olmadan dene (eski config ile calisiyor olabilir)
"%REDIS_CLI%" -p %REDIS_PORT% ping >nul 2>&1
if errorlevel 1 goto redis_try_taskkill

"%REDIS_CLI%" -p %REDIS_PORT% shutdown nosave >nul 2>&1
echo    [OK] Redis durduruldu (port %REDIS_PORT%, no-auth)
goto redis_done

:redis_try_taskkill
:: Hicbir yontem islemediyse process'i zorla durdur
tasklist /fi "imagename eq redis-server.exe" 2>nul | find /i "redis-server.exe" >nul
if errorlevel 1 goto redis_not_running

taskkill /f /im redis-server.exe >nul 2>&1
echo    [OK] Redis zorla durduruldu
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

:: Graceful fast shutdown
"%PG_BIN%\pg_ctl.exe" -D "%PG_DATA%" stop -m fast >nul 2>&1
if errorlevel 1 (
    :: Fast basarisizsa immediate dene
    echo    [UYARI] Fast shutdown basarisiz, immediate deneniyor...
    "%PG_BIN%\pg_ctl.exe" -D "%PG_DATA%" stop -m immediate >nul 2>&1
)
echo    [OK] PostgreSQL durduruldu
goto pg_done

:pg_not_running
:: Process kalmis olabilir - kontrol et
tasklist /fi "imagename eq postgres.exe" 2>nul | find /i "postgres.exe" >nul
if not errorlevel 1 (
    echo    [UYARI] PostgreSQL process'i kaldi, zorla durduruluyor...
    taskkill /f /im postgres.exe >nul 2>&1
    echo    [OK] PostgreSQL zorla durduruldu
) else (
    echo    [--] PostgreSQL zaten calismiyordu
)
:pg_done
echo.

:: =============================================================
:: SONUC
:: =============================================================
echo =============================================================
echo.
echo    Tum VYRA servisleri durduruldu!
echo.
echo    Durdurulan servisler:
echo      - Nginx (reverse proxy)
echo      - Uvicorn (backend API)
echo      - Redis (cache - port %REDIS_PORT%)
echo      - PostgreSQL (veritabani - port 5005)
echo.
echo    Tekrar baslatmak: canlida_calistir.bat
echo.
echo =============================================================
echo.
echo Cikis icin herhangi bir tusa basin...
pause >nul
