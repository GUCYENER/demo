"""
VYRA L1 Support API - Dialog Routes
====================================
WhatsApp tarzı çoklu mesaj dialog sistemi API endpoint'leri.

Version: 2.14.0
"""

from __future__ import annotations

import base64
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.services.logging_service import log_warning

from app.api.routes.auth import get_current_user
from app.core.websocket_manager import ws_manager
from app.services.dialog_service import (
    create_dialog,
    get_or_create_active_dialog,
    close_dialog,
    list_user_dialogs,
    get_dialog_history,  # v2.21.0
    add_message,
    get_dialog_messages,
    add_message_feedback,
    process_user_message,
    process_quick_reply,
    ask_corpix,  # v2.24.5
    generate_ticket_summary,  # v2.24.5
)
from app.services.logging_service import log_system_event

router = APIRouter(prefix="/dialogs", tags=["dialogs"])


# =============================================================================
# REQUEST / RESPONSE MODELS
# =============================================================================

class DialogCreateRequest(BaseModel):
    """Yeni dialog oluşturma."""
    title: Optional[str] = Field(None, max_length=255)


class DialogResponse(BaseModel):
    """Dialog yanıtı."""
    id: int
    user_id: int
    title: Optional[str]
    status: str
    created_at: str
    updated_at: str
    message_count: Optional[int] = 0


class MessageRequest(BaseModel):
    """Yeni mesaj gönderme."""
    content: str = Field(..., min_length=1, max_length=5000)
    images: Optional[List[str]] = None  # Base64 encoded images


class MessageResponse(BaseModel):
    """Mesaj yanıtı."""
    id: int
    role: str
    content: str
    content_type: str
    metadata: Optional[dict] = None
    created_at: str


class QuickReplyRequest(BaseModel):
    """Hızlı yanıt (Evet/Hayır veya seçim)."""
    action: str = Field(..., description="yes, no, select, multi_select")
    selection_id: Optional[int] = None
    selection_ids: Optional[List[int]] = None  # Çoklu seçim desteği
    message_id: Optional[int] = None  # Hedef assistant mesajı ID'si


class FeedbackRequest(BaseModel):
    """Mesaj feedback."""
    message_id: int
    feedback_type: str = Field(..., description="helpful, not_helpful")


class AIResponseWithQuickReply(BaseModel):
    """AI yanıtı + opsiyonel hızlı yanıt butonları."""
    message: MessageResponse
    quick_reply: Optional[dict] = None


# =============================================================================
# DIALOG ENDPOINTS
# =============================================================================

@router.get("", response_model=List[DialogResponse])
def list_dialogs(
    limit: int = Query(20, ge=1, le=100),
    user=Depends(get_current_user)
):
    """Kullanıcının dialoglarını listele."""
    dialogs = list_user_dialogs(user["id"], limit)
    return [
        DialogResponse(
            id=d["id"],
            user_id=user["id"],
            title=d.get("title"),
            status=d["status"],
            created_at=d["created_at"].isoformat() if d.get("created_at") else "",
            updated_at=d["updated_at"].isoformat() if d.get("updated_at") else "",
            message_count=d.get("message_count", 0)
        )
        for d in dialogs
    ]


@router.get("/history")
def get_history(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    source_type: Optional[str] = Query(None, description="Kaynak tipi: vyra_chat"),
    user=Depends(get_current_user)
):
    """
    v2.21.0: Geçmiş Çözümler için kapanmış dialog geçmişini getir.
    
    Kategori gösterimi için source_type dahil edilir.
    """
    result = get_dialog_history(
        user_id=user["id"],
        limit=limit,
        offset=offset,
        source_type=source_type
    )
    
    # Tarih formatlaması
    for item in result["items"]:
        if item.get("created_at"):
            item["created_at"] = item["created_at"].isoformat()
        if item.get("closed_at"):
            item["closed_at"] = item["closed_at"].isoformat()
    
    return result


