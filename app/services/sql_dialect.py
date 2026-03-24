"""
VYRA - SQL Dialect Adapter & Template Queries
==============================================
Çoklu veritabanı desteği için SQL dialect dönüşüm katmanı.

Desteklenen DB'ler:
- PostgreSQL (psycopg2)
- MSSQL (pymssql)
- MySQL (pymysql)
- Oracle (cx_Oracle / oracledb)

Version: 2.57.0
"""

from __future__ import annotations

import re
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# =====================================================
# Dialect Sabitleri
# =====================================================

class SQLDialect:
    """SQL Dialect bilgi sınıfı."""
    POSTGRESQL = "postgresql"
    MSSQL = "mssql"
    MYSQL = "mysql"
    ORACLE = "oracle"

    SUPPORTED = {POSTGRESQL, MSSQL, MYSQL, ORACLE}


# =====================================================
# Row Limit Adaptasyonu
# =====================================================

def apply_row_limit(sql: str, limit: int, dialect: str) -> str:
    """
    SQL sorgusuna dialect-uygun row limit ekler.

    PostgreSQL / MySQL: ... LIMIT N
    MSSQL:              SELECT TOP N ...
    Oracle:             ... FETCH FIRST N ROWS ONLY

    Eğer sorguda zaten LIMIT/TOP varsa dokunulmaz.

    Args:
        sql: Orijinal SQL sorgusu
        limit: Maksimum satır sayısı
        dialect: Veritabanı dialect'i

    Returns:
        Limit uygulanmış SQL
    """
    if not sql or limit <= 0:
        return sql

    sql_upper = sql.upper().strip()

    # Zaten limit var mı kontrol et
    if dialect in (SQLDialect.POSTGRESQL, SQLDialect.MYSQL):
        if re.search(r'\bLIMIT\s+\d+', sql_upper):
            return sql
        return f"{sql.rstrip().rstrip(';')} LIMIT {limit}"

    elif dialect == SQLDialect.MSSQL:
        if re.search(r'\bTOP\s+\d+', sql_upper):
            return sql
        # SELECT kelimesinden sonra TOP N ekle
        return re.sub(
            r'(?i)^(\s*SELECT\s+)',
            rf'\1TOP {limit} ',
            sql,
            count=1
        )

    elif dialect == SQLDialect.ORACLE:
        if re.search(r'\bFETCH\s+FIRST\b', sql_upper) or re.search(r'\bROWNUM\b', sql_upper):
            return sql
        return f"{sql.rstrip().rstrip(';')} FETCH FIRST {limit} ROWS ONLY"

    # Bilinmeyen dialect → PostgreSQL varsayalım
    return f"{sql.rstrip().rstrip(';')} LIMIT {limit}"


# =====================================================
# Fonksiyon Adaptasyonu
# =====================================================

_FUNCTION_MAP: Dict[str, Dict[str, str]] = {
    "NOW()": {
        SQLDialect.POSTGRESQL: "NOW()",
        SQLDialect.MSSQL: "GETDATE()",
        SQLDialect.MYSQL: "NOW()",
        SQLDialect.ORACLE: "SYSDATE",
    },
    "CURRENT_DATE": {
        SQLDialect.POSTGRESQL: "CURRENT_DATE",
        SQLDialect.MSSQL: "CAST(GETDATE() AS DATE)",
        SQLDialect.MYSQL: "CURDATE()",
        SQLDialect.ORACLE: "TRUNC(SYSDATE)",
    },
    "TRUE": {
        SQLDialect.POSTGRESQL: "TRUE",
        SQLDialect.MSSQL: "1",
        SQLDialect.MYSQL: "TRUE",
        SQLDialect.ORACLE: "1",
    },
    "FALSE": {
        SQLDialect.POSTGRESQL: "FALSE",
        SQLDialect.MSSQL: "0",
        SQLDialect.MYSQL: "FALSE",
        SQLDialect.ORACLE: "0",
    },
}


