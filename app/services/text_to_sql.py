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

Version: 3.9.0
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

TEXT_TO_SQL_SYSTEM_PROMPT = """Sen kurumsal veritabanları konusunda uzman bir SQL analistsin. Kullanıcının doğal dildeki sorusunu adım adım analiz ederek profesyonel SQL sorgusuna çeviriyorsun.

DÜŞÜNME SÜRECİ (Chain-of-Thought):
SQL yazmadan ÖNCE aşağıdaki adımları kısaca analiz et:
1. TABLO SEÇİMİ: Kullanıcının sorusu hangi tablolardaki verileri gerektiriyor?
2. JOIN STRATEJİSİ: Bu tablolar nasıl bağlanıyor? FK ilişkilerini kontrol et ve JOIN yolunu belirle.
3. FİLTRE & KOŞULLAR: Hangi WHERE koşulları gerekli? Tarih aralığı, durum filtresi vb.
4. GRUPLAMA & SIRALAMA: GROUP BY, ORDER BY, HAVING gerekli mi?
5. SQL YAZI: Yukarıdaki analizi kullanarak sorguyu oluştur.

KRİTİK KURALLAR:
1. SADECE SELECT sorguları yaz. INSERT, UPDATE, DELETE, DROP, ALTER, CREATE gibi komutlar KESİNLİKLE YASAK.
2. Kullanıcının isteğini karşılamak için şemada verilen tablolar arasından en uygun tabloyu veya tabloları seç. Eğer soru birden fazla tablodaki veriyi ilgilendiriyorsa, tabloları birbiriyle uygun alanlar (ID) üzerinden JOIN ile birleştirerek sorguyu oluştur. Eğer kullanıcının isteğini çözecek (örn: "son giriş tarihi") sütun/tablolar şemada HİÇ YOKSA, KESİNLİKLE SQL üretme ve sadece Nedenini 'DIAGNOSTIC:' başlığı ile açıkla.
3. KRİTİK HALÜSİNASYON YASAĞI: Yalnızca şemada YAZILI olan gerçek tablo ve sütun adlarını kullan. Şemada OLMAYAN kolon adı ASLA kullanma — tahmin etme, uydurma, benzer isim türetme. Eğer uygun sütun bulamıyorsan SQL üretme, DIAGNOSTIC yaz. Örneğin şemada "VALUE" yazıyorsa "USAGE_AMOUNT" veya "TOPLAM_KULLANIM" gibi isim UYDURMA, doğrudan "VALUE" kullan.
4. Metin aramasında büyük/küçük harf duyarsız karşılaştırma kullan (PostgreSQL: ILIKE, Oracle: UPPER(), MSSQL: COLLATE). KESİNLİKLE eşittir (=) kullanma.
5. Kullanıcı isim ve soyisim arıyorsa; tabloda Ad (Name) ve Soyad (Surname) kolonları AYRI ise iki sütunda da arama yap (örn: LOWER(Name) LIKE '%hakan%' AND LOWER(Surname) LIKE '%tütüncü%').
6. {dialect_rules}
7. Ürettiğin SQL'i KESİNLİKLE özel olarak ```sql <sorgu> ``` bloğu içine al. SQL kodunu bu blok dışına taşırma.
8. Kodun sonuna KESİNLİKLE noktalı virgül (;) koy. Ve SQL öncesinde "İş Adı"na atıf yaparak kısa analiz yap.

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
    schema_text = format_schema_for_llm(schema_context, query=query)

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
  - Tablo ve kolon adlarını çift tırnak (") içinde schema ile kullan: "SCHEMA"."TABLO"."KOLON"
  - Oracle "LIMIT" desteklemez. Bunun yerine "FETCH FIRST N ROWS ONLY" ekle.
  - Tarih işlemleri için SYSDATE kullan.
  - COUNT, SUM gibi aggregate fonksiyonlar doğrudan tabloda çalışır. "FROM dual" KULLANMA.
  - Birden fazla tablodan COUNT almak için subquery veya UNION ALL kullan, dual kullanma.'''
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

    # v4.0 Enhanced few-shot: Tüm tablolardan örnek sorular, max 5 toplam
    examples_block = ""
    all_examples = []
    for tbl in (schema_context.get("tables") or [])[:15]:
        sq = tbl.get("sample_questions")
        if sq and isinstance(sq, list):
            tbl_label = (
                tbl.get("admin_label_tr") or tbl.get("business_name_tr")
                or f"{tbl.get('schema', '')}.{tbl.get('name', '')}"
            )
            for q in sq[:2]:  # Her tablodan max 2 örnek
                if q and isinstance(q, str) and q.strip():
                    all_examples.append(f"-- [{tbl_label}]: {q.strip()}")
    if all_examples:
        examples_block = "\n".join(all_examples[:5])  # Toplam max 5
    if examples_block:
        user_msg += f"\n\nÖRNEK SORULAR (benzer sorgular için referans):\n{examples_block}"

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
    schema_hint: Optional[str] = None,
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

    # v4.0: schema_hint ile tablo önceliklendirmesi
    if schema_hint:
        ctx_tables = filter_tables_by_schema_hint(
            schema_context.get("tables", []), schema_hint
        )
        schema_context = dict(schema_context)
        schema_context["tables"] = ctx_tables

    # 1. Prompt oluştur
    messages = build_text_to_sql_prompt(query, schema_context)

    # 2. LLM çağır (temperature=0.1 ile daha deterministik SQL üretimi)
    try:
        llm_response = call_llm_api(messages, temperature=0.1)
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

    # M3: Parse başarısızsa bir kez daha basit prompt ile dene
    if not sql:
        # v3.6.8: DIAGNOSTIC mekanizması — Şemada veri yoksa LLM mantıklı bir hata dönebilir
        diagnostic_match = re.search(r'DIAGNOSTIC:\s*(.*)', llm_response, re.IGNORECASE | re.DOTALL)
        if diagnostic_match:
            # Gerçek bir DIAGNOSTIC yanıtı — retry gerekmez
            return {
                "success": False,
                "sql": None,
                "explanation": llm_response[:500],
                "error": diagnostic_match.group(1).strip(),
            }

        # Basit prompt ile tek retry
        log_system_event(
            "INFO",
            "Text-to-SQL parse başarısız, basit prompt ile retry yapılıyor",
            "hybrid_router"
        )
        retry_messages = messages.copy()
        retry_messages.append({"role": "assistant", "content": llm_response})
        retry_messages.append({
            "role": "user",
            "content": "Lütfen sadece SQL sorgusu döndür, başka açıklama ekleme. "
                       "SQL'i ```sql ... ``` bloğu içine yaz."
        })
        try:
            retry_response = call_llm_api(retry_messages, temperature=0.1)
            if retry_response:
                sql = parse_sql_from_llm(retry_response)
                if sql:
                    llm_response = retry_response  # açıklama çıkarmak için güncelle
                    log_system_event(
                        "INFO",
                        f"Text-to-SQL retry başarılı: {sql[:100]}",
                        "hybrid_router"
                    )
        except Exception as retry_err:
            log_warning(f"Text-to-SQL retry hatası: {retry_err}", "hybrid_router")

    if not sql:
        error_msg = "LLM yanıtından SQL parse edilemedi, sistem sorunuz için geçerli bir tablo eşleştirememiş olabilir."
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

    # 6. v3.14.0: Halüsinasyon kontrolü — SQL'deki kolonları şema ile karşılaştır
    hallucination_warning = _check_column_hallucination(sql, schema_context)
    if hallucination_warning:
        log_warning(f"Text-to-SQL halüsinasyon tespit: {hallucination_warning}", "hybrid_router")

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
        "hallucination_warning": hallucination_warning,
    }


# =====================================================
# v3.9.0: SQL Self-Healing / Retry
# =====================================================

def generate_sql_with_retry(
    query: str,
    schema_context: Dict[str, Any],
    allowed_tables: Optional[List[str]] = None,
    execution_error: Optional[str] = None,
    failed_sql: Optional[str] = None,
    max_retries: int = 2,
) -> Dict[str, Any]:
    """
    v3.9.0: SQL Self-Healing — İlk üretim başarısızsa hata bilgisiyle düzeltme denemesi.

    Pipeline:
    1. İlk denemede generate_sql() çağrısı
    2. DB execution hatası alınırsa, hata mesajını LLM'e geri gönder
    3. LLM düzeltilmiş SQL üretir → tekrar validate et
    4. Max 2 retry (toplam 3 deneme)

    Args:
        query: Kullanıcı sorusu
        schema_context: Schema bilgisi
        allowed_tables: İzin verilen tablo adları
        execution_error: İlk deneme exec hatası (yoksa ilk üretim yapılır)
        failed_sql: Hata veren SQL (retry için)
        max_retries: Max düzeltme denemesi

    Returns:
        generate_sql() ile aynı format + "retry_count" alanı
    """
    # İlk üretim (execution hatası yoksa)
    if not execution_error:
        result = generate_sql(query, schema_context, allowed_tables)
        result["retry_count"] = 0
        return result

    # Self-healing retry döngüsü
    from app.core.llm import call_llm_api
    from app.services.safe_sql_executor import validate_sql, check_table_whitelist

    current_error = execution_error
    current_sql = failed_sql

    for attempt in range(1, max_retries + 1):
        log_system_event(
            "INFO",
            f"SQL Self-Healing retry #{attempt}: {current_error[:100]}",
            "text_to_sql"
        )

        # Düzeltme prompt'u oluştur
        dialect = schema_context.get("dialect", "postgresql").lower()
        schema_text = format_schema_for_llm(schema_context, query=query)

        correction_prompt = f"""Aşağıdaki SQL sorgusu veritabanında çalıştırıldığında HATA aldı.
