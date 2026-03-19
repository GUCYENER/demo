# app/api/main.py

from __future__ import annotations

import time
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import auth, chat, health, rag as rag_routes, tickets, llm_config, prompts, users, system, websocket as ws_routes, organizations, feedback, dialog, permissions, assets, ldap_settings, domain_org_api, widget as widget_routes
from app.core.config import settings
from app.core.db import init_db
from app.core.rate_limiter import limiter, get_rate_limit_handler, get_rate_limit_exception


def _recover_stuck_files():
    """
    🛡️ v2.42.0: Crash recovery guard.
    Uygulama başladığında 'processing' durumundaki orphan dosyaları
    'failed' olarak işaretler. Bu dosyalar önceki crash sırasında
    takılı kalmış dosyalardır.
    """
    try:
        from app.core.db import get_db_conn
        from app.services.logging_service import log_system_event, log_warning
        
        conn = get_db_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "UPDATE uploaded_files SET status = 'failed' WHERE status = 'processing'"
            )
            stuck_count = cur.rowcount
            conn.commit()
            
            if stuck_count > 0:
                log_warning(
                    f"🛡️ Crash recovery: {stuck_count} takılı dosya 'failed' olarak güncellendi",
                    "startup"
                )
            else:
                log_system_event("DEBUG", "Crash recovery: Takılı dosya bulunamadı", "startup")
        finally:
            conn.close()
    except Exception as e:
        from app.services.logging_service import log_error
        log_error(f"Crash recovery hatası: {e}", "startup")


def _preload_embedding_model():
    """
    🚀 Embedding modelini ve sık kullanılan sorguları arka planda yükler.
    v2.23.0: Artık cache warm-up da yapılır.
    Not: Loglama preload_rag_service() içinde yapılır (çift log önleme).
    """
    try:
        from app.services.rag_service import preload_rag_service
        
        preload_rag_service()  # Model yükle + cache warm-up (loglama servis içinde)
    except Exception as e:
        from app.services.logging_service import log_error
        log_error(f"RAG preload hatası: {e}", "startup")


# Scheduler durumunu tutmak için global flag
_scheduler_running = False


