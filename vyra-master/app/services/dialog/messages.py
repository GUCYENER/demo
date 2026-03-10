"""
VYRA L1 Support API - Dialog Message Operations
=================================================
Mesaj CRUD ve feedback işlemleri.

Refactored from dialog_service.py (v2.29.14)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional, Dict, Any

from app.core.db import get_db_context
from app.services.logging_service import log_warning


# =============================================================================
# MESSAGE CRUD
# =============================================================================

def add_message(
    dialog_id: int,
    role: str,
    content: str,
    content_type: str = "text",
    metadata: Dict[str, Any] = None
) -> int:
    """Dialog'a mesaj ekle."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dialog_messages (dialog_id, role, content, content_type, metadata)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
        """, (
            dialog_id,
            role,
            content,
            content_type,
            json.dumps(metadata) if metadata else None
        ))
        message_id = cur.fetchone()["id"]
        
        # Dialog updated_at güncelle
        cur.execute("""
            UPDATE dialogs SET updated_at = CURRENT_TIMESTAMP WHERE id = %s
        """, (dialog_id,))
        
        conn.commit()
        return message_id


def update_message_metadata(message_id: int, key: str, value: Any) -> bool:
    """Mesaj metadata'sına yeni bir key-value ekle veya güncelle."""
    from psycopg2.extras import RealDictCursor
    
    with get_db_context() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Mevcut metadata'yı al
        cur.execute("""
            SELECT metadata FROM dialog_messages WHERE id = %s
        """, (message_id,))
        row = cur.fetchone()
        
        if not row:
            return False
        
        # Metadata'yı güncelle
        metadata = row["metadata"] or {}
        metadata[key] = value
        
        cur.execute("""
            UPDATE dialog_messages SET metadata = %s WHERE id = %s
        """, (json.dumps(metadata), message_id))
        
        conn.commit()
        return True