Hatayı analiz edip düzelt.

ORİJİNAL KULLANICI SORUSU:
{query}

HATA VEREN SQL:
```sql
{current_sql}
```

HATA MESAJI:
{current_error}

VERİTABANI ŞEMASI:
{schema_text}

DİALECT: {dialect}

HATA ANALİZ ADIMLARI:
1. Hata mesajını oku — hangi kolon/tablo bulunamadı?
2. Şemadaki gerçek kolon/tablo adlarını kontrol et — büyük/küçük harf, alt çizgi farkı olabilir.
3. "column not found" ise şemadan en yakın eşleşen kolonu bul (örn: total_price → total_amount).
4. "table not found" ise schema prefix'ini kontrol et (örn: orders → "CSN"."ORDERS").
5. "syntax error" ise {dialect} dialect kurallarını uygula (LIMIT vs FETCH FIRST, quote stili vb.).
6. Sonuç boş döndüyse filtreleri gevşet (tarih aralığını genişlet, LIKE yerine daha geniş pattern kullan).
7. Ambiguous column ise tablo alias'ı ekle (örn: o.order_id).

Düzeltilmiş SQL'i ```sql ... ``` bloğu içinde yaz.
"""

        messages = [
            {"role": "system", "content": "Sen SQL hata düzeltme uzmanısın. Verilen hatayı analiz edip düzeltilmiş SQL üretiyorsun."},
            {"role": "user", "content": correction_prompt},
        ]

        try:
            llm_response = call_llm_api(messages)
        except Exception as e:
            log_warning(f"SQL Self-Healing LLM hatası (retry #{attempt}): {e}", "text_to_sql")
            continue

        if not llm_response:
            continue

        # Parse corrected SQL
        corrected_sql = parse_sql_from_llm(llm_response)
        if not corrected_sql:
            continue

        # Güvenlik doğrulaması
        is_valid, validation_error = validate_sql(corrected_sql)
        if not is_valid:
            log_warning(f"SQL Self-Healing güvenlik reddi (retry #{attempt}): {validation_error}", "text_to_sql")
            continue

        # Whitelist kontrolü
        if allowed_tables:
            is_allowed, table_error = check_table_whitelist(corrected_sql, allowed_tables, dialect)
            if not is_allowed:
                log_warning(f"SQL Self-Healing whitelist reddi (retry #{attempt}): {table_error}", "text_to_sql")
                continue

        explanation = _extract_explanation(llm_response)

        log_system_event(
            "INFO",
            f"SQL Self-Healing başarılı (retry #{attempt}): {corrected_sql[:100]}",
            "text_to_sql"
        )

        return {
            "success": True,
            "sql": corrected_sql,
            "explanation": explanation,
            "error": None,
            "retry_count": attempt,
            "original_error": execution_error,
        }

    # Tüm retry'lar başarısız
    log_warning(
        f"SQL Self-Healing tüm denemeler başarısız ({max_retries} retry)",
        "text_to_sql"
    )
    return {
        "success": False,
        "sql": failed_sql,
        "explanation": None,
        "error": execution_error,
        "retry_count": max_retries,
    }


def _check_column_hallucination(sql: str, schema_context: Dict[str, Any]) -> Optional[str]:
    """
    v3.14.0: LLM'in ürettiği SQL'deki kolon adlarını şemadaki gerçek kolonlarla karşılaştırır.
    Halüsinasyon (uydurma kolon) tespit ederse uyarı döner.

    Returns:
        None: Sorun yok
        str: Uyarı mesajı (şüpheli kolon listesi)
    """
    tables = schema_context.get("tables", [])
    if not tables:
        return None

    # Şemadaki tüm gerçek kolon adlarını topla
    known_columns = set()
    for t in tables:
        for col in t.get("columns", []):
            col_name = col.get("name", "").upper()
            if col_name:
                known_columns.add(col_name)

    if not known_columns:
        return None

    # SQL'den SELECT ve WHERE kısmındaki kolon referanslarını çıkar
    # Basit regex — alias'lı kolonları da yakalar: t.column_name veya "column_name"
    sql_upper = sql.upper()
    # SQL fonksiyonları ve keyword'leri hariç tut
    sql_keywords = {
        "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "IN", "AS", "ON", "JOIN",
        "LEFT", "RIGHT", "INNER", "OUTER", "GROUP", "BY", "ORDER", "HAVING",
        "COUNT", "SUM", "AVG", "MIN", "MAX", "DISTINCT", "CASE", "WHEN", "THEN",
        "ELSE", "END", "NULL", "IS", "LIKE", "BETWEEN", "EXISTS", "UNION", "ALL",
        "FETCH", "FIRST", "ROWS", "ONLY", "TOP", "LIMIT", "DESC", "ASC", "OFFSET",
        "COALESCE", "NVL", "UPPER", "LOWER", "TRIM", "CAST", "TO_CHAR", "TO_DATE",
        "SYSDATE", "CURRENT_DATE", "NOW", "GETDATE", "ROWNUM", "DUAL",
        "TOTAL_USAGE",  # aggregate alias'lar sorun yaratmasın
    }

    # Tablo.kolon pattern'ı: t.COLUMN_NAME veya "SCHEMA"."TABLE"."COLUMN"
    col_refs = re.findall(r'["\w]+\.(["\w]+)', sql_upper)
    # Tırnaksız referansları temizle
    col_refs = [c.strip('"') for c in col_refs]

    suspicious = []
    for col in col_refs:
        if col in sql_keywords:
            continue
        if col not in known_columns:
            # Tablo adı olabilir — kontrol et
            is_table = any(t.get("name", "").upper() == col for t in tables)
            is_schema = any(t.get("schema", "").upper() == col for t in tables)
            if not is_table and not is_schema:
                suspicious.append(col)

    if suspicious:
        return f"Şüpheli kolon adları (şemada bulunamadı): {', '.join(suspicious[:5])}"

    return None


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

def get_schema_context(source_id: int, enriched_only: bool = False) -> Dict[str, Any]:
    """
    DS Learning'den öğrenilmiş schema bilgilerini context olarak hazırlar.

    Bu context LLM'e tablo yapısını anlatır ve SQL üretiminde kullanılır.

    Args:
        source_id: Veri kaynağı ID
        enriched_only: True ise sadece enrichment kaydı olan (öğrenilmiş) tabloları döner.
                       Text-to-SQL akışında ML eşleşme bulunamadığında kullanılır.

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

        # 🆕 v3.1.0: Tablolar + Enrichment bilgileri
        # v3.14.0: enriched_only=True ise sadece öğrenilmiş tabloları getir (INNER JOIN)
        if enriched_only:
            cur.execute("""
                SELECT o.schema_name, o.object_name, o.object_type, o.column_count,
                       o.row_count_estimate, o.columns_json,
                       e.business_name_tr, e.admin_label_tr,
                       e.category, e.description_tr
                FROM ds_db_objects o
                INNER JOIN ds_table_enrichments e
                    ON e.source_id = o.source_id
                    AND e.table_name = o.object_name
                    AND COALESCE(e.schema_name, '') = COALESCE(o.schema_name, '')
                    AND e.is_active = TRUE
                WHERE o.source_id = %s AND o.object_type = 'table'
                ORDER BY o.object_name
            """, (source_id,))
        else:
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

        # v3.10.0: Boş tablo filtresi — 0 satırlık tabloları context'ten çıkar
        # Bu tablolar LLM'i gereksiz yere yönlendirir ve token israfına neden olur
        non_empty_tables = [t for t in tables if (t.get("row_estimate") or 0) > 0]
        if non_empty_tables:
            filtered_count = len(tables) - len(non_empty_tables)
            if filtered_count > 0:
                log_system_event(
                    "DEBUG",
                    f"Schema context: {filtered_count} boş tablo filtrelendi ({len(non_empty_tables)} kaldı)",
                    "text_to_sql"
                )
            tables = non_empty_tables
        # else: tüm tablolar boş görünüyor, filtreleme yapma (ilk keşif olabilir)

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


