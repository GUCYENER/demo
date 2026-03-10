from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.routes.auth import get_current_user
from app.models.schemas import ChatRequest, TicketDetail
from app.services.ticket_service import create_ticket_from_chat, get_ticket_detail

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("", response_model=TicketDetail)
def chat_and_create_ticket(payload: ChatRequest, user=Depends(get_current_user)):
    ticket_id, verifier, steps = create_ticket_from_chat(user.id, payload.query)
    detail = get_ticket_detail(ticket_id)
    assert detail is not None  # create_ticket_from_chat zaten kayıt atıyor
    return detail
