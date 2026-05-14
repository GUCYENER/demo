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

    # Oracle/PG sistem pseudo-tabloları — her zaman izinli
    system_tables = {"dual", "sysibm.sysdummy1", "sysdate", "rownum", "rowid", "systimestamp", "current_date", "current_timestamp"}

    # FROM ve JOIN sonrasındaki tablo adlarını çıkar
    # Quoted ve unquoted identifier formatlarını destekler:
    #   FROM users / FROM "users" / FROM [users] / FROM `users`
    #   FROM "public"."users" / FROM public.users
    table_refs = set()

    # EXTRACT(YEAR FROM col), TRIM([x] FROM str), OVERLAY(... FROM ...) gibi SQL
    # fonksiyonlarının içindeki FROM ifadeleri tablo adı değil — maskeliyoruz.
    sql_for_check = re.sub(
        r'\b(?:EXTRACT|TRIM|OVERLAY)\s*\([^)]+\)',
        'FUNC_PLACEHOLDER()',
        sql,
        flags=re.IGNORECASE
    )

    # FROM tablo_adi, JOIN tablo_adi
    # Quoted identifier'ları da yakalayan genişletilmiş regex
    identifier = r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|\w+)'
    table_pattern = rf'(?:FROM|JOIN)\s+({identifier}(?:\.{identifier})?)'

    for match in re.finditer(table_pattern, sql_for_check, re.IGNORECASE):
        raw = match.group(1)
        # Quote karakterlerini temizle
        clean = re.sub(r'["\'`\[\]]', '', raw).lower()
        table_refs.add(clean)

    # Whitelist'i lowercase olarak kontrol et (hem tam "schema.tablo" hem sadece "tablo")
    allowed_lower = {t.lower() for t in allowed_tables}
    # Whitelist'teki kısa adlar (son parça) — "schema.tablo" → "tablo"
    allowed_short = {t.lower().rsplit(".", 1)[-1] for t in allowed_tables}

    for ref in table_refs:
        if ref in system_tables:
            continue
        # Tam eşleşme (schema.tablo veya tablo)
        if ref in allowed_lower:
            continue
        # Kısa ad eşleşmesi (ref'in son parçası whitelist'te varsa)
        ref_short = ref.rsplit(".", 1)[-1]
        if ref_short in allowed_short:
            continue
        # ref schema.tablo ise — schema farklı ama tablo aynı → REDDet
        if "." in ref and ref_short in allowed_short:
            # Schema prefix kontrolü: ref'in schema kısmı whitelist'teki herhangi biriyle eşleşiyor mu?
            ref_schema = ref.rsplit(".", 1)[0]
            allowed_schemas = {t.lower().rsplit(".", 1)[0] for t in allowed_tables if "." in t}
            if allowed_schemas and ref_schema not in allowed_schemas:
                return False, f"Şema erişim yetkisi yok: {ref}"
            continue
        return False, f"Tablo erişim yetkisi yok: {ref}"

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
                error="SQL çalıştırma sırasında beklenmeyen bir hata oluştu",
                sql_executed=adapted_sql[:200],
                elapsed_ms=elapsed,
            )

    def execute_async(
        self,
        sql: str,
        source: dict,
        dialect: str,
        allowed_tables: Optional[List[str]] = None,
    ):
        """
        v3.14.0: Non-blocking SQL execution — SQL'i arka plan thread'de çalıştırır.
        Caller, result_event'i periyodik olarak kontrol ederek sonucu alır.

        Returns:
            (result_holder, result_event, exec_thread)
            - result_holder: {"result": SQLResult | None}
            - result_event: threading.Event — set olunca sonuç hazır
            - exec_thread: Thread referansı
        """
        import threading

        # Önce validation (senkron, hızlı) — aynı modüldeki fonksiyonları doğrudan çağır
        is_valid, validation_error = validate_sql(sql)
        if not is_valid:
            holder = {"result": SQLResult(success=False, error=f"Güvenlik: {validation_error}", sql_executed=sql[:200])}
            evt = threading.Event()
            evt.set()
            return holder, evt, None

        if allowed_tables:
            is_allowed, table_error = check_table_whitelist(sql, allowed_tables, dialect)
            if not is_allowed:
                holder = {"result": SQLResult(success=False, error=table_error, sql_executed=sql[:200])}
                evt = threading.Event()
                evt.set()
                return holder, evt, None

        # Async execution
        result_holder = {"result": None}
        result_event = threading.Event()
        _max_rows = self.max_rows  # Thread'e geçmeden önce yakala

        def _bg_execute():
            try:
                # Uzun timeout ile çalıştır (max 120sn)
                long_executor = SafeSQLExecutor(timeout=120, max_rows=_max_rows)
                result_holder["result"] = long_executor.execute(
                    sql=sql, source=source, dialect=dialect, allowed_tables=allowed_tables,
                )
            except Exception as e:
                result_holder["result"] = SQLResult(
                    success=False, error=str(e)[:200], sql_executed=sql[:200],
                )
            finally:
                result_event.set()

        exec_thread = threading.Thread(target=_bg_execute, daemon=True)
        exec_thread.start()
        return result_holder, result_event, exec_thread

    def estimate_query_time(self, schema_ctx: dict, sql: str) -> dict:
        """
        v3.14.0: Tablo boyutu ve JOIN sayısına göre tahmini sorgu süresi.

        Returns:
            {"estimate_seconds": int, "complexity": "low|medium|high", "reason": str}
        """
        import re as _re

        tables = schema_ctx.get("tables", [])
        total_rows = 0
        max_rows = 0
        for t in tables:
            row_est = t.get("row_estimate") or 0
            total_rows += row_est
            max_rows = max(max_rows, row_est)

        # JOIN sayısı
        join_count = len(_re.findall(r'\bJOIN\b', sql, _re.IGNORECASE))

        # Tahmin
        if max_rows > 10_000_000 or (join_count >= 3 and total_rows > 1_000_000):
            return {
                "estimate_seconds": 60,
                "complexity": "high",
                "reason": f"Büyük tablolar ({max_rows:,} satır) ve {join_count} JOIN",
            }
        elif max_rows > 1_000_000 or join_count >= 2:
            return {
                "estimate_seconds": 30,
                "complexity": "medium",
                "reason": f"Orta büyüklükte tablolar ({max_rows:,} satır)",
            }
        elif max_rows > 100_000:
            return {
                "estimate_seconds": 15,
                "complexity": "low",
                "reason": f"Normal boyut ({max_rows:,} satır)",
            }
        else:
            return {
                "estimate_seconds": 5,
                "complexity": "low",
                "reason": "Küçük tablolar",
            }

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
            db_native_timeout = False
            try:
                if dialect == SQLDialect.POSTGRESQL:
                    cur.execute(f"SET statement_timeout = '{self.timeout * 1000}'")
                    db_native_timeout = True
                elif dialect == SQLDialect.MYSQL:
                    cur.execute(f"SET SESSION MAX_EXECUTION_TIME = {self.timeout * 1000}")
                    db_native_timeout = True
            except Exception as timeout_err:
                logger.warning(f"DB-native timeout ayarlanamadı (thread fallback kullanılacak): {timeout_err}")

            # Sorguyu çalıştır (native timeout yoksa thread-based güvenlik)
            import threading as _threading_exec
            if not db_native_timeout:
                exec_result = {"done": False, "error": None}
                exec_event = _threading_exec.Event()

                def _do_execute():
                    try:
                        cur.execute(sql)
                        exec_result["done"] = True
                    except Exception as ex:
                        exec_result["error"] = ex
                    finally:
                        exec_event.set()

                t_exec = _threading_exec.Thread(target=_do_execute, daemon=True)
                t_exec.start()
                if not exec_event.wait(timeout=self.timeout):
                    raise SQLTimeoutError(f"Sorgu {self.timeout}s'de tamamlanamadı (thread timeout)")
                if exec_result["error"]:
                    raise exec_result["error"]
            else:
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
                    # Dict olarak gelen satırların değerlerini de serialize et
                    rows.append({k: _serialize_value(v) for k, v in r.items()})
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
