"""
VYRA - Text-to-SQL Testleri
==============================
LLM SQL üretimi, parse ve güvenlik kontrolü testleri.

Version: 2.58.0
"""

import pytest
from app.services.text_to_sql import (
    parse_sql_from_llm,
    _clean_sql,
    _extract_explanation,
    build_text_to_sql_prompt,
)


class TestParseSQLFromLLM:
    """LLM yanıtından SQL parse testleri."""

    def test_parse_sql_code_block(self):
        """```sql ... ``` bloğundan SQL çıkarır."""
        response = """İşte sorgunuz:

```sql
SELECT name, age FROM users WHERE age > 18 LIMIT 10
```

Bu sorgu 18 yaşından büyük kullanıcıları listeler."""
        sql = parse_sql_from_llm(response)
        assert sql is not None
        assert "SELECT name, age FROM users" in sql
        assert "LIMIT 10" in sql

    def test_parse_sql_generic_code_block(self):
        """Etiket olmayan ``` ... ``` bloğundan SELECT çıkarır."""
        response = """Sonuç:

```
SELECT COUNT(*) FROM orders WHERE status = 'active'
```
"""
        sql = parse_sql_from_llm(response)
        assert sql is not None
        assert "SELECT COUNT(*)" in sql

    def test_parse_sql_fallback_select(self):
        """SELECT ile başlayan satırları fallback olarak bulur."""
        response = """Bu sorguda sipariş durumlarını kontrol edebilirsiniz:

SELECT status, COUNT(*) as cnt
FROM orders
GROUP BY status;
"""
        sql = parse_sql_from_llm(response)
        assert sql is not None
        assert "SELECT status" in sql
        assert "GROUP BY status" in sql

    def test_parse_sql_empty_response(self):
        """Boş yanıt None döndürür."""
        assert parse_sql_from_llm("") is None
        assert parse_sql_from_llm(None) is None
        assert parse_sql_from_llm("   ") is None

    def test_parse_sql_no_sql_in_response(self):
        """SQL içermeyen yanıt None döndürür."""
        response = "Üzgünüm, bu soruyu veritabanında sorgulayamam."
        assert parse_sql_from_llm(response) is None

    def test_parse_sql_with_semicolon_removal(self):
        """Trailing semicolon temizlenir."""
        response = """```sql
SELECT * FROM products;
```"""
        sql = parse_sql_from_llm(response)
        assert sql is not None
        assert not sql.endswith(";")

    def test_parse_with_cte(self):
        """WITH (CTE) ile başlayan sorguları parse eder."""
        response = """```
WITH recent AS (
    SELECT * FROM orders WHERE created_at > '2024-01-01'
)
SELECT * FROM recent LIMIT 50
```"""
        sql = parse_sql_from_llm(response)
        assert sql is not None
        assert "WITH recent AS" in sql


class TestCleanSQL:
    """SQL temizleme testleri."""

    def test_removes_trailing_semicolon(self):
        assert _clean_sql("SELECT 1;") == "SELECT 1"

    def test_normalizes_whitespace(self):
        result = _clean_sql("SELECT   name\n   FROM   users")
        assert "  " not in result  # İkili boşluk olmamalı

    def test_strips_whitespace(self):
        assert _clean_sql("  SELECT 1  ") == "SELECT 1"


class TestExtractExplanation:
    """LLM açıklama çıkarma testleri."""

    def test_extracts_before_code_block(self):
        response = "Bu sorgu kullanıcıları listeler:\n```sql\nSELECT * FROM users\n```"
        explanation = _extract_explanation(response)
        assert "kullanıcıları listeler" in explanation

    def test_empty_explanation(self):
        response = "```sql\nSELECT * FROM users\n```"
        explanation = _extract_explanation(response)
        assert explanation == ""


class TestBuildPrompt:
    """Prompt oluşturma testleri."""

    def test_builds_prompt_with_schema(self):
        """Schema context ile prompt oluşturur."""
        schema_context = {
            "tables": [
                {"name": "users", "schema": "public", "columns": [], "row_estimate": 100}
            ],
            "dialect": "postgresql",
            "source_name": "TestDB",
        }
        messages = build_text_to_sql_prompt("Kaç kullanıcı var?", schema_context)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "Kaç kullanıcı var?" in messages[1]["content"]

    def test_prompt_contains_dialect(self):
        """Prompt dialect bilgisi içerir."""
        schema_context = {
            "tables": [],
            "dialect": "mssql",
        }
        messages = build_text_to_sql_prompt("Test", schema_context)
        assert "mssql" in messages[0]["content"]
