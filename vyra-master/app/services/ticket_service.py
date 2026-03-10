"""
VYRA L1 Support API - Ticket Service
=====================================
Ticket oluşturma, görüntüleme ve listeleme servisleri.

v2.23.0: RAG sonuçları kaydediliyor, AI değerlendirmesi isteğe bağlı.
"""

from __future__ import annotations

import json
from typing import List, Optional, Tuple, Dict, Any

from app.core.db import get_db_conn
from app.services.logging_service import log_error
from app.core.llm import (
    PlannerPlan,
    VerifierResult,
    run_planner,
    run_verifier,
    run_worker,
)
from app.models.schemas import (
    TicketDetail,
    TicketHistoryResponse,
    TicketStep,
)


def create_ticket_rag_only(
    user_id: int, query: str
) -> Tuple[int, List[Dict[str, Any]], bool]:
    """
    🆕 v2.23.0: Sadece RAG araması yapar, LLM çağırmaz.
    
    Akış:
    1. Planner: Sorguyu analiz eder
    2. Worker: RAG araması yapar
    3. DB: RAG sonuçlarını kaydeder (LLM çözümü yok!)
    
    Returns:
        (ticket_id, rag_results, has_results)
    """
    from app.core.rag import search_knowledge_base
    from app.services.dialog_service import _parse_chunk_details
    
    # 1) Planner - Sorguyu analiz et
    plan: PlannerPlan = run_planner(query)
    
    # 2) RAG Araması
    rag_response = search_knowledge_base(query, n_results=5, min_score=0.4, user_id=user_id)
    
    # 3) RAG sonuçlarını JSON formatına çevir
    rag_results = []
    if rag_response and rag_response.has_results:
        for i, r in enumerate(rag_response.results[:5]):
            details = _parse_chunk_details(r.content)
            rag_results.append({
                "id": i,
                "file_name": r.source_file or "Bilgi Tabanı",
                "score": int(r.score * 100),
                "chunk_text": r.content,
                "details": details
            })
    
    # 4) DB kayıtları
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # 🔒 Kullanıcının mevcut AKTİF org_ids'lerini al
        cur.execute("""
            SELECT uo.org_id 
            FROM user_organizations uo
            JOIN organization_groups o ON uo.org_id = o.id
            JOIN users u ON uo.user_id = u.id
            WHERE uo.user_id = %s 
              AND o.is_active = true
              AND u.is_approved = true
        """, (user_id,))
        user_org_rows = cur.fetchall()
        user_org_ids = [row['org_id'] for row in user_org_rows]
        
        cur.execute(
            """
            INSERT INTO tickets (user_id, title, description, source_type, 
                                 rag_results, interaction_type, source_org_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                user_id,
                plan.title,
                query,
                "rag" if rag_results else None,
                json.dumps(rag_results),  # 🆕 RAG sonuçları JSON olarak
                "rag_only",  # 🆕 Henüz AI değerlendirmesi yok
                user_org_ids,
            ),
        )
        ticket_id = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    return ticket_id, rag_results, len(rag_results) > 0


def add_ai_evaluation_to_ticket(
    ticket_id: int, user_id: int
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    🆕 v2.23.0: Mevcut ticket'a AI değerlendirmesi ekler.
    
    Kullanıcı "AI Değerlendir" butonuna tıkladığında çağrılır.
    
    Returns:
        (success, final_solution, cym_text)
    """
    from app.core.llm import get_active_prompt, call_llm_api, _generate_cym_summary, SourceInfo
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Ticket'ı getir
        cur.execute("""
            SELECT id, user_id, description, rag_results 
            FROM tickets WHERE id = %s
        """, (ticket_id,))
        row = cur.fetchone()
        
        if not row:
            return False, None, None
        
        # Güvenlik: Sadece kendi ticket'ını güncelleyebilir
        if row["user_id"] != user_id:
            return False, None, None
        
        query = row["description"]
        rag_results = row["rag_results"] or []
        
        # RAG sonuçlarından context oluştur
        context = ""
        source_names = []
        if rag_results:
            for r in rag_results[:3]:  # En iyi 3 sonucu kullan
                context += f"\n---\n{r.get('chunk_text', '')}\n"
                if r.get('file_name'):
                    source_names.append(r['file_name'])
        
        # LLM çağrısı
        system_prompt = get_active_prompt()
        
        if context:
            user_message = f"""Kullanıcı Sorusu: {query}

---
BİLGİ TABANI İÇERİĞİ:
{context}
---

ÖNEMLİ TALİMATLAR:
1. Yukarıdaki bilgi tabanı içeriğini kullanarak kullanıcıya yanıt ver.
2. İçerikteki TÜM detayları koru.
3. Bilgileri **anahtar: değer** formatında göster.
4. Yanıtı Türkçe olarak ver.
5. Eğer bağlam yeterli değilse, kendi bilginle tamamla."""
        else:
            user_message = f"""Kullanıcı Sorusu: {query}

Bu soru için bilgi tabanında sonuç bulunamadı. 
Kendi bilginle kullanıcıya yardımcı ol."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        ai_response = call_llm_api(messages)
        
        # Kaynak bilgisini ekle
        source_info = SourceInfo(
            source_type="rag" if source_names else "ai",
            source_names=source_names,
            context=context
        )
        source_display = source_info.get_source_display()
        final_solution = f"{ai_response}\n\n---\n{source_display}"
        
        # CYM metni oluştur
        cym_text = _generate_cym_summary(query, ai_response, source_info)
        
        # Ticket'ı güncelle
        cur.execute("""
            UPDATE tickets 
            SET final_solution = %s, 
                cym_text = %s, 
                interaction_type = 'ai_evaluation',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (final_solution, cym_text, ticket_id))
        
        conn.commit()
        return True, final_solution, cym_text
        
    except Exception as e:
        log_error(f"AI değerlendirme ekleme hatası (ticket_id={ticket_id}): {e}", "ticket")
        return False, None, str(e)
    finally:
        conn.close()


