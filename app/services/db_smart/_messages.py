"""VYRA v3.30.0 FAZ 5 P34 — Server-side i18n messages (DB Smart Wizard).

`db_smart_api` ve `state_machine` katmanı kullanıcıya görünen hata
mesajlarını burada bulundurur. Frontend `Accept-Language` header'ı
gönderdiğinde `parse_accept_language` ile bundle seçilir; aksi halde
DEFAULT_LANG ('tr') döner.

ARES/HERMES notları:
    - Header parse defansif: malformed/eksik input → DEFAULT_LANG.
    - `get_message` key miss durumunda key adını döner (debug-friendly,
      hiçbir zaman None / raise).
    - `str.format(**params)` çağrısı KeyError/IndexError yakalanıp ham
      mesajla fallback yapılır (placeholder eksikse UI bozulmasın).
"""
from __future__ import annotations

from typing import Literal

Lang = Literal["tr", "en"]
DEFAULT_LANG: Lang = "tr"
SUPPORTED_LANGS: tuple[str, ...] = ("tr", "en")


# Mesaj kataloğu — anahtar adları UPPER_SNAKE (sabit kabul).
# FAZ 5 P34: db_smart_api'nin 5 ana hata noktası için temel set.
# Ek anahtarlar takip eden FAZ 5 sweep'lerinde eklenebilir.
_MESSAGES: dict[str, dict[str, str]] = {
    "ELIGIBILITY_EMPTY": {
        "tr": "Bu tabloya uygun metrik bulunamadı.",
        "en": "No eligible metrics found for this table.",
    },
    "SQL_GUARD_DENY": {
        "tr": "Sorgu güvenlik kontrolüne takıldı.",
        "en": "Query blocked by safety guard.",
    },
    "METRIC_NOT_FOUND": {
        "tr": "Metrik bulunamadı.",
        "en": "Metric not found.",
    },
    "SESSION_NOT_FOUND": {
        "tr": "Oturum bulunamadı veya yetkiniz yok.",
        "en": "Session not found or you don't have access.",
    },
    "SESSION_EXPIRED": {
        "tr": "Oturum süresi doldu.",
        "en": "Session expired.",
    },
    "SESSION_CONFLICT": {
        "tr": "Oturum başka bir cihazda güncellendi.",
        "en": "Session updated by another device.",
    },
    "AST_PATCH_INVALID": {
        "tr": "Geçersiz AST işlemi.",
        "en": "Invalid AST operation.",
    },
    "AST_NOT_INITIALIZED": {
        "tr": "AST henüz oluşturulmadı. Önce wizard'dan ilerleyin.",
        "en": "AST is not initialized yet. Advance the wizard first.",
    },
    "AST_OP_UNKNOWN": {
        "tr": "Bilinmeyen AST op: {op}",
        "en": "Unknown AST op: {op}",
    },
    "RATE_LIMITED": {
        "tr": "Çok fazla istek. Lütfen biraz bekleyin.",
        "en": "Too many requests. Please wait a moment.",
    },
    "SOURCE_NOT_FOUND": {
        "tr": "Veri kaynağı bulunamadı veya erişim yok.",
        "en": "Data source not found or access denied.",
    },
    "USER_UNAUTHENTICATED": {
        "tr": "Kullanıcı kimliği belirlenemedi.",
        "en": "Could not identify user.",
    },
}


def get_message(key: str, lang: str = DEFAULT_LANG, **params: object) -> str:
    """Lokalize edilmiş mesajı döner; bilinmeyen key → key adı (debug)."""
    if key not in _MESSAGES:
        return key
    bundle = _MESSAGES[key]
    msg = bundle.get(lang) or bundle.get(DEFAULT_LANG) or key
    if params:
        try:
            return msg.format(**params)
        except (KeyError, IndexError, ValueError):
            # Placeholder eksik/uyumsuz → format atla, ham mesajı döndür.
            return msg
    return msg


def parse_accept_language(header: str | None) -> str:
    """`Accept-Language` header'ından desteklenen dili tahmin et.

    Basit, RFC-7231 alt kümesi: ilk dil tag'ine bakar; 'en*' → 'en',
    aksi → DEFAULT_LANG. Quality (`;q=…`) sıralaması yok (FAZ 5 sonrası
    iyileştirme — şu an iki dil var, ilk tag yeterli).

    Defansif: None / empty / malformed → DEFAULT_LANG.
    """
    if not header or not isinstance(header, str):
        return DEFAULT_LANG
    try:
        primary = header.split(",")[0].strip().split(";")[0].strip().lower()
    except (AttributeError, IndexError):
        return DEFAULT_LANG
    if not primary:
        return DEFAULT_LANG
    if primary.startswith("en"):
        return "en"
    if primary.startswith("tr"):
        return "tr"
    return DEFAULT_LANG
