"""
VYRA L1 Support API - WebSocket Manager
========================================
Asenkron işlem sonuçlarını kullanıcılara bildirmek için WebSocket yönetimi.
"""

from __future__ import annotations

import asyncio
from typing import Dict, Set
from fastapi import WebSocket
from app.services.logging_service import log_system_event


class ConnectionManager:
    """WebSocket bağlantı yöneticisi - kullanıcı bazlı bağlantı takibi."""
    
    def __init__(self):
        # user_id -> Set[WebSocket] (bir kullanıcının birden fazla sekme/cihazı olabilir)
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, user_id: int):
        """Yeni WebSocket bağlantısı kabul et."""
        await websocket.accept()
        async with self._lock:
            if user_id not in self.active_connections:
                self.active_connections[user_id] = set()
            self.active_connections[user_id].add(websocket)
        log_system_event("INFO", f"WebSocket bağlantısı kuruldu: user_id={user_id}", "websocket")
    
    async def disconnect(self, websocket: WebSocket, user_id: int):
        """WebSocket bağlantısını kaldır."""
        async with self._lock:
            if user_id in self.active_connections:
                self.active_connections[user_id].discard(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
        log_system_event("INFO", f"WebSocket bağlantısı kapatıldı: user_id={user_id}", "websocket")
    
    async def send_to_user(self, user_id: int, message: dict):
        """Belirli bir kullanıcıya mesaj gönder (tüm aktif bağlantılarına)."""
        async with self._lock:
            connections = self.active_connections.get(user_id, set()).copy()
        
        if not connections:
            log_system_event("WARNING", f"WebSocket: user_id={user_id} aktif bağlantı yok", "websocket")
            return False
        
        disconnected = []
        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                log_system_event("ERROR", f"WebSocket gönderim hatası: {e}", "websocket")
                disconnected.append(websocket)
        
        # Başarısız bağlantıları temizle
        if disconnected:
            async with self._lock:
                for ws in disconnected:
                    if user_id in self.active_connections:
                        self.active_connections[user_id].discard(ws)
        
        return True
    
    async def broadcast(self, message: dict):
        """Tüm bağlı kullanıcılara mesaj gönder."""
        async with self._lock:
            all_connections = [
                (user_id, ws) 
                for user_id, connections in self.active_connections.items() 
                for ws in connections
            ]
        
        for user_id, websocket in all_connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                log_system_event("WARNING", f"WebSocket broadcast hatası (user_id={user_id}): {e}", "websocket")

    # ==========================================================================
    # DIALOG MESSAGE HELPERS (v2.15.0)
    # ==========================================================================

    async def send_dialog_message(self, user_id: int, dialog_id: int, message: dict, quick_reply: dict = None):
        """
        Dialog mesajı gönder.
        dialog_service tarafından çağrılır.
        """
        payload = {
            "type": "dialog_message",
            "dialog_id": dialog_id,
            "message": message,
            "quick_reply": quick_reply
        }
        return await self.send_to_user(user_id, payload)

    async def send_dialog_typing(self, user_id: int, is_typing: bool = True):
        """
        Typing indicator gönder.
        """
        payload = {
            "type": "dialog_typing",
            "is_typing": is_typing
        }
        return await self.send_to_user(user_id, payload)


# Global instance
ws_manager = ConnectionManager()