def get_dialog_messages(dialog_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Dialog mesajlarını getir."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, dialog_id, role, content, content_type, metadata, created_at
            FROM dialog_messages
            WHERE dialog_id = %s
            ORDER BY created_at ASC
            LIMIT %s
        """, (dialog_id, limit))
        
        messages = []
        for row in cur.fetchall():
            msg = dict(row)
            if msg.get("metadata") and isinstance(msg["metadata"], str):
                msg["metadata"] = json.loads(msg["metadata"])
            messages.append(msg)
        return messages


def add_message_feedback(message_id: int, feedback_type: str, user_id: int) -> bool:
    """
    Mesaja feedback ekle (like/dislike).
    
    v2.38.4: user_feedback tablosuna query_text, chunk_id ve dialog_id de kaydedilir.
    ML öğrenme verisi zenginleştirildi.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        # Mevcut metadata ve content'i al
        cur.execute("""
            SELECT metadata, content, dialog_id FROM dialog_messages WHERE id = %s
        """, (message_id,))
        row = cur.fetchone()
        if not row:
            return False
        
        metadata = row["metadata"] or {}
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        
        response_text = row["content"]
        dialog_id = row["dialog_id"]
        
        # Feedback bilgisini metadata'ya ekle
        metadata["feedback"] = {
            "type": feedback_type,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat()
        }
        
        cur.execute("""
            UPDATE dialog_messages SET metadata = %s WHERE id = %s
        """, (json.dumps(metadata), message_id))
        
        # 🆕 v2.38.4: Kullanıcının orijinal sorusunu bul
        query_text = None
        try:
            cur.execute("""
                SELECT content FROM dialog_messages
                WHERE dialog_id = %s AND role = 'user' AND created_at < (
                    SELECT created_at FROM dialog_messages WHERE id = %s
                )
                ORDER BY created_at DESC LIMIT 1
            """, (dialog_id, message_id))
            q_row = cur.fetchone()
            if q_row:
                query_text = q_row["content"]
        except Exception as e:
            log_warning(f"Feedback query text alınamadı: {e}", "dialog")
        
        # 🆕 v2.38.4: Chunk ID varsa metadata'dan al
        chunk_id = None
        try:
            rag_results = metadata.get("rag_results", [])
            if rag_results and isinstance(rag_results, list) and len(rag_results) > 0:
                first_result = rag_results[0]
                if isinstance(first_result, dict):
                    chunk_id = first_result.get("chunk_id")
        except Exception as e:
            log_warning(f"Feedback chunk_id parse hatası: {e}", "dialog")
        
        # ML feedback tablosuna zenginleştirilmiş veri kaydet
        cur.execute("""
            INSERT INTO user_feedback (user_id, feedback_type, response_text, query_text, chunk_id, dialog_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, feedback_type, response_text, query_text, chunk_id, dialog_id))
        
        # 🔧 v2.38.4: Tek commit — metadata UPDATE + user_feedback INSERT atomik
        conn.commit()
        
        return True


# =============================================================================
# MESSAGE QUERY HELPERS
# =============================================================================

def get_last_assistant_with_quick_reply(dialog_id: int) -> Optional[Dict[str, Any]]:
    """
    Son quick_reply içeren assistant mesajını bul.
    
    🔒 GÜVENLİK: En son mesajlardan geriye doğru arar.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        # En son 10 mesajı al (DESC sıralı - yeniden eskiye)
        cur.execute("""
            SELECT id, dialog_id, role, content, content_type, metadata, created_at
            FROM dialog_messages
            WHERE dialog_id = %s
            ORDER BY created_at DESC
            LIMIT 10
        """, (dialog_id,))
        
        for row in cur.fetchall():
            msg = dict(row)
            if msg.get("metadata") and isinstance(msg["metadata"], str):
                msg["metadata"] = json.loads(msg["metadata"])
            
            # quick_reply içeren ilk assistant mesajını bul
            if msg["role"] == "assistant":
                metadata = msg.get("metadata") or {}
                if metadata.get("rag_results") or metadata.get("quick_reply"):
                    return msg
        
        return None


def get_message_by_id(message_id: int) -> Optional[Dict[str, Any]]:
    """
    Mesajı ID ile direkt al.
    
    🔒 GÜVENLİK: En güvenilir yöntem - ID ile direkt erişim.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, dialog_id, role, content, content_type, metadata, created_at
            FROM dialog_messages
            WHERE id = %s
        """, (message_id,))
        
        row = cur.fetchone()
        if row:
            msg = dict(row)
            if msg.get("metadata") and isinstance(msg["metadata"], str):
                msg["metadata"] = json.loads(msg["metadata"])
            return msg
        
        return None


def find_rag_results_in_history(dialog_id: int) -> list:
    """
    v2.20.11: Dialog geçmişinde RAG sonuçlarını geriye dönük ara.
    Son 10 asistan mesajını kontrol eder.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT metadata FROM dialog_messages
            WHERE dialog_id = %s AND role = 'assistant'
            ORDER BY created_at DESC
            LIMIT 10
        """, (dialog_id,))
        
        for row in cur.fetchall():
            metadata = row["metadata"]
            if metadata:
                rag_results = metadata.get("rag_results", [])
                if rag_results:
                    return rag_results
        
        return []


def get_original_query(dialog_id: int) -> str:
    """
    Dialog'dan orijinal kullanıcı sorusunu bul.
    Son 10 mesaj içinde ilk user mesajını arar.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT content FROM dialog_messages
            WHERE dialog_id = %s AND role = 'user' AND content_type = 'text'
            ORDER BY created_at DESC
            LIMIT 5
        """, (dialog_id,))
        
        for row in cur.fetchall():
            content = row["content"]
            # Quick reply mesajlarını atla
            if not content.startswith("✅") and not content.startswith("👍") and not content.startswith("👎"):
                return content
        
        return "Kullanıcı sorusu"
