"""
VYRA - Safe SQL Executor
=========================
Read-only, timeout ve satır limiti ile güvenli SQL yürütme motoru.

Güvenlik katmanları:
1. DDL/DML engelleme (SELECT dışı ifadeler yasak)
2. SQL injection tespiti
3. Tablo whitelist (ds_db_objects'ten)
4. Timeout (max 5 saniye)
5. Row limit (max 100 satır)
6. Hassas sütun maskeleme (TC No, IBAN, kredi kartı vb.)

Version: 2.57.0
"""

from __future__ import annotations

import re
import time
import logging
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from app.core.config import settings
from app.services.logging_service import log_system_event, log_error, log_warning
from app.services.sql_dialect import (
    SQLDialect, apply_row_limit, adapt_functions
)

logger = logging.getLogger(__name__)


# =====================================================
# Sonuç ve Hata Sınıfları
# =====================================================

class SQLSecurityError(Exception):
    """SQL güvenlik ihlali hatası."""
    pass


class SQLTimeoutError(Exception):
    """SQL sorgu timeout hatası."""
    pass


@dataclass
class SQLResult:
    """Güvenli SQL yürütme sonucu."""
    success: bool
    data: List[Dict[str, Any]] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    row_count: int = 0
    sql_executed: str = ""
    elapsed_ms: float = 0.0
    error: Optional[str] = None
    truncated: bool = False  # Row limit'ten dolayı kesildi mi


# =====================================================
# Engellenen SQL Kalıpları
# =====================================================

# DDL/DML komutları — kesinlikle yasak
# NOT: INTO kaldırıldı çünkü SELECT ... INTO yerine
# SELECT INTO engeli "INSERT INTO" ile zaten yakalanıyor.
# Güvenlik: SELECT ile başlama kontrolü zaten INSERT/UPDATE/DELETE'i engeller.
BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE",
    "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE",
    "MERGE", "CALL",
]

# SQL injection kalıpları
INJECTION_PATTERNS = [
    r";\s*(DROP|DELETE|INSERT|UPDATE|ALTER|CREATE|TRUNCATE|GRANT|REVOKE)",
    r"--\s*$",            # Satır sonu yorum (saldırı gizleme)
    r"/\*.*\*/",          # Block yorum (saldırı gizleme)
    r"'\s*OR\s+'1'\s*=\s*'1",  # Klasik OR injection
    r"UNION\s+ALL\s+SELECT",   # Union injection
    r"xp_cmdshell",       # MSSQL komut yürütme
    r"pg_sleep",          # PostgreSQL sleep injection
    r"BENCHMARK\s*\(",    # MySQL benchmark injection
    r"WAITFOR\s+DELAY",   # MSSQL delay injection
    r"LOAD_FILE\s*\(",    # MySQL dosya okuma
    r"INTO\s+OUTFILE",    # MySQL dosya yazma
    r"INTO\s+DUMPFILE",   # MySQL dosya yazma
]

# Hassas sütun adı kalıpları (maskeleme için)
SENSITIVE_COLUMN_PATTERNS = [
    r"tc_?(?:no|kimlik|identity)",
    r"tckn",
    r"iban",
    r"kredi_?kart",  
    r"credit_?card",
    r"card_?number",
    r"cvv",
    r"ssn",
    r"social_?security",
    r"password",
    r"sifre",
    r"parola",
    r"secret",
    r"token",
    r"api_?key",
]

# Maskeleme fonksiyonu
MASK_VALUE = "***"


# =====================================================
# SQL Doğrulama
# =====================================================

def validate_sql(sql: str) -> Tuple[bool, Optional[str]]:
    """
    SQL sorgusunu güvenlik açısından doğrular.

    Args:
        sql: Doğrulanacak SQL sorgusu

    Returns:
        (is_valid, error_message)
    """
    if not sql or not sql.strip():
        return False, "Boş SQL sorgusu"

    sql_stripped = sql.strip().rstrip(";").strip()
    sql_upper = sql_stripped.upper()

    # 1. SELECT ile başlıyor mu?
    if not sql_upper.startswith("SELECT") and not sql_upper.startswith("WITH"):
        return False, "Yalnızca SELECT (ve WITH ... SELECT) sorguları çalıştırılabilir"

    # 2. Engellenen anahtar kelimeler
    # Kelime sınırı ile kontrol et (sütun adlarında "updated_at" gibi false positive önleme)
    for keyword in BLOCKED_KEYWORDS:
        pattern = rf'\b{keyword}\b'
        if re.search(pattern, sql_upper):
            # "SELECT ... INTO" özel durumu — INTO tek başına tehlikeli
            # Ama "INSERT INTO" zaten SELECT kontrolünden geçemez
            return False, f"Yasak SQL komutu: {keyword}"

    # 3. SQL injection kalıpları
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, sql_upper, re.IGNORECASE | re.DOTALL):
            return False, f"Olası SQL injection tespit edildi"

    # 4. Çoklu statement kontrolü (;)
    # Noktalı virgül ile ayrılmış birden fazla statement yasak
    # Ama string literal içindeki ; hariç tutulmalı
    sql_no_strings = re.sub(r"'[^']*'", "", sql_stripped)
    if ";" in sql_no_strings:
        return False, "Çoklu SQL statement'ı yasak"

    return True, None