def add_user_selection_to_ticket(
    ticket_id: int, user_id: int, selected_chunk_text: str, selected_file_name: str
) -> Tuple[bool, Optional[str]]:
    """
    🆕 v2.23.0: Kullanıcı seçimini ticket'a ekler.
    
    Kullanıcı RAG sonuçlarından birini seçtiğinde çağrılır.
    
    Returns:
        (success, cym_text)
    """
    from app.core.llm import _generate_cym_summary, SourceInfo
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Ticket'ı getir
        cur.execute("""
            SELECT id, user_id, description FROM tickets WHERE id = %s
        """, (ticket_id,))
        row = cur.fetchone()
        
        if not row:
            return False, None
        
        # Güvenlik: Sadece kendi ticket'ını güncelleyebilir
        if row["user_id"] != user_id:
            return False, None
        
        query = row["description"]
        
        # CYM metni oluştur
        source_info = SourceInfo(
            source_type="rag",
            source_names=[selected_file_name] if selected_file_name else [],
            context=selected_chunk_text
        )
        cym_text = _generate_cym_summary(query, selected_chunk_text, source_info)
        
        # Kaynak bilgisini ekle
        source_display = source_info.get_source_display()
        final_solution = f"{selected_chunk_text}\n\n---\n{source_display}"
        
        # Ticket'ı güncelle
        cur.execute("""
            UPDATE tickets 
            SET final_solution = %s, 
                cym_text = %s,
                source_name = %s,
                interaction_type = 'user_selection',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """, (final_solution, cym_text, selected_file_name, ticket_id))
        
        conn.commit()
        return True, cym_text
        
    except Exception as e:
        log_error(f"Kullanıcı seçimi ekleme hatası (ticket_id={ticket_id}): {e}", "ticket")
        return False, str(e)
    finally:
        conn.close()


# ⚠️ DEPRECATED - Geriye uyumluluk için korunuyor
def create_ticket_from_chat(
    user_id: int, query: str
) -> Tuple[int, VerifierResult, List[TicketStep]]:
    """
    ⚠️ DEPRECATED: Bu fonksiyon geriye uyumluluk için korunuyor.
    Yeni kod create_ticket_rag_only() kullanmalı.
    """
    # Eski davranış: LLM ile tam akış
    plan: PlannerPlan = run_planner(query)
    worker_results, source_info = run_worker(query, plan, user_id=user_id)
    verifier: VerifierResult = run_verifier(query, plan, worker_results, source_info)
    
    # Hata kontrolü
    error_indicators = [
        "LLM Bağlantı Hatası:",
        "Hata: Aktif bir LLM konfigürasyonu bulunamadı",
        "API Cevabı beklenmedik formatta:",
        "LLM Beklenmeyen Hata:",
    ]
    for indicator in error_indicators:
        if indicator in verifier.final_solution:
            raise Exception(verifier.final_solution)

    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT uo.org_id FROM user_organizations uo
            JOIN organization_groups o ON uo.org_id = o.id
            JOIN users u ON uo.user_id = u.id
            WHERE uo.user_id = %s AND o.is_active = true AND u.is_approved = true
        """, (user_id,))
        user_org_ids = [row['org_id'] for row in cur.fetchall()]
        
        cur.execute("""
            INSERT INTO tickets (user_id, title, description, final_solution, 
                                 cym_text, interaction_type, source_org_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (user_id, plan.title, query, verifier.final_solution, 
              verifier.cym_text, 'ai_evaluation', user_org_ids))
        ticket_id = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()

    return ticket_id, verifier, []



