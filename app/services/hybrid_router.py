"""
VYRA - Hybrid Router Service
==============================
Intent'e göre Document RAG, DB Query veya her ikisini çağıran orkestrasyon servisi.

Pipeline:
  Kullanıcı Sorusu
       ↓
  Intent Router → document / database / both
       ↓              ↓
  Document RAG   DB Text-to-SQL (template shortcuts)
       ↓              ↓
  Birleşik Yanıt

v3.1.0: Enrichment-Aware Routing
  - get_schema_context() → ds_table_enrichments LEFT JOIN
  - match_template_query() → Türkçe iş adı eşleştirme
  - format_schema_for_llm() → Türkçe açıklamalar LLM context'e dahil

Version: 3.1.0
"""

from __future__ import annotations

import re
import json
import time
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from app.services.deep_think.types import IntentType, IntentResult
from app.services.logging_service import log_system_event, log_warning

logger = logging.getLogger(__name__)


# =====================================================
# Sonuç Veri Sınıfı
# =====================================================

@dataclass
class HybridResult:
    """Hybrid Router sonucu."""
    db_results: List[Dict[str, Any]] = field(default_factory=list)
    rag_results: List[Dict[str, Any]] = field(default_factory=list)
    sql_executed: Optional[str] = None
    source_db: Optional[str] = None
    db_error: Optional[str] = None
    elapsed_ms: float = 0.0


# =====================================================
# DB Intent Pattern'leri
# =====================================================

# Canlı veritabanı sorgusu gerektiren kalıplar
DB_PATTERNS = [
    # Sayısal sorgular
    r'\bkaç\s+(kayıt|adet|tane|satır|kişi|müşteri|sipariş|fatura|kullanıcı|ürün)',
    r'\b(toplam|total)\s+(tutar|miktar|adet|hacim|sayı|süre)',
    r'\b(son|en\s+son|güncel)\s+(fatura|sipariş|ödeme|işlem|kayıt)',
    r'\b(bakiye|hesap\s+bakiye|borç|alacak|kalan)',
    r'\b(ortalama|average|ort)\s+\w+',
    r'\b(minimum|min|en\s+düşük)\s+\w+',
    r'\b(maksimum|max|en\s+yüksek)\s+\w+',
    # Tablo/veri erişimi
    r'\b(müşteri|kullanıcı|ürün|sipariş|fatura)\s+(sayısı|listesi|raporu)',
    r'\b(aylık|haftalık|günlük|yıllık)\s+(rapor|özet|istatistik)',
    r'\btablodaki\s+\w+',
    r'\bveritabanındaki\s+\w+',
    # Doğrudan SQL referansları
    r'\bSQL\s+(sorgula|çalıştır|yürüt)',
    r'\bsorguyla\s+(bul|getir|ara)',
]

# Hem doküman hem DB gerektiren kalıplar
HYBRID_PATTERNS = [
    r'\b(nasıl|nedir).+ve.+(kaç|toplam|sayısı)',
    r'\b(açıklama|tanım).+ve.+(son|güncel)\s+(veri|kayıt)',
]


# =====================================================
# Intent Analizi (DB-aware)
# =====================================================

def detect_db_intent(query: str) -> Optional[IntentType]:
    """
    Sorgunun veritabanı sorgusu gerektirip gerektirmediğini belirler.

    Args:
        query: Kullanıcı sorusu

    Returns:
        IntentType.DATABASE_QUERY, IntentType.HYBRID veya None
    """
    query_lower = query.lower()

    # Hybrid kontrol (hem doc hem db)
    for pattern in HYBRID_PATTERNS:
        if re.search(pattern, query_lower):
            return IntentType.HYBRID

    # DB intent kontrol
    db_matches = sum(1 for p in DB_PATTERNS if re.search(p, query_lower))
    if db_matches >= 1:
        return IntentType.DATABASE_QUERY

    return None


# =====================================================
# Schema Context Builder
# =====================================================

