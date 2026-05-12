#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VYRA L1 Support - Linux Production Launcher
=============================================
canlida_calistir.bat dosyasının Linux (RHEL 8.10) karşılığı.

Kullanım:
    python3 canlida_calistir_linux.py

Durdurma:
    CTRL+C  (graceful shutdown)

Gereksinimler (önceden kurulmuş olmalı):
    - Python 3.11          : sudo rpm -ivh setup/rpms/python3.11-*.rpm
    - PostgreSQL 16        : sudo rpm -ivh setup/rpms/postgresql16-*.rpm
    - Redis                : sudo rpm -ivh setup/rpms/redis-*.rpm
    - Nginx                : sudo rpm -ivh setup/rpms/nginx-*.rpm
    - venv + paketler      : python3.11 -m venv venv  (launcher otomatik kurar)

Detaylı kurulum: setup/KURULUM_REHBERI.md
"""

import os
import sys
import subprocess
import time
import signal
import socket
import shutil
import urllib.request
import urllib.error
from pathlib import Path

# ── Proje Kökü ────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent

# ── PostgreSQL ────────────────────────────────────────────────────────────────
# PGDG RPM kurulumu varsayılan yolu: /usr/pgsql-16/bin/
# Farklı bir konumda ise PG_BIN_OVERRIDE ortam değişkeni ile override edin.
_pg_bin_override = os.environ.get("PG_BIN_OVERRIDE", "")
PG_BIN    = Path(_pg_bin_override) if _pg_bin_override else Path("/usr/pgsql-16/bin")
PG_DATA   = PROJECT_ROOT / "pgsql" / "data"
PG_LOG    = PG_DATA / "server.log"
PG_PORT   = 5005
PG_USER   = "postgres"
PG_DBNAME = "vyra"

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_BIN  = shutil.which("redis-server") or "/usr/bin/redis-server"
REDIS_CLI  = shutil.which("redis-cli")    or "/usr/bin/redis-cli"
REDIS_CONF = PROJECT_ROOT / "setup" / "redis.conf"
REDIS_DATA = PROJECT_ROOT / "redis" / "data"
REDIS_PORT = 6380
REDIS_PASS = "VyraR3d1s_Sec2026"

# ── Uygulama ──────────────────────────────────────────────────────────────────
VENV_PYTHON   = PROJECT_ROOT / "venv" / "bin" / "python"
BACKEND_PORT  = 8002
WORKERS       = 1

# ── Nginx ─────────────────────────────────────────────────────────────────────
NGINX_CONF_SRC  = PROJECT_ROOT / "deploy" / "nginx" / "vyra.conf"
NGINX_CONF_DEST = Path("/etc/nginx/conf.d/vyra.conf")

# ── ANSI Renkler ──────────────────────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

# ── Global süreç referansları (shutdown için) ─────────────────────────────────
_uvicorn_proc = None
_redis_proc   = None


# ═══════════════════════════════════════════════════════════════════════════════
# Yardımcı fonksiyonlar
# ═══════════════════════════════════════════════════════════════════════════════

def log(color, tag, msg):
    print(f"   {color}[{tag}]{RESET} {msg}", flush=True)


def log_step(step, total, title):
    print(f"\n{CYAN}[{step}/{total}] {title}...{RESET}", flush=True)


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run(cmd, env=None, cwd=None, capture=True, check=False):
    """Komutu çalıştır, sonucu döndür."""
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else None,
        check=check,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 0: Banner
# ═══════════════════════════════════════════════════════════════════════════════

def print_header():
    print(f"\n{CYAN}{'='*62}{RESET}")
    print(f"{CYAN}{BOLD}   VYRA L1 Support - Linux Production Launcher{RESET}")
    print(f"{CYAN}{'='*62}{RESET}")
    print(f"   Proje : {PROJECT_ROOT}")
    print(f"   Python: {VENV_PYTHON}")
    print(f"{CYAN}{'='*62}{RESET}\n")


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 0: .env Kontrolü
# ═══════════════════════════════════════════════════════════════════════════════

def check_env_file() -> bool:
    log_step("0", "8", ".env dosyası kontrol ediliyor")
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        log(RED, "HATA", ".env dosyası bulunamadı!")
        log(RED, "BİLGİ", "  cp .env.example .env  komutuyla oluşturun ve düzenleyin.")
        return False
    log(GREEN, "OK", ".env dosyası mevcut")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 1: PostgreSQL Binary Kontrolü
# ═══════════════════════════════════════════════════════════════════════════════

def check_pg_binary() -> bool:
    log_step("1", "8", "PostgreSQL binary kontrol ediliyor")

    pg_ctl = PG_BIN / "pg_ctl"

    # Önce yapılandırılmış yolu dene
    if pg_ctl.exists():
        log(GREEN, "OK", f"pg_ctl bulundu: {pg_ctl}")
        return True

    # PATH üzerinde ara (sistem kurulumu farklı yerde olabilir)
    pg_ctl_which = shutil.which("pg_ctl")
    if pg_ctl_which:
        log(YELLOW, "BİLGİ", f"pg_ctl PATH'te bulundu: {pg_ctl_which}")
        log(YELLOW, "BİLGİ", f"PG_BIN_OVERRIDE ortam değişkeni ile yolu ayarlayın.")
        # PATH'teki sürümü kullan
        global PG_BIN
        PG_BIN = Path(pg_ctl_which).parent
        log(GREEN, "OK", f"PG_BIN güncellendi: {PG_BIN}")
        return True

    log(RED, "HATA", f"pg_ctl bulunamadı: {pg_ctl}")
    log(RED, "KURU", "PostgreSQL 16 kurulumu:")
    log(RED, "KURU", "  sudo rpm -ivh setup/rpms/postgresql16-libs-*.rpm")
    log(RED, "KURU", "  sudo rpm -ivh setup/rpms/postgresql16-*.rpm")
    log(RED, "KURU", "  sudo rpm -ivh setup/rpms/postgresql16-server-*.rpm")
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 2: Python Venv + Bağımlılıklar
# ═══════════════════════════════════════════════════════════════════════════════

def check_and_install_dependencies() -> bool:
    log_step("2", "8", "Python venv ve bağımlılıklar kontrol ediliyor")

    if not VENV_PYTHON.exists():
        log(YELLOW, "OLUŞTUR", f"venv bulunamadı, oluşturuluyor: {PROJECT_ROOT / 'venv'}")
        # python3.11 tercih et, yoksa python3
        py_exec = shutil.which("python3.11") or shutil.which("python3") or "python3"
        result = run([py_exec, "-m", "venv", str(PROJECT_ROOT / "venv")], capture=False)
        if result.returncode != 0:
            log(RED, "HATA", "venv oluşturulamadı!")
            log(RED, "KURU", f"  {py_exec} -m venv {PROJECT_ROOT / 'venv'}")
            return False
        log(GREEN, "OK", "venv oluşturuldu")

    # uvicorn kurulu mu? (hızlı kontrol)
    uvicorn_marker = PROJECT_ROOT / "venv" / "lib"
    uvicorn_installed = False
    if uvicorn_marker.exists():
        for lib_dir in uvicorn_marker.iterdir():
            marker = lib_dir / "site-packages" / "uvicorn" / "__init__.py"
            if marker.exists():
                uvicorn_installed = True
                break

    if uvicorn_installed:
        log(GREEN, "OK", "Bağımlılıklar zaten kurulu")
        return True

    # Offline kurulum
    linux_wheels = PROJECT_ROOT / "setup" / "linux_wheels"
    req_linux    = PROJECT_ROOT / "setup" / "requirements_linux.txt"

    if not linux_wheels.exists() or not any(linux_wheels.glob("*.whl")):
        log(RED, "HATA", f"setup/linux_wheels/ klasörü boş veya yok!")
        log(RED, "BİLGİ", "Windows makinesinde önce şunu çalıştırın:")
        log(RED, "BİLGİ", "  python setup\\indir_linux_paketleri.py")
        return False

    if not req_linux.exists():
        log(RED, "HATA", "setup/requirements_linux.txt bulunamadı!")
        return False

    log(YELLOW, "KURULUM", "Bağımlılıklar offline olarak kuruluyor...")
    log(YELLOW, "BİLGİ",  "Bu işlem 5-10 dakika sürebilir...")

    result = run(
        [
            str(VENV_PYTHON), "-m", "pip", "install",
            "--no-index",
            "--find-links", str(linux_wheels),
            "-r", str(req_linux),
        ],
        capture=False,
    )

    if result.returncode != 0:
        log(RED, "HATA", "Bağımlılıklar kurulamadı!")
        return False

    log(GREEN, "OK", "Tüm bağımlılıklar kuruldu")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 3: Nginx Konfigürasyonu
# ═══════════════════════════════════════════════════════════════════════════════

def configure_nginx() -> bool:
    log_step("3", "8", "Nginx konfigürasyonu hazırlanıyor")

    if not NGINX_CONF_SRC.exists():
        log(RED, "HATA", f"Nginx şablon config bulunamadı: {NGINX_CONF_SRC}")
        return False

    # Şablonu oku
    content = NGINX_CONF_SRC.read_text(encoding="utf-8")

    # __PROJECT_ROOT__ → gerçek yol (forward slash)
    root_str = str(PROJECT_ROOT).replace("\\", "/")
    content = content.replace("__PROJECT_ROOT__", root_str)

    # Relative log path'leri absolute'a çevir (Linux nginx için)
    content = content.replace(
        "access_log  logs/vyra_access.log;",
        "access_log  /var/log/nginx/vyra_access.log;"
    )
    content = content.replace(
        "error_log   logs/vyra_error.log warn;",
        "error_log   /var/log/nginx/vyra_error.log warn;"
    )

    # /etc/nginx/conf.d/vyra.conf'a yaz
    try:
        NGINX_CONF_DEST.parent.mkdir(parents=True, exist_ok=True)
        NGINX_CONF_DEST.write_text(content, encoding="utf-8")
        log(GREEN, "OK", f"nginx config yazıldı: {NGINX_CONF_DEST}")
    except PermissionError:
        # sudo gerektiren yol - geçici konuma yaz, kullanıcıya bildir
        tmp_conf = PROJECT_ROOT / "setup" / "vyra_nginx_generated.conf"
        tmp_conf.write_text(content, encoding="utf-8")
        log(YELLOW, "UYARI", f"İzin hatası! Config geçici konuma yazıldı: {tmp_conf}")
        log(YELLOW, "MANUEL", "Aşağıdaki komutu çalıştırın:")
        log(YELLOW, "MANUEL", f"  sudo cp {tmp_conf} {NGINX_CONF_DEST}")
        log(YELLOW, "MANUEL", "  sudo nginx -t && sudo nginx -s reload")

    # nginx -t testi
    nginx_exec = shutil.which("nginx") or "/usr/sbin/nginx"
    result = run([nginx_exec, "-t"])
    if result.returncode == 0:
        log(GREEN, "OK", "Nginx config testi başarılı")
    else:
        log(YELLOW, "UYARI", "Nginx config test uyarısı:")
        if result.stderr:
            for line in result.stderr.strip().splitlines():
                log(YELLOW, ">>", line)

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 4: PostgreSQL
# ═══════════════════════════════════════════════════════════════════════════════

def cleanup_pg_pid():
    """Windows'tan gelen stale postmaster.pid dosyasını temizle."""
    pid_file = PG_DATA / "postmaster.pid"
    if pid_file.exists():
        log(YELLOW, "TEMİZLE", "Eski postmaster.pid siliniyor (Windows kalıntısı)...")
        try:
            pid_file.unlink()
            log(GREEN, "OK", "postmaster.pid silindi")
        except OSError as e:
            log(YELLOW, "UYARI", f"postmaster.pid silinemedi: {e}")


