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
from typing import Dict, Any, Optional, List

from app.services.logging_service import log_system_event, log_warning

logger = logging.getLogger(__name__)


# =====================================================
# System Prompt
# =====================================================

TEXT_TO_SQL_SYSTEM_PROMPT = """Sen bir SQL uzmanısın. Kullanıcının doğal dildeki sorusunu SQL sorgusuna çeviriyorsun.

KRİTİK KURALLAR:
1. SADECE SELECT sorguları yaz. INSERT, UPDATE, DELETE, DROP, ALTER gibi komutlar KESİNLİKLE YASAK.
2. Yalnızca verilen tablolar ve sütunları kullan. Olmayan tablo/sütun kullanma.
3. LIMIT ekle (max 100 satır).
4. WHERE filtresi uygunsa ekle.
5. Tarih filtreleri için dialect'e uygun tarih fonksiyonları kullan.
6. Tablo ve sütun adlarını gerektiğinde quote et.
7. SQL'i ```sql ... ``` bloğu içinde yaz.
8. SQL'den önce kısa bir açıklama yaz.

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

    Returns:
        LLM messages listesi
    """
    from app.services.hybrid_router import format_schema_for_llm

    dialect = schema_context.get("dialect", "postgresql")
    schema_text = format_schema_for_llm(schema_context)

    system = TEXT_TO_SQL_SYSTEM_PROMPT.format(dialect=dialect)

    user_msg = f"""VERİTABANI ŞEMASI:
{schema_text}

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
        return {
            "success": False,
            "sql": None,
            "explanation": llm_response[:300],
            "error": "LLM yanıtından SQL parse edilemedi",
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
