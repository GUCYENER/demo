"""VYRA v3.27.0 — Synthetic SQL Templates (G1).

FK ilişkisinden 2 örnek SQL üretir:

  - **LOOKUP_JOIN**     : iki tabloyu FK üzerinden birleştir, ilk N satırı dök
  - **AGGREGATE_COUNT** : referans alınan tabloya göre kaç satır var (GROUP BY)

Dialect-aware: PostgreSQL/MySQL → LIMIT n
               Oracle           → FETCH FIRST n ROWS ONLY
               MSSQL            → SELECT TOP n
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

TEMPLATE_KINDS = ("LOOKUP_JOIN", "AGGREGATE_COUNT")
DEFAULT_LIMIT = 10


@dataclass
class Relationship:
    """ds_db_relationships satırının yalın temsili (dataclass dict access için)."""
    id: int
    from_schema: Optional[str]
    from_table: str
    from_column: str
    to_schema: Optional[str]
    to_table: str
    to_column: str


@dataclass
class RenderedQuery:
    """Tek template'den üretilmiş SQL + meta + soru."""
    template_kind: str
    dialect: str
    sql: str
    question_tr: str
    schema_signature: str
    tables: List[str]
    columns_meta: List[Dict[str, str]]


# ─────────────────────────────────────────────────────────────
# Identifier quoting
# ─────────────────────────────────────────────────────────────

_PG_QUOTE = '"'
_MSSQL_OPEN = "["
_MSSQL_CLOSE = "]"


def _quote_identifier(name: str, dialect: str) -> str:
    """Dialect-aware identifier quote — boş veya quote'lanmış girişi yutmaz."""
    if not name:
        return name
    n = name.strip()
    if not n:
        return n
    if dialect == "mssql":
        return f"{_MSSQL_OPEN}{n}{_MSSQL_CLOSE}"
    if dialect == "mysql":
        return f"`{n}`"
    # postgresql + oracle → ""
    return f'{_PG_QUOTE}{n}{_PG_QUOTE}'


def _qualify(schema: Optional[str], table: str, dialect: str) -> str:
    """schema.table — schema boşsa table döner."""
    t = _quote_identifier(table, dialect)
    if schema and schema.strip():
        s = _quote_identifier(schema, dialect)
        return f"{s}.{t}"
    return t


def _limit_clause(dialect: str, n: int) -> str:
    """SELECT sonu için LIMIT/FETCH/TOP — TOP ise SELECT'in başında olmalı (caller'da)."""
    if dialect == "oracle":
        return f"FETCH FIRST {int(n)} ROWS ONLY"
    if dialect == "mssql":
        return ""  # TOP ile kullanılır
    # postgresql + mysql
    return f"LIMIT {int(n)}"


def _select_prefix(dialect: str, n: int) -> str:
    """SELECT [TOP n] ya da SELECT."""
    if dialect == "mssql":
        return f"SELECT TOP {int(n)}"
    return "SELECT"


# ─────────────────────────────────────────────────────────────
# Templates
# ─────────────────────────────────────────────────────────────

