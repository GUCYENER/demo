from __future__ import annotations

import asyncio
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.routes.auth import get_current_admin, get_current_user
from app.models.schemas import ChatRequest, TicketDetail, TicketHistoryResponse
from app.services.ticket_service import (
    create_ticket_from_chat,
    get_ticket_detail,
    list_ticket_history_for_user,
)
from app.core.async_task_manager import task_manager, TaskStatus
from app.core.websocket_manager import ws_manager
from app.core.rag import search_knowledge_base
from app.services.logging_service import log_system_event

router = APIRouter(tags=["tickets"])


# --- Response Models ---

class AsyncTaskResponse(BaseModel):
    """Asenkron görev başlatma yanıtı."""
    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    """Görev durumu yanıtı."""
    task_id: str
    status: str
    progress_message: str
    result: Optional[dict] = None
    error: Optional[str] = None


class RAGSearchResult(BaseModel):
    """RAG arama sonucu."""
    id: int
    file_name: str
    score: int
    chunk_text: str
    details: dict


class RAGSearchResponse(BaseModel):
    """RAG arama yanıtı."""
    query: str
    results: List[RAGSearchResult]
    has_results: bool


class SelectionRequest(BaseModel):
    """Seçim ile ticket oluşturma isteği."""
    query: str
    selected_chunk_text: str
    selected_file_name: str


class LLMEvaluateRequest(BaseModel):
    """LLM değerlendirme isteği."""
    query: str
    context: str
    ticket_id: Optional[int] = None  # Varsa değerlendirmeyi ticket'a kaydeder


class LLMEvaluateResponse(BaseModel):
    """LLM değerlendirme yanıtı."""
    llm_response: str
    formatted_html: str
    ticket_id: Optional[int] = None  # Kaydedilen ticket ID


# --- RAG Search (Seçenek A - VYRA'ya Sor gibi) ---

@router.post("/search", response_model=RAGSearchResponse)
def search_rag(
    payload: ChatRequest,
    user=Depends(get_current_user),
):
    """
    RAG araması yap ve sonuçları döndür.
    
    Bu endpoint LLM kullanmaz, sadece RAG araması yapar.
    Kullanıcı sonuçlardan birini seçtikten sonra /create-from-selection ile ticket oluşturur.
    """
    from app.services.dialog_service import _parse_chunk_details
    
    user_id = user["id"]
    query = payload.query
    
    log_system_event("INFO", f"RAG araması başlatıldı: {query[:50]}...", "tickets", user_id)
    
    try:
        rag_response = search_knowledge_base(query, n_results=5, min_score=0.4, user_id=user_id)
        
        if not rag_response or not rag_response.has_results:
            return RAGSearchResponse(
                query=query,
                results=[],
                has_results=False
            )
        
        results = []
        for i, r in enumerate(rag_response.results[:5]):
            details = _parse_chunk_details(r.content)
            results.append(RAGSearchResult(
                id=i,
                file_name=r.source_file or "Bilgi Tabanı",
                score=int(r.score * 100),
                chunk_text=r.content,
                details=details
            ))
        
        log_system_event("INFO", f"RAG araması tamamlandı: {len(results)} sonuç", "tickets", user_id)
        
        return RAGSearchResponse(
            query=query,
            results=results,
            has_results=len(results) > 0
        )
        
    except Exception as e:
        log_system_event("ERROR", f"RAG arama hatası: {e}", "tickets", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Arama sırasında bir hata oluştu."
        )


@router.post("/create-from-selection", response_model=TicketDetail)
def create_ticket_from_selection(
    payload: SelectionRequest,
    user=Depends(get_current_user),
):
    """
    Seçilen RAG sonucundan ticket oluştur.
    
    LLM kullanmadan, direkt seçilen chunk'ı çözüm olarak kaydeder.
    """
    from app.services.ticket_service import create_ticket_direct
    
    user_id = user["id"]
    
    log_system_event("INFO", f"Seçimden ticket oluşturuluyor: {payload.selected_file_name}", "tickets", user_id)
    
    try:
        ticket_id = create_ticket_direct(
            user_id=user_id,
            query=payload.query,
            solution=payload.selected_chunk_text,
            source_name=payload.selected_file_name
        )
        
        detail = get_ticket_detail(ticket_id)
        if not detail:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Ticket kaydedilemedi."
            )
        
        return detail
        
    except Exception as e:
        log_system_event("ERROR", f"Ticket oluşturma hatası: {e}", "tickets", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ticket oluşturma sırasında bir hata oluştu."
        )


