@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion
title VYRA L1 Support - Production Launcher
color 0B

:: =============================================================
:: VYRA L1 Support - Tek Tikla Production Launcher
:: =============================================================
:: Bu dosyayi cift tiklayarak calistirin.
:: Ilk calistirmada: venv + pip + Nginx otomatik kurulur.
:: Her calistirmada: PostgreSQL + Backend + Nginx baslatilir.
:: =============================================================

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"

set "VENV_PYTHON=%PROJECT_ROOT%\python\Scripts\python.exe"
set "VENV_PIP=%PROJECT_ROOT%\python\Scripts\pip.exe"
set "PG_BIN=%PROJECT_ROOT%\pgsql\bin"
set "PG_DATA=%PROJECT_ROOT%\pgsql\data"
set "PG_LOG=%PG_DATA%\server.log"
set "REDIS_DIR=%PROJECT_ROOT%\redis"
set "REDIS_EXE=%REDIS_DIR%\redis-server.exe"
set "REDIS_CLI=%REDIS_DIR%\redis-cli.exe"
set "REDIS_CONF=%REDIS_DIR%\redis.windows.conf"
set "NGINX_DIR=%PROJECT_ROOT%\nginx"
set "NGINX_EXE=%NGINX_DIR%\nginx.exe"
set "NGINX_VERSION=1.27.4"
set "BACKEND_PORT=8002"
set "WORKERS=4"

echo.
echo =============================================================
echo    VYRA L1 Support - Production Launcher
echo =============================================================
echo    Proje: %PROJECT_ROOT%
echo =============================================================
echo.

:: =============================================================
:: ADIM 0: .env kontrolu
:: =============================================================
echo [0/7] .env dosyasi kontrol ediliyor...
if not exist "%PROJECT_ROOT%\.env" goto env_missing
echo    [OK] .env dosyasi mevcut
echo.
goto step1

:env_missing
echo    [HATA] .env dosyasi bulunamadi!
echo    [INFO] .env.example dosyasini .env olarak kopyalayin ve duzenleyin.
pause
exit /b 1

:: =============================================================
:: ADIM 1: Portable Python kontrol
:: =============================================================
:step1
echo [1/7] Portable Python kontrol ediliyor...
if not exist "%VENV_PYTHON%" goto python_missing
echo    [OK] Portable Python mevcut
goto step2

:python_missing
echo    [HATA] Portable Python bulunamadi: %VENV_PYTHON%
echo    [INFO] python/ klasoru proje icinde olmalidir.
pause
exit /b 1

:: =============================================================
:: ADIM 2: pip bagimliliklari (offline)
:: =============================================================
:step2
echo [2/7] Python bagimliliklari kontrol ediliyor...
"%VENV_PYTHON%" -c "import uvicorn" >nul 2>&1
if not errorlevel 1 goto deps_ok

echo    [KURULUM] Bagimliliklar offline olarak yukleniyor...
echo    [INFO] Bu islem 3-5 dakika surebilir...
if exist "%PROJECT_ROOT%\offline_packages" (
    "%VENV_PIP%" install --no-index --find-links "%PROJECT_ROOT%\offline_packages" -r "%PROJECT_ROOT%\requirements_frozen.txt"
) else (
    echo    [HATA] offline_packages klasoru bulunamadi!
    pause
    exit /b 1
)
if errorlevel 1 goto deps_fail
echo    [OK] Tum bagimliliklar yuklendi
echo.
goto step3

:deps_fail
echo    [HATA] Bagimliliklar yuklenemedi!
pause
exit /b 1

:deps_ok
echo    [OK] Bagimliliklar zaten yuklu
echo.

:: =============================================================
:: ADIM 3: Nginx (Portable - proje icinde)
:: =============================================================
:step3
echo [3/7] Nginx kontrol ediliyor...
if exist "%NGINX_EXE%" goto nginx_exists

echo    [HATA] Nginx bulunamadi: %NGINX_DIR%
echo    [INFO] nginx/ klasoru proje icinde olmalidir.
pause
exit /b 1

:nginx_exists
echo    [OK] Nginx zaten kurulu: %NGINX_DIR%

:nginx_config
:: Config kopyala
if not exist "%NGINX_DIR%\conf\conf.d" mkdir "%NGINX_DIR%\conf\conf.d"
copy /y "%PROJECT_ROOT%\deploy\nginx\vyra.conf" "%NGINX_DIR%\conf\conf.d\vyra.conf" >nul

:: nginx.conf kontrol et ve gerekirse yeniden yaz
powershell -Command "$c = Get-Content '%NGINX_DIR%\conf\nginx.conf' -Raw -ErrorAction SilentlyContinue; if ($c -notmatch 'include\s+conf\.d') { $t = \"worker_processes auto;`nerror_log logs/error.log warn;`npid logs/nginx.pid;`nevents { worker_connections 1024; }`nhttp {`n    include mime.types;`n    default_type application/octet-stream;`n    sendfile on;`n    keepalive_timeout 65;`n    gzip on;`n    gzip_types text/plain text/css application/json application/javascript text/xml;`n    include conf.d/*.conf;`n}`n\"; $u = New-Object System.Text.UTF8Encoding $false; [System.IO.File]::WriteAllText('%NGINX_DIR%\conf\nginx.conf', $t, $u); Write-Host '   [OK] nginx.conf guncellendi' } else { Write-Host '   [OK] nginx.conf hazir' }"

