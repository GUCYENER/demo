"""VYRA v3.29.2 — Synthetic SQL Templates (G1 + G3).

G1 (v3.27): LOOKUP_JOIN, AGGREGATE_COUNT
G3 (v3.29.2): CHAIN_JOIN_3HOP, CHAIN_JOIN_NHOP, CTE_LATEST_N_PER_GROUP,
              LATERAL_TOP_K, STRING_AGG_DETAILS, JUNCTION_N2M,
              TIME_SERIES_GENERATE, WINDOW_RUNNING_TOTAL

G3 renderer'ları "chain" (Relationship listesi) ile çalışır; her ardışık çift
ortak tablo paylaşır (FK üzerinden join'lenebilir). Dialect: G1 örnekleri 4
diyalekt destekler, G3 örnekleri **postgresql** odaklıdır (CTE/LATERAL/
GENERATE_SERIES/STRING_AGG PG-spesifik). Diğer dialect istenirse fallback'i
PG variant'a düşer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from app.services.db_learning.synthetic_dialect import string_agg

TEMPLATE_KINDS = (
    # G1
    "LOOKUP_JOIN",
    "AGGREGATE_COUNT",
    # G6 (v3.45.0 P2) — tip-farkında, 4-dialect per-FK
    "AGGREGATE_STATS",
    "EXISTS_ANTI_JOIN",
    "DISTINCT_COUNT",
    # G3 — multi-table
    "CHAIN_JOIN_3HOP",
    "CHAIN_JOIN_NHOP",
    "CTE_LATEST_N_PER_GROUP",
    "LATERAL_TOP_K",
    "STRING_AGG_DETAILS",
    "JUNCTION_N2M",
    "TIME_SERIES_GENERATE",
    "WINDOW_RUNNING_TOTAL",
)

# Complexity score — learned_db_queries.complexity_score
COMPLEXITY_BY_KIND: Dict[str, int] = {
    "LOOKUP_JOIN": 2,
    "AGGREGATE_COUNT": 2,
    "AGGREGATE_STATS": 3,
    "EXISTS_ANTI_JOIN": 3,
    "DISTINCT_COUNT": 3,
    "CHAIN_JOIN_3HOP": 3,
    "CHAIN_JOIN_NHOP": 4,
    "CTE_LATEST_N_PER_GROUP": 4,
    "LATERAL_TOP_K": 4,
    "STRING_AGG_DETAILS": 4,
    "JUNCTION_N2M": 3,
    "TIME_SERIES_GENERATE": 3,
    "WINDOW_RUNNING_TOTAL": 5,
}

DEFAULT_LIMIT = 10
DEFAULT_TOP_K = 3


@dataclass
class Relationship:
    """ds_db_relationships satırının yalın temsili.

    v3.32.0: Composite FK desteği — ``from_columns`` / ``to_columns`` listeleri.
    Backward compat: tek-column ilişkiler için ``from_column`` / ``to_column``
    field'ları korunur ve listelerin ilk elemanıyla eşleşmesi beklenir. Eski
    construction (sadece tekil field'lar ile) çalışmaya devam eder; listeler
    __post_init__'te otomatik doldurulur.
    """
    id: int
    from_schema: Optional[str]
    from_table: str
    from_column: str
    to_schema: Optional[str]
    to_table: str
    to_column: str
    cardinality_from: Optional[str] = None   # '1' | 'N'
    cardinality_to: Optional[str] = None
    is_junction: bool = False
    from_columns: List[str] = field(default_factory=list)
    to_columns: List[str] = field(default_factory=list)
    constraint_name: Optional[str] = None
    confidence_score: Optional[float] = None

    def __post_init__(self) -> None:
        # Backward compat: tekil column ilk eleman olur, liste boşsa tek-column
        # FK olarak ele alınır.
        if not self.from_columns and self.from_column:
            self.from_columns = [self.from_column]
        if not self.to_columns and self.to_column:
            self.to_columns = [self.to_column]
        # Eğer composite listeler verildi ama tekil column boş ise senkronize et
        if self.from_columns and not self.from_column:
            self.from_column = self.from_columns[0]
        if self.to_columns and not self.to_column:
            self.to_column = self.to_columns[0]

    @property
    def is_self_ref(self) -> bool:
        """Self-referential FK mi? (örn. employee.manager_id → employee.id)"""
        same_schema = (self.from_schema or "") == (self.to_schema or "")
        return same_schema and self.from_table == self.to_table

    @property
    def is_composite(self) -> bool:
        return len(self.from_columns) > 1 or len(self.to_columns) > 1


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
    complexity_score: int = 1
    join_path: List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────
# Identifier quoting
# ─────────────────────────────────────────────────────────────

_PG_QUOTE = '"'
_MSSQL_OPEN = "["
_MSSQL_CLOSE = "]"


def _quote_identifier(name: str, dialect: str) -> str:
    if not name:
        return name
    n = name.strip()
    if not n:
        return n
    if dialect == "mssql":
        return f"{_MSSQL_OPEN}{n}{_MSSQL_CLOSE}"
    if dialect == "mysql":
        return f"`{n}`"
    return f'{_PG_QUOTE}{n}{_PG_QUOTE}'


def _qualify(schema: Optional[str], table: str, dialect: str) -> str:
    t = _quote_identifier(table, dialect)
    if schema and schema.strip():
        s = _quote_identifier(schema, dialect)
        return f"{s}.{t}"
    return t


def _limit_clause(dialect: str, n: int) -> str:
    if dialect == "oracle":
        return f"FETCH FIRST {int(n)} ROWS ONLY"
    if dialect == "mssql":
        return ""
    return f"LIMIT {int(n)}"


def _select_prefix(dialect: str, n: int) -> str:
    if dialect == "mssql":
        return f"SELECT TOP {int(n)}"
    return "SELECT"


def _full_name(schema: Optional[str], table: str) -> str:
    return f"{schema}.{table}" if schema else table


# ─────────────────────────────────────────────────────────────
# G1 Templates
# ─────────────────────────────────────────────────────────────

def _fk_column_pairs(rel: Relationship) -> List[tuple]:
    """Composite FK için ``[(from_col, to_col), ...]`` listesi döndür.

    Tek-column FK'lerde tek elemanlı liste döner. Listelerin uzunluğu farklıysa
    en kısasına göre zip yapılır (defansif). Boş liste durumunda tekil
    ``from_column`` / ``to_column`` alanlarına düşer.
    """
    fcs = list(rel.from_columns or ([rel.from_column] if rel.from_column else []))
    tcs = list(rel.to_columns or ([rel.to_column] if rel.to_column else []))
    return list(zip(fcs, tcs))


def render_lookup_join(rel: Relationship, dialect: str = "postgresql", limit: int = DEFAULT_LIMIT) -> RenderedQuery:
    d = dialect.lower()
    from_q = _qualify(rel.from_schema, rel.from_table, d)
    to_q = _qualify(rel.to_schema, rel.to_table, d)
    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)

    pairs = _fk_column_pairs(rel)
    if not pairs:
        # defansif: pair yoksa eski davranışa düş
        pairs = [(rel.from_column, rel.to_column)]

    # SELECT: composite ise her column ayrı alias (from_key1, from_key2, ...)
    sel_parts: List[str] = []
    on_parts: List[str] = []
    columns_meta: List[Dict[str, str]] = []
    for i, (fc, tc) in enumerate(pairs, start=1):
        fcq = _quote_identifier(fc, d)
        tcq = _quote_identifier(tc, d)
        if len(pairs) == 1:
            sel_parts.append(f"a.{fcq} AS from_key")
            sel_parts.append(f"b.{tcq} AS to_key")
        else:
            sel_parts.append(f"a.{fcq} AS from_key{i}")
            sel_parts.append(f"b.{tcq} AS to_key{i}")
        on_parts.append(f"a.{fcq} = b.{tcq}")
        columns_meta.append({"name": fc, "table": rel.from_table, "role": f"from_key{i}" if len(pairs) > 1 else "from_key"})
        columns_meta.append({"name": tc, "table": rel.to_table, "role": f"to_key{i}" if len(pairs) > 1 else "to_key"})

    select_clause = ", ".join(sel_parts)
    on_clause = " AND ".join(on_parts)

    sql = (
        f"{sel_prefix} {select_clause} "
        f"FROM {from_q} a JOIN {to_q} b ON {on_clause}"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"

    # Self-ref durumunda question_tr daha anlamlı bir cümle olur
    if rel.is_self_ref:
        question_tr = (
            f"{rel.from_table} tablosundaki kayıtların ilgili üst (parent) "
            f"kayıtlarını göster"
        )
    else:
        question_tr = (
            f"{rel.from_table} tablosundaki kayıtların ilgili "
            f"{rel.to_table} bilgilerini göster"
        )

    full_from = _full_name(rel.from_schema, rel.from_table)
    full_to = _full_name(rel.to_schema, rel.to_table)
    return RenderedQuery(
        template_kind="LOOKUP_JOIN",
        dialect=d,
        sql=sql,
        question_tr=question_tr,
        schema_signature=",".join(sorted({full_from.lower(), full_to.lower()})),
        tables=[full_from, full_to],
        columns_meta=columns_meta,
        complexity_score=COMPLEXITY_BY_KIND["LOOKUP_JOIN"],
        join_path=[full_from, full_to],
    )


def render_aggregate_count(rel: Relationship, dialect: str = "postgresql", limit: int = DEFAULT_LIMIT) -> RenderedQuery:
    d = dialect.lower()
    from_q = _qualify(rel.from_schema, rel.from_table, d)
    to_q = _qualify(rel.to_schema, rel.to_table, d)
    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)

    pairs = _fk_column_pairs(rel)
    if not pairs:
        pairs = [(rel.from_column, rel.to_column)]

    # GROUP BY: tüm to_columns; SELECT: ref_key (composite ise ref_key1..N)
    sel_parts: List[str] = []
    on_parts: List[str] = []
    group_parts: List[str] = []
    columns_meta: List[Dict[str, str]] = []
    for i, (fc, tc) in enumerate(pairs, start=1):
        fcq = _quote_identifier(fc, d)
        tcq = _quote_identifier(tc, d)
        if len(pairs) == 1:
            sel_parts.append(f"b.{tcq} AS ref_key")
        else:
            sel_parts.append(f"b.{tcq} AS ref_key{i}")
        on_parts.append(f"a.{fcq} = b.{tcq}")
        group_parts.append(f"b.{tcq}")
        columns_meta.append({"name": tc, "table": rel.to_table, "role": f"ref_key{i}" if len(pairs) > 1 else "ref_key"})
    # COUNT: ilk from_column üzerinden (NULL'sız satırlar sayılır)
    first_fcq = _quote_identifier(pairs[0][0], d)
    columns_meta.append({"name": pairs[0][0], "table": rel.from_table, "role": "count_target"})

    select_clause = ", ".join(sel_parts) + f", COUNT(a.{first_fcq}) AS cnt"
    on_clause = " AND ".join(on_parts)
    group_clause = ", ".join(group_parts)

    sql = (
        f"{sel_prefix} {select_clause} "
        f"FROM {to_q} b LEFT JOIN {from_q} a ON {on_clause} "
        f"GROUP BY {group_clause} ORDER BY cnt DESC"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"

    if rel.is_self_ref:
        question_tr = (
            f"Her {rel.from_table} parent'ı için alt (child) kayıt sayısı"
        )
    else:
        question_tr = (
            f"Her bir {rel.to_table} için kaç {rel.from_table} kaydı var "
            f"(en fazlası başta)?"
        )

    full_from = _full_name(rel.from_schema, rel.from_table)
    full_to = _full_name(rel.to_schema, rel.to_table)
    return RenderedQuery(
        template_kind="AGGREGATE_COUNT",
        dialect=d,
        sql=sql,
        question_tr=question_tr,
        schema_signature=",".join(sorted({full_from.lower(), full_to.lower()})),
        tables=[full_from, full_to],
        columns_meta=columns_meta,
        complexity_score=COMPLEXITY_BY_KIND["AGGREGATE_COUNT"],
        join_path=[full_to, full_from],
    )


# ─────────────────────────────────────────────────────────────
# G6 (v3.45.0 P2) — Tip-farkında, 4-dialect per-FK template'leri
# ─────────────────────────────────────────────────────────────

def render_aggregate_stats(
    rel: Relationship,
    value_column: str,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """Her parent (1-tarafı) için child'ın SAYISAL bir kolonunun istatistikleri.

    AGGREGATE_COUNT yalnız satır sayar; bu template SUM/AVG/MIN/MAX da verir → "her
    müşterinin toplam/ortalama sipariş tutarı" gibi. `value_column` child (rel.from)
    tablosunda SAYISAL bir ölçü kolonudur — generator tip-keşfiyle seçip geçer
    (FK/PK/other kolonlar elenir). 4 dialect: standart agregat + TOP/FETCH/LIMIT.
    """
    d = dialect.lower()
    from_q = _qualify(rel.from_schema, rel.from_table, d)   # child (N)
    to_q = _qualify(rel.to_schema, rel.to_table, d)         # parent (1)
    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)

    pairs = _fk_column_pairs(rel)
    if not pairs:
        pairs = [(rel.from_column, rel.to_column)]

    sel_parts: List[str] = []
    on_parts: List[str] = []
    group_parts: List[str] = []
    columns_meta: List[Dict[str, str]] = []
    for i, (fc, tc) in enumerate(pairs, start=1):
        fcq = _quote_identifier(fc, d)
        tcq = _quote_identifier(tc, d)
        role = f"ref_key{i}" if len(pairs) > 1 else "ref_key"
        sel_parts.append(f"b.{tcq} AS {role}")
        on_parts.append(f"a.{fcq} = b.{tcq}")
        group_parts.append(f"b.{tcq}")
        columns_meta.append({"name": tc, "table": rel.to_table, "role": role})

    vq = _quote_identifier(value_column, d)
    columns_meta.append({"name": value_column, "table": rel.from_table, "role": "measure"})

    stats = (
        f"COUNT(a.{vq}) AS cnt, "
        f"SUM(a.{vq}) AS toplam, "
        f"AVG(a.{vq}) AS ortalama, "
        f"MIN(a.{vq}) AS en_dusuk, "
        f"MAX(a.{vq}) AS en_yuksek"
    )
    select_clause = ", ".join(sel_parts) + f", {stats}"
    on_clause = " AND ".join(on_parts)
    group_clause = ", ".join(group_parts)

    # INNER JOIN (child'ı OLAN parent'lar): AGGREGATE_COUNT zero-count için LEFT kullanır
    # ama STATS'ta child'sız parent'ın SUM/AVG'i NULL olur → ORDER BY toplam DESC'te NULL'lar
    # dialect'e göre farklı sıralanıp (PG'de başa) LIMIT penceresini doldurur. INNER ile NULL
    # toplam yok → sıralama deterministik ve 4 dialect tutarlı.
    sql = (
        f"{sel_prefix} {select_clause} "
        f"FROM {to_q} b JOIN {from_q} a ON {on_clause} "
        f"GROUP BY {group_clause} ORDER BY toplam DESC"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"

    if rel.is_self_ref:
        question_tr = f"Her {rel.from_table} parent'ı için alt kayıtların {value_column} istatistikleri (toplam/ortalama/min/max)"
    else:
        question_tr = f"Her {rel.to_table} için {rel.from_table}.{value_column} istatistikleri (toplam/ortalama/min/max)"

    full_from = _full_name(rel.from_schema, rel.from_table)
    full_to = _full_name(rel.to_schema, rel.to_table)
    return RenderedQuery(
        template_kind="AGGREGATE_STATS",
        dialect=d,
        sql=sql,
        question_tr=question_tr,
        schema_signature=",".join(sorted({full_from.lower(), full_to.lower()})),
        tables=[full_from, full_to],
        columns_meta=columns_meta,
        complexity_score=COMPLEXITY_BY_KIND["AGGREGATE_STATS"],
        join_path=[full_to, full_from],
    )


def render_exists_anti_join(
    rel: Relationship,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """Hiç child kaydı OLMAYAN parent satırları (orphan/kullanılmamış tespiti).

    "Siparişi olmayan müşteriler", "hiç hareketi olmayan hesaplar" gibi veri-kalitesi
    sorularını karşılar. NOT EXISTS standart SQL → 4 dialect (kolon tipi GEREKMEZ).
    """
    d = dialect.lower()
    from_q = _qualify(rel.from_schema, rel.from_table, d)   # child (N)
    to_q = _qualify(rel.to_schema, rel.to_table, d)         # parent (1)
    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)

    pairs = _fk_column_pairs(rel)
    if not pairs:
        pairs = [(rel.from_column, rel.to_column)]

    on_parts: List[str] = []
    order_parts: List[str] = []
    columns_meta: List[Dict[str, str]] = []
    for i, (fc, tc) in enumerate(pairs, start=1):
        fcq = _quote_identifier(fc, d)
        tcq = _quote_identifier(tc, d)
        on_parts.append(f"a.{fcq} = b.{tcq}")
        order_parts.append(f"b.{tcq}")
        columns_meta.append({"name": tc, "table": rel.to_table, "role": f"pk{i}" if len(pairs) > 1 else "pk"})
    on_clause = " AND ".join(on_parts)
    order_clause = ", ".join(order_parts)

    # ORDER BY parent anahtarı: TOP/LIMIT/FETCH ile deterministik subset → re-run'da aynı
    # orphan satırlar (idempotent öğrenme/önizleme).
    sql = (
        f"{sel_prefix} b.* FROM {to_q} b "
        f"WHERE NOT EXISTS (SELECT 1 FROM {from_q} a WHERE {on_clause}) "
        f"ORDER BY {order_clause}"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"

    if rel.is_self_ref:
        question_tr = f"{rel.from_table} tablosunda hiç alt (child) kaydı olmayan kayıtlar"
    else:
        question_tr = f"Hiç {rel.from_table} kaydı olmayan {rel.to_table} satırları"

    full_from = _full_name(rel.from_schema, rel.from_table)
    full_to = _full_name(rel.to_schema, rel.to_table)
    return RenderedQuery(
        template_kind="EXISTS_ANTI_JOIN",
        dialect=d,
        sql=sql,
        question_tr=question_tr,
        schema_signature=",".join(sorted({full_from.lower(), full_to.lower()})),
        tables=[full_from, full_to],
        columns_meta=columns_meta,
        complexity_score=COMPLEXITY_BY_KIND["EXISTS_ANTI_JOIN"],
        join_path=[full_to, full_from],
    )


def render_distinct_count(
    rel: Relationship,
    distinct_column: str,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """Her parent için child'ın bir kolonundaki FARKLI değer sayısı ("her müşterinin kaç
    farklı ürün/durum değeri var"). `distinct_column` child (rel.from) tablosunda kategorik
    (text) bir kolon — generator tip-keşfiyle seçer. INNER JOIN + COUNT(DISTINCT), 4-dialect.
    """
    d = dialect.lower()
    from_q = _qualify(rel.from_schema, rel.from_table, d)   # child (N)
    to_q = _qualify(rel.to_schema, rel.to_table, d)         # parent (1)
    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)

    pairs = _fk_column_pairs(rel)
    if not pairs:
        pairs = [(rel.from_column, rel.to_column)]

    sel_parts: List[str] = []
    on_parts: List[str] = []
    group_parts: List[str] = []
    columns_meta: List[Dict[str, str]] = []
    for i, (fc, tc) in enumerate(pairs, start=1):
        fcq = _quote_identifier(fc, d)
        tcq = _quote_identifier(tc, d)
        role = f"ref_key{i}" if len(pairs) > 1 else "ref_key"
        sel_parts.append(f"b.{tcq} AS {role}")
        on_parts.append(f"a.{fcq} = b.{tcq}")
        group_parts.append(f"b.{tcq}")
        columns_meta.append({"name": tc, "table": rel.to_table, "role": role})

    dcq = _quote_identifier(distinct_column, d)
    columns_meta.append({"name": distinct_column, "table": rel.from_table, "role": "distinct_target"})
    select_clause = ", ".join(sel_parts) + f", COUNT(DISTINCT a.{dcq}) AS farkli_adet"

    sql = (
        f"{sel_prefix} {select_clause} "
        f"FROM {to_q} b JOIN {from_q} a ON {' AND '.join(on_parts)} "
        f"GROUP BY {', '.join(group_parts)} ORDER BY farkli_adet DESC"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"

    if rel.is_self_ref:
        question_tr = f"Her {rel.from_table} parent'ı için alt kayıtların farklı {distinct_column} değeri sayısı"
    else:
        question_tr = f"Her {rel.to_table} için kaç farklı {rel.from_table}.{distinct_column} değeri var?"

    full_from = _full_name(rel.from_schema, rel.from_table)
    full_to = _full_name(rel.to_schema, rel.to_table)
    return RenderedQuery(
        template_kind="DISTINCT_COUNT",
        dialect=d,
        sql=sql,
        question_tr=question_tr,
        schema_signature=",".join(sorted({full_from.lower(), full_to.lower()})),
        tables=[full_from, full_to],
        columns_meta=columns_meta,
        complexity_score=COMPLEXITY_BY_KIND["DISTINCT_COUNT"],
        join_path=[full_to, full_from],
    )


# ─────────────────────────────────────────────────────────────
# G3 Helpers — Chain join utilities
# ─────────────────────────────────────────────────────────────

def _chain_tables(chain: Sequence[Relationship]) -> List[str]:
    """Chain'in ziyaret ettiği tabloları sırayla döndür (full_name)."""
    if not chain:
        return []
    out = [_full_name(chain[0].from_schema, chain[0].from_table)]
    last = (chain[0].from_schema, chain[0].from_table)
    for rel in chain:
        cur_from = (rel.from_schema, rel.from_table)
        cur_to = (rel.to_schema, rel.to_table)
        next_node = cur_to if cur_from == last else cur_from
        out.append(_full_name(*next_node))
        last = next_node
    return out


def _build_join_clauses_pg(chain: Sequence[Relationship]) -> str:
    """Chain'i FROM ... JOIN ... ON ... cümleciğine çevir (PG)."""
    if not chain:
        return ""
    parts: List[str] = []
    aliases: Dict[str, str] = {}

    def _alias_for(schema: Optional[str], table: str) -> str:
        key = _full_name(schema, table).lower()
        if key not in aliases:
            aliases[key] = f"t{len(aliases) + 1}"
        return aliases[key]

    first = chain[0]
    a0 = _alias_for(first.from_schema, first.from_table)
    parts.append(f"FROM {_qualify(first.from_schema, first.from_table, 'postgresql')} {a0}")

    for rel in chain:
        a_from = _alias_for(rel.from_schema, rel.from_table)
        a_to = _alias_for(rel.to_schema, rel.to_table)
        # Hangi tarafa join? Daha önce ziyaret edilmemiş olana.
        from_key = _full_name(rel.from_schema, rel.from_table).lower()
        to_key = _full_name(rel.to_schema, rel.to_table).lower()
        existing = list(aliases.keys())
        if existing.index(from_key) < existing.index(to_key):
            # to tarafı yeni
            new_q = _qualify(rel.to_schema, rel.to_table, "postgresql")
            new_alias = a_to
            on_clause = f"{new_alias}.{_quote_identifier(rel.to_column, 'postgresql')} = {a_from}.{_quote_identifier(rel.from_column, 'postgresql')}"
        else:
            new_q = _qualify(rel.from_schema, rel.from_table, "postgresql")
            new_alias = a_from
            on_clause = f"{new_alias}.{_quote_identifier(rel.from_column, 'postgresql')} = {a_to}.{_quote_identifier(rel.to_column, 'postgresql')}"
        # İlk satırdaki tablo yine eklenmesin
        if parts[0].endswith(f" {new_alias}") and len(parts) == 1:
            continue
        parts.append(f"JOIN {new_q} {new_alias} ON {on_clause}")
    return "\n".join(parts)


def _terminal_aliases(chain: Sequence[Relationship]) -> tuple[str, str]:
    """İlk ve son tablonun alias'larını döndür (t1, tN)."""
    tables = _chain_tables(chain)
    return ("t1", f"t{len(tables)}")


# ─────────────────────────────────────────────────────────────
# G3 Templates
# ─────────────────────────────────────────────────────────────

def render_chain_join(
    chain: Sequence[Relationship],
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
    kind: str = "CHAIN_JOIN_3HOP",
) -> RenderedQuery:
    """3+ tablo zincir join (PG ağırlıklı)."""
    d = "postgresql"
    join_block = _build_join_clauses_pg(chain)
    a_start, a_end = _terminal_aliases(chain)
    tables = _chain_tables(chain)
    start_table = chain[0].from_table
    end_table = tables[-1].split(".")[-1] if tables else ""
    sql = (
        f"SELECT {a_start}.*, {a_end}.* \n"
        f"{join_block}\n"
        f"LIMIT {int(limit)}"
    )
    return RenderedQuery(
        template_kind=kind,
        dialect=d,
        sql=sql,
        question_tr=f"{start_table} ile {end_table} arasındaki ilişkili kayıtları zincir join ile listele",
        schema_signature=",".join(sorted({t.lower() for t in tables})),
        tables=tables,
        columns_meta=[],
        complexity_score=COMPLEXITY_BY_KIND.get(kind, 3),
        join_path=tables,
    )


def render_cte_latest_n_per_group(
    chain: Sequence[Relationship],
    dialect: str = "postgresql",
    n: int = DEFAULT_TOP_K,
    order_column: str = "created_at",
) -> RenderedQuery:
    """ROW_NUMBER() OVER (PARTITION BY group ORDER BY order_col DESC) — her grupta son N."""
    if not chain:
        raise ValueError("chain must be non-empty")
    d = "postgresql"
    tables = _chain_tables(chain)
    fact = chain[0]
    join_block = _build_join_clauses_pg(chain)
    a_start, a_end = _terminal_aliases(chain)
    sql = (
        f"WITH ranked AS (\n"
        f"  SELECT {a_start}.*, {a_end}.*, \n"
        f"         ROW_NUMBER() OVER (PARTITION BY {a_end}.id ORDER BY {a_start}.\"{order_column}\" DESC) AS rn\n"
        f"  {join_block}\n"
        f")\n"
        f"SELECT * FROM ranked WHERE rn <= {int(n)} ORDER BY rn"
    )
    return RenderedQuery(
        template_kind="CTE_LATEST_N_PER_GROUP",
        dialect=d,
        sql=sql,
        question_tr=f"Her {tables[-1].split('.')[-1] if tables else 'grup'} için son {n} {fact.from_table} kaydı",
        schema_signature=",".join(sorted({t.lower() for t in tables})),
        tables=tables,
        columns_meta=[{"name": order_column, "table": fact.from_table, "role": "order_key"}],
        complexity_score=COMPLEXITY_BY_KIND["CTE_LATEST_N_PER_GROUP"],
        join_path=tables,
    )


def render_lateral_top_k(
    parent: Relationship,
    detail_table: str,
    detail_fk_column: str,
    detail_order_column: str = "acted_at",
    k: int = 2,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """LATERAL ile her ana kayıt için top-K detay."""
    d = "postgresql"
    parent_q = _qualify(parent.from_schema, parent.from_table, d)
    parent_pk = _quote_identifier(parent.from_column, d)
    detail_q = _quote_identifier(detail_table, d)
    detail_fk = _quote_identifier(detail_fk_column, d)
    order_col = _quote_identifier(detail_order_column, d)
    sql = (
        f"SELECT p.*, dt.*\n"
        f"FROM {parent_q} p\n"
        f"LEFT JOIN LATERAL (\n"
        f"  SELECT * FROM {detail_q}\n"
        f"  WHERE {detail_fk} = p.{parent_pk}\n"
        f"  ORDER BY {order_col} DESC LIMIT {int(k)}\n"
        f") dt ON TRUE\n"
        f"ORDER BY p.{parent_pk} DESC LIMIT {int(limit)}"
    )
    full_parent = _full_name(parent.from_schema, parent.from_table)
    full_detail = detail_table
    return RenderedQuery(
        template_kind="LATERAL_TOP_K",
        dialect=d,
        sql=sql,
        question_tr=f"Her {parent.from_table} için son {k} {detail_table} kaydı",
        schema_signature=",".join(sorted({full_parent.lower(), full_detail.lower()})),
        tables=[full_parent, full_detail],
        columns_meta=[{"name": detail_order_column, "table": detail_table, "role": "order_key"}],
        complexity_score=COMPLEXITY_BY_KIND["LATERAL_TOP_K"],
        join_path=[full_parent, full_detail],
    )


def render_string_agg_details(
    rel: Relationship,
    label_column: str,
    order_column: Optional[str] = None,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """Her PARENT için child detay etiketlerini tek hücrede birleştir (ordered).

    v3.45.0 P2b — ORYANTASYON FIX: FK satırı from=child/to=parent gelir. Eski sürüm from'u
    "parent" sanıp her child'a tek parent etiketini N kez birleştiriyordu (anlamsız). Doğrusu:
    parent=rel.to (1-tarafı, GROUP key), detail=rel.from (N-tarafı). `label_column` (+opsiyonel
    `order_column`) CHILD tablosunda — generator tip-keşfiyle seçer (text + temporal). 4-dialect
    STRING_AGG/LISTAGG/GROUP_CONCAT (`synthetic_dialect.string_agg`).
    """
    d = dialect.lower()
    parent_q = _qualify(rel.to_schema, rel.to_table, d)     # 1-tarafı (group)
    child_q = _qualify(rel.from_schema, rel.from_table, d)  # N-tarafı (detay)
    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)

    pairs = _fk_column_pairs(rel)
    if not pairs:
        pairs = [(rel.from_column, rel.to_column)]

    sel_parts: List[str] = []
    on_parts: List[str] = []
    group_parts: List[str] = []
    columns_meta: List[Dict[str, str]] = []
    for i, (fc, tc) in enumerate(pairs, start=1):
        fcq = _quote_identifier(fc, d)
        tcq = _quote_identifier(tc, d)
        role = f"ref_key{i}" if len(pairs) > 1 else "ref_key"
        sel_parts.append(f"b.{tcq} AS {role}")
        on_parts.append(f"a.{fcq} = b.{tcq}")
        group_parts.append(f"b.{tcq}")
        columns_meta.append({"name": tc, "table": rel.to_table, "role": role})

    lblq = _quote_identifier(label_column, d)
    order_expr = f"a.{_quote_identifier(order_column, d)}" if order_column else f"a.{lblq}"
    agg = string_agg(f"a.{lblq}", order_expr, d)
    columns_meta.append({"name": label_column, "table": rel.from_table, "role": "label"})

    select_clause = ", ".join(sel_parts) + f", {agg} AS detay"
    # ORDER BY group key → TOP/LIMIT/FETCH ile deterministik parent subset (diğer agregat
    # template'lerle tutarlı; re-run idempotent öğrenme/önizleme).
    sql = (
        f"{sel_prefix} {select_clause} "
        f"FROM {parent_q} b JOIN {child_q} a ON {' AND '.join(on_parts)} "
        f"GROUP BY {', '.join(group_parts)} ORDER BY {', '.join(group_parts)}"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"

    full_parent = _full_name(rel.to_schema, rel.to_table)
    full_detail = _full_name(rel.from_schema, rel.from_table)
    return RenderedQuery(
        template_kind="STRING_AGG_DETAILS",
        dialect=d,
        sql=sql,
        question_tr=f"Her {rel.to_table} için ilgili {rel.from_table} detaylarını ({label_column}) tek metinde birleştir",
        schema_signature=",".join(sorted({full_parent.lower(), full_detail.lower()})),
        tables=[full_parent, full_detail],
        columns_meta=columns_meta,
        complexity_score=COMPLEXITY_BY_KIND["STRING_AGG_DETAILS"],
        join_path=[full_parent, full_detail],
    )


def render_junction_n2m(
    junction: Relationship,
    other_side: Relationship,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """N:M köprü üzerinden iki tarafı birleştir.

    junction: bridge tablonun ilk FK'si (örn. user_role.user_id → user.id)
    other_side: bridge tablonun ikinci FK'si (örn. user_role.role_id → role.id)
    """
    d = "postgresql"
    bridge_q = _qualify(junction.from_schema, junction.from_table, d)
    left_q = _qualify(junction.to_schema, junction.to_table, d)
    right_q = _qualify(other_side.to_schema, other_side.to_table, d)
    bridge_l_col = _quote_identifier(junction.from_column, d)
    bridge_r_col = _quote_identifier(other_side.from_column, d)
    left_pk = _quote_identifier(junction.to_column, d)
    right_pk = _quote_identifier(other_side.to_column, d)
    sql = (
        f"SELECT l.*, r.*\n"
        f"FROM {left_q} l\n"
        f"JOIN {bridge_q} br ON br.{bridge_l_col} = l.{left_pk}\n"
        f"JOIN {right_q} r ON r.{right_pk} = br.{bridge_r_col}\n"
        f"LIMIT {int(limit)}"
    )
    tables = [
        _full_name(junction.to_schema, junction.to_table),
        _full_name(junction.from_schema, junction.from_table),
        _full_name(other_side.to_schema, other_side.to_table),
    ]
    return RenderedQuery(
        template_kind="JUNCTION_N2M",
        dialect=d,
        sql=sql,
        question_tr=f"{junction.to_table} ile {other_side.to_table} arasındaki N:M ilişkili kayıtlar",
        schema_signature=",".join(sorted({t.lower() for t in tables})),
        tables=tables,
        columns_meta=[],
        complexity_score=COMPLEXITY_BY_KIND["JUNCTION_N2M"],
        join_path=tables,
    )


def render_time_series_generate(
    fact: Relationship,
    date_column: str,
    days: int = 30,
    dialect: str = "postgresql",
) -> RenderedQuery:
    """GENERATE_SERIES + LEFT JOIN — boş günler dahil zaman serisi sayımı.

    v3.45.0 P2b: `date_column` artık generator tip-keşfinden gelir (eski 'created_at' tahmini
    yerine gerçek tarih kolonu). Takvim CTE'si PG-spesifik (GENERATE_SERIES) → generator bu kind'i
    non-PG'de ATLAR (_PG_ONLY_KINDS); 4-dialect takvim (CONNECT BY / recursive CTE) sonraki faza."""
    d = "postgresql"
    fact_q = _qualify(fact.from_schema, fact.from_table, d)
    date_q = _quote_identifier(date_column, d)
    pk_q = _quote_identifier(fact.from_column, d)
    sql = (
        f"WITH days AS (\n"
        f"  SELECT d::date AS day\n"
        f"  FROM GENERATE_SERIES(CURRENT_DATE - {int(days - 1)}, CURRENT_DATE, '1 day') d\n"
        f")\n"
        f"SELECT d.day, COUNT(f.{pk_q}) AS cnt\n"
        f"FROM days d\n"
        f"LEFT JOIN {fact_q} f ON f.{date_q}::date = d.day\n"
        f"GROUP BY d.day\n"
        f"ORDER BY d.day"
    )
    full_fact = _full_name(fact.from_schema, fact.from_table)
    return RenderedQuery(
        template_kind="TIME_SERIES_GENERATE",
        dialect=d,
        sql=sql,
        question_tr=f"Son {days} gündeki günlük {fact.from_table} sayısı (boş günler dahil)",
        schema_signature=full_fact.lower(),
        tables=[full_fact],
        columns_meta=[{"name": date_column, "table": fact.from_table, "role": "date"}],
        complexity_score=COMPLEXITY_BY_KIND["TIME_SERIES_GENERATE"],
        join_path=[full_fact],
    )


def render_window_running_total(
    fact: Relationship,
    value_column: str,
    date_column: str,
    partition_column: Optional[str] = None,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> RenderedQuery:
    """SUM() OVER — koşan toplam (cumulative sum). Tek-tablo (fact = rel.from).

    v3.45.0 P2b — 4-DIALECT + gerçek kolon: window fonksiyonu PG/Oracle/MSSQL/MySQL8 standart;
    yalnız tırnaklama + TOP/FETCH/LIMIT ayrışır. `value_column` (sayısal) + `date_column` (tarih)
    generator tip-keşfiyle seçilir (eski sürüm 'amount'/'created_at' TAHMİN edip non-PG'de
    `d="postgresql"` ile PG SQL üretip patlıyordu)."""
    d = dialect.lower()
    fact_q = _qualify(fact.from_schema, fact.from_table, d)
    value_q = _quote_identifier(value_column, d)
    date_q = _quote_identifier(date_column, d)
    sel_prefix = _select_prefix(d, limit)
    limit_suffix = _limit_clause(d, limit)
    partition_clause = ""
    if partition_column:
        pq = _quote_identifier(partition_column, d)
        partition_clause = f"PARTITION BY {pq} "
    sql = (
        f"{sel_prefix} *, "
        f"SUM({value_q}) OVER ({partition_clause}ORDER BY {date_q} "
        f"ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_total "
        f"FROM {fact_q} ORDER BY {date_q}"
    )
    if limit_suffix:
        sql += f" {limit_suffix}"
    full_fact = _full_name(fact.from_schema, fact.from_table)
    return RenderedQuery(
        template_kind="WINDOW_RUNNING_TOTAL",
        dialect=d,
        sql=sql,
        question_tr=f"{fact.from_table} {value_column} alanının koşan toplamı (tarihe göre)",
        schema_signature=full_fact.lower(),
        tables=[full_fact],
        columns_meta=[
            {"name": value_column, "table": fact.from_table, "role": "value"},
            {"name": date_column, "table": fact.from_table, "role": "order_key"},
        ],
        complexity_score=COMPLEXITY_BY_KIND["WINDOW_RUNNING_TOTAL"],
        join_path=[full_fact],
    )


# ─────────────────────────────────────────────────────────────
# Dispatch
# ─────────────────────────────────────────────────────────────

def render(
    rel: Relationship,
    template_kind: str,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
    col_ctx: Optional[Dict[str, str]] = None,
) -> RenderedQuery:
    """G1 + tek-Relationship temelli G3/G6 template'leri için dispatch.

    `col_ctx` (v3.45.0 P2): generator'ın tip-keşfiyle bulduğu kolonlar —
    {'numeric': <child sayısal kolon>, 'temporal': ..., 'text': ...}. Tip-bağımlı
    template'ler (AGGREGATE_STATS) gerekli kolonu buradan alır; generator kolon
    yoksa o kind'i ZATEN render'a göndermez (KeyError defansif fallback ile korunur).
    """
    cc = col_ctx or {}
    if template_kind == "LOOKUP_JOIN":
        return render_lookup_join(rel, dialect, limit)
    if template_kind == "AGGREGATE_COUNT":
        return render_aggregate_count(rel, dialect, limit)
    if template_kind == "AGGREGATE_STATS":
        value_column = cc.get("numeric")
        if not value_column:
            raise ValueError("AGGREGATE_STATS requires a numeric child column (col_ctx['numeric'])")
        return render_aggregate_stats(rel, value_column, dialect=dialect, limit=limit)
    if template_kind == "EXISTS_ANTI_JOIN":
        return render_exists_anti_join(rel, dialect=dialect, limit=limit)
    if template_kind == "DISTINCT_COUNT":
        distinct_column = cc.get("text")
        if not distinct_column:
            raise ValueError("DISTINCT_COUNT requires a categorical/text child column (col_ctx['text'])")
        return render_distinct_count(rel, distinct_column, dialect=dialect, limit=limit)
    if template_kind == "STRING_AGG_DETAILS":
        label_column = cc.get("text")
        if not label_column:
            raise ValueError("STRING_AGG_DETAILS requires a text label child column (col_ctx['text'])")
        return render_string_agg_details(rel, label_column, order_column=cc.get("temporal"),
                                         dialect=dialect, limit=limit)
    if template_kind == "TIME_SERIES_GENERATE":
        date_column = cc.get("temporal")
        if not date_column:
            raise ValueError("TIME_SERIES_GENERATE requires a temporal child column (col_ctx['temporal'])")
        return render_time_series_generate(rel, date_column, dialect=dialect)
    if template_kind == "WINDOW_RUNNING_TOTAL":
        value_column = cc.get("numeric")
        date_column = cc.get("temporal")
        if not value_column or not date_column:
            raise ValueError("WINDOW_RUNNING_TOTAL requires numeric + temporal child columns")
        # FK kolonuyla PARTITION BY → her parent için AYRI koşan toplam (global cumsum yerine
        # anlamlı: "her siparişin satır-bazında biriken tutarı"). İlişki-düzeyli (tablo-düzeyli değil).
        return render_window_running_total(rel, value_column, date_column,
                                           partition_column=rel.from_column,
                                           dialect=dialect, limit=limit)
    raise ValueError(f"unknown or chain-only template_kind: {template_kind}")


def render_all(
    rel: Relationship,
    dialect: str = "postgresql",
    limit: int = DEFAULT_LIMIT,
) -> List[RenderedQuery]:
    """G1: 2 örnek (LOOKUP_JOIN + AGGREGATE_COUNT). Geriye uyumlu."""
    return [
        render_lookup_join(rel, dialect, limit),
        render_aggregate_count(rel, dialect, limit),
    ]


__all__ = [
    "TEMPLATE_KINDS",
    "COMPLEXITY_BY_KIND",
    "DEFAULT_LIMIT",
    "DEFAULT_TOP_K",
    "Relationship",
    "RenderedQuery",
    "render_lookup_join",
    "render_aggregate_count",
    "render_aggregate_stats",
    "render_exists_anti_join",
    "render_distinct_count",
    "render_chain_join",
    "render_cte_latest_n_per_group",
    "render_lateral_top_k",
    "render_string_agg_details",
    "render_junction_n2m",
    "render_time_series_generate",
    "render_window_running_total",
    "render",
    "render_all",
]