def get_schema_context(source_id: int) -> Dict[str, Any]:
    """
    DS Learning'den öğrenilmiş schema bilgilerini context olarak hazırlar.

    Bu context LLM'e tablo yapısını anlatır ve SQL üretiminde kullanılır.

    Args:
        source_id: Veri kaynağı ID

    Returns:
        {
            "tables": [...],
            "relationships": [...],
            "dialect": "postgresql",
            "source_name": "...",
        }
    """
    try:
        from app.core.db import get_db_conn

        conn = get_db_conn()
        cur = conn.cursor()

        # Kaynak bilgisi
        cur.execute(
            "SELECT name, db_type FROM data_sources WHERE id = %s",
            (source_id,)
        )
        source_row = cur.fetchone()
        if not source_row:
            conn.close()
            return {}

        source_name = source_row["name"]
        dialect = source_row["db_type"]

        # 🆕 v3.1.0: Tablolar + Enrichment bilgileri (LEFT JOIN)
        cur.execute("""
            SELECT o.schema_name, o.object_name, o.object_type, o.column_count,
                   o.row_count_estimate, o.columns_json,
                   e.business_name_tr, e.admin_label_tr,
                   e.category, e.description_tr
            FROM ds_db_objects o
            LEFT JOIN ds_table_enrichments e
                ON e.source_id = o.source_id
                AND e.table_name = o.object_name
                AND COALESCE(e.schema_name, '') = COALESCE(o.schema_name, '')
                AND e.is_active = TRUE
            WHERE o.source_id = %s AND o.object_type = 'table'
            ORDER BY o.object_name
        """, (source_id,))

        tables = []
        for row in cur.fetchall():
            columns_json = row["columns_json"]
            if columns_json is None:
                columns_json = []
            elif isinstance(columns_json, str):
                try:
                    columns_json = json.loads(columns_json)
                except (json.JSONDecodeError, TypeError):
                    columns_json = []
            elif not isinstance(columns_json, list):
                columns_json = []

            tables.append({
                "schema": row["schema_name"],
                "name": row["object_name"],
                "type": row["object_type"],
                "columns": columns_json,
                "column_count": row["column_count"],
                "row_estimate": row["row_count_estimate"],
                # 🆕 v3.1.0: Enrichment bilgileri
                "business_name_tr": row.get("business_name_tr", "") or "",
                "admin_label_tr": row.get("admin_label_tr", "") or "",
                "category": row.get("category", "") or "",
                "description_tr": row.get("description_tr", "") or "",
            })

        # İlişkiler
        cur.execute("""
            SELECT from_schema, from_table, from_column,
                   to_schema, to_table, to_column, constraint_name
            FROM ds_db_relationships
            WHERE source_id = %s
        """, (source_id,))

        relationships = []
        for row in cur.fetchall():
            relationships.append({
                "from": f"{row['from_schema']}.{row['from_table']}.{row['from_column']}",
                "to": f"{row['to_schema']}.{row['to_table']}.{row['to_column']}",
                "constraint": row["constraint_name"],
            })

        conn.close()

        return {
            "tables": tables,
            "relationships": relationships,
            "dialect": dialect,
            "source_name": source_name,
            "source_id": source_id,
        }

    except Exception as e:
        log_warning(f"Schema context alınamadı: {e}", "hybrid_router")
        return {}


def format_schema_for_llm(schema_context: Dict[str, Any]) -> str:
    """
    Schema bilgilerini LLM'e gönderilebilecek context formatına çevirir.

    Args:
        schema_context: get_schema_context() çıktısı

    Returns:
        LLM'e gönderilecek schema açıklaması
    """
    if not schema_context or not schema_context.get("tables"):
        return ""

    parts = [f"Veritabanı: {schema_context.get('source_name', 'Bilinmeyen')}"]
    parts.append(f"Dialect: {schema_context.get('dialect', 'postgresql')}")
    parts.append(f"Tablo sayısı: {len(schema_context['tables'])}")
    parts.append("")

    for t in schema_context["tables"][:30]:  # Max 30 tablo context'e alınır
        cols = t.get("columns", [])
        col_names = []
        pk_cols = []
        date_cols = []

        for c in cols:
            col_names.append(f"{c['name']} ({c['data_type']})")
            if c.get("is_pk"):
                pk_cols.append(c["name"])
            if c.get("data_type", "").lower() in (
                "timestamp", "timestamptz", "datetime", "date",
                "timestamp without time zone", "timestamp with time zone"
            ):
                date_cols.append(c["name"])

        # 🆕 v3.1.0: Enrichment bilgilerini LLM context'e dahil et
        bname = t.get("admin_label_tr") or t.get("business_name_tr") or ""
        desc = t.get("description_tr", "")
        label = f"📋 {t.get('schema', '')}.{t['name']}"
        if bname:
            label += f" [{bname}]"
        label += f" (~{t.get('row_estimate', 0)} satır)"
        parts.append(label)
        if desc:
            parts.append(f"   Açıklama: {desc}")
        if pk_cols:
            parts.append(f"   PK: {', '.join(pk_cols)}")
        parts.append(f"   Sütunlar: {', '.join(col_names[:20])}")
        if date_cols:
            parts.append(f"   Tarih sütunları: {', '.join(date_cols)}")
        parts.append("")

    # İlişkiler
    rels = schema_context.get("relationships", [])
    if rels:
        parts.append("İlişkiler:")
        for r in rels[:20]:  # Max 20 ilişki
            parts.append(f"  {r['from']} → {r['to']}")
        parts.append("")

    return "\n".join(parts)


