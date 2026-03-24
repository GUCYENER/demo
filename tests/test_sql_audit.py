"""
VYRA - SQL Audit Log Testleri
================================
SQL audit log kayıt, sorgulama ve istatistik testleri.

Version: 2.58.0
"""

import pytest
from unittest.mock import patch, MagicMock


class TestLogSQLExecution:
    """SQL audit log kayıt testleri."""

    @patch('app.core.db.get_db_conn')
    def test_log_execution_success(self, mock_conn):
        """Başarılı SQL yürütme loglanır."""
        from app.services.sql_audit_log import log_sql_execution
        
        mock_cur = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cur
        
        log_sql_execution(
            user_id=1,
            source_id=5,
            source_name="TestDB",
            sql_text="SELECT * FROM users",
            dialect="postgresql",
            status="success",
            row_count=10,
            elapsed_ms=45.5,
        )
        
        mock_cur.execute.assert_called_once()
        call_args = mock_cur.execute.call_args
        assert "INSERT INTO sql_audit_log" in call_args[0][0]
        mock_conn.return_value.commit.assert_called_once()

    @patch('app.core.db.get_db_conn')
    def test_log_execution_error_does_not_raise(self, mock_conn):
        """Audit log hatası ana akışı engellememeli."""
        from app.services.sql_audit_log import log_sql_execution
        
        mock_conn.side_effect = Exception("DB connection failed")
        
        # Hata fırlatmamalı
        log_sql_execution(
            user_id=1, source_id=1, source_name="X",
            sql_text="SELECT 1", dialect="pg",
            status="success",
        )

    @patch('app.core.db.get_db_conn')
    def test_log_truncates_long_sql(self, mock_conn):
        """2000 char'dan uzun SQL kesilir."""
        from app.services.sql_audit_log import log_sql_execution
        
        mock_cur = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cur
        
        long_sql = "SELECT " + "x" * 3000
        log_sql_execution(
            user_id=1, source_id=1, source_name="X",
            sql_text=long_sql, dialect="pg",
            status="success",
        )
        
        params = mock_cur.execute.call_args[0][1]
        # sql_text parametresinin pozisyonunu bul (company_id sonrası 4. param)
        sql_param = params[4]  # user_id, company_id, source_id, source_name, sql_text
        assert len(sql_param) <= 2000

    @patch('app.core.db.get_db_conn')
    def test_log_with_error_message(self, mock_conn):
        """Hata mesajı loglanır."""
        from app.services.sql_audit_log import log_sql_execution
        
        mock_cur = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cur
        
        log_sql_execution(
            user_id=1, source_id=1, source_name="X",
            sql_text="SELECT 1", dialect="pg",
            status="security_rejected",
            error_msg="DDL detected: DROP TABLE",
        )
        
        params = mock_cur.execute.call_args[0][1]
        # status index 6 (user_id, company_id, source_id, source_name, sql_text, dialect, status)
        assert params[6] == "security_rejected"


class TestGetSQLAuditStats:
    """SQL audit istatistik testleri."""

    @patch('app.core.db.get_db_conn')
    def test_stats_returns_dict(self, mock_conn):
        """İstatistik sözlüğü döndürür."""
        from app.services.sql_audit_log import get_sql_audit_stats
        
        mock_cur = MagicMock()
        mock_conn.return_value.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = {
            "total_queries": 100,
            "success_count": 90,
            "error_count": 8,
            "security_rejected_count": 2,
            "timeout_count": 0,
            "avg_elapsed_ms": 45.2,
            "template_count": 60,
            "llm_count": 40,
        }
        
        stats = get_sql_audit_stats()
        
        assert stats["total_queries"] == 100
        assert stats["success_count"] == 90
        assert stats["error_count"] == 8
        assert stats["template_count"] == 60
        assert stats["llm_count"] == 40

    @patch('app.core.db.get_db_conn')
    def test_stats_error_returns_zeros(self, mock_conn):
        """Hata durumunda sıfır değerler döndürür."""
        from app.services.sql_audit_log import get_sql_audit_stats
        
        mock_conn.side_effect = Exception("DB error")
        
        stats = get_sql_audit_stats()
        assert stats["total_queries"] == 0
        assert stats["success_count"] == 0
