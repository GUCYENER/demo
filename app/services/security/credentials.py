"""
VYRA L1 Support API — Multi-Key Fernet Credential Wrapper
==========================================================
Ajan-J v3.32.0 (MVP) — Fernet Credential Rotation Infrastructure

Bu modül `cryptography.fernet.MultiFernet` üzerinden çoklu key destekli
şifreleme/çözme sunar. `data_sources.db_password_encrypted` gibi hassas
alanlar için kullanılır.

Key Convention
--------------
Env değişkeni: ``VYRA_FERNET_KEYS`` — virgülle ayrılmış Fernet key listesi.
    - Listedeki SON key = en yeni (write key)
    - Decrypt: tüm key'ler sırasıyla denenir (cryptography lib default)
    - Encrypt: her zaman en yeni key kullanılır
Legacy tek-key: ``VYRA_FERNET_KEY`` env'i de kabul edilir (tek elemanlı
liste muamelesi görür).

Backward Compat
---------------
``encrypt(value) -> bytes`` ve ``decrypt(token) -> str`` signature'ları
korunur — mevcut çağrı yerleri etkilenmez.

NOT: ``app/core/encryption.py`` modülü (DB-stored key, AES-256 Fernet)
ayrı bir mekanizmadır ve değiştirilmemiştir; bu yeni modül **env-based
multi-key** rotation için paralel bir altyapıdır. Rotation script
(``scripts/rotate_fernet_credentials.py``) bu modülü kullanır.

Version: v3.32.0 (MVP — auto-scheduler v3.33'e ertelendi)
"""
from __future__ import annotations

import logging
import os
import threading
from typing import List, Optional, Union

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Module-level lazy singleton — thread-safe init
# ---------------------------------------------------------------------------
_multi_fernet: Optional[MultiFernet] = None
_key_count: int = 0
_lock = threading.Lock()


def _read_keys_from_env() -> List[str]:
    """
    VYRA_FERNET_KEYS > VYRA_FERNET_KEY (legacy) sırasıyla okur.
    Boş/whitespace key'leri atar. Geri dönen listenin SON elemanı en yeni
    (write) key'tir.

    Raises:
        RuntimeError: Hiç key yoksa.
    """
    raw = os.getenv("VYRA_FERNET_KEYS") or os.getenv("VYRA_FERNET_KEY")
    if not raw:
        raise RuntimeError(
            "Fernet key bulunamadı: VYRA_FERNET_KEYS (önerilen) veya "
            "VYRA_FERNET_KEY (legacy) env değişkenlerinden biri set edilmeli."
        )
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("VYRA_FERNET_KEYS değişkeni geçersiz (boş liste).")
    return keys


def _build_multifernet(keys: List[str]) -> MultiFernet:
    """Liste içindeki tüm key'lerden MultiFernet kurar.

    cryptography lib: MultiFernet([f1, f2, f3]) → encrypt f1 ile, decrypt
    sırayla f1, f2, f3 dener. Bu yüzden EN YENİ key listenin BAŞINDA
    olmalıdır. Brief "son eklenen = write key" diyor → ENV'den okurken
    listeyi REVERSE ediyoruz: kullanıcı ``OLD,NEW`` yazar; MultiFernet'e
    ``[NEW, OLD]`` veririz.
    """
    fernets = [Fernet(k.encode() if isinstance(k, str) else k) for k in keys]
    # Reverse: env convention (son=yeni) → MultiFernet convention (ilk=yeni)
    fernets.reverse()
    return MultiFernet(fernets)


def _load_fernet() -> MultiFernet:
    """Lazy, thread-safe singleton MultiFernet builder."""
    global _multi_fernet, _key_count
    if _multi_fernet is not None:
        return _multi_fernet
    with _lock:
        if _multi_fernet is None:
            keys = _read_keys_from_env()
            _multi_fernet = _build_multifernet(keys)
            _key_count = len(keys)
            logger.info(
                "[Credentials] MultiFernet initialized with %d key(s); "
                "write-key index = %d (last in env)",
                _key_count,
                _key_count,
            )
    return _multi_fernet


def reset_cache() -> None:
    """Test/rotation amaçlı: singleton'ı sıfırlar (env değişince yeniden okur)."""
    global _multi_fernet, _key_count
    with _lock:
        _multi_fernet = None
        _key_count = 0


# ---------------------------------------------------------------------------
#  Public API — backward-compatible signatures
# ---------------------------------------------------------------------------
def encrypt(value: str) -> bytes:
    """Düz metni en yeni (write) Fernet key ile şifreler.

    Returns:
        bytes: Fernet token (base64-url-safe). Caller `.decode("utf-8")`
        ile string'e çevirebilir.

    Raises:
        ValueError: value boş ise.
        RuntimeError: Fernet key yoksa.
    """
    if not value:
        raise ValueError("Şifrelenecek değer boş olamaz")
    return _load_fernet().encrypt(value.encode("utf-8"))


def decrypt(token: Union[str, bytes]) -> str:
    """Fernet token'ı çözer; tüm key'leri sırayla dener.

    Args:
        token: bytes veya str (base64 Fernet token).

    Returns:
        str: Çözülmüş düz metin.

    Raises:
        ValueError: token boş ise veya hiçbir key ile çözülemezse.
        RuntimeError: Fernet key yoksa.
    """
    if not token:
        raise ValueError("Çözülecek token boş olamaz")
    if isinstance(token, str):
        token = token.encode("utf-8")
    try:
        return _load_fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        logger.error("[Credentials] Decrypt FAILED — tüm key'ler denendi, hiçbiri uymadı")
        raise ValueError("Fernet decrypt başarısız: hiçbir key uymadı") from exc


def current_key_version() -> int:
    """ENV'de tanımlı key sayısı = en yeni key'in version numarası.

    Convention: tek key → v1, iki key → v2 (NEW), vs. Rotation script
    yeniden şifrelediği satırlara bu değeri yazar.

    Returns:
        int: 1, 2, 3, ... — en az 1.
    """
    _load_fernet()  # ensures _key_count populated
    return _key_count


def rotate_token(token: Union[str, bytes]) -> bytes:
    """Mevcut token'ı eski key ile çözer, en yeni key ile yeniden şifreler.

    MultiFernet.rotate() etrafında ince bir wrapper. Rotation script
    tarafından kullanılır.

    Returns:
        bytes: En yeni key ile şifrelenmiş yeni Fernet token.
    """
    if not token:
        raise ValueError("Rotate edilecek token boş olamaz")
    if isinstance(token, str):
        token = token.encode("utf-8")
    return _load_fernet().rotate(token)