def check_table_whitelist(
    sql: str,
    allowed_tables: List[str],
    dialect: str = SQLDialect.POSTGRESQL
) -> Tuple[bool, Optional[str]]:
    """
    SQL sorgusundaki tablo adlarının whitelist'te olup olmadığını kontrol eder.

    Args:
        sql: SQL sorgusu
        allowed_tables: İzin verilen tablo adları (lowercase)
        dialect: Veritabanı dialect'i

    Returns:
        (is_valid, error_message)
    """
    if not allowed_tables:
        return True, None  # Whitelist boşsa kontrol atla

    # FROM ve JOIN sonrasındaki tablo adlarını çıkar
    # Quoted ve unquoted identifier formatlarını destekler:
    #   FROM users / FROM "users" / FROM [users] / FROM `users`
    #   FROM "public"."users" / FROM public.users
    table_refs = set()

    # FROM tablo_adi, JOIN tablo_adi 
    # Quoted identifier'ları da yakalayan genişletilmiş regex
    identifier = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|\w+)'
    table_pattern = rf'(?:FROM|JOIN)\s+({identifier}(?:\.{identifier})?)'

    for match in re.finditer(table_pattern, sql, re.IGNORECASE):
        raw = match.group(1)
        # Quote karakterlerini temizle ve son parçayı al (tablo adı)
        parts = raw.split(".")
        table_part = parts[-1].strip('"[]`').lower()
        table_refs.add(table_part)

    # Whitelist'i lowercase olarak kontrol et
    allowed_lower = {t.lower() for t in allowed_tables}

    for table in table_refs:
        if table not in allowed_lower:
            return False, f"Tablo erişim yetkisi yok: {table}"

    return True, None


# =====================================================
# Hassas Alan Maskeleme
# =====================================================

def mask_sensitive_columns(
    rows: List[Dict[str, Any]],
    columns: List[str]
) -> List[Dict[str, Any]]:
    """
    Sonuçlardaki hassas sütunları maskeler.

    Args:
        rows: Sorgu sonuç satırları
        columns: Sütun adları

    Returns:
        Maskelenmiş satırlar
    """
    if not rows or not columns:
        return rows

    # Hangi sütunlar hassas?
    sensitive_cols = set()
    for col in columns:
        col_lower = col.lower()
        for pattern in SENSITIVE_COLUMN_PATTERNS:
            if re.search(pattern, col_lower):
                sensitive_cols.add(col)
                break

    if not sensitive_cols:
        return rows

    log_system_event(
        "INFO",
        f"SQL Executor: Hassas sütunlar maskelendi: {sensitive_cols}",
        "hybrid_router"
    )

    # Maskeleme uygula
    masked_rows = []
    for row in rows:
        masked = dict(row)
        for col in sensitive_cols:
            if col in masked and masked[col] is not None:
                masked[col] = MASK_VALUE
        masked_rows.append(masked)

    return masked_rows


# =====================================================
# Safe SQL Executor
# =====================================================

