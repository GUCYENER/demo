@echo off
chcp 65001 >nul
echo ============================================================
echo   VYRA Oracle Test DB — Docker Desktop Kurulum Rehberi
echo ============================================================
echo.
echo   Docker Desktop henuz kurulu degil.
echo   Asagidaki adimlarla kurun:
echo.
echo   1. https://www.docker.com/products/docker-desktop/ adresinden
echo      Docker Desktop for Windows'u indirin
echo.
echo   2. Installer'i calistirin (yonetici olarak)
echo.
echo   3. Kurulum bitince bilgisayari yeniden baslatin
echo.
echo   4. Docker Desktop'u acin ve baslamasini bekleyin
echo      (System tray'de balina ikonu yesil olana kadar)
echo.
echo   5. Bu klasorde asagidaki komutu calistirin:
echo      docker compose up -d
echo.
echo   6. Container hazir oldugunda (~2 dk):
echo      python 03_setup_oracle.py
echo.
echo ============================================================
echo.
echo   NOT: Docker Desktop ucretsizdir (bireysel kullanim).
echo   Kurumsal kullanim icin lisans gerekebilir.
echo.
echo   Alternatif: Oracle Database Free 23ai
echo   https://www.oracle.com/database/free/
echo   (Dogrudan Windows'a kurulur, Docker gerektirmez)
echo.
echo ============================================================
pause