def start_postgresql() -> bool:
    log_step("4", "8", "PostgreSQL başlatılıyor")

    pg_ctl      = PG_BIN / "pg_ctl"
    pg_isready  = PG_BIN / "pg_isready"

    if not PG_DATA.exists():
        log(RED, "HATA", f"PostgreSQL data dizini bulunamadı: {PG_DATA}")
        log(RED, "BİLGİ", "pgsql/data/ klasörünü Windows'tan kopyaladığınızdan emin olun.")
        return False

    # Zaten çalışıyor mu?
    result = run([str(pg_isready), "-h", "localhost", "-p", str(PG_PORT)])
    if result.returncode == 0:
        log(GREEN, "OK", f"PostgreSQL zaten çalışıyor (port {PG_PORT})")
        return True

    # Stale PID temizle
    cleanup_pg_pid()

    # Eski server.log'u yeniden adlandır (kilitli olabilir)
    if PG_LOG.exists():
        try:
            old_log = PG_LOG.with_suffix(".log.old")
            PG_LOG.rename(old_log)
        except OSError:
            pass

    log(YELLOW, "BAŞLAT", f"pg_ctl start çağrılıyor (data: {PG_DATA})...")
    log(YELLOW, "BAŞLAT", f"Log: {PG_LOG}")

    result = run(
        [str(pg_ctl), "-D", str(PG_DATA), "-l", str(PG_LOG), "start", "-w"],
        capture=False,
    )

    # -w ile bekledi, ama yine de doğrula
    for attempt in range(1, 31):
        result = run([str(pg_isready), "-h", "localhost", "-p", str(PG_PORT)])
        if result.returncode == 0:
            log(GREEN, "OK", f"PostgreSQL başlatıldı (port {PG_PORT})")
            return True
        log(YELLOW, "BEKLE", f"pg_isready bekleniyor... ({attempt}/30)")
        time.sleep(3)

    log(RED, "HATA", "PostgreSQL başlatılamadı!")
    log(RED, "LOG",  f"Son 15 satır ({PG_LOG}):")
    try:
        lines = PG_LOG.read_text(errors="replace").splitlines()
        for line in lines[-15:]:
            print(f"    {line}")
    except OSError:
        log(RED, "HATA", "Log dosyası okunamadı.")

    log(RED, "SELinux", "SELinux sorunu olabilir. Kontrol:")
    log(RED, "SELinux", "  sudo ausearch -m avc -ts recent | grep postgres")
    log(RED, "SELinux", "  sudo semanage port -a -t postgresql_port_t -p tcp 5005")
    log(RED, "SELinux", "  sudo semanage fcontext -a -t postgresql_db_t \"/opt/vyra/pgsql/data(/.*)?\"")
    log(RED, "SELinux", "  sudo restorecon -Rv pgsql/data/")
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# DB Bakımı
# ═══════════════════════════════════════════════════════════════════════════════

