"""
VYRA - LLM Text-to-SQL Service
================================
Template SQL eşleşmediğinde LLM ile SQL üretimi.

Akış:
  1. Schema context + soru → LLM prompt oluştur
  2. LLM çağrısı (mevcut call_llm_api)
  3. Yanıttan SQL parse et (```sql ... ``` bloğu)
  4. Güvenlik doğrulaması (validate_sql + whitelist)

Güvenlik:
  - LLM'e sadece SELECT yazması söylenir
  - Üretilen SQL safe_sql_executor.validate_sql() ile doğrulanır
  - DDL/DML/injection kontrollerinden geçemeyen SQL reddedilir

Version: 2.58.0
"""

from __future__ import annotations

import re
import logging
import json
from typing import Dict, Any, Optional, List

from app.services.logging_service import log_system_event, log_warning

logger = logging.getLogger(__name__)


# =====================================================
# System Prompt
# =====================================================

TEXT_TO_SQL_SYSTEM_PROMPT = """Sen bir SQL uzmanısın. Kullanıcının doğal dildeki sorusunu SQL sorgusuna çeviriyorsun.

KRİTİK KURALLAR:
1. SADECE SELECT sorguları yaz. INSERT, UPDATE, DELETE, DROP, ALTER, CREATE gibi komutlar KESİNLİKLE YASAK.
2. Kullanıcının isteğini karşılamak için şemada verilen tablolar arasından en uygun tabloyu veya tabloları seç. Eğer soru birden fazla tablodaki veriyi ilgilendiriyorsa, tabloları birbiriyle uygun alanlar (ID) üzerinden JOIN ile birleştirerek sorguyu oluştur. Eğer kullanıcının isteğini çözecek (örn: "son giriş tarihi") sütun/tablolar şemada HİÇ YOKSA, KESİNLİKLE SQL üretme ve sadece Nedenini 'DIAGNOSTIC:' başlığı ile açıkla.
3. Yalnızca verilen şemadaki gerçek tablo ve sütunları kullan. Hayali sütun uydurma!
4. Sütunlardaki kelime veya metin aramalarında HER ZAMAN LOWER() ile LIKE veya ILIKE kullan (harf duyarlılığını aşmak için). KESİNLİKLE eşittir (=) kullanma.
5. Kullanıcı isim ve soyisim arıyorsa; tabloda Ad (Name) ve Soyad (Surname) kolonları AYRI ise iki sütunda da arama yap (örn: LOWER(Name) LIKE '%hakan%' AND LOWER(Surname) LIKE '%tütüncü%').
6. {dialect_rules}
7. Ürettiğin SQL'i KESİNLİKLE özel olarak ```sql <sorgu> ``` bloğu içine al. SQL kodunu bu blok dışına taşırma.
8. Kodun sonuna KESİNLİKLE noktalı virgül (;) koy. Ve SQL öncesinde "İş Adı"na atıf yaparak 1 cümlelik analiz yap.

DİALECT: {dialect}
"""


# =====================================================
# Prompt Builder
# =====================================================