def adapt_functions(sql: str, dialect: str) -> str:
    """
    SQL içindeki standart fonksiyonları hedef dialect'e dönüştürür.

    Args:
        sql: Orijinal SQL
        dialect: Hedef dialect

    Returns:
        Dönüştürülmüş SQL
    """
    if dialect not in SQLDialect.SUPPORTED:
        return sql

    result = sql
    for generic_func, dialect_map in _FUNCTION_MAP.items():
        target = dialect_map.get(dialect, generic_func)
        if generic_func != target:
            result = re.sub(
                re.escape(generic_func),
                target,
                result,
                flags=re.IGNORECASE
            )

    return result


# =====================================================
# Tablo Adı Quoting
# =====================================================

def quote_identifier(name: str, dialect: str) -> str:
    """
    Tablo/sütun adını dialect'e uygun şekilde quote eder.

    PostgreSQL: "name"
    MSSQL: [name]
    MySQL: `name`
    Oracle: "name"
    """
    # Tehlikeli karakterler varsa reddet
    if any(c in name for c in (';', '--', '/*', '*/', '\x00')):
        raise ValueError(f"Geçersiz tanımlayıcı adı: {name}")

    if dialect == SQLDialect.MSSQL:
        return f"[{name}]"
    elif dialect == SQLDialect.MYSQL:
        return f"`{name}`"
    else:
        return f'"{name}"'


def quote_table(schema: Optional[str], table: str, dialect: str) -> str:
    """
    Schema.table formatında tam nitelikli tablo adı üretir.

    Args:
        schema: Şema adı (None olabilir)
        table: Tablo adı
        dialect: Hedef dialect

    Returns:
        Quoted full-qualified table name
    """
    quoted_table = quote_identifier(table, dialect)
    if schema:
        quoted_schema = quote_identifier(schema, dialect)
        return f"{quoted_schema}.{quoted_table}"
    return quoted_table


# =====================================================
# Template SQL Sorguları
# =====================================================

TEMPLATE_QUERIES = {
    "row_count": "SELECT COUNT(*) AS total FROM {table}",
    "latest_records": "SELECT * FROM {table} ORDER BY {date_col} DESC",
    "sum_column": "SELECT SUM({col}) AS total FROM {table}",
    "avg_column": "SELECT AVG({col}) AS average FROM {table}",
    "min_column": "SELECT MIN({col}) AS minimum FROM {table}",
    "max_column": "SELECT MAX({col}) AS maximum FROM {table}",
    "distinct_count": "SELECT COUNT(DISTINCT {col}) AS unique_count FROM {table}",
    "distinct_values": "SELECT DISTINCT {col} FROM {table} ORDER BY {col}",
    "group_count": "SELECT {col}, COUNT(*) AS cnt FROM {table} GROUP BY {col} ORDER BY cnt DESC",
}


def build_template_sql(
    template_name: str,
    table: str,
    dialect: str,
    schema: Optional[str] = None,
    col: Optional[str] = None,
    date_col: Optional[str] = None,
    row_limit: int = 100,
) -> Optional[str]:
    """
    Template adına göre SQL sorgusu üretir ve dialect'e uyarlar.

    Args:
        template_name: Template key (row_count, latest_records, vb.)
        table: Tablo adı
        dialect: Hedef dialect
        schema: Opsiyonel şema adı
        col: Opsiyonel sütun adı (aggregate template'ler için)
        date_col: Opsiyonel tarih sütunu (latest_records için)
        row_limit: Row limit (varsayılan 100)

    Returns:
        Üretilmiş SQL sorgusu veya None (template bulunamadıysa)
    """
    template = TEMPLATE_QUERIES.get(template_name)
    if not template:
        logger.warning(f"Bilinmeyen SQL template: {template_name}")
        return None

    # Tablo adını quote et
    fqn = quote_table(schema, table, dialect)

    # Template'i doldur
    sql = template.replace("{table}", fqn)

    if col:
        quoted_col = quote_identifier(col, dialect)
        sql = sql.replace("{col}", quoted_col)

    if date_col:
        quoted_date = quote_identifier(date_col, dialect)
        sql = sql.replace("{date_col}", quoted_date)

    # Fonksiyon adaptasyonu
    sql = adapt_functions(sql, dialect)

    # Row limit uygula
    sql = apply_row_limit(sql, row_limit, dialect)

    return sql