def run_db_maintenance():
    log(YELLOW, "BAKIM", "Veritabanı bakımı yapılıyor (REINDEX + VACUUM)...")

    psql = PG_BIN / "psql"
    env  = os.environ.copy()
    env["PGPASSWORD"] = "postgres"

    tables = [
        "ds_table_enrichments",
        "ds_db_objects",
        "rag_chunks",
        "learned_answers",
    ]

    reindex_cmds = " ".join(f'-c "REINDEX TABLE {t};"' for t in tables)
    vacuum_cmds  = " ".join(f'-c "VACUUM ANALYZE {t};"' for t in tables)

    for label, cmds in [("REINDEX", tables), ("VACUUM", tables)]:
        cmd = [
            str(psql), "-h", "localhost", "-p", str(PG_PORT),
            "-U", PG_USER, "-d", PG_DBNAME, "-q",
        ]
        for t in cmds:
            cmd += ["-c", f"{'REINDEX TABLE' if label == 'REINDEX' else 'VACUUM ANALYZE'} {t};"]

        result = run(cmd, env=env)
        if result.returncode == 0:
            log(GREEN, "OK", f"{label} tamamlandı")
        else:
            log(YELLOW, "UYARI", f"{label} sırasında uyarı - devam ediliyor")


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 5: Redis
# ═══════════════════════════════════════════════════════════════════════════════

