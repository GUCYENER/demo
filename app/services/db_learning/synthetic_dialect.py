"""VYRA v3.45.0 — Synthetic Template Dialect & Type Helpers (P2).

FK Loop sentetik template motorunun TİP-FARKINDALIK ve ÇOK-DİALEKT ihtiyaçları
için saf (DB-erişimsiz, ağır-import'suz) yardımcılar.

İki sorumluluk:
  1. **Tip sınıflandırma** — ham `data_type` (4 dialect: PG/Oracle/MSSQL/MySQL)
     → kanonik kategori (numeric/temporal/text/boolean/other). `fk_inference_dialects`
     yalnız int/uuid/str/other verir (FK tip-uyumu için); agregasyon TEMPLATE'leri ise
     numeric vs temporal AYRIMINA ihtiyaç duyar (SUM/AVG sayısalda, koşan-toplam sırası
     tarihte). Bu yüzden burada ayrı, agregasyona-uygun sınıflandırma.
  2. **Dialect SQL fonksiyonları** — STRING_AGG/LISTAGG/GROUP_CONCAT, gün-truncate,
     N-gün-önce gibi diyalekt-ayrışan ifadeler (P2b template'leri kullanır).

Kategori token'ları `llm_column_filter_service._semantic_bucket` ile uyumlu tutuldu
(orada da numeric/datetime/categorical sınıfları var) ama burası ham data_type'a göre
çalışır ve template katmanına LLM servis bağımlılığı sokmaz.
"""
from __future__ import annotations

from typing import Optional

# ── Kategoriler ──────────────────────────────────────────────
CAT_NUMERIC = "numeric"
CAT_TEMPORAL = "temporal"
CAT_TEXT = "text"
CAT_BOOLEAN = "boolean"
CAT_OTHER = "other"

# Ham data_type alt-dizgileri (4 dialect, lowercase). Sıra önemli: boolean ve
# temporal, numeric'ten ÖNCE denenir ("timestamp" içinde "time"; "bool" tek başına).
_TEMPORAL_HINTS = (
    "timestamp", "datetime", "date", "time",  # PG/MySQL/MSSQL
    "year",                                     # MySQL YEAR
    # Oracle: DATE (date içinde), TIMESTAMP, INTERVAL
    "interval",
)
_NUMERIC_HINTS = (
    "int",                                      # int/integer/bigint/smallint/tinyint
    "numeric", "number", "decimal", "dec",      # PG numeric, Oracle NUMBER, MSSQL/MySQL decimal
    "real", "double", "float", "money",         # float aileleri + para
    "smallmoney", "fixed",
)
_TEXT_HINTS = (
    "char", "varchar", "varchar2", "nvarchar", "nchar", "text", "clob",
    "string", "enum", "set",                    # MySQL enum/set
    "uuid",                                      # tanımlayıcı ama metin gibi davranır
)


def classify_data_type(raw: Optional[str]) -> str:
    """Ham data_type → kanonik kategori (numeric/temporal/text/boolean/other).

    4 dialect destekli, lowercase substring eşleme. Tanınmayan tip → 'other'
    (template tarafı 'other' kolonu agregasyona sokmaz → güvenli).

    Örn: 'NUMBER(10,2)'→numeric, 'TIMESTAMP(6)'→temporal, 'VARCHAR2(50)'→text,
         'tinyint(1)'→numeric (MySQL bool ayrımı net değil → sayısal kabul),
         'boolean'→boolean, 'bytea'→other.
    """
    if not raw:
        return CAT_OTHER
    s = str(raw).strip().lower()
    if not s:
        return CAT_OTHER
    # boolean önce: PG 'boolean'/'bool', MSSQL 'bit' (TAM eşleşme). 'bit varying'/'varbit'
    # (PG bitstring) boolean DEĞİL → eşleşmez, aşağıda 'other'a düşer (agregasyona girmez).
    if "bool" in s or s == "bit":
        return CAT_BOOLEAN
    # temporal, numeric'ten önce ("timestamp"/"datetime" içinde sayısal token yok ama
    # "interval"/"time" net temporal)
    if any(h in s for h in _TEMPORAL_HINTS):
        return CAT_TEMPORAL
    if any(h in s for h in _NUMERIC_HINTS):
        return CAT_NUMERIC
    if any(h in s for h in _TEXT_HINTS):
        return CAT_TEXT
    return CAT_OTHER


def is_numeric_type(raw: Optional[str]) -> bool:
    return classify_data_type(raw) == CAT_NUMERIC


def is_temporal_type(raw: Optional[str]) -> bool:
    return classify_data_type(raw) == CAT_TEMPORAL


def is_text_type(raw: Optional[str]) -> bool:
    return classify_data_type(raw) == CAT_TEXT


# ── Dialect SQL fonksiyonları (P2b template'leri için) ────────

def string_agg(value_expr: str, order_expr: str, dialect: str, sep: str = " → ") -> str:
    """Satırları tek hücrede birleştir (ordered). 4 dialect:

      PG / MSSQL(2017+): STRING_AGG(value, sep) WITHIN GROUP/ORDER BY
      Oracle:            LISTAGG(value, sep) WITHIN GROUP (ORDER BY ...)
      MySQL:             GROUP_CONCAT(value ORDER BY ... SEPARATOR sep)

    `value_expr`/`order_expr` çağıran tarafça ZATEN tırnaklanmış/alias'lı verilmeli
    (örn. 'd."label"'). `sep` literal — tek-tırnak kaçışı uygulanır (injection-safe).
    """
    d = (dialect or "postgresql").lower()
    qsep = "''".join(sep.split("'"))  # tek tırnak ikile
    if d == "oracle":
        return f"LISTAGG({value_expr}, '{qsep}') WITHIN GROUP (ORDER BY {order_expr})"
    if d == "mysql":
        return f"GROUP_CONCAT({value_expr} ORDER BY {order_expr} SEPARATOR '{qsep}')"
    if d == "mssql":
        # STRING_AGG WITHIN GROUP MSSQL 2017+; ORDER BY WITHIN GROUP
        return f"STRING_AGG({value_expr}, '{qsep}') WITHIN GROUP (ORDER BY {order_expr})"
    # postgresql
    return f"STRING_AGG({value_expr}, '{qsep}' ORDER BY {order_expr})"


def to_day_expr(col_expr: str, dialect: str) -> str:
    """Timestamp/datetime'ı GÜN'e indir (saat at). 4 dialect:

      PG:     (col)::date
      Oracle: TRUNC(col)
      MSSQL:  CAST(col AS date)
      MySQL:  DATE(col)
    """
    d = (dialect or "postgresql").lower()
    if d == "oracle":
        return f"TRUNC({col_expr})"
    if d == "mssql":
        return f"CAST({col_expr} AS date)"
    if d == "mysql":
        return f"DATE({col_expr})"
    return f"({col_expr})::date"


def current_date_expr(dialect: str) -> str:
    """Bugünün tarihi (saatsiz). PG/MySQL: CURRENT_DATE; Oracle: TRUNC(SYSDATE);
    MSSQL: CAST(GETDATE() AS date)."""
    d = (dialect or "postgresql").lower()
    if d == "oracle":
        return "TRUNC(SYSDATE)"
    if d == "mssql":
        return "CAST(GETDATE() AS date)"
    return "CURRENT_DATE"


__all__ = [
    "CAT_NUMERIC", "CAT_TEMPORAL", "CAT_TEXT", "CAT_BOOLEAN", "CAT_OTHER",
    "classify_data_type", "is_numeric_type", "is_temporal_type", "is_text_type",
    "string_agg", "to_day_expr", "current_date_expr",
]