@router.post("/evaluate-with-llm", response_model=LLMEvaluateResponse)
def evaluate_with_llm(
    payload: LLMEvaluateRequest,
    user=Depends(get_current_user),
):
    """
    Seçilen sonucu LLM (Corpix) ile değerlendir.
    
    RAG sonucu + kullanıcı sorusu LLM'e gönderilir,
    zenginleştirilmiş yanıt döner.
    
    Eğer ticket_id verilmişse, değerlendirme o ticket'ın llm_evaluation alanına kaydedilir.
    """
    from app.core.llm import call_llm_api, get_active_prompt
    from app.services.ticket_service import update_ticket_llm_evaluation
    
    user_id = user["id"]
    
    log_system_event("INFO", "LLM değerlendirmesi başlatıldı", "tickets", user_id)
    
    try:
        system_prompt = get_active_prompt()
        
        user_message = f"""Kullanıcı Sorusu: {payload.query}

---
BİLGİ TABANI İÇERİĞİ:
{payload.context}
---

ÖNEMLİ TALİMATLAR:
1. Yukarıdaki bilgi tabanı içeriğini kullanarak kullanıcıya yanıt ver.
2. İçerikteki TÜM detayları koru (Uygulama Adı, Keyflow Search, Talep Tipi, Rol Seçimi, Yetki Bilgisi, dosya yolları vb.)
3. Bilgileri **anahtar: değer** formatında göster.
4. Dosya yollarını ASLA kısaltma veya atlama.
5. Yanıtı Türkçe olarak ver.
6. Daha detaylı ve açıklayıcı bir yanıt oluştur."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        llm_response = call_llm_api(messages)
        
        # Yanıtı formatla
        formatted_html = _format_llm_response_html(llm_response)
        
        # Eğer ticket_id varsa değerlendirmeyi kaydet
        saved_ticket_id = None
        if payload.ticket_id:
            success = update_ticket_llm_evaluation(
                ticket_id=payload.ticket_id,
                llm_evaluation=llm_response,
                user_id=user_id
            )
            if success:
                saved_ticket_id = payload.ticket_id
                log_system_event("INFO", f"LLM değerlendirmesi ticket #{payload.ticket_id}'e kaydedildi", "tickets", user_id)
        
        log_system_event("INFO", "LLM değerlendirmesi tamamlandı", "tickets", user_id)
        
        return LLMEvaluateResponse(
            llm_response=llm_response,
            formatted_html=formatted_html,
            ticket_id=saved_ticket_id
        )
        
    except Exception as e:
        log_system_event("ERROR", f"LLM değerlendirme hatası: {e}", "tickets", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Değerlendirme sırasında bir hata oluştu."
        )


def _format_llm_response_html(response: str) -> str:
    """LLM yanıtını HTML formatına dönüştür - Modern SaaS stilinde."""
    import re
    
    html = response
    
    # Numaralı liste tespit et ve formatla (1. 2. 3. vb.)
    has_numbered_list = bool(re.search(r'^\d+\.\s', html, re.MULTILINE))
    if has_numbered_list:
        lines = html.split('\n')
        in_list = False
        result = []
        
        for line in lines:
            trimmed = line.strip()
            list_match = re.match(r'^(\d+)\.\s+(.+)$', trimmed)
            
            if list_match:
                if not in_list:
                    result.append('<ol class="llm-steps-list">')
                    in_list = True
                # Numaralı öğe
                item_content = list_match.group(2)
                # Bold formatla
                item_content = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', item_content)
                # Dosya yollarını code olarak formatla
                item_content = re.sub(r'(\\\\[^\s<]+)', r'<code>\1</code>', item_content)
                result.append(f'<li>{item_content}</li>')
            else:
                if in_list:
                    result.append('</ol>')
                    in_list = False
                if trimmed:
                    result.append(trimmed)
        
        if in_list:
            result.append('</ol>')
        
        html = '\n'.join(result)
    
    # Markdown bold -> HTML bold
    html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', html)
    
    # Markdown italic -> HTML italic  
    html = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', html)
    
    # Key: Value formatını tespit et ve formatla
    html = re.sub(r'^([A-Za-zÇçĞğİıÖöŞşÜü\s\/]+):\s*(.+)$', r'<strong>\1:</strong> \2', html, flags=re.MULTILINE)
    
    # Dosya yollarını code olarak formatla (eğer henüz formatlanmamışsa)
    html = re.sub(r'(?<!<code>)(\\\\[^\s<]+)(?!</code>)', r'<code>\1</code>', html)
    
    # Satır sonları - liste içinde olmayanları paragraf yap
    paragraphs = re.split(r'\n\n+', html)
    formatted_paragraphs = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        # Zaten ol ile başlıyorsa dokunma
        if p.startswith('<ol') or p.startswith('<li') or p.startswith('</ol'):
            formatted_paragraphs.append(p)
        else:
            # Tek satırlık satır sonları
            p = p.replace('\n', '<br>')
            formatted_paragraphs.append(f'<div class="llm-paragraph">{p}</div>')
    
    html = ''.join(formatted_paragraphs)
    
    return html


# --- Async Ticket Creation ---

def _process_ticket_async(user_id: int, query: str, task_id: str):
    """
    🆕 v2.23.0: Sadece RAG araması yapar, LLM çağırmaz.
    Arka planda ticket oluşturma işlemi.
    """
    import uuid
    import traceback
    from datetime import datetime
    
    try:
        from app.services.ticket_service import create_ticket_rag_only
        
        ticket_id, rag_results, has_results = create_ticket_rag_only(user_id, query)
        
        return {
            "ticket_id": ticket_id,
            "title": "VYRA Çözüm Süreci",
            "description": query,
            "rag_results": rag_results,  # 🆕 RAG sonuçları
            "has_results": has_results,  # 🆕 Sonuç var mı?
            "final_solution": None,  # 🆕 Henüz AI değerlendirmesi yok
            "cym_text": None,
        }
    except Exception as e:
        # 🆕 v2.23.0: Hata loglama
        error_uid = f"ERR-{uuid.uuid4().hex[:8].upper()}"
        error_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"[VYRA ERROR] {error_time} | {error_uid} | User: {user_id} | Task: {task_id}")
        print(f"[VYRA ERROR] Query: {query[:100]}...")
        print(f"[VYRA ERROR] Exception: {type(e).__name__}: {str(e)}")
        traceback.print_exc()
        
        # Kullanıcıya gösterilecek mesaj
        raise Exception(f"Teknik bir sorun oluştu. Hata Kodu: {error_uid}. Lütfen daha sonra tekrar deneyin.")




def _on_ticket_complete(task_id: str, result: dict | None, error: str | None):
    """
    Ticket işlemi tamamlandığında WebSocket ile bildirim gönder.
    Bu callback ThreadPoolExecutor içinden çağrılır.
    """
    import threading
    
    task = task_manager.get_task_status(task_id)
    if not task:
        return
    
    user_id = task.user_id
    
    if error:
        message = {
            "type": "task_failed",
            "task_id": task_id,
            "error": error
        }
    else:
        message = {
            "type": "task_complete",
            "task_id": task_id,
            "result": result
        }
    
    # Thread-safe WebSocket mesajı gönderme
    # asyncio.run() yeni event loop oluşturur (thread içinde)
    try:
        asyncio.run(_send_ws_message(user_id, message))
    except Exception as e:
        print(f"[VYRA] WebSocket mesaj gönderimi hatası: {e}")


async def _send_ws_message(user_id: int, message: dict):
    """Helper: Thread içinden WebSocket mesajı gönder."""
    await ws_manager.send_to_user(user_id, message)



@router.post("/from-chat-async", response_model=AsyncTaskResponse)
def create_ticket_async(
    payload: ChatRequest,
    user=Depends(get_current_user),
):
    """
    Asenkron ticket oluşturma.
    
    Hemen task_id döner, işlem arka planda devam eder.
    Sonuç WebSocket üzerinden bildirilir veya /task-status endpoint'inden sorgulanabilir.
    """
    user_id = user["id"]
    
    # Görev oluştur
    task_id = task_manager.create_task(user_id, task_type="ticket")
    
    # Arka plana gönder
    task_manager.submit_task(
        task_id,
        _process_ticket_async,
        user_id,
        payload.query,
        task_id,
        on_complete=_on_ticket_complete
    )
    
    return AsyncTaskResponse(
        task_id=task_id,
        status="pending",
        message="Çözüm önerisi hazırlanıyor. Sonuç WebSocket üzerinden bildirilecek."
    )


@router.get("/task-status/{task_id}", response_model=TaskStatusResponse)
def get_task_status(
    task_id: str,
    user=Depends(get_current_user),
):
    """Görev durumunu sorgula."""
    task = task_manager.get_task_status(task_id)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Görev bulunamadı."
        )
    
    # Güvenlik: Sadece kendi görevini görebilir
    if task.user_id != user["id"] and user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu göreve erişim yetkiniz yok."
        )
    
    result_dict = None
    if task.status == TaskStatus.COMPLETED and task.result:
        result_dict = task.result
    
    return TaskStatusResponse(
        task_id=task_id,
        status=task.status.value,
        progress_message=task.progress_message,
        result=result_dict,
        error=task.error
    )


# --- Sync Endpoints (Eski - Geriye uyumluluk için) ---

@router.post("/from-chat", response_model=TicketDetail)
def create_ticket_via_chat(
    payload: ChatRequest,
    user=Depends(get_current_user),
):
    """Senkron ticket oluşturma (geriye uyumluluk için korunuyor)."""
    ticket_id, verifier, steps = create_ticket_from_chat(user["id"], payload.query)
    detail = get_ticket_detail(ticket_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ticket kaydedilemedi.",
        )
    return detail


@router.get("/history", response_model=TicketHistoryResponse)
def get_ticket_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user=Depends(get_current_user),
):
    is_admin = user["role"] == "admin"
    
    return list_ticket_history_for_user(
        user_id=user["id"],
        is_admin=is_admin,
        page=page,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/{ticket_id}", response_model=TicketDetail)
def get_ticket(ticket_id: int, user=Depends(get_current_user)):
    detail = get_ticket_detail(ticket_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Kayıt bulunamadı.")

    is_admin = user["role"] == "admin" or user.get("is_admin", False)
    if not is_admin:
        if detail.user_id != user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu kayda erişim yetkiniz yok."
            )

    return detail


# =====================================================
# 🆕 v2.23.0: İsteğe Bağlı AI Değerlendirmesi
# =====================================================

class AIEvaluateRequest(BaseModel):
    """AI değerlendirme isteği (ticket_id URL'den gelir)"""
    pass  # Boş - ticket bilgileri zaten DB'de


class AIEvaluateResponse(BaseModel):
    """AI değerlendirme yanıtı"""
    success: bool
    ticket_id: int
    final_solution: Optional[str] = None
    cym_text: Optional[str] = None
    error: Optional[str] = None


class UserSelectionRequest(BaseModel):
    """Kullanıcı seçimi isteği"""
    selected_chunk_text: str
    selected_file_name: str


class UserSelectionResponse(BaseModel):
    """Kullanıcı seçimi yanıtı"""
    success: bool
    ticket_id: int
    cym_text: Optional[str] = None
    error: Optional[str] = None


@router.post("/{ticket_id}/ai-evaluate", response_model=AIEvaluateResponse)
def add_ai_evaluation(
    ticket_id: int,
    user=Depends(get_current_user),
):
    """
    🆕 v2.23.0: Mevcut ticket'a AI değerlendirmesi ekle.
    
    Kullanıcı "Corpix ile Değerlendir" butonuna tıkladığında çağrılır.
    RAG sonuçlarını kullanarak LLM'den zenginleştirilmiş yanıt alır.
    """
    from app.services.ticket_service import add_ai_evaluation_to_ticket
    
    user_id = user["id"]
    
    log_system_event("INFO", f"AI değerlendirmesi istendi - Ticket #{ticket_id}", "tickets", user_id)
    
    try:
        success, final_solution, cym_text = add_ai_evaluation_to_ticket(ticket_id, user_id)
        
        if not success:
            return AIEvaluateResponse(
                success=False,
                ticket_id=ticket_id,
                error=cym_text or "Ticket bulunamadı veya yetkiniz yok"
            )
        
        log_system_event("INFO", f"AI değerlendirmesi tamamlandı - Ticket #{ticket_id}", "tickets", user_id)
        
        return AIEvaluateResponse(
            success=True,
            ticket_id=ticket_id,
            final_solution=final_solution,
            cym_text=cym_text
        )
        
    except Exception as e:
        log_system_event("ERROR", f"AI değerlendirme hatası: {e}", "tickets", user_id)
        return AIEvaluateResponse(
            success=False,
            ticket_id=ticket_id,
            error=str(e)
        )


@router.post("/{ticket_id}/select", response_model=UserSelectionResponse)
def add_user_selection(
    ticket_id: int,
    payload: UserSelectionRequest,
    user=Depends(get_current_user),
):
    """
    🆕 v2.23.0: Kullanıcı seçimini ticket'a ekle.
    
    Kullanıcı RAG sonuçlarından birini seçtiğinde çağrılır.
    Seçilen chunk doğrudan çözüm olarak kaydedilir.
    """
    from app.services.ticket_service import add_user_selection_to_ticket
    
    user_id = user["id"]
    
    log_system_event("INFO", f"Kullanıcı seçimi - Ticket #{ticket_id}", "tickets", user_id)
    
    try:
        success, cym_text = add_user_selection_to_ticket(
            ticket_id=ticket_id,
            user_id=user_id,
            selected_chunk_text=payload.selected_chunk_text,
            selected_file_name=payload.selected_file_name
        )
        
        if not success:
            return UserSelectionResponse(
                success=False,
                ticket_id=ticket_id,
                error=cym_text or "Ticket bulunamadı veya yetkiniz yok"
            )
        
        log_system_event("INFO", f"Kullanıcı seçimi kaydedildi - Ticket #{ticket_id}", "tickets", user_id)
        
        return UserSelectionResponse(
            success=True,
            ticket_id=ticket_id,
            cym_text=cym_text
        )
        
    except Exception as e:
        log_system_event("ERROR", f"Kullanıcı seçimi hatası: {e}", "tickets", user_id)
        return UserSelectionResponse(
            success=False,
            ticket_id=ticket_id,
            error=str(e)
        )
