"""VYRA v3.46.0 — Synthetic Query Error Classification (P3 ops).

FK Loop'un hedef DB'de çalıştırdığı sentetik sorguların başarısızlık nedenini KANONİK bir
kategoriye indirir. `ds_synthetic_query_runs.error_message` ham (4 dialect karışık ORA-/MSSQL/
MySQL/PG mesajları) → ops paneli "neden başarısız" sorusunu sınıf bazında yanıtlayabilsin:

  permission     → yetki yok (grant eksik) — kullanıcı aksiyonu: yetki ver
  not_found      → tablo/kolon yok (keşif bayat / drift) — re-keşif gerekir
  type_mismatch  → tip uyumsuz JOIN/agregat (FK çıkarımı şüpheli) — FK doğrulama
  syntax         → SQL söz dizimi (dialect bug / template hatası) — kod tarafı
  timeout        → sorgu zaman aşımı (büyük tablo / index yok) — perf
  infra          → bağlantı/ağ (DB erişilemez) — geçici, DB sağlığı
  empty          → 0 satır (hata değil; tablo boş) — bilgi
  unknown        → sınıflanamadı (ham mesaja bak)

Saf fonksiyon (DB-erişimsiz, ağır-import'suz). Substring/regex; 4 dialect hata kodları.
`_is_infra_db_error` mantığı deep_think_service'tekiyle uyumlu tutuldu ama bağımsız kopya
(template katmanına servis bağımlılığı sokmamak için).
"""
from __future__ import annotations

from typing import Optional

# Kanonik kategoriler (ds_synthetic_query_runs.error_kind, VARCHAR(24))
EK_PERMISSION = "permission"
EK_NOT_FOUND = "not_found"
EK_TYPE_MISMATCH = "type_mismatch"
EK_SYNTAX = "syntax"
EK_TIMEOUT = "timeout"
EK_INFRA = "infra"
EK_EMPTY = "empty"
EK_UNKNOWN = "unknown"

ERROR_KINDS = (
    EK_PERMISSION, EK_NOT_FOUND, EK_TYPE_MISMATCH, EK_SYNTAX,
    EK_TIMEOUT, EK_INFRA, EK_EMPTY, EK_UNKNOWN,
)

# Boş-sonuç marker'ı (fk_synthetic_generator empty path'te yazar)
_EMPTY_MARKERS = ("empty_result_skipped_learn",)

# Bağlantı/altyapı — en yüksek öncelik (diğer hataları maskeler). 4 dialect + generic.
_INFRA_PATTERNS = (
    "ora-12170", "ora-12541", "ora-12545", "ora-12537", "ora-12514", "ora-12505",
    "ora-03113", "ora-03114", "ora-28547", "tns:", "tns-",
    "dpy-", "dpi-",                                  # python-oracledb
    "could not connect", "connection refused", "connection reset", "connection closed",
    "connection timed out", "no route to host", "network is unreachable",
    "server closed the connection", "terminating connection",
    "communications link failure",                  # MySQL/JDBC
    "can't connect to mysql", "lost connection to mysql server",  # MySQL 2003/2013
    "a network-related or instance-specific error",  # MSSQL
    "target machine actively refused",
)

# Zaman aşımı
_TIMEOUT_PATTERNS = (
    "statement timeout", "canceling statement due to statement timeout",  # PG
    "ora-01013",                                     # Oracle user cancel (timeout)
    "execution timeout expired", "query timeout", "timeout expired",  # MSSQL
    "query execution was interrupted", "max_execution_time",          # MySQL
)

# Yetki / privilege
_PERMISSION_PATTERNS = (
    "permission denied", "must be owner",            # PG
    "ora-01031", "insufficient privileges",          # Oracle
    "the select permission", "permission was denied", "permission denied on",  # MSSQL
    "command denied to user", "access denied for user",  # MySQL 1142/1045
)

# Tablo/kolon/obje yok (bayat keşif / drift)
_NOT_FOUND_PATTERNS = (
    "does not exist", "doesn't exist", "unknown column", "unknown table",  # PG/MySQL
    "ora-00942",                                     # table or view does not exist
    "ora-00904",                                     # invalid identifier (kolon)
    "invalid object name", "invalid column name",    # MSSQL
    "no such table", "no such column",
    # NOT: bare "relation" KALDIRILDI (çok geniş — PG 'relation "x" does not exist' zaten
    # "does not exist" ile yakalanır; "relation" başka mesajlarda da geçer → yanlış sınıflama).
)