def _run_schedule_checker():
    """Periyodik olarak scheduled training koşullarını kontrol eder"""
    import time
    
    from app.services.logging_service import log_system_event, log_error
    
    log_system_event("INFO", "[Scheduler] ML Training schedule checker baslatildi", "scheduler")
    
    while _scheduler_running:
        try:
            # Her SCHEDULER_INTERVAL_SECONDS saniyede bir kontrol et (config'den)
            time.sleep(settings.SCHEDULER_INTERVAL_SECONDS)
            
            if not _scheduler_running:
                break
            
            # v2.21.8: İnaktif dialog'ları kapat (30 dk)
            try:
                from app.services.dialog_service import close_inactive_dialogs
                closed_count = close_inactive_dialogs(inactivity_minutes=30)
                if closed_count > 0:
                    log_system_event("INFO", f"[Scheduler] {closed_count} inaktif dialog kapatildi", "scheduler")
            except Exception as e:
                log_error(f"[Scheduler] Dialog inaktivite kontrol hatasi: {e}", "scheduler")
            
            from app.services.ml_training_service import get_ml_training_service
            service = get_ml_training_service()
            
            # 1) Önce stale job'ları temizle (timeout değerini DB'den oku)
            timeout_minutes = service.get_job_timeout_setting()
            if timeout_minutes > 0:
                killed = service.kill_stale_jobs(timeout_minutes=timeout_minutes)
                if killed > 0:
                    log_system_event("WARNING", f"[Scheduler] {killed} stale job(s) otomatik sonlandirildi (limit: {timeout_minutes} dk)", "scheduler")
            
            # 2) Eğitim zaten devam ediyorsa atla
            if service.is_training():
                continue
            
            # 3) Schedule koşullarını kontrol et
            if service.check_scheduled_trigger():
                log_system_event("INFO", "[Scheduler] Otomatik egitim tetiklendi", "scheduler")
                service.start_training(user_id=1, trigger="scheduled")
                
        except Exception as e:
            log_error(f"[Scheduler] Kontrol hatasi: {e}", "scheduler")
    
    log_system_event("INFO", "[Scheduler] ML Training schedule checker durduruldu", "scheduler")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü - startup ve shutdown olayları"""
    global _scheduler_running
    
    # 🛡️ v2.42.0: Crash recovery — takılı dosyaları temizle (senkron, hızlı)
    _recover_stuck_files()
    
    # Startup: Embedding modelini arka planda yükle
    thread = threading.Thread(target=_preload_embedding_model, daemon=True)
    thread.start()
    
    # Startup: Schedule checker'ı başlat
    _scheduler_running = True
    scheduler_thread = threading.Thread(target=_run_schedule_checker, daemon=True)
    scheduler_thread.start()
    
    yield
    
    # Shutdown: Schedule checker'ı durdur
    _scheduler_running = False


def create_app() -> FastAPI:
    init_db()

    # v2.48.0: Production'da Swagger/ReDoc/OpenAPI kapat
    is_prod = not settings.debug

    app = FastAPI(
        title=settings.app_name, 
        debug=settings.debug,
        lifespan=lifespan,
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
    )
    
    # 🔒 Rate Limiting - Brute force ve DoS koruması
    app.state.limiter = limiter
    app.add_exception_handler(get_rate_limit_exception(), get_rate_limit_handler())

    # �️ Global Exception Handler — 500 hatalarında CORS header ekler (v2.46.0)
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        import logging
        logger = logging.getLogger("vyra")
        logger.error(f"[Global] Unhandled exception: {type(exc).__name__}: {exc}", exc_info=True)

        origin = request.headers.get("origin", "")
        headers = {}
        if origin in settings.backend_cors_origins:
            headers["access-control-allow-origin"] = origin
            headers["access-control-allow-credentials"] = "true"

        return JSONResponse(
            status_code=500,
            content={"detail": "Sunucu hatası oluştu. Lütfen tekrar deneyin."},
            headers=headers,
        )

    # �🚀 Gzip Compression - 500 byte üzeri yanıtları sıkıştır (v2.30.1)
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # CORS Ayarları — v2.48.0: config.py'den okunuyor, production-safe
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.backend_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Accept"],
        expose_headers=["Content-Disposition"],
    )

    # v2.60.0: Widget token endpoint herkese açık CORS (herhangi bir domain'den embed)
    @app.middleware("http")
    async def widget_cors_middleware(request: Request, call_next):
        """Widget /api/widget/token endpoint'i için wildcard CORS."""
        is_widget_path = request.url.path in ("/api/widget/token",)
        if is_widget_path and request.method == "OPTIONS":
            from fastapi.responses import Response as FastAPIResponse
            return FastAPIResponse(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Content-Type",
                    "Access-Control-Max-Age": "86400",
                },
            )
        response = await call_next(request)
        if is_widget_path:
            response.headers["Access-Control-Allow-Origin"] = "*"
        return response
    
    # 📊 Request Logging Middleware (v2.27.2)
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Merkezi HTTP request/response loglama"""
        from app.services.logging_service import log_system_event, log_request
        
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        
        # Sadece /api endpoint'lerini logla (health check hariç)
        if request.url.path.startswith("/api") and not request.url.path.endswith("/health"):
            # DB sütunlarını doğru dolduran log_request kullan
            log_request(
                request_path=request.url.path,
                request_method=request.method,
                response_status=response.status_code,
            )
            
            # Yavaş istekler için ayrıca WARNING logu
            if duration > 2.0:
                log_system_event(
                    "WARNING",
                    f"Yavaş istek: {request.method} {request.url.path} - {response.status_code} - {duration:.2f}s",
                    "http"
                )
        
        return response

    # Dikkat: prefix'ler
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(rag_routes.router, prefix="/api/rag", tags=["rag"])
    app.include_router(llm_config.router, prefix="/api/llm-config", tags=["llm_config"])
    app.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(system.router, prefix="/api/system", tags=["system"])
    app.include_router(ws_routes.router, prefix="/api", tags=["websocket"])
    app.include_router(organizations.router, prefix="/api", tags=["organizations"])
    app.include_router(feedback.router, prefix="/api", tags=["feedback"])  # v2.13.0 - CatBoost Feedback
    app.include_router(dialog.router, prefix="/api", tags=["dialogs"])  # v2.14.0 - Dialog Chat System
    app.include_router(permissions.router)  # v2.20.0 - RBAC Permissions
    app.include_router(assets.router, prefix="/api/assets", tags=["assets"])  # v2.22.0 - System Assets
    app.include_router(ldap_settings.router)  # v2.46.0 - LDAP/AD Integration
    app.include_router(domain_org_api.router, prefix="/api")  # v2.46.0 - Domain Org Permissions
    app.include_router(widget_routes.router, prefix="/api")  # v2.60.0 - Web Widget

    import os
    from pathlib import Path
    from fastapi.responses import FileResponse

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.exists():
        _no_cache = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}

        @app.get("/")
        async def serve_index():
            return FileResponse(str(frontend_dir / "login.html"), headers=_no_cache)

        @app.get("/home.html")
        async def serve_home():
            return FileResponse(str(frontend_dir / "home.html"), headers=_no_cache)

        @app.get("/login.html")
        async def serve_login():
            return FileResponse(str(frontend_dir / "login.html"), headers=_no_cache)

        @app.get("/organization_management.html")
        async def serve_org():
            return FileResponse(str(frontend_dir / "organization_management.html"))

        app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")
        app.mount("/partials", StaticFiles(directory=str(frontend_dir / "partials")), name="partials")

        dist_dir = frontend_dir / "dist"
        if dist_dir.exists():
            app.mount("/dist", StaticFiles(directory=str(dist_dir)), name="dist")

        # v2.60.0: Widget static dosyalarını sun (widget.js)
        widget_dir = frontend_dir / "widget" / "dist"
        if widget_dir.exists():
            app.mount("/widget", StaticFiles(directory=str(widget_dir)), name="widget")

    return app


app = create_app()