def format_schema_for_llm(schema_context: Dict[str, Any], query: str = "") -> str:
    """
    Schema bilgilerini LLM'e gönderilebilecek context formatına çevirir.

    v3.14.0: Opsiyonel query parametresi ile kolon pruning yapar.
    Soru ile ilgili kolonları öncelikli gösterir, ilgisiz kolonları kısaltır.

    Args:
        schema_context: get_schema_context() çıktısı
        query: Kullanıcı sorusu (kolon pruning için, opsiyonel)

    Returns:
        LLM'e gönderilecek schema açıklaması
    """
    if not schema_context or not schema_context.get("tables"):
        return ""

    # v3.14.0: Kolon pruning için soru tokenları
    query_tokens = set()
    if query:
        query_tokens = {w.lower() for w in query.split() if len(w) > 2}

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

        # v3.14.0: Kolon pruning — çok kolonlu tablolarda sadece ilgili kolonları göster
        relevant_cols = []
        other_cols = []
        for c in cols[:80]:  # Max 80 kolon kontrol edilir
            col_name = c['name']
            col_dtype = c['data_type']
            enr = col_enrichments.get(col_name, {})
            bname_col = enr.get("business_name_tr", "")
            synonyms = enr.get("synonyms", [])

            col_str = f"{col_name} ({col_dtype})"
            if bname_col:
                col_str += f" [{bname_col}]"
            if synonyms:
                col_str += f" synonyms: {', '.join(synonyms[:5])}"
            # v3.14.0: Enum/status kolonları için örnek değerler
            sample_vals = c.get("sample_values") or []
            if not sample_vals and col_dtype.upper() in ("VARCHAR", "VARCHAR2", "CHAR", "NVARCHAR", "NVARCHAR2"):
                sample_vals = c.get("distinct_values") or []
            if sample_vals and len(sample_vals) <= 15:
                col_str += f" değerler: {', '.join(str(v) for v in sample_vals[:8])}"

            # Kolon relevance kontrolü
            is_relevant = False
            if c.get("is_pk") or c.get("is_fk"):
                is_relevant = True
            elif col_dtype.lower() in ("timestamp", "timestamptz", "datetime", "date",
                                        "timestamp without time zone", "timestamp with time zone"):
                is_relevant = True
            elif query_tokens:
                col_lower = col_name.lower()
                bname_lower = bname_col.lower()
                syn_text = " ".join(s.lower() for s in synonyms)
                for token in query_tokens:
                    if token in col_lower or token in bname_lower or token in syn_text:
                        is_relevant = True
                        break

            if is_relevant or not query_tokens:
                relevant_cols.append(col_str)
            else:
                other_cols.append(col_str)

        # İlgili kolonlar az ise geri kalanı da ekle (min 5 kolon garanti)
        if len(relevant_cols) < 5:
            relevant_cols.extend(other_cols[:50 - len(relevant_cols)])
            col_names = relevant_cols
        else:
            col_names = relevant_cols[:50]
            if other_cols:
                col_names.append(f"... ve {len(other_cols)} kolon daha")
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

    # v3.9.0: İlişkiler — JOIN doğruluğu için yapılandırılmış format
    rels = schema_context.get("relationships", [])
    if rels:
        parts.append("")
        parts.append("JOIN İLİŞKİLERİ (Foreign Key):")
        parts.append("| İlişki No | Ana Tablo.Sütun | → | Referans Tablo.Sütun | Constraint |")
        parts.append("|-----------|-----------------|---|----------------------|------------|")
        for idx, r in enumerate(rels[:30], 1):  # v3.9.0: 20→30 ilişki
            from_parts = r.get('from', '').split('.')
            to_parts = r.get('to', '').split('.')
            # from: schema.table.column → table.column
            from_display = f"{from_parts[-2]}.{from_parts[-1]}" if len(from_parts) >= 2 else r.get('from', '')
            to_display = f"{to_parts[-2]}.{to_parts[-1]}" if len(to_parts) >= 2 else r.get('to', '')
            constraint = r.get('constraint', '')
            parts.append(f"| {idx} | {from_display} | → | {to_display} | {constraint} |")
        parts.append("")
        parts.append("NOT: Yukarıdaki ilişkileri JOIN sorguları oluştururken ON koşulu olarak kullan.")
        parts.append("Örn: JOIN referans_tablo ON ana_tablo.FK_sutun = referans_tablo.PK_sutun")
        parts.append("")

    return "\n".join(parts)