# Tip uyumsuz / cast / operator
_TYPE_PATTERNS = (
    "operator does not exist", "cannot be cast", "invalid input syntax for",  # PG
    "ora-00932", "inconsistent datatypes", "ora-01722", "invalid number",     # Oracle
    "conversion failed", "operand type clash",       # MSSQL
    "incorrect integer value", "incorrect decimal value", "truncated incorrect",  # MySQL
    "cannot be applied", "datatype mismatch",
)

# Söz dizimi (dialect mismatch burada yüzeye çıkar)
_SYNTAX_PATTERNS = (
    "syntax error",                                  # PG/MySQL generic
    "ora-00900", "ora-00933", "ora-00936", "ora-00923", "ora-00911",  # Oracle
    "incorrect syntax near", "must be the first statement",            # MSSQL
    "you have an error in your sql syntax",          # MySQL 1064
    "not properly ended", "missing expression", "missing keyword",
)


def _any(text: str, patterns) -> bool:
    return any(p in text for p in patterns)


def classify_synthetic_error(error_message: Optional[str], dialect: Optional[str] = None) -> str:
    """Ham hata mesajını kanonik error_kind'e indir. Sınıflanamazsa 'unknown'.

    Öncelik sırası: empty → infra → timeout → permission → type_mismatch → not_found → syntax.
    (infra/timeout diğerlerini maskeler; permission explicit kodlarla önce; type_mismatch
    not_found'dan ÖNCE — PG "operator does not exist" tip hatasıdır ama generic "does not exist"
    ile not_found'a düşmesin.)
    """
    if not error_message:
        return EK_UNKNOWN
    s = str(error_message).lower().strip()
    if not s:
        return EK_UNKNOWN
    if _any(s, _EMPTY_MARKERS):
        return EK_EMPTY
    if _any(s, _INFRA_PATTERNS):
        return EK_INFRA
    if _any(s, _TIMEOUT_PATTERNS):
        return EK_TIMEOUT
    if _any(s, _PERMISSION_PATTERNS):
        return EK_PERMISSION
    if _any(s, _TYPE_PATTERNS):
        return EK_TYPE_MISMATCH
    if _any(s, _NOT_FOUND_PATTERNS):
        return EK_NOT_FOUND
    if _any(s, _SYNTAX_PATTERNS):
        return EK_SYNTAX
    return EK_UNKNOWN


# Ops paneli için insan-okur açıklama + önerilen aksiyon (TR).
ERROR_KIND_LABELS = {
    EK_PERMISSION: ("Yetki yok", "Kullanıcıya ilgili tablo için SELECT yetkisi verin."),
    EK_NOT_FOUND: ("Tablo/kolon yok", "Şema değişmiş olabilir — kaynağı yeniden keşfedin."),
    EK_TYPE_MISMATCH: ("Tip uyumsuz", "FK çıkarımı şüpheli — ilişkiyi admin doğrulaması ile gözden geçirin."),
    EK_SYNTAX: ("Söz dizimi", "Template/dialect hatası olabilir — geliştirici incelemesi."),
    EK_TIMEOUT: ("Zaman aşımı", "Büyük tablo veya eksik index — sorgu/altyapı performansı."),
    EK_INFRA: ("Bağlantı/altyapı", "DB'ye ulaşılamadı — geçici; birkaç dk sonra tekrar denenir."),
    EK_EMPTY: ("Boş sonuç", "Hata değil — tablo şu an boş, öğretilmedi."),
    EK_UNKNOWN: ("Sınıflanamadı", "Ham hata mesajına bakın."),
}


__all__ = [
    "ERROR_KINDS", "classify_synthetic_error", "ERROR_KIND_LABELS",
    "EK_PERMISSION", "EK_NOT_FOUND", "EK_TYPE_MISMATCH", "EK_SYNTAX",
    "EK_TIMEOUT", "EK_INFRA", "EK_EMPTY", "EK_UNKNOWN",
]