def render_lookup_join(
    rel: Relationship,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """LOOKUP_JOIN — from_table'dan FK ile to_table'a join, ilk N satır.

    Üretilen örnek (postgresql):
        SELECT a."order_id", a."customer_id", b."name"
        FROM "sales"."orders" a
        JOIN "public"."customers" b ON a."customer_id" = b."id"
        LIMIT 10
    """
    d = dialect.lower()
    from_q = _qualify(rel.from_schema, rel.from_table, d)
    to_q = _qualify(rel.to_schema, rel.to_table, d)
    from_col_q = _quote_identifier(rel.from_column, d)
    to_col_q = _quote_identifier(rel.to_column, d)

    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)

    sql = (
        f"{sel_prefix} a.{from_col_q} AS from_key, "
        f"b.{to_col_q} AS to_key "
        f"FROM {from_q} a "
        f"JOIN {to_q} b ON a.{from_col_q} = b.{to_col_q}"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"

    full_from = f"{rel.from_schema}.{rel.from_table}" if rel.from_schema else rel.from_table
    full_to = f"{rel.to_schema}.{rel.to_table}" if rel.to_schema else rel.to_table

    return RenderedQuery(
        template_kind="LOOKUP_JOIN",
        dialect=d,
        sql=sql,
        question_tr=(
            f"{rel.from_table} tablosundaki kayıtların ilgili "
            f"{rel.to_table} bilgilerini göster"
        ),
        schema_signature=",".join(sorted({full_from.lower(), full_to.lower()})),
        tables=[full_from, full_to],
        columns_meta=[
            {"name": rel.from_column, "table": rel.from_table, "role": "from_key"},
            {"name": rel.to_column, "table": rel.to_table, "role": "to_key"},
        ],
    )


def render_aggregate_count(
    rel: Relationship,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """AGGREGATE_COUNT — referans tablodaki her satır için from_table'da kaç eşleşme var.

    Üretilen örnek (postgresql):
        SELECT b."id", COUNT(a."customer_id") AS cnt
        FROM "public"."customers" b
        LEFT JOIN "sales"."orders" a ON a."customer_id" = b."id"
        GROUP BY b."id"
        ORDER BY cnt DESC
        LIMIT 10
    """
    d = dialect.lower()
    from_q = _qualify(rel.from_schema, rel.from_table, d)
    to_q = _qualify(rel.to_schema, rel.to_table, d)
    from_col_q = _quote_identifier(rel.from_column, d)
    to_col_q = _quote_identifier(rel.to_column, d)

    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)

    # MSSQL TOP n ORDER BY ile uyumludur; Oracle FETCH ORDER BY sonrasındadır
    sql = (
        f"{sel_prefix} b.{to_col_q} AS ref_key, "
        f"COUNT(a.{from_col_q}) AS cnt "
        f"FROM {to_q} b "
        f"LEFT JOIN {from_q} a ON a.{from_col_q} = b.{to_col_q} "
        f"GROUP BY b.{to_col_q} "
        f"ORDER BY cnt DESC"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"

    full_from = f"{rel.from_schema}.{rel.from_table}" if rel.from_schema else rel.from_table
    full_to = f"{rel.to_schema}.{rel.to_table}" if rel.to_schema else rel.to_table

    return RenderedQuery(
        template_kind="AGGREGATE_COUNT",
        dialect=d,
        sql=sql,
        question_tr=(
            f"Her bir {rel.to_table} için kaç {rel.from_table} kaydı var "
            f"(en fazlası başta)?"
        ),
        schema_signature=",".join(sorted({full_from.lower(), full_to.lower()})),
        tables=[full_from, full_to],
        columns_meta=[
            {"name": rel.to_column, "table": rel.to_table, "role": "ref_key"},
            {"name": rel.from_column, "table": rel.from_table, "role": "count_target"},
        ],
    )


# ─────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────

def render(
    rel: Relationship,
    template_kind: str,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """template_kind'a göre uygun render'ı çağır."""
    if template_kind == "LOOKUP_JOIN":
        return render_lookup_join(rel, dialect, limit)
    if template_kind == "AGGREGATE_COUNT":
        return render_aggregate_count(rel, dialect, limit)
    raise ValueError(f"unknown template_kind: {template_kind}")


def render_all(
    rel: Relationship,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> List[RenderedQuery]:
    """Bir FK için her iki template'i de üret — kullanıcı kuralı: '2 örnek yeter'."""
    return [
        render_lookup_join(rel, dialect, limit),
        render_aggregate_count(rel, dialect, limit),
    ]


__all__ = [
    "TEMPLATE_KINDS",
    "DEFAULT_LIMIT",
    "Relationship",
    "RenderedQuery",
    "render_lookup_join",
    "render_aggregate_count",
    "render",
    "render_all",
]