@router.post("", response_model=DialogResponse, status_code=status.HTTP_201_CREATED)
def create_new_dialog(
    request: DialogCreateRequest,
    user=Depends(get_current_user)
):
    """Yeni dialog başlat."""
    dialog_id = create_dialog(user["id"], request.title)
    return DialogResponse(
        id=dialog_id,
        user_id=user["id"],
        title=request.title or "Yeni Dialog",
        status="active",
        created_at="",
        updated_at="",
        message_count=0
    )


@router.get("/active", response_model=DialogResponse)
def get_active(user=Depends(get_current_user)):
    """Aktif dialogu getir (yoksa oluştur)."""
    dialog = get_or_create_active_dialog(user["id"])
    return DialogResponse(
        id=dialog["id"],
        user_id=dialog["user_id"],
        title=dialog.get("title"),
        status=dialog["status"],
        created_at=dialog["created_at"].isoformat() if dialog.get("created_at") else "",
        updated_at=dialog["updated_at"].isoformat() if dialog.get("updated_at") else "",
        message_count=0
    )


@router.post("/{dialog_id}/close")
def close_dialog_endpoint(
    dialog_id: int,
    user=Depends(get_current_user)
):
    """Dialogu kapat."""
    success = close_dialog(dialog_id, user["id"])
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dialog bulunamadı veya zaten kapalı."
        )
    return {"message": "Dialog kapatıldı."}


# =============================================================================
# MESSAGE ENDPOINTS
# =============================================================================

@router.get("/{dialog_id}/messages", response_model=List[MessageResponse])
def get_messages(
    dialog_id: int,
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user)
):
    """Dialog mesajlarını getir."""
    messages = get_dialog_messages(dialog_id, limit)
    return [
        MessageResponse(
            id=m["id"],
            role=m["role"],
            content=m["content"],
            content_type=m["content_type"],
            metadata=m.get("metadata"),
            created_at=m["created_at"].isoformat() if m.get("created_at") else ""
        )
        for m in messages
    ]


@router.post("/{dialog_id}/messages", response_model=AIResponseWithQuickReply)
async def send_message(
    dialog_id: int,
    request: MessageRequest,
    user=Depends(get_current_user)
):
    """
    Mesaj gönder ve AI yanıtı al.
    
    - Görsel varsa OCR yapılır
    - RAG araması yapılır
    - Çoklu eşleşme varsa seçim butonları döner
    - WebSocket üzerinden bildirim gönderilir
    """
    # Base64 görselleri decode et
    images = None
    if request.images:
        images = []
        for img_b64 in request.images[:5]:  # Max 5 görsel
            try:
                # "data:image/png;base64,..." formatını handle et
                if "," in img_b64:
                    img_b64 = img_b64.split(",")[1]
                images.append(base64.b64decode(img_b64))
            except Exception as e:
                log_warning(f"Base64 görsel decode hatası: {e}", "dialog")
    
    # Widget config (JWT'den — use_rag, prompt_id, llm_config_id)
    widget_config = None
    if user.get("widget"):
        widget_config = {
            "use_rag": user.get("widget_use_rag", True),
            "prompt_id": user.get("widget_prompt_id"),
            "llm_config_id": user.get("widget_llm_config_id"),
        }

    # AI işleme
    assistant_msg, quick_reply = process_user_message(
        dialog_id=dialog_id,
        user_id=user["id"],
        content=request.content,
        images=images,
        widget_config=widget_config,
    )
    
    # WebSocket üzerinden bildirim gönder (async context'teyiz)
    try:
        await ws_manager.send_dialog_message(
            user_id=user["id"],
            dialog_id=dialog_id,
            message=assistant_msg,
            quick_reply=quick_reply
        )
    except Exception as ws_err:
        log_system_event("WARNING", f"WebSocket bildirimi gönderilemedi: {ws_err}", "dialog", user["id"])
    
    return AIResponseWithQuickReply(
        message=MessageResponse(
            id=assistant_msg["id"],
            role=assistant_msg["role"],
            content=assistant_msg["content"],
            content_type=assistant_msg["content_type"],
            metadata=assistant_msg.get("metadata"),
            created_at=assistant_msg["created_at"]
        ),
        quick_reply=quick_reply
    )


