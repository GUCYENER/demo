"""VYRA — single source of truth for DB dialect constants.

Three maps lived in three different files before this module landed:
- `db_smart_api._load_source` carried its own `_DIALECT_ALIAS`,
  `_SUPPORTED_DIALECTS`, and (briefly) `_DEFAULT_PORTS`, rebuilt on
  every call.
- `ds_learning_service._get_db_connector` hard-coded `5432` as the
  PostgreSQL default — silently wrong for Oracle/MSSQL/MySQL.
- `data_sources_api._test_database_connection` did the same `5432`
  default.

When the dialect list grows (e.g. clickhouse, db2), the contributor
must remember to update three places — and historically didn't. This
module is the import-once, cite-everywhere fix.
"""
from __future__ import annotations

from typing import Dict, Set

# Engine aliases the wizard / source-create UI may accept; normalized to
# the canonical key the rest of the code matches on.
DIALECT_ALIAS: Dict[str, str] = {
    "postgres": "postgresql",
    "psql": "postgresql",
    "pg": "postgresql",
    "ora": "oracle",
    "oracledb": "oracle",
    "sqlserver": "mssql",
    "sql_server": "mssql",
    "ms_sql": "mssql",
}

# Dialects the SafeSQLExecutor / query_assembler know how to dispatch.
# Anything outside this set falls back to postgresql with a WARN log.
SUPPORTED_DIALECTS: Set[str] = {"postgresql", "oracle", "mssql", "mysql"}

# Canonical TCP port per dialect. Used only when a defensive fallback
# is acceptable (e.g. `_get_db_connector`'s legacy `source.get("port",
# default)` shape). `db_smart_api._load_source` does NOT use this map
# any more — corrupted port values raise a hard 500 with an admin-
# actionable UPDATE statement.
DEFAULT_PORTS: Dict[str, int] = {
    "postgresql": 5432,
    "oracle": 1521,
    "mssql": 1433,
    "mysql": 3306,
}


def normalize_dialect(db_type: str | None) -> str:
    """Return the canonical dialect key, falling back to 'postgresql'.

    Pure function — no logging, no exceptions. Callers that want
    DEBUG/WARN telemetry should add it themselves so the noise floor
    stays predictable.
    """
    raw = (db_type or "").strip().lower()
    canonical = DIALECT_ALIAS.get(raw, raw)
    if canonical not in SUPPORTED_DIALECTS:
        return "postgresql"
    return canonical


def default_port(db_type: str | None) -> int:
    """Canonical port for the dialect; falls back to postgresql's 5432.

    Intended for hot-path defaulting where raising would be inappropriate
    (legacy connector helpers). Strict integrity checks live in
    `db_smart_api._load_source`.
    """
    return DEFAULT_PORTS[normalize_dialect(db_type)]


# v3.37.8 SSOT (code-review wf_1da517ba bulgu #1/#2/#11):
# Kanary placeholder set — kullanıcının kolon adı / placeholder string'lerini
# (örn. literal "host", "port", "db_user") gerçek değer yerine girmesini hem
# yazma yolu Pydantic validator'ları hem de okuma yolu `_load_source` defansif
# guard'ı **aynı kaynaktan** kontrol eder. v3.37.7'de iki ayrı liste tanımlandı
# ve içerikleri DIVERGE oldu (`db_password` write tarafında vardı, read'de yoktu);
# case-sensitivity da divergent idi (write `.lower()`, read raw). Bu modül o
# divergence'i kapatır — tek liste, tek normalize.
HOST_VALUE_CANARIES: "frozenset[str]" = frozenset({
    "host", "port", "db_type", "db_name", "db_user",
    "db_password", "db_password_encrypted", "id",
})


def is_canary_value(v: object) -> bool:
    """True iff `v` is a placeholder/column-name canary string.

    - Non-string / None / whitespace-only → False (boş ayrı handle edilir)
    - Case-insensitive lookup against `HOST_VALUE_CANARIES`.
    """
    if not isinstance(v, str):
        return False
    s = v.strip()
    if not s:
        return False
    return s.lower() in HOST_VALUE_CANARIES
