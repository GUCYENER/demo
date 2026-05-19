"""v3.29.9 — FK Inference Dialect Adapters.

Multi-dialect identifier handling, type normalization, sample validation
query construction. Each adapter encapsulates the dialect-specific quirks
so the core service `fk_inference_service` stays generic.

Supported dialects:
    - PostgreSQL  (case-folding: lower)
    - Oracle      (case-folding: UPPER, NUMBER variants)
    - MSSQL       (case-folding: collation-aware, default CI)
    - MySQL       (case-folding: config-aware, default CI on Win/Mac)

Each adapter implements `FKInferenceDialect` Protocol:
    - name (str)
    - normalize_ident(s) -> str
    - quote_ident(s) -> str
    - normalize_type(raw_type) -> str  (canonical category)
    - statement_timeout_ms() -> int | None
    - build_sample_validate_sql(from_t, from_c, to_t, to_c) -> tuple[str, sequence]
        Returns SQL+params such that the row is (distinct_from, covered).

SECURITY: Identifiers passed to build_* methods MUST be validated by the
caller using `_is_safe_identifier` from fk_inference_service.
"""
from __future__ import annotations

import re
from typing import Optional, Protocol, Sequence, Tuple


# Canonical type categories used by `_type_compatible` in core service.
TYPE_CAT_INT = "int"
TYPE_CAT_UUID = "uuid"
TYPE_CAT_STR = "str"
TYPE_CAT_OTHER = "other"


class FKInferenceDialect(Protocol):
    name: str

    def normalize_ident(self, s: str) -> str: ...

    def quote_ident(self, s: str) -> str: ...

    def normalize_type(self, raw_type: str) -> str: ...

    def statement_timeout_ms(self) -> Optional[int]: ...

    def build_sample_validate_sql(
        self,
        from_schema: str,
        from_table: str,
        from_column: str,
        to_schema: str,
        to_table: str,
        to_column: str,
        sample_rows: int,
    ) -> Tuple[str, Sequence]: ...


# ─────────────────────────────────────────────────────────────
# PostgreSQL
# ─────────────────────────────────────────────────────────────
class PostgresDialect:
    name = "postgresql"

    def normalize_ident(self, s: str) -> str:
        if s is None:
            return ""
        # PG folds unquoted identifiers to lower; we mirror that.
        return s.strip().lower()

    def quote_ident(self, s: str) -> str:
        # Caller MUST validate s via _is_safe_identifier first.
        return '"' + s.replace('"', '""') + '"'

    def normalize_type(self, raw_type: str) -> str:
        if not raw_type:
            return TYPE_CAT_OTHER
        t = raw_type.strip().lower()
        if t in ("smallint", "integer", "int", "int2", "int4", "int8", "bigint", "serial", "bigserial", "smallserial"):
            return TYPE_CAT_INT
        if t in ("uuid",):
            return TYPE_CAT_UUID
        if t.startswith(("character varying", "varchar", "char", "text", "citext")):
            return TYPE_CAT_STR
        return TYPE_CAT_OTHER

    def statement_timeout_ms(self) -> Optional[int]:
        return 3000  # SET LOCAL statement_timeout='3s' applied by caller

    def build_sample_validate_sql(
        self,
        from_schema: str,
        from_table: str,
        from_column: str,
        to_schema: str,
        to_table: str,
        to_column: str,
        sample_rows: int,
    ) -> Tuple[str, Sequence]:
        fs = self.quote_ident(from_schema)
        ft = self.quote_ident(from_table)
        fc = self.quote_ident(from_column)
        ts = self.quote_ident(to_schema)
        tt = self.quote_ident(to_table)
        tc = self.quote_ident(to_column)
        # COUNT distinct FK values vs how many of them exist in target.
        # Uses LIMIT in a CTE for bounded scan.
        sql = (
            f"WITH s AS ("
            f"  SELECT DISTINCT {fc} AS v FROM {fs}.{ft} "
            f"  WHERE {fc} IS NOT NULL LIMIT %s"
            f") "
            f"SELECT COUNT(*) AS distinct_from, "
            f"       COUNT(t.{tc}) AS covered "
            f"  FROM s LEFT JOIN {ts}.{tt} t ON t.{tc} = s.v"
        )
        return sql, (sample_rows,)