:: Config test
pushd "%NGINX_DIR%"
"%NGINX_EXE%" -t >nul 2>&1
if errorlevel 1 (
    echo    [UYARI] Nginx config testi basarisiz
) else (
    echo    [OK] Nginx config testi basarili
)
popd
echo.

:: =============================================================
:: ADIM 4: PostgreSQL
:: =============================================================
echo [4/7] PostgreSQL baslatiliyor...
"%PG_BIN%\pg_isready.exe" -h localhost -p 5005 >nul 2>&1
if not errorlevel 1 goto pg_already_running

start "" /B "%PG_BIN%\pg_ctl.exe" -D "%PG_DATA%" -l "%PG_LOG%" start >nul 2>&1

set "PG_ATTEMPTS=0"
:pg_wait
timeout /t 3 /nobreak >nul
"%PG_BIN%\pg_isready.exe" -h localhost -p 5005 >nul 2>&1
if not errorlevel 1 goto pg_started

set /a PG_ATTEMPTS+=1
if !PG_ATTEMPTS! lss 10 goto pg_wait
echo    [HATA] PostgreSQL baslatilamadi! Log: %PG_LOG%
pause
exit /b 1

:pg_already_running
echo    [OK] PostgreSQL zaten calisiyor
goto pg_done
:pg_started
echo    [OK] PostgreSQL baslatildi
:pg_done
echo.

:: =============================================================
:: ADIM 5: Redis Cache
:: =============================================================
echo [5/7] Redis baslatiliyor...

if not exist "%REDIS_EXE%" goto redis_skip

:: Zaten calisiyor mu?
"%REDIS_CLI%" ping >nul 2>&1
if not errorlevel 1 goto redis_already

:: Baslat
start "" /B "%REDIS_EXE%" "%REDIS_CONF%"
timeout /t 2 /nobreak >nul

:: Bellek limiti ayarla
"%REDIS_CLI%" CONFIG SET maxmemory 128mb >nul 2>&1
"%REDIS_CLI%" CONFIG SET maxmemory-policy allkeys-lru >nul 2>&1

echo    [OK] Redis baslatildi - port 6379 (128MB LRU)
goto redis_done

:redis_already
echo    [OK] Redis zaten calisiyor
goto redis_done

:redis_skip
echo    [UYARI] Redis bulunamadi, in-memory cache kullanilacak
:redis_done
echo.

:: =============================================================
:: ADIM 6: Backend - Uvicorn
:: =============================================================
echo [6/7] Backend baslatiliyor...

:: Zaten calisiyor mu?
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:%BACKEND_PORT%/api/health' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop; exit 0 } catch { exit 1 }"
if not errorlevel 1 goto backend_already

:: Uvicorn baslat (minimize pencere)
start "VYRA-Backend" /MIN powershell -NoExit -Command "cd '%PROJECT_ROOT%'; $env:PYTHONPATH='%PROJECT_ROOT%'; & '%VENV_PYTHON%' -m uvicorn app.api.main:app --host 0.0.0.0 --port %BACKEND_PORT% --workers %WORKERS% --limit-concurrency 100 --timeout-keep-alive 30 --no-server-header --log-level warning"

:: Health check bekle
set "BE_ATTEMPTS=0"
:be_wait
timeout /t 3 /nobreak >nul
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://localhost:%BACKEND_PORT%/api/health' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop; exit 0 } catch { exit 1 }"
if not errorlevel 1 goto backend_started

set /a BE_ATTEMPTS+=1
if !BE_ATTEMPTS! lss 30 goto be_wait
echo    [UYARI] Backend henuz hazir degil, devam ediliyor...
goto backend_done

:backend_already
echo    [OK] Backend zaten calisiyor
goto backend_done
:backend_started
echo    [OK] Backend hazir - port %BACKEND_PORT%, %WORKERS% worker
:backend_done
echo.

:: =============================================================
:: ADIM 6: Nginx
:: =============================================================
echo [7/7] Nginx baslatiliyor...
tasklist /fi "imagename eq nginx.exe" 2>nul | find /i "nginx.exe" >nul
if not errorlevel 1 goto nginx_reload

:: Baslat
pushd "%NGINX_DIR%"
start "" /B "%NGINX_EXE%"
popd
timeout /t 1 /nobreak >nul
echo    [OK] Nginx baslatildi - port 80
goto nginx_done

:nginx_reload
pushd "%NGINX_DIR%"
"%NGINX_EXE%" -s reload >nul 2>&1
popd
echo    [OK] Nginx reload edildi - port 80
:nginx_done
echo.

:: =============================================================
:: Versiyon
:: =============================================================
set "PAGER="
set "VERSION="
for /f "tokens=*" %%v in ('powershell -Command "$env:PAGER=''; & '%PG_BIN%\psql.exe' -U postgres -d vyra -h localhost -p 5005 -t -A -c \"SELECT setting_value FROM system_settings WHERE setting_key = ''app_version''\" 2>$null"') do set "VERSION=%%v"
if not defined VERSION set "VERSION=?.?.?"

:: =============================================================
:: SONUC
:: =============================================================
echo =============================================================
echo.
echo    VYRA v%VERSION% - PRODUCTION HAZIR!
echo.
echo    URL:   http://localhost/login.html
echo    API:   http://localhost/api/health
echo    DB:    localhost:5005/vyra
echo    Redis: localhost:6379 (128MB LRU)
echo.
echo    Durdurmak: deploy\stop_production.ps1
echo.
echo =============================================================
echo.

:: Tarayici ac
start "" "http://localhost/login.html"

echo Cikis icin herhangi bir tusa basin...
pause >nul