def start_redis() -> bool:
    global _redis_proc
    log_step("5", "8", "Redis başlatılıyor")

    if not Path(REDIS_BIN).exists() and not shutil.which("redis-server"):
        log(YELLOW, "ATLA", f"redis-server bulunamadı: {REDIS_BIN}")
        log(YELLOW, "ATLA", "In-memory cache kullanılacak (Redis olmadan devam)")
        return True  # Redis opsiyonel, uygulama in-memory fallback'e geçer

    if not REDIS_CONF.exists():
        log(YELLOW, "UYARI", f"setup/redis.conf bulunamadı: {REDIS_CONF}")
        log(YELLOW, "UYARI", "Redis varsayılan config ile başlatılıyor...")

    # Zaten çalışıyor mu?
    result = run([REDIS_CLI, "-p", str(REDIS_PORT), "-a", REDIS_PASS, "ping"])
    if result.returncode == 0 and "PONG" in result.stdout:
        log(GREEN, "OK", f"Redis zaten çalışıyor (port {REDIS_PORT})")
        return True

    # Redis data dizini oluştur
    REDIS_DATA.mkdir(parents=True, exist_ok=True)

    log(YELLOW, "BAŞLAT", f"Redis başlatılıyor (port {REDIS_PORT})...")
    cmd = [REDIS_BIN]
    if REDIS_CONF.exists():
        cmd.append(str(REDIS_CONF))
    cmd += ["--dir", str(REDIS_DATA)]

    _redis_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

    # Doğrula
    for attempt in range(1, 11):
        result = run([REDIS_CLI, "-p", str(REDIS_PORT), "-a", REDIS_PASS, "ping"])
        if result.returncode == 0 and "PONG" in result.stdout:
            log(GREEN, "OK", f"Redis başlatıldı - port {REDIS_PORT} (128MB LRU)")
            return True
        time.sleep(1)

    log(YELLOW, "UYARI", "Redis başlatılamadı - in-memory cache ile devam")
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 6: Backend (Uvicorn)
# ═══════════════════════════════════════════════════════════════════════════════