# =====================================================
# Template SQL Matching
# =====================================================

def match_template_query(
    query: str,
    schema_context: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """
    Kullanıcı sorusunu template SQL kalıplarıyla eşleştirmeye çalışır.

    Basit kural tabanlı eşleşme — Faz 2'de LLM Text-to-SQL eklenecek.

    Args:
        query: Kullanıcı sorusu
        schema_context: Schema context bilgisi

    Returns:
        {
            "template": "row_count",
            "table": "users",
            "col": "salary",  # opsiyonel
            "date_col": "created_at",  # opsiyonel
        }
        veya None (eşleşme yoksa)
    """
    query_lower = query.lower()
    tables = schema_context.get("tables", [])
    dialect = schema_context.get("dialect", "postgresql")

    if not tables:
        return None

    # 🆕 v3.1.0: Hangi tablo hakkında sorulduğunu bul (enrichment alias'ları dahil)
    matched_table = None
    # Türkçe ek kalıpları
    tr_suffixes = (
        "lar", "ler", "da", "de", "dan", "den", "ki", "daki", "deki",
        "nın", "nin", "nun", "nün", "ın", "in", "un", "ün",
        "ları", "leri", "ları", "ya", "ye", "na", "ne"
    )
    for t in tables:
        # Aday isimler: teknik ad + Türkçe iş adı + admin etiketi
        aliases = [t["name"].lower()]
        if t.get("business_name_tr"):
            aliases.append(t["business_name_tr"].lower())
        if t.get("admin_label_tr"):
            aliases.append(t["admin_label_tr"].lower())

        for alias in aliases:
            if not alias:
                continue
            # Doğrudan eşleşme
            if alias in query_lower:
                matched_table = t
                break
            # Türkçe çoğul/ek kontrolü
            for suffix in tr_suffixes:
                if f"{alias}{suffix}" in query_lower or f"{alias}'{suffix}" in query_lower:
                    matched_table = t
                    break
            if matched_table:
                break
        if matched_table:
            break

    if not matched_table:
        return None

    # Hangi sütun hakkında sorulduğunu bul (opsiyonel)
    matched_col = None
    for c in matched_table.get("columns", []):
        col_name = c["name"].lower()
        if col_name in query_lower and col_name not in ("id", "name", "type"):
            matched_col = c["name"]
            break

    # Tarih sütununu bul (en son / sıralama için)
    date_col = None
    for c in matched_table.get("columns", []):
        if c.get("data_type", "").lower() in (
            "timestamp", "timestamptz", "datetime", "date",
            "timestamp without time zone", "timestamp with time zone"
        ):
            date_col = c["name"]
            break

    # Template eşleştirme
    result = {
        "table": matched_table["name"],
        "schema": matched_table.get("schema"),
        "dialect": dialect,
    }

    # "kaç kayıt", "kaç tane", "sayısı"
    if re.search(r'\bkaç\s+(kayıt|adet|tane|satır)', query_lower) or \
       re.search(r'\b(sayısı|adedi|toplam\s+sayı)\b', query_lower):
        result["template"] = "row_count"
        return result

    # "toplam", "sum"
    if re.search(r'\b(toplam|sum)\b', query_lower) and matched_col:
        result["template"] = "sum_column"
        result["col"] = matched_col
        return result

    # "ortalama", "average"
    if re.search(r'\b(ortalama|average|ort)\b', query_lower) and matched_col:
        result["template"] = "avg_column"
        result["col"] = matched_col
        return result

    # "minimum", "en düşük"
    if re.search(r'\b(minimum|min|en\s+düşük)\b', query_lower) and matched_col:
        result["template"] = "min_column"
        result["col"] = matched_col
        return result

    # "maksimum", "en yüksek"
    if re.search(r'\b(maksimum|max|en\s+yüksek)\b', query_lower) and matched_col:
        result["template"] = "max_column"
        result["col"] = matched_col
        return result

    # "son", "en son", "güncel"
    if re.search(r'\b(son|en\s+son|güncel|latest)\b', query_lower) and date_col:
        result["template"] = "latest_records"
        result["date_col"] = date_col
        return result

    # "farklı", "unique", "distinct"
    if re.search(r'\b(farklı|unique|distinct|benzersiz)\b', query_lower) and matched_col:
        result["template"] = "distinct_count"
        result["col"] = matched_col
        return result

    # Genel count fallback — tablo bulundu ama özel template yok
    if re.search(r'\bkaç\b', query_lower):
        result["template"] = "row_count"
        return result

    return None


# =====================================================
# Hybrid Router
# =====================================================

class HybridRouter:
    """
    Intent'e göre Document RAG, DB Query veya her ikisini çağıran orkestrasyon servisi.

    Kullanım:
        router = HybridRouter()
        result = router.route(query, user_id, intent)
        if result:
            # Hybrid sonuç var — DB sorgusu çalıştırıldı
        else:
            # Standart RAG pipeline devam eder
    """

    def route(
        self,
        query: str,
        user_id: int,
        intent: IntentResult,
    ) -> Optional[HybridResult]:
        """
        Soruyu intent'e göre yönlendirir.

        - DATABASE_QUERY → Sadece DB sorgusu
        - HYBRID → Hem DB hem RAG
        - Diğer → None (standart RAG akışı)

        Args:
            query: Kullanıcı sorusu
            user_id: Kullanıcı ID
            intent: Intent analiz sonucu

        Returns:
            HybridResult veya None
        """
        if intent.intent_type not in (IntentType.DATABASE_QUERY, IntentType.HYBRID):
            return None

        start = time.time()

        log_system_event(
            "INFO",
            f"Hybrid Router: {intent.intent_type.value} intent, "
            f"query='{query[:50]}...'",
            "hybrid_router"
        )

        # Kullanıcının erişebildiği DB kaynaklarını bul
        db_sources = self._get_user_db_sources(user_id)

        if not db_sources:
            log_system_event(
                "INFO",
                "Hybrid Router: Kullanıcının DB kaynağı yok, RAG'a fallback",
                "hybrid_router"
            )
            return None  # DB kaynağı yoksa standart RAG'a geri dön

        # Her kaynak için schema context al ve template eşleştir
        for source in db_sources:
            source_id = source["id"]
            schema_ctx = get_schema_context(source_id)

            if not schema_ctx or not schema_ctx.get("tables"):
                continue

            # Template SQL eşleştirme dene
            template_match = match_template_query(query, schema_ctx)

            if template_match:
                # Template SQL bulundu — çalıştır
                db_result = self._execute_template(template_match, source, schema_ctx)

                elapsed = (time.time() - start) * 1000

                return HybridResult(
                    db_results=db_result.get("data", []),
                    sql_executed=db_result.get("sql", ""),
                    source_db=schema_ctx.get("source_name", ""),
                    db_error=db_result.get("error"),
                    elapsed_ms=elapsed,
                )

            # 🆕 v2.58.0: Template eşleşmedi → LLM Text-to-SQL fallback
            llm_result = self._generate_and_execute_llm_sql(query, source, schema_ctx)
            if llm_result is not None:
                return llm_result

        # Hiçbir template veya LLM SQL eşleşmedi
        log_system_event(
            "INFO",
            "Hybrid Router: Template + LLM eşleşmesi bulunamadı, RAG'a fallback",
            "hybrid_router"
        )
        return None

    def _get_user_db_sources(self, user_id: int) -> List[Dict[str, Any]]:
        """
        Kullanıcının erişebildiği DB veri kaynaklarını döndürür.

        Kriterler:
        - source_type = 'database'
        - status = 'active'
        - ds_db_objects tablosunda keşfedilmiş objeleri var
        """
        try:
            from app.core.db import get_db_conn

            conn = get_db_conn()
            cur = conn.cursor()

            # Aktif DB kaynakları (keşfi tamamlanmış)
            cur.execute("""
                SELECT ds.id, ds.name, ds.db_type, ds.host, ds.port,
                       ds.db_name, ds.db_user, ds.db_password_encrypted
                FROM data_sources ds
                WHERE ds.source_type = 'database'
                  AND ds.is_active = TRUE
                  AND EXISTS (
                      SELECT 1 FROM ds_db_objects dbo
                      WHERE dbo.source_id = ds.id
                  )
                ORDER BY ds.name
                LIMIT 5
            """)

            sources = []
            for row in cur.fetchall():
                sources.append({
                    "id": row["id"],
                    "name": row["name"],
                    "db_type": row["db_type"],
                    "host": row["host"],
                    "port": row["port"],
                    "db_name": row["db_name"],
                    "db_user": row["db_user"],
                    "db_password_encrypted": row["db_password_encrypted"],
                })

            conn.close()
            return sources

        except Exception as e:
            log_warning(f"DB kaynakları alınamadı: {e}", "hybrid_router")
            return []

    def _execute_template(
        self,
        template_match: Dict[str, Any],
        source: Dict[str, Any],
        schema_ctx: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Template SQL eşleşmesini çalıştırır.

        Args:
            template_match: match_template_query() çıktısı
            source: Veri kaynağı bağlantı bilgileri
            schema_ctx: Schema context

        Returns:
            {"data": [...], "sql": "...", "error": None}
        """
        from app.services.sql_dialect import build_template_sql
        from app.services.safe_sql_executor import SafeSQLExecutor

        dialect = template_match.get("dialect", "postgresql")
        template_name = template_match.get("template")
        table = template_match.get("table")
        schema = template_match.get("schema")
        col = template_match.get("col")
        date_col = template_match.get("date_col")

        # SQL üret
        sql = build_template_sql(
            template_name=template_name,
            table=table,
            dialect=dialect,
            schema=schema,
            col=col,
            date_col=date_col,
            row_limit=100,
        )

        if not sql:
            return {"data": [], "sql": "", "error": "SQL template üretilemedi"}

        log_system_event(
            "INFO",
            f"Hybrid Router: Template '{template_name}' → SQL: {sql[:100]}",
            "hybrid_router"
        )

        # Güvenli çalıştır
        executor = SafeSQLExecutor()
        allowed_tables = executor.get_allowed_tables(source["id"])

        result = executor.execute(
            sql=sql,
            source=source,
            dialect=dialect,
            allowed_tables=allowed_tables,
        )

        if result.success:
            return {
                "data": result.data,
                "sql": result.sql_executed,
                "error": None,
                "row_count": result.row_count,
                "columns": result.columns,
            }
        else:
            return {
                "data": [],
                "sql": result.sql_executed,
                "error": result.error,
            }

    def _generate_and_execute_llm_sql(
        self,
        query: str,
        source: Dict[str, Any],
        schema_ctx: Dict[str, Any],
    ) -> Optional[HybridResult]:
        """
        🆕 v2.58.0: LLM ile SQL üretir ve güvenli şekilde çalıştırır.

        Template eşleşmediğinde fallback olarak kullanılır.

        Args:
            query: Kullanıcı sorusu
            source: Veri kaynağı bağlantı bilgileri
            schema_ctx: Schema context

        Returns:
            HybridResult veya None (LLM SQL üretemezse)
        """
        try:
            from app.services.text_to_sql import generate_sql
            from app.services.safe_sql_executor import SafeSQLExecutor

            # LLM'den SQL üret
            executor = SafeSQLExecutor()
            allowed_tables = executor.get_allowed_tables(source["id"])

            gen_result = generate_sql(
                query=query,
                schema_context=schema_ctx,
                allowed_tables=allowed_tables,
            )

            if not gen_result["success"]:
                log_system_event(
                    "INFO",
                    f"Text-to-SQL başarısız: {gen_result.get('error', '')}",
                    "hybrid_router"
                )
                return None

            sql = gen_result["sql"]
            dialect = schema_ctx.get("dialect", "postgresql")

            log_system_event(
                "INFO",
                f"Text-to-SQL üretildi: {sql[:100]}",
                "hybrid_router"
            )

            # Güvenli çalıştır
            result = executor.execute(
                sql=sql,
                source=source,
                dialect=dialect,
                allowed_tables=allowed_tables,
            )


            if result.success and result.data:
                return HybridResult(
                    db_results=result.data,
                    sql_executed=result.sql_executed,
                    source_db=schema_ctx.get("source_name", ""),
                    db_error=None,
                    elapsed_ms=result.elapsed_ms,
                )
            elif not result.success:
                log_warning(
                    f"Text-to-SQL yürütme hatası: {result.error}",
                    "hybrid_router"
                )
                return None
            else:
                # Başarılı ama veri yok
                return HybridResult(
                    db_results=[],
                    sql_executed=result.sql_executed,
                    source_db=schema_ctx.get("source_name", ""),
                    db_error=None,
                    elapsed_ms=result.elapsed_ms,
                )

        except Exception as e:
            log_warning(f"Text-to-SQL hata: {e}", "hybrid_router")
            return None