# =====================================================
# v4.0: Disambiguation & Schema Hint Yardımcıları
# =====================================================

def detect_ambiguous_tables(tables: List[Dict]) -> Dict[str, List[Dict]]:
    """
    Farklı schema'larda aynı base isimde tablolar tespit eder.

    Returns:
        {base_table_name: [table_dict, ...]} — sadece birden fazla eşleşme olanlar.
    """
    from collections import defaultdict
    name_groups: Dict[str, List] = defaultdict(list)
    for t in tables:
        name_groups[t.get("name", "").lower()].append(t)
    return {n: g for n, g in name_groups.items() if len(g) > 1}


def resolve_entities(query: str, tables: List[Dict]) -> List[str]:
    """
    v3.14.0: Deterministik Entity Resolution — soru kelimelerini tablo/kolon
    iş isimleri ve synonyms ile eşleştirerek seed tabloları bulur.

    ML embedding aramasından ÖNCE çalıştırılır, daha hızlı ve güvenilir.
    Fuzzy matching ile yakın eşleşmeleri de yakalar.

    Args:
        query: Kullanıcı sorusu
        tables: Schema context'ten gelen tablo listesi

    Returns:
        Eşleşen tablo isimleri listesi (schema.table formatında)
    """
    try:
        from rapidfuzz import fuzz
        has_fuzz = True
    except ImportError:
        has_fuzz = False
        log_warning("rapidfuzz yüklü değil; fuzzy entity matching devre dışı", "text_to_sql")

    query_lower = query.lower()
    # Türkçe stop words filtresi
    stop_words = {
        "bir", "bu", "şu", "ve", "ile", "için", "den", "dan", "da", "de",
        "mi", "mu", "mı", "nedir", "nasıl", "kaç", "ne", "hangi", "göster",
        "listele", "bul", "getir", "hazırla", "rapor", "olan", "olan",
        "numaralı", "son", "ilk", "en", "tüm", "toplam",
    }
    query_tokens = [w for w in query_lower.split() if len(w) > 2 and w not in stop_words]

    matched = []
    for t in tables:
        table_name = (t.get("name") or "").lower()
        schema_name = (t.get("schema") or "").lower()
        full_name = f"{schema_name}.{table_name}" if schema_name else table_name
        bname = (t.get("admin_label_tr") or t.get("business_name_tr") or "").lower()
        desc = (t.get("description_tr") or "").lower()

        score = 0

        # 1. Tablo adı doğrudan eşleşme
        for token in query_tokens:
            if token in table_name:
                score += 3
            if bname and token in bname:
                score += 5
            if desc and token in desc:
                score += 1

        # 2. Kolon synonym eşleşmesi
        col_enrichments = t.get("col_enrichments", {})
        for col_name, enr in col_enrichments.items():
            col_bname = (enr.get("business_name_tr") or "").lower()
            synonyms = [s.lower() for s in (enr.get("synonyms") or [])]

            for token in query_tokens:
                if token in col_bname:
                    score += 2
                for syn in synonyms:
                    if token in syn or syn in token:
                        score += 2

        # 3. Fuzzy matching (rapidfuzz varsa)
        if has_fuzz and score == 0 and bname:
            for token in query_tokens:
                if fuzz.partial_ratio(token, bname) > 80:
                    score += 3

        if score >= 3:
            matched.append((full_name, score))

    # Score'a göre sırala, en yüksek skoru olanları döndür
    matched.sort(key=lambda x: x[1], reverse=True)
    return [m[0] for m in matched[:10]]