def is_backend_healthy() -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{BACKEND_PORT}/api/health", timeout=2
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_uvicorn() -> bool:
    global _uvicorn_proc
    log_step("6", "8", f"Backend başlatılıyor ({WORKERS} instance)")

    if not VENV_PYTHON.exists():
        log(RED, "HATA", f"Python venv bulunamadı: {VENV_PYTHON}")
        return False

    # Zaten çalışıyor mu?
    if is_backend_healthy():
        log(GREEN, "OK", "Backend zaten çalışıyor")
        return True

    # Port müsait mi?
    if is_port_in_use(BACKEND_PORT):
        log(RED, "HATA", f"Port {BACKEND_PORT} başka bir uygulama tarafından kullanılıyor!")
        log(RED, "HATA", "  lsof -i :8002  komutuyla kontrol edin.")
        return False

    log(YELLOW, "BAŞLAT", f"Uvicorn başlatılıyor (port {BACKEND_PORT})...")
    log(YELLOW, "BAŞLAT", f"Python: {VENV_PYTHON}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PROJECT_ROOT)

    cmd = [
        str(VENV_PYTHON), "-m", "uvicorn", "app.api.main:app",
        "--host", "0.0.0.0",
        "--port", str(BACKEND_PORT),
        "--workers", str(WORKERS),
        "--limit-concurrency", "100",
        "--timeout-keep-alive", "30",
        "--no-server-header",
        "--log-level", "info",
    ]

    log_file = PROJECT_ROOT / "logs" / "uvicorn.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with open(log_file, "a") as lf:
        _uvicorn_proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=lf,
            stderr=lf,
        )

    log(YELLOW, "BEKLE", f"Backend hazır olana kadar bekleniyor (max 300sn)...")

    for attempt in range(1, 101):
        time.sleep(3)
        if is_backend_healthy():
            log(GREEN, "OK", f"Backend hazır - port {BACKEND_PORT}")
            log(GREEN, "LOG", f"Uvicorn log: {log_file}")
            return True

        # Süreç çöktü mü?
        if _uvicorn_proc.poll() is not None:
            log(RED, "HATA", f"Uvicorn beklenmedik şekilde kapandı (exit code: {_uvicorn_proc.returncode})")
            log(RED, "LOG",  f"Log dosyasını kontrol edin: {log_file}")
            return False

        if attempt % 10 == 0:
            log(YELLOW, "BEKLE", f"Deneme {attempt}/100 ({attempt * 3}sn)...")

    log(YELLOW, "UYARI", "Backend 300sn içinde hazır olmadı.")
    log(YELLOW, "UYARI", f"Log dosyasını kontrol edin: {log_file}")
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 7: Nginx
# ═══════════════════════════════════════════════════════════════════════════════