def build_text_to_sql_prompt(
    query: str,
    schema_context: Dict[str, Any],
) -> List[Dict[str, str]]:
    """
    LLM'e gönderilecek Text-to-SQL prompt'unu oluşturur.

    Args:
        query: Kullanıcı sorusu
        schema_context: Schema bilgisi (get_schema_context() çıktısı)
            extra_context anahtarı varsa (örn. ML öğrenme bilgisi) prompt başına eklenir.

    Returns:
        LLM messages listesi
    """
    

    dialect = schema_context.get("dialect", "postgresql").lower()
    schema_text = format_schema_for_llm(schema_context)
    
    # Tüm veritabanları için özel kurallar (Best Practices)
    if dialect == "postgresql":
        dialect_rules = '''PostgreSQL Özel Kuralları:
  - Büyük/küçük harf duyarlılığını sağlamak için ŞEMA, TABLO ve SÜTUN adlarını DAİMA çift tırnak (") içine al. (Örn: SELECT * FROM "elysion"."T_ORG_USER")
  - Sorguya DAİMA "LIMIT 100" ekle.
  - Tarih işlemleri için CURRENT_DATE veya NOW() kullan.'''
    elif dialect == "mssql":
        dialect_rules = '''MSSQL Özel Kuralları:
  - Şema, tablo ve sütun adlarını köşeli parantez ([]) içine al. (Örn: SELECT * FROM [elysion].[T_ORG_USER])
  - MSSQL desteklemediği için KESİNLİKLE "LIMIT" anahtar kelimesini KULLANMA! Bunun yerine her sorgunun başına "SELECT TOP(100) ..." ekle.
  - Tarih işlemleri için GETDATE() veya CAST(GETDATE() AS DATE) kullan.'''
    elif dialect == "mysql":
        dialect_rules = '''MySQL Özel Kuralları:
  - Şema, tablo ve sütun adlarını ters tırnak (`) içine al.
  - Sorguya DAİMA "LIMIT 100" ekle.
  - Tarih işlemleri için CURDATE() veya NOW() kullan ve metin birleştirirken CONCAT() kullan.'''
    elif dialect == "oracle":
        dialect_rules = '''Oracle Özel Kuralları:
  - Anahtar kelimeleri korumak için çift tırnak (") kullan.
  - Oracle "LIMIT" desteklemez. Bunun yerine tam cümlenin sonuna "FETCH FIRST 100 ROWS ONLY" ekle.
  - Tarih işlemleri için SYSDATE kullan.'''
    else:
        dialect_rules = "Sorguya maksimum 100 satır sınırı ekle (LIMIT veya TOP) ve sütun adlarını veritabanının diline uygun quote et."

    system = TEXT_TO_SQL_SYSTEM_PROMPT.format(dialect=dialect, dialect_rules=dialect_rules)

    # ML öğrenme bilgisi varsa şema öncesine ekle
    extra_ctx = schema_context.get("extra_context", "")
    if extra_ctx:
        schema_block = f"{extra_ctx}\n\n{schema_text}"
    else:
        schema_block = schema_text

    user_msg = f"""VERİTABANI ŞEMASI:
{schema_block}

KULLANICI SORUSU:
{query}

Lütfen bu soruyu yanıtlayacak bir SELECT sorgusu yaz. SQL'i ```sql ... ``` bloğu içine yaz."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_msg},
    ]


# =====================================================
# SQL Parser
# =====================================================

def parse_sql_from_llm(response: str) -> Optional[str]:
    """
    LLM yanıtından SQL sorgusunu çıkarır.

    Arar:
    1. ```sql ... ``` bloğu
    2. ``` ... ``` bloğu (sql etiketi olmayan)
    3. SELECT ile başlayan satırlar (fallback)

    Args:
        response: LLM yanıt metni

    Returns:
        Temizlenmiş SQL sorgusu veya None
    """
    if not response or not response.strip():
        return None

    # 1. ```sql ... ``` bloğu
    match = re.search(r'```sql\s*\n?(.*?)\n?```', response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(1).strip()
        if sql:
            return _clean_sql(sql)

    # 2. ``` ... ``` bloğu (etiket yok)
    match = re.search(r'```\s*\n?(.*?)\n?```', response, re.DOTALL)
    if match:
        sql = match.group(1).strip()
        if sql and sql.upper().startswith(("SELECT", "WITH")):
            return _clean_sql(sql)

    # 3. Fallback: SELECT ile başlayan satırları topla
    lines = response.strip().split("\n")
    sql_lines = []
    collecting = False
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith(("SELECT", "WITH")):
            collecting = True
        if collecting:
            sql_lines.append(stripped)
            # Noktalı virgül ile bitiyor mu?
            if stripped.endswith(";"):
                break

    if sql_lines:
        return _clean_sql("\n".join(sql_lines))

    return None


def _clean_sql(sql: str) -> str:
    """SQL'i temizler: trailing semicolon, fazla boşluk."""
    sql = sql.strip()
    sql = sql.rstrip(";").strip()
    # Birden fazla boşluğu tekle
    sql = re.sub(r'\s+', ' ', sql)
    return sql


# =====================================================
# Ana Fonksiyon: LLM ile SQL Üretimi
# =====================================================