def create_ticket_direct(
    user_id: int, 
    query: str, 
    solution: str, 
    source_name: str = None
) -> int:
    """
    LLM kullanmadan direkt ticket oluşturur.
    
    RAG sonucundan seçilen chunk doğrudan çözüm olarak kaydedilir.
    Bu yaklaşım çok daha hızlıdır (~3sn vs ~7sn).
    """
    from app.core.llm import _generate_cym_summary, SourceInfo
    
    # Basit başlık oluştur
    title = query[:100] + ('...' if len(query) > 100 else '')
    
    # CYM metni oluştur
    source_info = SourceInfo(
        source_type="rag",
        source_names=[source_name] if source_name else [],
        context=solution
    )
    cym_text = _generate_cym_summary(query, solution, source_info)
    
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # 🔒 Kullanıcının mevcut AKTİF org_ids'lerini al
        cur.execute("""
            SELECT uo.org_id 
            FROM user_organizations uo
            JOIN organization_groups o ON uo.org_id = o.id
            JOIN users u ON uo.user_id = u.id
            WHERE uo.user_id = %s 
              AND o.is_active = true
              AND u.is_approved = true
        """, (user_id,))
        user_org_rows = cur.fetchall()
        user_org_ids = [row['org_id'] for row in user_org_rows]
        
        cur.execute(
            """
            INSERT INTO tickets (user_id, title, description, source_type, source_name,
                                 final_solution, cym_text, cym_portal_url, source_org_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """,
            (
                user_id,
                title,
                query,
                "rag",
                source_name,
                solution,
                cym_text,
                None,
                user_org_ids,
            ),
        )
        ticket_id = cur.fetchone()["id"]
        
        conn.commit()
    finally:
        conn.close()

    return ticket_id