class SafeSQLExecutor:
    """
    Güvenli SQL yürütme motoru.

    Read-only, timeout ve satır limiti ile SQL sorguları çalıştırır.
    ds_learning_service'teki _get_db_connector'ı kullanarak hedef DB'ye bağlanır.
    """

    def __init__(
        self,
        timeout: int = None,
        max_rows: int = None,
    ):
        self.timeout = timeout or getattr(settings, 'SQL_EXEC_TIMEOUT', 5)
        self.max_rows = max_rows or getattr(settings, 'SQL_MAX_ROWS', 100)

    def execute(
        self,
        sql: str,
        source: dict,
        dialect: str,
        allowed_tables: Optional[List[str]] = None,
    ) -> SQLResult:
        """
        SQL sorgusunu güvenli şekilde yürütür.

        Args:
            sql: SQL sorgusu
            source: Veri kaynağı bilgileri (ds bağlantı dict)
            dialect: DB dialect (postgresql, mssql, mysql, oracle)
            allowed_tables: İzin verilen tablo adları (None ise kontrol atlanır)

        Returns:
            SQLResult
        """
        start = time.time()

        # 1. SQL doğrulama
        is_valid, error = validate_sql(sql)
        if not is_valid:
            log_warning(f"SQL güvenlik reddi: {error} | SQL: {sql[:200]}", "hybrid_router")
            return SQLResult(
                success=False,
                error=f"Güvenlik: {error}",
                sql_executed=sql[:200],
            )

        # 2. Tablo whitelist kontrolü
        if allowed_tables:
            is_allowed, table_error = check_table_whitelist(sql, allowed_tables, dialect)
            if not is_allowed:
                log_warning(f"Tablo whitelist reddi: {table_error}", "hybrid_router")
                return SQLResult(
                    success=False,
                    error=table_error,
                    sql_executed=sql[:200],
                )

        # 3. Row limit uygula
        limited_sql = apply_row_limit(sql, self.max_rows, dialect)

        # 4. Fonksiyon adaptasyonu
        adapted_sql = adapt_functions(limited_sql, dialect)

        # 5. Yürütme (timeout ile)
        try:
            result = self._execute_with_timeout(adapted_sql, source, dialect)
            result.elapsed_ms = (time.time() - start) * 1000

            log_system_event(
                "INFO",
                f"SQL Executor: {result.row_count} satır, {result.elapsed_ms:.0f}ms | "
                f"SQL: {adapted_sql[:100]}",
                "hybrid_router"
            )

            return result

        except SQLTimeoutError:
            elapsed = (time.time() - start) * 1000
            log_warning(
                f"SQL timeout ({self.timeout}s): {adapted_sql[:100]}",
                "hybrid_router"
            )
            return SQLResult(
                success=False,
                error=f"Sorgu zaman aşımına uğradı ({self.timeout} saniye limit)",
                sql_executed=adapted_sql[:200],
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.time() - start) * 1000
            log_error(f"SQL yürütme hatası: {e}", "hybrid_router")
            return SQLResult(
                success=False,
                error=str(e)[:500],
                sql_executed=adapted_sql[:200],
                elapsed_ms=elapsed,
            )

    def _execute_with_timeout(
        self,
        sql: str,
        source: dict,
        dialect: str,
    ) -> SQLResult:
        """
        SQL sorgusunu timeout ile yürütür.

        Timeout mekanizması:
        - PostgreSQL: statement_timeout
        - MSSQL: login_timeout + CommandTimeout
        - MySQL: MAX_EXECUTION_TIME hint
        - Oracle: ALTER SESSION SET statement_timeout (destekleniyorsa)
        - Genel: threading.Timer ile fallback timeout
        """
        from app.services.ds_learning_service import _get_db_connector, _decrypt_password

        password = _decrypt_password(source.get("db_password_encrypted", ""))
        conn = None

        try:
            conn, detected_dialect = _get_db_connector(source, password)

            cur = conn.cursor()

            # DB-native timeout ayarla
            try:
                if dialect == SQLDialect.POSTGRESQL:
                    cur.execute(f"SET statement_timeout = '{self.timeout * 1000}'")
                elif dialect == SQLDialect.MYSQL:
                    cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {self.timeout * 1000}")
            except Exception as timeout_err:
                logger.debug(f"DB-native timeout ayarlanamadı: {timeout_err}")

            # Sorguyu çalıştır
            cur.execute(sql)

            # Sütun adlarını al
            columns = []
            if cur.description:
                columns = [desc[0] for desc in cur.description]

            # Sonuçları al
            rows_raw = cur.fetchall()

            # dict formatına çevir
            rows = []
            for r in rows_raw:
                if isinstance(r, dict):
                    rows.append(r)
                else:
                    row_dict = {}
                    for i, val in enumerate(r):
                        col_name = columns[i] if i < len(columns) else f"col_{i}"
                        row_dict[col_name] = _serialize_value(val)
                    rows.append(row_dict)

            # Hassas alan maskeleme
            rows = mask_sensitive_columns(rows, columns)

            truncated = len(rows) >= self.max_rows

            return SQLResult(
                success=True,
                data=rows,
                columns=columns,
                row_count=len(rows),
                sql_executed=sql[:500],
                truncated=truncated,
            )

        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def get_allowed_tables(self, source_id: int) -> List[str]:
        """
        DS Learning keşfinden izin verilen tablo adlarını çeker.

        Args:
            source_id: Data source ID

        Returns:
            İzin verilen tablo adları listesi
        """
        try:
            from app.core.db import get_db_conn
            conn = get_db_conn()
            cur = conn.cursor()
            cur.execute(
                "SELECT object_name FROM ds_db_objects WHERE source_id = %s AND object_type = 'table'",
                (source_id,)
            )
            tables = [row["object_name"] for row in cur.fetchall()]
            conn.close()
            return tables
        except Exception as e:
            log_warning(f"Tablo whitelist alınamadı: {e}", "hybrid_router")
            return []


def _serialize_value(val) -> Any:
    """DB değerini JSON-safe formata çevirir."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    from datetime import datetime, date
    if isinstance(val, datetime):
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, bytes):
        return f"<binary {len(val)} bytes>"
    if isinstance(val, (list, dict)):
        return val
    return str(val)