# ─────────────────────────────────────────────────────────────
# Oracle
# ─────────────────────────────────────────────────────────────
class OracleDialect:
    name = "oracle"

    def normalize_ident(self, s: str) -> str:
        if s is None:
            return ""
        # Oracle folds unquoted identifiers to UPPER.
        return s.strip().upper()

    def quote_ident(self, s: str) -> str:
        return '"' + s.replace('"', '""') + '"'

    def normalize_type(self, raw_type: str) -> str:
        if not raw_type:
            return TYPE_CAT_OTHER
        t = raw_type.strip().upper()
        # Oracle has NUMBER, NUMBER(p), NUMBER(p,0) for integer-likes.
        if t.startswith("NUMBER") or t in ("INTEGER", "INT", "SMALLINT", "PLS_INTEGER", "BINARY_INTEGER"):
            return TYPE_CAT_INT
        if t in ("RAW", "RAW(16)") or t == "UUID":
            return TYPE_CAT_UUID
        if t.startswith(("VARCHAR", "NVARCHAR", "CHAR", "NCHAR", "CLOB", "NCLOB")):
            return TYPE_CAT_STR
        return TYPE_CAT_OTHER

    def statement_timeout_ms(self) -> Optional[int]:
        # Oracle doesn't have a session-level statement_timeout equivalent
        # to PG. Caller should rely on connect-level call_timeout instead.
        return None

    def build_sample_validate_sql(
        self,
        from_schema: str,
        from_table: str,
        from_column: str,
        to_schema: str,
        to_table: str,
        to_column: str,
        sample_rows: int,
    ) -> Tuple[str, Sequence]:
        fs = self.quote_ident(from_schema)
        ft = self.quote_ident(from_table)
        fc = self.quote_ident(from_column)
        ts = self.quote_ident(to_schema)
        tt = self.quote_ident(to_table)
        tc = self.quote_ident(to_column)
        # Oracle: ROWNUM for LIMIT. Use bind variable :1.
        sql = (
            f"WITH s AS ("
            f"  SELECT v FROM ("
            f"    SELECT DISTINCT {fc} AS v FROM {fs}.{ft} WHERE {fc} IS NOT NULL"
            f"  ) WHERE ROWNUM <= :1"
            f") "
            f"SELECT COUNT(*) AS distinct_from, "
            f"       COUNT(t.{tc}) AS covered "
            f"  FROM s LEFT JOIN {ts}.{tt} t ON t.{tc} = s.v"
        )
        return sql, (sample_rows,)


# ─────────────────────────────────────────────────────────────
# MSSQL
# ─────────────────────────────────────────────────────────────
class MSSQLDialect:
    name = "mssql"

    def normalize_ident(self, s: str) -> str:
        if s is None:
            return ""
        # Default SQL Server collation is case-insensitive (CI). We lowercase
        # for matching but the actual quoted identifier retains original case.
        return s.strip().lower()

    def quote_ident(self, s: str) -> str:
        # Bracket-quoted; escape closing bracket per T-SQL rules.
        return "[" + s.replace("]", "]]") + "]"

    def normalize_type(self, raw_type: str) -> str:
        if not raw_type:
            return TYPE_CAT_OTHER
        t = raw_type.strip().lower()
        if t in ("tinyint", "smallint", "int", "bigint"):
            return TYPE_CAT_INT
        if t in ("uniqueidentifier",):
            return TYPE_CAT_UUID
        if t.startswith(("varchar", "nvarchar", "char", "nchar", "text", "ntext")):
            return TYPE_CAT_STR
        return TYPE_CAT_OTHER

    def statement_timeout_ms(self) -> Optional[int]:
        return 3000  # SET LOCK_TIMEOUT / query hint applied by caller

    def build_sample_validate_sql(
        self,
        from_schema: str,
        from_table: str,
        from_column: str,
        to_schema: str,
        to_table: str,
        to_column: str,
        sample_rows: int,
    ) -> Tuple[str, Sequence]:
        fs = self.quote_ident(from_schema)
        ft = self.quote_ident(from_table)
        fc = self.quote_ident(from_column)
        ts = self.quote_ident(to_schema)
        tt = self.quote_ident(to_table)
        tc = self.quote_ident(to_column)
        # T-SQL: TOP N inside a derived table.
        sql = (
            f"WITH s AS ("
            f"  SELECT TOP (?) v FROM ("
            f"    SELECT DISTINCT {fc} AS v FROM {fs}.{ft} WHERE {fc} IS NOT NULL"
            f"  ) d"
            f") "
            f"SELECT COUNT(*) AS distinct_from, "
            f"       COUNT(t.{tc}) AS covered "
            f"  FROM s LEFT JOIN {ts}.{tt} t ON t.{tc} = s.v"
        )
        return sql, (sample_rows,)