def get_ticket_detail(ticket_id: int) -> Optional[TicketDetail]:
    """Ticket detaylarını getirir."""
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, user_id, title, description, source_type, source_name,
                   final_solution, cym_text, cym_portal_url, llm_evaluation,
                   rag_results, interaction_type, created_at
            FROM tickets
            WHERE id = %s
        """,
            (ticket_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        cur.execute(
            """
            SELECT step_order, step_title, step_body
            FROM ticket_steps
            WHERE ticket_id = %s
            ORDER BY step_order ASC
        """,
            (ticket_id,),
        )
        cur_steps = cur.fetchall()
    finally:
        conn.close()

    steps = [
        TicketStep(
            step_order=s["step_order"],
            step_title=s["step_title"],
            step_body=s["step_body"],
        )
        for s in cur_steps
    ]

    return TicketDetail(
        id=row["id"],
        user_id=row["user_id"],  # GÜVENLİK: IDOR koruması için
        title=row["title"],
        description=row["description"],
        source_type=row["source_type"],
        source_name=row["source_name"],
        final_solution=row["final_solution"],
        cym_text=row["cym_text"],
        cym_portal_url=row["cym_portal_url"],
        llm_evaluation=row["llm_evaluation"],
        rag_results=row["rag_results"],  # 🆕 v2.23.0
        interaction_type=row["interaction_type"],  # 🆕 v2.23.0
        created_at=row["created_at"],
        steps=steps,
    )



def list_ticket_history_for_user(
    user_id: int,
    is_admin: bool,
    page: int,
    page_size: int,
    start_date: Optional[str],
    end_date: Optional[str],
) -> TicketHistoryResponse:
    """
    Kullanıcı için ticket geçmişini listeler.
    
    🔒 GÜVENLİK: Org bazlı filtreleme - Kullanıcının mevcut org'ları ile 
    ticket'ın oluşturulma anındaki org'ları (source_org_ids) kesişim kontrolü yapar.
    Kullanıcının org'u değişmişse eski ticket'ları göremez.
    """
    offset = (page - 1) * page_size

    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # 🔒 Kullanıcının mevcut AKTİF org_ids'lerini al
        cur.execute("""
            SELECT uo.org_id 
            FROM user_organizations uo
            JOIN organization_groups o ON uo.org_id = o.id
            JOIN users u ON uo.user_id = u.id
            WHERE uo.user_id = %s 
              AND o.is_active = true
              AND u.is_approved = true
        """, (user_id,))
        user_org_rows = cur.fetchall()
        user_org_ids = [row['org_id'] for row in user_org_rows]
        
        where_clauses = ["1=1"]
        params: list = []

        if not is_admin:
            where_clauses.append("user_id = %s")
            params.append(user_id)
            
            # 🔒 ORG KESİŞİM FİLTRESİ: Ticket'ın source_org_ids ile kullanıcının mevcut org'ları kesişmeli
            # VEYA eski ticket'lar (source_org_ids boş/null) da gösterilsin
            if user_org_ids:
                where_clauses.append("(source_org_ids && %s OR source_org_ids IS NULL OR source_org_ids = '{}')")
                params.append(user_org_ids)
            else:
                # Kullanıcının org'u yoksa sadece eski (org atanmamış) ticket'lar
                where_clauses.append("(source_org_ids IS NULL OR source_org_ids = '{}')")

        if start_date:
            where_clauses.append("created_at::date >= %s::date")
            params.append(start_date)

        if end_date:
            where_clauses.append("created_at::date <= %s::date")
            params.append(end_date)

        where_sql = " AND ".join(where_clauses)
        
        # Tek sorguda hem count hem data çek
        params_with_pagination = params + [page_size, offset]
        cur.execute(
            f"""
            SELECT 
                id, user_id, title, description, source_type, source_name,
                final_solution, cym_text, cym_portal_url, llm_evaluation,
                rag_results, interaction_type, created_at,
                COUNT(*) OVER() as total_count
            FROM tickets
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """,
            params_with_pagination,
        )
        rows = cur.fetchall()
        
        total = rows[0]["total_count"] if rows else 0
        
        items: list[TicketDetail] = []
        for row in rows:
            items.append(
                TicketDetail(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    description=row["description"],
                    source_type=row["source_type"],
                    source_name=row["source_name"],
                    final_solution=row["final_solution"],
                    cym_text=row["cym_text"],
                    cym_portal_url=row["cym_portal_url"],
                    llm_evaluation=row["llm_evaluation"],
                    rag_results=row["rag_results"],  # 🆕 v2.23.0
                    interaction_type=row["interaction_type"],  # 🆕 v2.23.0
                    created_at=row["created_at"],
                    steps=[],  # Artık kullanılmıyor
                )
            )
        
        return TicketHistoryResponse(
            items=items, page=page, page_size=page_size, total=total
        )
    finally:
        conn.close()


def get_ticket_details_bulk(ticket_ids: list[int]) -> list[TicketDetail]:
    """Birden fazla ticket'ın detaylarını (adımları dahil) tek sorguda getirir."""
    if not ticket_ids:
        return []
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                t.id,
                t.user_id,
                t.title,
                t.description,
                t.source_type,
                t.source_name,
                t.final_solution,
                t.cym_text,
                t.cym_portal_url,
                t.created_at,
                json_agg(
                    json_build_object(
                        'step_order', s.step_order,
                        'step_title', s.step_title,
                        'step_body', s.step_body
                    ) ORDER BY s.step_order
                ) AS steps_json
            FROM tickets t
            LEFT JOIN ticket_steps s ON t.id = s.ticket_id
            WHERE t.id = ANY(%s)
            GROUP BY t.id
            """,
            (ticket_ids,),
        )
        results: list[TicketDetail] = []
        for row in cur.fetchall():
            steps: list[TicketStep] = []
            if row["steps_json"] and row["steps_json"][0] is not None:
                for s in row["steps_json"]:
                    steps.append(
                        TicketStep(
                            step_order=s["step_order"],
                            step_title=s["step_title"],
                            step_body=s["step_body"],
                        )
                    )
            results.append(
                TicketDetail(
                    id=row["id"],
                    user_id=row["user_id"],
                    title=row["title"],
                    description=row["description"],
                    source_type=row["source_type"],
                    source_name=row["source_name"],
                    final_solution=row["final_solution"],
                    cym_text=row["cym_text"],
                    cym_portal_url=row["cym_portal_url"],
                    created_at=row["created_at"],
                    steps=steps,
                )
            )
        return results
    finally:
        conn.close()


def update_ticket_llm_evaluation(ticket_id: int, llm_evaluation: str, user_id: int) -> bool:
    """
    Ticket'ın Corpix AI değerlendirmesini günceller.
    
    Args:
        ticket_id: Güncellenecek ticket ID
        llm_evaluation: LLM değerlendirme metni
        user_id: İşlemi yapan kullanıcı ID (güvenlik kontrolü için)
        
    Returns:
        bool: Başarılı ise True
    """
    conn = get_db_conn()
    try:
        cur = conn.cursor()
        
        # Güvenlik: Önce ticket'ın sahibini kontrol et
        cur.execute("SELECT user_id FROM tickets WHERE id = %s", (ticket_id,))
        row = cur.fetchone()
        if not row:
            return False
        
        # Sadece kendi ticket'ını güncelleyebilir
        if row["user_id"] != user_id:
            return False
        
        cur.execute(
            """
            UPDATE tickets 
            SET llm_evaluation = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (llm_evaluation, ticket_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