# =============================================================================
# STREAMING SSE ENDPOINT (v2.50.0)
# =============================================================================

@router.post("/{dialog_id}/messages/stream")
async def send_message_stream(
    dialog_id: int,
    request: MessageRequest,
    user=Depends(get_current_user)
):
    """
    🆕 v2.50.0: Streaming mesaj gönder — SSE (Server-Sent Events) ile token token yanıt.
    
    Event Tipleri:
    - rag_complete: RAG araması tamamlandı
    - token: LLM'den gelen bir token parçası
    - status: Durum güncellemesi
    - cached: Cache hit — tam yanıt tek seferde döner
    - done: Tamamlandı — final metadata ile
    - error: Hata durumu
    """
    import json
    from starlette.responses import StreamingResponse
    from app.services.dialog.processor import process_user_message_stream
    
    # Base64 görselleri decode et
    images = None
    if request.images:
        images = []
        for img_b64 in request.images[:5]:
            try:
                if "," in img_b64:
                    img_b64 = img_b64.split(",")[1]
                images.append(base64.b64decode(img_b64))
            except Exception as e:
                log_warning(f"Base64 görsel decode hatası: {e}", "dialog")
    
    # Widget config (JWT'den)
    stream_widget_config = None
    if user.get("widget"):
        stream_widget_config = {
            "use_rag": user.get("widget_use_rag", True),
            "prompt_id": user.get("widget_prompt_id"),
            "llm_config_id": user.get("widget_llm_config_id"),
        }

    def event_generator():
        """SSE event stream generator."""
        try:
            for event in process_user_message_stream(
                dialog_id=dialog_id,
                user_id=user["id"],
                content=request.content,
                images=images,
                widget_config=stream_widget_config,
            ):
                event_type = event.get("type", "token")
                event_data = event.get("data", "")
                
                # SSE format: "data: {json}\n\n"
                payload = json.dumps({"type": event_type, "data": event_data}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
                
        except Exception as e:
            log_system_event("ERROR", f"SSE stream hatası: {e}", "dialog", user["id"])
            error_payload = json.dumps({"type": "error", "data": str(e)}, ensure_ascii=False)
            yield f"data: {error_payload}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Nginx proxy buffering kapatma
        }
    )


# 🆕 v2.51.0: Vyra Önerisi — CatBoost bypass sonrası LLM ile cevap iyileştirme
class EnhanceRequest(BaseModel):
    """Vyra önerisi isteği."""
    query: str = Field(..., min_length=2, max_length=2000)
    message_id: int = Field(..., description="Orijinal mesaj ID")