def start_or_reload_nginx() -> bool:
    log_step("7", "8", "Nginx başlatılıyor/yenileniyor")

    nginx_exec = shutil.which("nginx") or "/usr/sbin/nginx"

    if not Path(nginx_exec).exists():
        log(YELLOW, "ATLA", "nginx bulunamadı. Uvicorn'a direkt erişim kullanın:")
        log(YELLOW, "ATLA", f"  http://SUNUCU_IP:{BACKEND_PORT}/login.html")
        return True

    # Çalışıyor mu?
    result = run(["pgrep", "-x", "nginx"])
    nginx_running = result.returncode == 0

    if nginx_running:
        result = run([nginx_exec, "-s", "reload"])
        if result.returncode == 0:
            log(GREEN, "OK", "Nginx reload edildi - port 8000")
        else:
            log(YELLOW, "UYARI", "Nginx reload hatası:")
            if result.stderr:
                log(YELLOW, ">>", result.stderr.strip()[:200])
    else:
        result = run([nginx_exec], capture=False)
        time.sleep(1)
        if result.returncode == 0:
            log(GREEN, "OK", "Nginx başlatıldı - port 8000")
        else:
            log(YELLOW, "UYARI", "Nginx başlatılamadı:")
            log(YELLOW, "MANUEL", f"  sudo {nginx_exec}")
            log(YELLOW, "MANUEL", f"  sudo systemctl start nginx")

    return True


# ═══════════════════════════════════════════════════════════════════════════════
# ADIM 8: Versiyon
# ═══════════════════════════════════════════════════════════════════════════════

def read_app_version() -> str:
    log_step("8", "8", "Versiyon bilgisi okunuyor")

    psql = PG_BIN / "psql"
    env  = os.environ.copy()
    env["PGPASSWORD"] = "postgres"

    result = run(
        [
            str(psql), "-h", "localhost", "-p", str(PG_PORT),
            "-U", PG_USER, "-d", PG_DBNAME,
            "-t", "-A",
            "-c", "SELECT setting_value FROM system_settings WHERE setting_key = 'app_version'",
        ],
        env=env,
    )

    version = result.stdout.strip() if result.returncode == 0 else ""
    return version if version else "?.?.?"


# ═══════════════════════════════════════════════════════════════════════════════
# Graceful Shutdown
# ═══════════════════════════════════════════════════════════════════════════════

