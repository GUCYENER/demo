"""
VYRA L1 Support API - Async Task Manager
==========================================
Arka planda çalışan görevleri yönetir ve durumlarını takip eder.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional

from app.services.logging_service import log_system_event, log_error


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskResult:
    """Görev sonucu."""
    task_id: str
    user_id: int
    status: TaskStatus
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    progress_message: str = "Bekliyor..."


class AsyncTaskManager:
    """Asenkron görev yöneticisi."""
    
    def __init__(self, max_workers: int = 4):
        self.tasks: Dict[str, TaskResult] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._callbacks: Dict[str, Callable] = {}
    
    def create_task(self, user_id: int, task_type: str = "ticket") -> str:
        """Yeni görev oluştur ve task_id döndür."""
        task_id = f"{task_type}_{uuid.uuid4().hex[:12]}"
        
        with self._lock:
            self.tasks[task_id] = TaskResult(
                task_id=task_id,
                user_id=user_id,
                status=TaskStatus.PENDING,
                progress_message="Görev kuyruğa alındı..."
            )
        
        log_system_event("INFO", f"Görev oluşturuldu: {task_id} (user_id={user_id})", "async_task")
        return task_id
    
    def submit_task(
        self, 
        task_id: str, 
        func: Callable, 
        *args,
        on_complete: Optional[Callable] = None,
        **kwargs
    ):
        """Görevi arka planda çalıştırmak üzere gönder."""
        
        def wrapped_task():
            try:
                # Durumu güncelle
                with self._lock:
                    if task_id in self.tasks:
                        self.tasks[task_id].status = TaskStatus.PROCESSING
                        self.tasks[task_id].progress_message = "İşleniyor..."
                
                # Fonksiyonu çalıştır
                result = func(*args, **kwargs)
                
                # Başarılı sonuç
                with self._lock:
                    if task_id in self.tasks:
                        self.tasks[task_id].status = TaskStatus.COMPLETED
                        self.tasks[task_id].completed_at = datetime.now()
                        self.tasks[task_id].result = result
                        self.tasks[task_id].progress_message = "Tamamlandı!"
                
                log_system_event("INFO", f"Görev tamamlandı: {task_id}", "async_task")
                
                # Callback çağır
                if on_complete:
                    try:
                        on_complete(task_id, result, None)
                    except Exception as cb_err:
                        log_error(f"Callback hatası: {cb_err}", "async_task")
                
            except Exception as e:
                # Hata durumu
                error_msg = str(e)
                with self._lock:
                    if task_id in self.tasks:
                        self.tasks[task_id].status = TaskStatus.FAILED
                        self.tasks[task_id].completed_at = datetime.now()
                        self.tasks[task_id].error = error_msg
                        self.tasks[task_id].progress_message = f"Hata: {error_msg[:100]}"
                
                log_error(f"Görev başarısız: {task_id} - {error_msg}", "async_task")
                
                # Callback çağır (hata ile)
                if on_complete:
                    try:
                        on_complete(task_id, None, error_msg)
                    except Exception as cb_err:
                        log_error(f"Callback hatası: {cb_err}", "async_task")
        
        self.executor.submit(wrapped_task)
    
    def get_task_status(self, task_id: str) -> Optional[TaskResult]:
        """Görev durumunu getir."""
        with self._lock:
            return self.tasks.get(task_id)
    
    def get_user_tasks(self, user_id: int, limit: int = 10) -> list[TaskResult]:
        """Kullanıcının son görevlerini getir."""
        with self._lock:
            user_tasks = [t for t in self.tasks.values() if t.user_id == user_id]
            # Son oluşturulanlara göre sırala
            user_tasks.sort(key=lambda x: x.created_at, reverse=True)
            return user_tasks[:limit]
    
    def cleanup_old_tasks(self, max_age_seconds: int = 3600):
        """Eski görevleri temizle (1 saatten eski olanlar)."""
        now = datetime.now()
        to_remove = []
        
        with self._lock:
            for task_id, task in self.tasks.items():
                if task.completed_at:
                    age = (now - task.completed_at).total_seconds()
                    if age > max_age_seconds:
                        to_remove.append(task_id)
        
            for task_id in to_remove:
                del self.tasks[task_id]
        
        if to_remove:
            log_system_event("INFO", f"{len(to_remove)} eski görev temizlendi", "async_task")


# Global instance
task_manager = AsyncTaskManager()