def generate_sql(
    query: str,
    schema_context: Dict[str, Any],
    allowed_tables: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    LLM kullanarak kullanıcı sorusundan SQL üretir.

    Pipeline:
    1. Prompt oluştur
    2. LLM çağır
    3. SQL parse et
    4. Güvenlik doğrulaması (validate_sql + whitelist)

    Args:
        query: Kullanıcı sorusu
        schema_context: Schema bilgisi
        allowed_tables: İzin verilen tablo adları (whitelist)

    Returns:
        {
            "success": True/False,
            "sql": "SELECT ...",
            "explanation": "LLM açıklaması",
            "error": None veya hata mesajı
        }
    """
    from app.core.llm import call_llm_api
    from app.services.safe_sql_executor import validate_sql, check_table_whitelist

    # 1. Prompt oluştur
    messages = build_text_to_sql_prompt(query, schema_context)

    # 2. LLM çağır
    try:
        llm_response = call_llm_api(messages)
    except Exception as e:
        log_warning(f"Text-to-SQL LLM çağrısı başarısız: {e}", "hybrid_router")
        return {
            "success": False,
            "sql": None,
            "explanation": None,
            "error": f"LLM hatası: {str(e)[:200]}",
        }

    if not llm_response:
        return {
            "success": False,
            "sql": None,
            "explanation": None,
            "error": "LLM boş yanıt döndü",
        }

    log_system_event(
        "DEBUG",
        f"Text-to-SQL LLM yanıtı: {llm_response[:200]}...",
        "hybrid_router"
    )

    # 3. SQL parse et
    sql = parse_sql_from_llm(llm_response)
    if not sql:
        # v3.6.8: DIAGNOSTIC mekanizması — Şemada veri yoksa LLM mantıklı bir hata dönebilir
        diagnostic_match = re.search(r'DIAGNOSTIC:\s*(.*)', llm_response, re.IGNORECASE | re.DOTALL)
        error_msg = "LLM yanıtından SQL parse edilemedi, sistem sorunuz için geçerli bir tablo eşleştirememiş olabilir."
        if diagnostic_match:
            error_msg = diagnostic_match.group(1).strip()
            
        return {
            "success": False,
            "sql": None,
            "explanation": llm_response[:500],
            "error": error_msg,
        }

    # 4. Güvenlik doğrulaması
    is_valid, validation_error = validate_sql(sql)
    if not is_valid:
        log_warning(
            f"Text-to-SQL güvenlik reddi: {validation_error} | SQL: {sql[:200]}",
            "hybrid_router"
        )
        return {
            "success": False,
            "sql": sql,
            "explanation": llm_response[:300],
            "error": f"Güvenlik: {validation_error}",
        }

    # 5. Whitelist kontrolü
    if allowed_tables:
        dialect = schema_context.get("dialect", "postgresql")
        is_allowed, table_error = check_table_whitelist(sql, allowed_tables, dialect)
        if not is_allowed:
            log_warning(
                f"Text-to-SQL whitelist reddi: {table_error}",
                "hybrid_router"
            )
            return {
                "success": False,
                "sql": sql,
                "explanation": llm_response[:300],
                "error": table_error,
            }

    # Açıklamayı çıkar (SQL bloğundan önceki metin)
    explanation = _extract_explanation(llm_response)

    log_system_event(
        "INFO",
        f"Text-to-SQL başarılı: {sql[:100]}",
        "hybrid_router"
    )

    return {
        "success": True,
        "sql": sql,
        "explanation": explanation,
        "error": None,
    }


def _extract_explanation(llm_response: str) -> str:
    """LLM yanıtından SQL öncesi açıklamayı çıkarır."""
    # ```sql bloğundan önceki metni al
    match = re.search(r'```(?:sql)?', llm_response, re.IGNORECASE)
    if match:
        before = llm_response[:match.start()].strip()
        if before:
            return before[:500]
    return ""


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

        # 🆕 v5.0: Kolon enrichment bilgilerini al (iş isimleri, eşanlamlılar)
        col_enrichments_map = {}  # {(schema, table): {col_name: {business_name_tr, ...}}}
        try:
            cur.execute("""
                SELECT te.schema_name, te.table_name,
                       ce.column_name, ce.business_name_tr AS col_bname,
                       ce.admin_label_tr AS col_admin_label,
                       ce.synonyms_json, ce.is_searchable, ce.semantic_type
                FROM ds_column_enrichments ce
                JOIN ds_table_enrichments te ON te.id = ce.table_enrichment_id
                WHERE te.source_id = %s AND te.is_active = TRUE AND te.admin_approved = TRUE
            """, (source_id,))
            for crow in cur.fetchall():
                key = (crow.get("schema_name") or "", crow["table_name"])
                col_name = crow["column_name"]

                # Synonyms parse
                synonyms = []
                raw_syn = crow.get("synonyms_json")
                if raw_syn:
                    try:
                        synonyms = json.loads(raw_syn) if isinstance(raw_syn, str) else (raw_syn or [])
                    except Exception:
                        synonyms = []

                col_enrichments_map.setdefault(key, {})[col_name] = {
                    "business_name_tr": crow.get("col_bname") or crow.get("col_admin_label") or "",
                    "synonyms": synonyms,
                    "is_searchable": crow.get("is_searchable", False),
                    "semantic_type": crow.get("semantic_type") or "",
                }
        except Exception:
            pass  # synonyms_json kolonu henüz yoksa sessizce geç

        # Tablolara kolon enrichment'larını ekle
        for t in tables:
            key = (t.get("schema") or "", t["name"])
            t["col_enrichments"] = col_enrichments_map.get(key, {})

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
        col_enrichments = t.get("col_enrichments", {})
        col_names = []
        pk_cols = []
        date_cols = []

        for c in cols[:50]:  # Max 50 kolon prompt'a alınır
            col_name = c['name']
            col_dtype = c['data_type']
            # 🆕 v5.0: Kolon iş ismi eklendi
            enr = col_enrichments.get(col_name, {})
            bname_col = enr.get("business_name_tr", "")
            if bname_col:
                col_names.append(f"{col_name} ({col_dtype}) [{bname_col}]")
            else:
                col_names.append(f"{col_name} ({col_dtype})")
            if c.get("is_pk"):
                pk_cols.append(col_name)
            if c.get("data_type", "").lower() in (
                "timestamp", "timestamptz", "datetime", "date",
                "timestamp without time zone", "timestamp with time zone"
            ):
                date_cols.append(col_name)

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
        parts.append(f"   Sütunlar: {', '.join(col_names[:50])}")
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