# ─────────────────────────────────────────────────────────────
# MySQL / MariaDB
# ─────────────────────────────────────────────────────────────
class MySQLDialect:
    name = "mysql"

    def normalize_ident(self, s: str) -> str:
        if s is None:
            return ""
        # MySQL identifier case sensitivity depends on lower_case_table_names.
        # Default on Linux: 0 (case-sensitive), on Win/Mac: 1 (CI, stored lower).
        # We lowercase for matching — slight over-match on Linux is acceptable
        # since FK candidate evaluation is followed by sample validation.
        return s.strip().lower()

    def quote_ident(self, s: str) -> str:
        # Backtick-quoted; escape backtick by doubling.
        return "`" + s.replace("`", "``") + "`"

    def normalize_type(self, raw_type: str) -> str:
        if not raw_type:
            return TYPE_CAT_OTHER
        t = raw_type.strip().lower()
        if t in ("tinyint", "smallint", "mediumint", "int", "integer", "bigint"):
            return TYPE_CAT_INT
        if t in ("uuid",) or t == "binary(16)":
            return TYPE_CAT_UUID
        if t.startswith(("varchar", "char", "text", "tinytext", "mediumtext", "longtext")):
            return TYPE_CAT_STR
        return TYPE_CAT_OTHER

    def statement_timeout_ms(self) -> Optional[int]:
        # MySQL 5.7.8+ supports MAX_EXECUTION_TIME hint (ms); set via caller.
        return 3000

    def build_sample_validate_sql(
        self,
        from_schema: str,
        from_table: str,
        from_column: str,
        to_schema: str,
        to_table: str,
        to_column: str,
        sample_rows: int,
    ) -> Tuple[str, Sequence]:
        fs = self.quote_ident(from_schema)
        ft = self.quote_ident(from_table)
        fc = self.quote_ident(from_column)
        ts = self.quote_ident(to_schema)
        tt = self.quote_ident(to_table)
        tc = self.quote_ident(to_column)
        # MySQL: LIMIT inside a subquery.
        sql = (
            f"WITH s AS ("
            f"  SELECT v FROM ("
            f"    SELECT DISTINCT {fc} AS v FROM {fs}.{ft} WHERE {fc} IS NOT NULL"
            f"  ) d LIMIT %s"
            f") "
            f"SELECT COUNT(*) AS distinct_from, "
            f"       COUNT(t.{tc}) AS covered "
            f"  FROM s LEFT JOIN {ts}.{tt} t ON t.{tc} = s.v"
        )
        return sql, (sample_rows,)


# ─────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────
_REGISTRY = {
    "postgresql": PostgresDialect,
    "postgres": PostgresDialect,
    "pg": PostgresDialect,
    "oracle": OracleDialect,
    "ora": OracleDialect,
    "mssql": MSSQLDialect,
    "sqlserver": MSSQLDialect,
    "mysql": MySQLDialect,
    "mariadb": MySQLDialect,
}


def get_dialect(name: str) -> FKInferenceDialect:
    """Return adapter for dialect name. Defaults to PostgresDialect.

    Raises ValueError on unknown dialect when name is truthy but unrecognized,
    so callers explicitly opt into the default by passing None or "".
    """
    if not name:
        return PostgresDialect()
    key = name.strip().lower()
    cls = _REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"Unsupported dialect: {name!r}")
    return cls()


# Whitelist regex for safe identifiers (no quotes, no spaces, no ; --).
# Allows letters, digits, underscore, dollar (Oracle), dot is NOT allowed
# because schema/table/column come separately.
_SAFE_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,127}$")


def is_safe_identifier(ident: str) -> bool:
    """Return True if ident is safe to quote into SQL.

    This is a defense-in-depth guard ON TOP of quote_ident escaping. We
    reject identifiers we cannot positively prove are simple table/column
    names, which prevents pathological cases like NUL bytes.
    """
    if not isinstance(ident, str):
        return False
    if not ident:
        return False
    return bool(_SAFE_IDENT_RE.match(ident))