def filter_tables_by_schema_hint(tables: List[Dict], schema_hint: str) -> List[Dict]:
    """
    schema_hint ('schema.table' formatı) ile hedef tabloyu öne alır,
    aynı base name'e sahip diğer schema'ları konteksten çıkarır.

    Args:
        tables: Schema context tablo listesi
        schema_hint: 'schema_name.table_name' — kullanıcı seçimi

    Returns:
        Önceliklendirilmiş tablo listesi
    """
    if not schema_hint or "." not in schema_hint:
        return tables

    parts = schema_hint.split(".", 1)
    hint_schema = parts[0].strip().lower()
    hint_table = parts[1].strip().lower()

    # Hedef tabloyu bul
    primary = [
        t for t in tables
        if t.get("name", "").lower() == hint_table
        and t.get("schema", "").lower() == hint_schema
    ]

    # Aynı isimde ama farklı schema'daki rakip tabloları çıkar
    others = [
        t for t in tables
        if not (t.get("name", "").lower() == hint_table
                and t.get("schema", "").lower() != hint_schema)
    ]

    # Birleştir: primary önde, duplicate olmadan
    result = list(primary)
    primary_ids = {id(t) for t in primary}
    for t in others:
        if id(t) not in primary_ids:
            result.append(t)

    return result


