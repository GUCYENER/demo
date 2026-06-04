"""
VYRA L1 Support API - Logging Service
======================================
Sistem loglarını PostgreSQL + dosya (rotation) + console'a yazar.

v2.30.1: Structured file logging eklendi
- logs/vyra.log → günlük rotation, 7 gün saklama
- JSON structured format (machine parsing)
- Console WARNING+ (debug modunda)
"""

from __future__ import annotations

import json
import logging
import traceback as _traceback
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Optional

from app.core.db import get_db_conn

# ── File Logger Setup ────────────────────────────────────────

_file_logger: Optional[logging.Logger] = None

def _get_file_logger() -> logging.Logger:
    """Lazy-init file logger (rotation destekli)"""
    global _file_logger
    if _file_logger is not None:
        return _file_logger
    
    # logs/ dizinini oluştur
    from app.core.config import BASE_DIR
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    
    logger = logging.getLogger("vyra")
    logger.setLevel(logging.DEBUG)
    
    # Dosya handler: günlük rotation, 7 gün saklama
    # Windows multi-worker safe: PermissionError'da rotation atlanır
    file_handler = TimedRotatingFileHandler(
        filename=str(log_dir / "vyra.log"),
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
        delay=True  # Dosyayı hemen açma, ilk yazımda aç (kilit azaltır)
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Windows'ta multi-worker rotation fix: PermissionError'da sessizce atla
    _original_rotate = file_handler.doRollover
    def _safe_rollover():
        try:
            _original_rotate()
        except PermissionError:
            pass  # Başka bir worker zaten rotate etti
    file_handler.doRollover = _safe_rollover
    
    # JSON structured format — v3.38.3: exc_info (traceback) + request_id + zengin alanlar
    class JSONFormatter(logging.Formatter):
        def format(self, record):
            log_entry = {
                "ts": datetime.now().isoformat(),
                "level": record.levelname,
                "module": getattr(record, "vyra_module", "system"),
                "msg": record.getMessage(),
            }
            # Opsiyonel alanlar
            for key in ("user_id", "error_detail", "request_path", "request_method",
                        "response_status", "request_id", "exc_type"):
                val = getattr(record, key, None)
                if val is not None:
                    log_entry[key] = val
            # v3.38.3: traceback — global handler exc_info=True ile loglar; ESKİDEN
            # bu formatter onu DÜŞÜRÜYORDU (traceback yalnız konsola gidiyordu).
            if record.exc_info:
                log_entry["traceback"] = self.formatException(record.exc_info)
            return json.dumps(log_entry, ensure_ascii=False)

    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    # v3.38.3: AYRI hata akışı — logs/errors.jsonl (yalnız ERROR+, tam traceback).
    # "Tek yerden bak" dosyası: gürültüsüz, her satır bir hata + context + traceback.
    err_handler = TimedRotatingFileHandler(
        filename=str(log_dir / "errors.jsonl"),
        when="midnight", interval=1, backupCount=14,
        encoding="utf-8", delay=True,
    )
    err_handler.setLevel(logging.ERROR)
    err_handler.setFormatter(JSONFormatter())
    _orig_err_rotate = err_handler.doRollover
    def _safe_err_rollover():
        try:
            _orig_err_rotate()
        except PermissionError:
            pass
    err_handler.doRollover = _safe_err_rollover
    logger.addHandler(err_handler)
    
    # Console handler (WARNING+)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(console_handler)
    
    _file_logger = logger
    return logger


_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def log_system_event(
    level: str,
    message: str,
    module: Optional[str] = None,
    user_id: Optional[int] = None,
    request_path: Optional[str] = None,
    request_method: Optional[str] = None,
    response_status: Optional[int] = None,
    error_detail: Optional[str] = None,
    request_id: Optional[str] = None,
    exc_type: Optional[str] = None,
    exc_info=None,
) -> None:
    """
    Sistem loglarını `system_logs` tablosuna yazar.

    Args:
        level: Log seviyesi (INFO, WARNING, ERROR, CRITICAL)
        message: Log mesajı
        module: Modül adı (örn: 'auth', 'tickets', 'llm')
        user_id: İşlemi yapan kullanıcı ID (varsa)
        request_path: API request path (varsa)
        request_method: HTTP method (GET, POST, vb.)
        response_status: HTTP response status code
        error_detail: Hata detayı (varsa)
    """
    # 1) Dosya loglama (structured JSON → logs/vyra.log)
    try:
        file_log = _get_file_logger()
        py_level = _LEVEL_MAP.get(level.upper(), logging.INFO)
        extra = {
            "vyra_module": module or "system",
            "user_id": user_id,
            "error_detail": error_detail,
            "request_path": request_path,
            "request_method": request_method,
            "response_status": response_status,
            "request_id": request_id,
            "exc_type": exc_type,
        }
        # exc_info verilmişse JSONFormatter "traceback" alanını üretir + errors.jsonl'e düşer
        file_log.log(py_level, message, extra=extra, exc_info=exc_info)
    except Exception as e:
        print(f"[LOGGING] File log hatası: {e}")  # File log hatası kritik değil
    
    # 2) Veritabanı loglama (mevcut davranış)
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        
        cur.execute(
            """
            INSERT INTO system_logs (
                level, message, module, user_id, request_path,
                request_method, response_status, error_detail, request_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                level,
                (message or "").replace("\x00", ""),  # v3.38.2 dersi: PG NUL'ı reddeder
                module,
                user_id,
                request_path,
                request_method,
                response_status,
                (error_detail.replace("\x00", "") if error_detail else None),
                request_id,
            ),
        )
        
        conn.commit()
        conn.close()
    except Exception as e:
        # Loglama sistemi başarısız olursa bile uygulama çalışmaya devam etmeli
        print(f"[LOGGING ERROR] {str(e)}")


def log_request(
    request_path: str,
    request_method: str,
    user_id: Optional[int] = None,
    response_status: Optional[int] = None,
) -> None:
    """API request/response loglar."""
    log_system_event(
        level="INFO",
        message=f"{request_method} {request_path} - Status: {response_status}",
        module="api",
        user_id=user_id,
        request_path=request_path,
        request_method=request_method,
        response_status=response_status,
    )


def log_error(
    message: str,
    module: str,
    error_detail: Optional[str] = None,
    user_id: Optional[int] = None,
) -> None:
    """Hata loglar."""
    log_system_event(
        level="ERROR",
        message=message,
        module=module,
        user_id=user_id,
        error_detail=error_detail,
    )


def log_warning(
    message: str,
    module: str,
    user_id: Optional[int] = None,
) -> None:
    """Uyarı loglar."""
    log_system_event(
        level="WARNING",
        message=message,
        module=module,
        user_id=user_id,
    )


def log_critical(
    message: str,
    module: str,
    error_detail: Optional[str] = None,
    user_id: Optional[int] = None,
) -> None:
    """Kritik hata loglar."""
    log_system_event(
        level="CRITICAL",
        message=message,
        module=module,
        user_id=user_id,
        error_detail=error_detail,
    )


# ── v3.38.3: Merkezi exception loglama (tam traceback + redaksiyon) ──────────

# Loglarda maskelenecek hassas anahtarlar (request body/header özetinde)
_REDACT_KEYS = (
    "password", "passwd", "pwd", "token", "secret", "authorization",
    "db_password", "db_pass", "api_key", "apikey", "cookie", "session",
)
_MAX_TRACEBACK = 16000  # bayt — devasa traceback'leri kırp


def redact_sensitive(data):
    """dict/list içindeki hassas alanları maskeler (log'a yazmadan önce)."""
    try:
        if isinstance(data, dict):
            out = {}
            for k, v in data.items():
                if any(s in str(k).lower() for s in _REDACT_KEYS):
                    out[k] = "***"
                else:
                    out[k] = redact_sensitive(v)
            return out
        if isinstance(data, (list, tuple)):
            return [redact_sensitive(v) for v in data]
        return data
    except Exception:
        return "<redaction-error>"


def log_exception(
    exc: BaseException,
    *,
    module: str = "api",
    request_id: Optional[str] = None,
    request_path: Optional[str] = None,
    request_method: Optional[str] = None,
    user_id: Optional[int] = None,
    response_status: int = 500,
    context: Optional[dict] = None,
) -> None:
    """Unhandled exception'ı TAM traceback + context ile MERKEZİ olarak loglar.

    Hedef: logs/errors.jsonl (yalnız ERROR+, traceback'li) + logs/vyra.log + system_logs DB.
    `request_id` ile kullanıcının gördüğü 500 ↔ log kaydı birebir eşleşir.
    Güvenlik: NUL strip (PG), hassas alan redaksiyonu, traceback boyut limiti.
    Loglama hatası ASLA çağrıyı kırmaz (her şey best-effort).
    """
    try:
        tb = "".join(_traceback.format_exception(type(exc), exc, exc.__traceback__))
    except Exception:
        tb = repr(exc)
    tb = (tb or "").replace("\x00", "")[:_MAX_TRACEBACK]
    exc_type = type(exc).__name__
    msg = f"[{exc_type}] {str(exc)[:500]}".replace("\x00", "")
    if context:
        try:
            ctx_json = json.dumps(redact_sensitive(context), ensure_ascii=False, default=str)
            tb = tb + "\n\n--- context ---\n" + ctx_json[:4000]
        except Exception:
            pass
    log_system_event(
        level="ERROR",
        message=msg,
        module=module,
        user_id=user_id,
        request_path=request_path,
        request_method=request_method,
        response_status=response_status,
        error_detail=tb,
        request_id=request_id,
        exc_type=exc_type,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
