"""
VYRA L1 Support API - Dialog CRUD Operations
=============================================
Dialog oturumu CRUD (Create, Read, Update, Delete) işlemleri.

Refactored from dialog_service.py (v2.29.14)
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any

from app.core.db import get_db_context
from app.services.logging_service import log_system_event


# =============================================================================
# DIALOG CRUD
# =============================================================================

def create_dialog(user_id: int, title: str = None, source_type: str = "vyra_chat") -> int:
    """
    Yeni dialog oturumu başlat.
    
    Args:
        user_id: Kullanıcı ID
        title: Dialog başlığı (opsiyonel)
        source_type: Kaynak tipi - 'vyra_chat' (v2.24.0)
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO dialogs (user_id, title, source_type, status)
            VALUES (%s, %s, %s, 'active')
            RETURNING id
        """, (user_id, title or "Yeni Dialog", source_type))
        dialog_id = cur.fetchone()["id"]
        conn.commit()
        
        log_system_event("INFO", f"Dialog #{dialog_id} oluşturuldu (source: {source_type})", "dialog", user_id)
        return dialog_id


def get_active_dialog(user_id: int) -> Optional[Dict[str, Any]]:
    """Kullanıcının aktif dialogunu getir. Yoksa None döner."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, user_id, title, status, created_at, updated_at
            FROM dialogs
            WHERE user_id = %s AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
        """, (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_or_create_active_dialog(user_id: int) -> Dict[str, Any]:
    """Aktif dialogu getir, yoksa yeni oluştur."""
    dialog = get_active_dialog(user_id)
    if dialog:
        return dialog
    
    dialog_id = create_dialog(user_id)
    return {
        "id": dialog_id,
        "user_id": user_id,
        "title": "Yeni Dialog",
        "status": "active",
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    }


def close_dialog(dialog_id: int, user_id: int) -> bool:
    """Dialogu kapat."""
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE dialogs
            SET status = 'closed', closed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND user_id = %s
            RETURNING id
        """, (dialog_id, user_id))
        result = cur.fetchone()
        conn.commit()
        
        if result:
            log_system_event("INFO", f"Dialog #{dialog_id} kapatıldı", "dialog", user_id)
            return True
        return False


def close_inactive_dialogs(inactivity_minutes: int = 30) -> int:
    """
    v2.21.8: Belirli süre inaktif kalan dialog'ları otomatik kapat.
    
    Args:
        inactivity_minutes: Kaç dakika inaktif kaldıktan sonra kapatılacak (default: 30)
    
    Returns:
        Kapatılan dialog sayısı
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            UPDATE dialogs
            SET status = 'closed', closed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE status = 'active'
              AND source_type = 'vyra_chat'
              AND updated_at < CURRENT_TIMESTAMP - INTERVAL '%s minutes'
            RETURNING id
        """, (inactivity_minutes,))
        closed_ids = [row["id"] for row in cur.fetchall()]
        conn.commit()
        
        if closed_ids:
            log_system_event(
                "INFO", 
                f"{len(closed_ids)} inaktif dialog kapatıldı (IDs: {closed_ids[:5]}{'...' if len(closed_ids) > 5 else ''})",
                "dialog_scheduler"
            )
        
        return len(closed_ids)


def list_user_dialogs(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Kullanıcının dialoglarını listele.
    v2.28.0: LEFT JOIN ile optimize edildi.
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT d.id, d.title, d.source_type, d.status, d.created_at, d.updated_at, d.closed_at,
                   COALESCE(dm.message_count, 0) as message_count
            FROM dialogs d
            LEFT JOIN (
                SELECT dialog_id, COUNT(*) as message_count 
                FROM dialog_messages 
                GROUP BY dialog_id
            ) dm ON dm.dialog_id = d.id
            WHERE d.user_id = %s
            ORDER BY d.updated_at DESC
            LIMIT %s
        """, (user_id, limit))
        return [dict(row) for row in cur.fetchall()]


def get_dialog_history(
    user_id: int, 
    limit: int = 50, 
    offset: int = 0,
    source_type: str = None
) -> Dict[str, Any]:
    """
    v2.21.1: Geçmiş Çözümler için dialog geçmişini getir.
    v2.28.0: Performans optimizasyonu - JOINs kullanarak 10x hızlandırıldı.
    
    - vyra_chat için status kontrolü YOK (aktif de olsa göster)
    - v2.24.0: Sadece vyra_chat desteği
    - Opsiyonel source_type filtresi
    """
    with get_db_context() as conn:
        cur = conn.cursor()
        
        # 🚀 v2.28.0: Optimize edilmiş sorgu - subquery yerine JOIN kullanıyoruz
        # Tek sorguda tüm veriler çekiliyor (N+4 → 1 sorgu)
        
        cur.execute("""
            WITH dialog_stats AS (
                SELECT 
                    dialog_id,
                    COUNT(*) as message_count,
                    MIN(CASE WHEN role = 'user' THEN created_at END) as first_user_msg_time,
                    MAX(CASE WHEN role = 'assistant' THEN created_at END) as last_assistant_msg_time
                FROM dialog_messages
                GROUP BY dialog_id
                HAVING COUNT(*) > 0
            ),
            first_questions AS (
                SELECT DISTINCT ON (dialog_id) 
                    dialog_id, content as first_question
                FROM dialog_messages 
                WHERE role = 'user'
                ORDER BY dialog_id, created_at ASC
            ),
            last_answers AS (
                SELECT DISTINCT ON (dialog_id)
                    dialog_id, content as last_answer
                FROM dialog_messages
                WHERE role = 'assistant'
                ORDER BY dialog_id, created_at DESC
            )
            SELECT 
                d.id, d.title, d.source_type, d.status, 
                d.created_at, d.closed_at,
                fq.first_question,
                la.last_answer,
                ds.message_count
            FROM dialogs d
            INNER JOIN dialog_stats ds ON ds.dialog_id = d.id
            LEFT JOIN first_questions fq ON fq.dialog_id = d.id
            LEFT JOIN last_answers la ON la.dialog_id = d.id
            WHERE d.user_id = %s 
              AND d.source_type = 'vyra_chat'
            ORDER BY d.updated_at DESC, d.created_at DESC
            LIMIT %s OFFSET %s
        """, [user_id, limit, offset])
        
        dialogs = [dict(row) for row in cur.fetchall()]
        
        # Count (ayrı basit sorgu - çok hızlı)
        cur.execute("""
            SELECT COUNT(*) as total 
            FROM dialogs d
            WHERE d.user_id = %s 
              AND d.source_type = 'vyra_chat'
              AND EXISTS (SELECT 1 FROM dialog_messages WHERE dialog_id = d.id)
        """, [user_id])
        total = cur.fetchone()["total"]
        
        return {
            "items": dialogs,
            "total": total,
            "limit": limit,
            "offset": offset
        }