# =====================================================
# v3.14.0: Golden SQL Store
# =====================================================

def search_golden_sql(query: str, source_id: int, company_id: int,
                      min_score: float = 0.80, max_results: int = 3) -> list:
    """
    Doğrulanmış Golden SQL'ler arasında kullanıcı sorusuna en benzer olanları bulur.

    Embedding cosine similarity ile arama yapar.
    - Skor > 0.95: Direkt çalıştır (LLM bypass)
    - Skor > 0.80: Few-shot örnek olarak LLM prompt'una ekle

    Returns:
        [{question_text, sql_query, tables_used, score, id}, ...]
    """
    try:
        from app.core.db import get_db_conn
        from app.services.rag.embedding import EmbeddingManager

        emb_mgr = EmbeddingManager()
        query_emb = emb_mgr.get_embedding(query)
        if not query_emb:
            return []

        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, question_text, sql_query, tables_used,
                   question_embedding, dialect
            FROM golden_sql
            WHERE source_id = %s AND company_id = %s
              AND verified = TRUE AND question_embedding IS NOT NULL
        """, (source_id, company_id))

        rows = cur.fetchall()
        conn.close()

        if not rows:
            return []

        import numpy as np
        query_vec = np.array(query_emb, dtype=np.float32)
        results = []

        for row in rows:
            row_dict = dict(row) if hasattr(row, 'keys') else dict(
                zip(["id", "question_text", "sql_query", "tables_used",
                     "question_embedding", "dialect"], row)
            )
            stored_emb = row_dict.get("question_embedding")
            if not stored_emb:
                continue
            stored_vec = np.array(stored_emb, dtype=np.float32)

            # Cosine similarity
            norm_q = np.linalg.norm(query_vec)
            norm_s = np.linalg.norm(stored_vec)
            if norm_q == 0 or norm_s == 0:
                continue
            score = float(np.dot(query_vec, stored_vec) / (norm_q * norm_s))

            if score >= min_score:
                results.append({
                    "id": row_dict["id"],
                    "question_text": row_dict["question_text"],
                    "sql_query": row_dict["sql_query"],
                    "tables_used": row_dict.get("tables_used") or [],
                    "dialect": row_dict.get("dialect", ""),
                    "score": round(score, 4),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]

    except Exception as e:
        log_warning(f"Golden SQL arama hatası: {e}", "text_to_sql")
        return []


def save_golden_sql(source_id: int, company_id: int, question: str,
                    sql_query: str, tables_used: list = None,
                    dialect: str = "postgresql", user_id: int = None) -> bool:
    """
    Doğrulanmış SQL'i Golden SQL Store'a kaydeder.

    Returns:
        True: Başarıyla kaydedildi
    """
    try:
        from app.core.db import get_db_conn
        from app.services.rag.embedding import EmbeddingManager

        emb_mgr = EmbeddingManager()
        question_emb = emb_mgr.get_embedding(question)

        conn = get_db_conn()
        cur = conn.cursor()

        # Aynı soru varsa güncelle (ON CONFLICT yok — manual check)
        cur.execute("""
            SELECT id FROM golden_sql
            WHERE source_id = %s AND company_id = %s AND question_text = %s
        """, (source_id, company_id, question))
        existing = cur.fetchone()

        if existing:
            eid = existing[0] if not isinstance(existing, dict) else existing["id"]
            cur.execute("""
                UPDATE golden_sql
                SET sql_query = %s, tables_used = %s, question_embedding = %s,
                    verified = TRUE, usage_count = usage_count + 1, updated_at = NOW()
                WHERE id = %s
            """, (sql_query, tables_used, question_emb, eid))
        else:
            cur.execute("""
                INSERT INTO golden_sql
                    (source_id, company_id, question_text, question_embedding,
                     sql_query, tables_used, dialect, verified, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s)
            """, (source_id, company_id, question, question_emb,
                  sql_query, tables_used, dialect, user_id))

        conn.commit()
        conn.close()
        log_system_event("INFO", f"Golden SQL kaydedildi: {question[:80]}", "text_to_sql")
        return True

    except Exception as e:
        log_warning(f"Golden SQL kaydetme hatası: {e}", "text_to_sql")
        return False


def value_retrieval(query: str, source_id: int, tables: list,
                    max_results: int = 3) -> list:
    """
    v3.14.0: Value Retrieval — kullanıcı sorusundaki spesifik değerleri
    (isim, numara, kod) veritabanında arar.

    Örn: "Hakan Yılmaz'ın siparişleri" → customers.name'de 'Hakan Yılmaz' bulur.

    Returns:
        [{table, schema, column, value, match_type}, ...]
    """
    # Soruda tırnak içi veya sayısal değerleri çıkar
    import re
    quoted_values = re.findall(r"['\"]([^'\"]+)['\"]", query)
    numeric_values = re.findall(r'\b(\d{5,})\b', query)  # 5+ haneli sayılar (ID'ler)

    candidates = quoted_values + numeric_values
    if not candidates:
        # Büyük harfle başlayan kelimeleri potansiyel isim olarak al
        words = query.split()
        proper_nouns = []
        for i, w in enumerate(words):
            if w[0:1].isupper() and len(w) > 2 and i > 0:
                proper_nouns.append(w)
        # Ardışık özel isimleri birleştir (Ad Soyad)
        if len(proper_nouns) >= 2:
            candidates.append(" ".join(proper_nouns[:2]))
        elif proper_nouns:
            candidates.extend(proper_nouns)

    if not candidates:
        return []

    results = []
    try:
        for table in tables[:10]:
            t_name = table.get("name", "")
            t_schema = table.get("schema", "")
            searchable_cols = []

            # Aranabilir kolon tespiti (VARCHAR/CHAR + enrichment flagı)
            for col in table.get("columns", [])[:30]:
                dtype = (col.get("data_type") or "").upper()
                enr = table.get("col_enrichments", {}).get(col["name"], {})
                if dtype in ("VARCHAR", "VARCHAR2", "CHAR", "NVARCHAR", "NVARCHAR2", "TEXT", "CLOB"):
                    searchable_cols.append(col["name"])
                elif enr.get("is_searchable"):
                    searchable_cols.append(col["name"])

            # Her aday değer için aranabilir kolonlarda ara
            for val in candidates[:3]:
                for col_name in searchable_cols[:5]:
                    results.append({
                        "table": t_name,
                        "schema": t_schema,
                        "column": col_name,
                        "value": val,
                        "match_type": "potential",
                    })

    except Exception as e:
        log_warning(f"Value retrieval hatası: {e}", "text_to_sql")

    return results[:max_results]