def graceful_shutdown(sig=None, frame=None):
    print(f"\n\n{YELLOW}Graceful shutdown başlatılıyor...{RESET}\n")

    if _uvicorn_proc and _uvicorn_proc.poll() is None:
        log(YELLOW, "DURDUR", "Uvicorn durduruluyor...")
        _uvicorn_proc.terminate()
        try:
            _uvicorn_proc.wait(timeout=10)
            log(GREEN, "OK", "Uvicorn durduruldu")
        except subprocess.TimeoutExpired:
            _uvicorn_proc.kill()
            log(YELLOW, "ZORLA", "Uvicorn zorla kapatıldı")

    if _redis_proc and _redis_proc.poll() is None:
        log(YELLOW, "DURDUR", "Redis durduruluyor...")
        _redis_proc.terminate()
        try:
            _redis_proc.wait(timeout=5)
            log(GREEN, "OK", "Redis durduruldu")
        except subprocess.TimeoutExpired:
            _redis_proc.kill()

    log(YELLOW, "BİLGİ", "PostgreSQL'i durdurmak için:")
    log(YELLOW, "BİLGİ", f"  {PG_BIN}/pg_ctl -D {PG_DATA} stop -m fast")
    log(YELLOW, "BİLGİ", "Nginx'i durdurmak için:")
    log(YELLOW, "BİLGİ", "  sudo nginx -s stop  VEYA  sudo systemctl stop nginx")

    print(f"\n{CYAN}VYRA durduruldu.{RESET}\n")
    sys.exit(0)


# ═══════════════════════════════════════════════════════════════════════════════
# Ana Fonksiyon
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    signal.signal(signal.SIGINT,  graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    print_header()

    # ── Adım 0: .env ──────────────────────────────────────────────────────────
    if not check_env_file():
        sys.exit(1)

    # ── Adım 1: PostgreSQL binary ─────────────────────────────────────────────
    if not check_pg_binary():
        sys.exit(1)

    # ── Adım 2: Venv + bağımlılıklar ─────────────────────────────────────────
    if not check_and_install_dependencies():
        log(YELLOW, "UYARI", "Bağımlılıklar kurulamadı, devam ediliyor...")

    # ── Adım 3: Nginx config ──────────────────────────────────────────────────
    configure_nginx()

    # ── Adım 4: PostgreSQL ────────────────────────────────────────────────────
    if not start_postgresql():
        sys.exit(1)

    # ── DB Bakımı ─────────────────────────────────────────────────────────────
    run_db_maintenance()

    # ── Adım 5: Redis ─────────────────────────────────────────────────────────
    start_redis()

    # ── Adım 6: Backend ───────────────────────────────────────────────────────
    if not start_uvicorn():
        log(YELLOW, "UYARI", "Backend başlatılamadı. Log dosyasını kontrol edin.")

    # ── Adım 7: Nginx ─────────────────────────────────────────────────────────
    start_or_reload_nginx()

    # ── Adım 8: Versiyon ──────────────────────────────────────────────────────
    version = read_app_version()

    # ── Sonuç ─────────────────────────────────────────────────────────────────
    server_ip = "SUNUCU_IP"  # hostname -I ile alınabilir
    try:
        result = run(["hostname", "-I"])
        if result.returncode == 0:
            ips = result.stdout.strip().split()
            if ips:
                server_ip = ips[0]
    except Exception:
        pass

    print(f"\n{CYAN}{'='*62}{RESET}")
    print(f"\n   {GREEN}{BOLD}VYRA v{version} - PRODUCTION HAZIR!{RESET}\n")
    print(f"   URL  : {CYAN}http://{server_ip}:8000/login.html{RESET}")
    print(f"   API  : {CYAN}http://{server_ip}:8000/api/health{RESET}")
    print(f"   DB   : localhost:{PG_PORT}/{PG_DBNAME}")
    print(f"   Redis: localhost:{REDIS_PORT} (128MB LRU)")
    print()
    print(f"   Durdurmak için: {YELLOW}CTRL+C{RESET}")
    print(f"\n{CYAN}{'='*62}{RESET}\n")

    # CTRL+C bekle
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
