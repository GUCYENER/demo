"""
VYRA L1 Support API - WebSocket Routes
=======================================
WebSocket bağlantı endpoint'leri.
"""

from __future__ import annotations

import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import jwt, JWTError

from app.core.config import settings
from app.core.websocket_manager import ws_manager
from app.core.async_task_manager import task_manager, TaskStatus
from app.services.logging_service import log_system_event, log_error

router = APIRouter(tags=["websocket"])


def verify_ws_token(token: str) -> dict | None:
    """WebSocket için JWT token doğrulama."""
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        log_error(f"WebSocket JWT hatası: {e}", "websocket")
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(None)
):
    """
    Ana WebSocket endpoint'i.
    
    Bağlantı: ws://localhost:8002/api/ws?token=<JWT_TOKEN>
    
    Mesaj formatları:
    - Server -> Client: {"type": "task_complete", "task_id": "...", "result": {...}}
    - Server -> Client: {"type": "task_failed", "task_id": "...", "error": "..."}
    - Client -> Server: {"type": "ping"}
    - Server -> Client: {"type": "pong"}
    """
    
    # Token doğrulama
    if not token:
        await websocket.close(code=4001, reason="Token gerekli")
        return
    
    payload = verify_ws_token(token)
    if not payload:
        await websocket.close(code=4002, reason="Geçersiz token")
        return
    
    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4003, reason="Geçersiz kullanıcı")
        return
    
    user_id = int(user_id)
    
    # Bağlantıyı kabul et
    await ws_manager.connect(websocket, user_id)
    
    try:
        # Bağlantı onay mesajı
        await websocket.send_json({
            "type": "connected",
            "message": "WebSocket bağlantısı kuruldu",
            "user_id": user_id
        })
        
        # Mesaj döngüsü
        while True:
            try:
                data = await websocket.receive_text()
                message = json.loads(data)
                
                msg_type = message.get("type", "")
                
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                
                elif msg_type == "get_task_status":
                    task_id = message.get("task_id")
                    if task_id:
                        task = task_manager.get_task_status(task_id)
                        if task:
                            await websocket.send_json({
                                "type": "task_status",
                                "task_id": task_id,
                                "status": task.status.value,
                                "progress_message": task.progress_message
                            })
                
                elif msg_type == "get_pending_tasks":
                    tasks = task_manager.get_user_tasks(user_id, limit=5)
                    pending = [
                        {
                            "task_id": t.task_id,
                            "status": t.status.value,
                            "progress_message": t.progress_message,
                            "created_at": t.created_at.isoformat()
                        }
                        for t in tasks
                        if t.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]
                    ]
                    await websocket.send_json({
                        "type": "pending_tasks",
                        "tasks": pending
                    })
                    
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Geçersiz JSON formatı"
                })
                
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket, user_id)
    except Exception as e:
        log_error(f"WebSocket hatası: {e}", "websocket")
        await ws_manager.disconnect(websocket, user_id)