@router.post("/{dialog_id}/messages/enhance")
def enhance_message(
    dialog_id: int,
    request: EnhanceRequest,
    user=Depends(get_current_user)
):
    """
    CatBoost bypass cevabını LLM ile iyileştir.
    Kullanıcı 'Vyra önerisi al' tıkladığında çağrılır.
    """
    import time
    start = time.time()
    
    try:
        from app.services.deep_think_service import DeepThinkService
        service = DeepThinkService()
        
        # Intent analizi
        intent = service.analyze_intent(request.query)
        
        # Expanded retrieval (RAG arama)
        rag_results = service.expanded_retrieval(request.query, intent, user["id"])
        
        if not rag_results:
            return {"success": False, "error": "Bilgi bulunamadı"}
        
        # LLM synthesis (bypass yok — tam sentez)
        synthesized = service.synthesize_response(request.query, rag_results, intent)
        
        # 🛡️ v2.51.0: Halüsinasyon kontrolü — sentezlenen cevabı kaynağa karşı doğrula
        try:
            from app.services.learned_qa_service import get_learned_qa_service
            qa_service = get_learned_qa_service()
            
            # RAG kaynak metinlerini birleştir (doğrulama için)
            source_texts = " ".join(
                r.get("content", "")[:300] for r in rag_results[:3]
            )
            
            # v2.52.1: Kısa kaynak metinlerde (@@ < 500 char, Excel komut tabloları vb.)
            # validation çok agresif oluyor çünkü LLM cevabı doğal olarak
            # kaynaktan farklı kelimeler içerir — bu halüsinasyon değil, zenginleştirme.
            # Kısa kaynaklar için validasyonu atla (source zaten kısa = sınırlı bilgi).
            source_len = len(source_texts.strip())
            
            if source_len >= 500:
                # Yeterli kaynak metin var → validasyonu uygula
                validation = qa_service._validate_answer(
                    answer=synthesized,
                    source_text=source_texts,
                    question=request.query
                )
                
                if not validation["passed"]:
                    log_warning(
                        f"Enhance REJECTED (hallucination): "
                        f"reason={validation['reason']}, "
                        f"faithfulness={validation.get('faithfulness', 0):.2f}, "
                        f"grounding={validation.get('grounding', 0):.1%}",
                        "dialog"
                    )
                    return {
                        "success": False,
                        "error": "Üretilen cevap güvenilirlik kontrolünden geçemedi. Kaynak bilgiye daha sadık bir cevap üretilemedi."
                    }
            else:
                log_system_event(
                    "INFO",
                    f"Enhance validation SKIPPED: source_len={source_len} < 500 (kısa chunk)",
                    "dialog"
                )
        except Exception as val_err:
            log_warning(f"Enhance validation hatası: {val_err}", "dialog")
            # Validation başarısız olursa yine de devam et (fail-open)
        
        elapsed_ms = (time.time() - start) * 1000
        
        # Orijinal mesajı güncelle (metadata'ya enhanced ekle)
        try:
            from app.core.db import get_db_context
            import json
            
            with get_db_context() as conn:
                with conn.cursor() as cur:
                    # Mevcut metadata'yı al
                    cur.execute(
                        "SELECT metadata FROM dialog_messages WHERE id = %s",
                        (request.message_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        meta = row.get("metadata") if isinstance(row, dict) else row[0]
                        if isinstance(meta, str):
                            meta = json.loads(meta)
                        if not isinstance(meta, dict):
                            meta = {}
                        
                        meta["enhanced"] = True
                        meta["enhanced_content"] = synthesized
                        meta["enhance_time_ms"] = elapsed_ms
                        
                        cur.execute(
                            "UPDATE dialog_messages SET content = %s, metadata = %s WHERE id = %s",
                            (synthesized, json.dumps(meta), request.message_id)
                        )
                    conn.commit()
        except Exception as db_err:
            log_warning(f"Enhance DB güncelleme hatası: {db_err}", "dialog")
        
        # Cache'i de güncelle
        try:
            from app.core.cache import cache_service
            import hashlib
            user_id = user['id']
            cache_key = f"dt:{hashlib.md5(f'{request.query.lower().strip()}:{user_id}'.encode()).hexdigest()}"
            cache_service.deep_think.delete(cache_key)
        except Exception:
            pass
        
        return {
            "success": True,
            "content": synthesized,
            "elapsed_ms": elapsed_ms
        }
        
    except Exception as e:
        log_warning(f"Enhance hatası: {e}", "dialog")
        return {"success": False, "error": "Yanıt iyileştirilemedi"}


@router.post("/{dialog_id}/quick-reply", response_model=MessageResponse)
def handle_quick_reply(
    dialog_id: int,
    request: QuickReplyRequest,
    user=Depends(get_current_user)
):
    """Hızlı yanıt işle (Evet/Hayır veya doküman seçimi)."""
    result = process_quick_reply(
        dialog_id=dialog_id,
        user_id=user["id"],
        action=request.action,
        selection_id=request.selection_id,
        selection_ids=request.selection_ids,  # Çoklu seçim desteği
        message_id=request.message_id  # Opsiyonel - varsa direkt o mesajı kullan
    )
    return MessageResponse(
        id=result["id"],
        role=result["role"],
        content=result["content"],
        content_type=result["content_type"],
        metadata=result.get("metadata"),
        created_at=result["created_at"]
    )


@router.post("/{dialog_id}/feedback")
def add_feedback(
    dialog_id: int,
    request: FeedbackRequest,
    user=Depends(get_current_user)
):
    """Mesaja feedback ekle (ML için)."""
    success = add_message_feedback(
        message_id=request.message_id,
        feedback_type=request.feedback_type,
        user_id=user["id"]
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mesaj bulunamadı."
        )
    
    log_system_event(
        "INFO",
        f"Dialog mesaj #{request.message_id} feedback: {request.feedback_type}",
        "dialog",
        user["id"]
    )
    return {"message": "Feedback kaydedildi. Teşekkürler!"}


class ResponseTimeRequest(BaseModel):
    """Response time güncelleme."""
    message_id: int
    response_time: float = Field(..., description="Response time in seconds")


@router.post("/{dialog_id}/response-time")
def update_response_time(
    dialog_id: int,
    request: ResponseTimeRequest,
    user=Depends(get_current_user)
):
    """Mesajın response time değerini güncelle."""
    from app.services.dialog_service import update_message_metadata
    
    success = update_message_metadata(
        message_id=request.message_id,
        key="response_time",
        value=request.response_time
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mesaj bulunamadı."
        )
    
    return {"message": "Response time kaydedildi."}


# =============================================================================
# CORPIX FALLBACK & TICKET SUMMARY ENDPOINTS (v2.24.5)
# =============================================================================

class AskCorpixRequest(BaseModel):
    """Corpix'e soru sorma isteği."""
    query: str = Field(..., min_length=1, max_length=2000)


class TicketSummaryResponse(BaseModel):
    """Ticket özeti yanıtı."""
    summary: str
    dialog_id: int


@router.post("/{dialog_id}/ask-corpix", response_model=MessageResponse)
async def ask_corpix_endpoint(
    dialog_id: int,
    request: AskCorpixRequest,
    user=Depends(get_current_user)
):
    """
    v2.24.5: Corpix L1 Destek'e soru sor.
    
    RAG'da yetkili doküman bulunamadığında kullanıcı 
    Corpix'e yönlendirilir ve LLM'den yanıt alır.
    """
    # Kullanıcı mesajını kaydet
    add_message(dialog_id, "user", f"🤖 Corpix'e soruyorum: {request.query}", "text")
    
    # Corpix'ten yanıt al
    corpix_response = ask_corpix(request.query, user["id"])
    
    # Assistant yanıtını kaydet
    msg_id = add_message(dialog_id, "assistant", corpix_response, "text")
    
    log_system_event("INFO", f"Corpix yanıtı: dialog #{dialog_id}", "dialog", user["id"])
    
    from datetime import datetime
    return MessageResponse(
        id=msg_id,
        role="assistant",
        content=corpix_response,
        content_type="text",
        metadata=None,
        created_at=datetime.now().isoformat()
    )


@router.post("/{dialog_id}/generate-ticket-summary", response_model=TicketSummaryResponse)
def generate_ticket_summary_endpoint(
    dialog_id: int,
    user=Depends(get_current_user)
):
    """
    v2.24.5: Dialog akışından IT jargonlu çağrı özeti oluştur.
    
    Kullanıcı 'Çağrı Aç' butonuna tıkladığında çağrılır.
    LLM kullanarak dialog'u profesyonel IT çağrı metnine dönüştürür.
    """
    summary = generate_ticket_summary(dialog_id, user["id"])
    
    log_system_event("INFO", f"Ticket özeti oluşturuldu: dialog #{dialog_id}", "dialog", user["id"])
    
    return TicketSummaryResponse(
        summary=summary,
        dialog_id=dialog_id
    )
