#!/usr/bin/env bash
# ============================================================
#  VYRA L1 Support API — WSL/Linux başlatma köprüsü
#  Windows tarafındaki start.ps1'i powershell.exe ile çağırır,
#  ardından WSL tarafından port healthcheck (yalan söylemeyen rapor) yapar.
#  HERMES: hata durumunda çıkış kodu != 0, sessiz başarı yasak.
# ============================================================

set -u  # undefined var = exit; -e DEĞİL (port retry loop'u kendi yönetir)

# ---------- 1) Ortam tespiti ----------
if [ -z "${WSL_DISTRO_NAME:-}" ] && [ "$(uname -s)" != "Linux" ]; then
    echo "[start.sh] Bu script WSL/Linux içindir. Windows için: powershell -File start.ps1" >&2
    exit 1
fi

if ! command -v powershell.exe >/dev/null 2>&1; then
    echo "[start.sh] HATA: powershell.exe PATH'te yok." >&2
    echo "          /mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/ erişilebilir mi?" >&2
    exit 1
fi

if ! command -v wslpath >/dev/null 2>&1; then
    echo "[start.sh] HATA: wslpath bulunamadı — WSL kurulumu eksik." >&2
    exit 1
fi

# ---------- 2) start.ps1 path'ini Windows formatına çevir ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PS1_WSL="$SCRIPT_DIR/start.ps1"

if [ ! -f "$PS1_WSL" ]; then
    echo "[start.sh] HATA: $PS1_WSL bulunamadı." >&2
    exit 1
fi

PS1_WIN=$(wslpath -w "$PS1_WSL")

echo "============================================================"
echo "  VYRA WSL → Windows BAŞLA köprüsü"
echo "  Script: $PS1_WIN"
echo "============================================================"
echo ""

# ---------- 3) start.ps1'i Windows tarafında çalıştır ----------
# stdin'i kapat — PS interaktif okumaya çalışmasın
# stdout/stderr WSL terminaline akar
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$PS1_WIN" </dev/null
PS_EXIT=$?

if [ "$PS_EXIT" -ne 0 ]; then
    echo ""
    echo "[start.sh] ⚠️  start.ps1 exit=$PS_EXIT — servisler kısmen kalkmış olabilir."
fi

# ---------- 4) WSL-tarafı port healthcheck ----------
echo ""
echo "============================================================"
echo "  WSL-tarafı sağlık kontrolü (yalan söylemeyen rapor)"
echo "============================================================"

# WSL2 default networking'de `localhost` distro'nun kendi loopback'idir,
# Windows host'a değil. Default gateway = Windows host IP. Mirrored mode'da
# `localhost` zaten Windows'a forward eder — her iki hedefi de dener (OR).
WIN_HOST=$(ip route 2>/dev/null | awk '/^default/ {print $3}' | head -1)
if [ -z "$WIN_HOST" ]; then
    WIN_HOST="127.0.0.1"
    echo "  uyarı: Windows host IP belirlenemedi, sadece localhost denenecek"
else
    echo "  Healthcheck hedefleri: localhost + $WIN_HOST (Windows host)"
fi

check_port() {
    local name=$1
    local port=$2
    local timeout_s=${3:-15}
    local i=0
    while [ $i -lt $timeout_s ]; do
        if (echo > /dev/tcp/localhost/$port) 2>/dev/null \
           || (echo > /dev/tcp/$WIN_HOST/$port) 2>/dev/null; then
            echo "  ✅  $name (port $port) — AÇIK"
            return 0
        fi
        sleep 1
        i=$((i+1))
    done
    echo "  ❌  $name (port $port) — KAPALI ($timeout_s sn beklendi)"
    return 1
}

FAIL=0
check_port "PostgreSQL" 5005 15 || FAIL=$((FAIL+1))
check_port "Redis"       6380 5  || FAIL=$((FAIL+1))
check_port "Backend"     8002 30 || FAIL=$((FAIL+1))
check_port "Nginx"       8000 10 || FAIL=$((FAIL+1))
# Oracle opsiyonel — Docker yoksa veya kapalıysa fail sayma
check_port "Oracle DB"   1521 3 || echo "     ↳ Oracle opsiyonel (Docker yoksa normal)"

echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "  🟢  Tüm zorunlu servisler ayakta."
    echo "      URL: http://localhost:8000/login.html"
    exit 0
else
    echo "  🟡  $FAIL zorunlu servis kapalı."
    echo "      Windows tarafı log'a bak:"
    echo "        D:\\demo_vyra\\pgsql\\data\\server.log"
    echo "        Backend penceresi (Start-Process powershell ile ayrı pencerede)"
    exit 2
fi
