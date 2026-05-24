#!/usr/bin/env bash
# Oracle Test DB — VYRA (WSL / Git Bash versiyonu)
# .bat ile aynı davranış, bash-native.

set -e

# Docker CLI yolu — Windows Docker Desktop'ı WSL'den kullan
if [[ -x "/c/Program Files/Docker/Docker/resources/bin/docker.exe" ]]; then
    DOCKER="/c/Program Files/Docker/Docker/resources/bin/docker.exe"
elif command -v docker.exe >/dev/null 2>&1; then
    DOCKER="docker.exe"
elif command -v docker >/dev/null 2>&1; then
    DOCKER="docker"
else
    echo "[HATA] docker bulunamadi (Docker Desktop kurulu mu?)"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/oracle_local_test/docker-compose.yml"
CONTAINER="vyra-oracle-test"

echo "============================================================"
echo "  Oracle Test DB — Hizli Baslatici (WSL/Bash)"
echo "============================================================"

# Docker Desktop ayakta mi?
if ! "$DOCKER" info >/dev/null 2>&1; then
    echo "[*] Docker Desktop baslatiliyor..."
    cmd.exe /c start "" "C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe" 2>/dev/null || \
        powershell.exe -Command "Start-Process 'C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe'" 2>/dev/null
    echo "    Bekleniyor..."
    for i in $(seq 1 60); do
        sleep 5
        if "$DOCKER" info >/dev/null 2>&1; then
            break
        fi
        echo "    [$((i*5))s] hala bekleniyor..."
    done
    if ! "$DOCKER" info >/dev/null 2>&1; then
        echo "[HATA] Docker Desktop 5 dakika icinde acilmadi."
        exit 1
    fi
fi

# Engine kontrolu (WSL2/Linux bekleniyor)
ENGINE_OS=$("$DOCKER" version --format "{{.Server.Os}}" 2>/dev/null | tr -d '\r\n')
if [[ "$ENGINE_OS" != "linux" ]]; then
    echo "[UYARI] Docker engine '$ENGINE_OS' modunda — Linux containers gerekli."
    echo "        Docker Desktop sag-tik > 'Switch to Linux containers' deneyin."
    exit 1
fi
echo "[OK] Docker Desktop hazir (engine: $ENGINE_OS)"

# Container durumu
STATUS=$("$DOCKER" ps -a --filter "name=${CONTAINER}" --format "{{.Status}}" 2>/dev/null | head -1)

if [[ "$STATUS" == Up* ]]; then
    echo "[OK] Oracle container zaten calisiyor."
elif [[ "$STATUS" == Exited* ]]; then
    echo "[*] Container durdurulmus, yeniden baslatiliyor..."
    "$DOCKER" start "$CONTAINER"
else
    echo "[*] Container bulunamadi, olusturuluyor..."
    # docker-compose.yml Windows path ise convert
    COMPOSE_WIN=$(cygpath -w "$COMPOSE_FILE" 2>/dev/null || echo "$COMPOSE_FILE")
    "$DOCKER" compose -f "$COMPOSE_WIN" up -d
fi

# Hazir olmasini bekle
echo "[*] Oracle DB hazir olmasini bekliyoruz (max 5 dk)..."
for i in $(seq 1 60); do
    sleep 5
    if "$DOCKER" logs --tail 5 "$CONTAINER" 2>&1 | grep -qi "DATABASE IS READY"; then
        echo "[OK] Oracle DB hazir!"
        break
    fi
    echo "    [$((i*5))s] hala bekleniyor..."
done

if ! "$DOCKER" logs --tail 5 "$CONTAINER" 2>&1 | grep -qi "DATABASE IS READY"; then
    echo "[UYARI] 'DATABASE IS READY' tetiklenmedi. Son loglar:"
    "$DOCKER" logs --tail 20 "$CONTAINER"
    exit 1
fi

echo
echo "    Host:     localhost"
echo "    Port:     1521"
echo "    Service:  FREEPDB1"
echo "    User:     VYRA_TEST"
echo "    Pass:     VyraTest2026"
echo
echo "============================================================"
