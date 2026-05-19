"""
langfuse_adapter — v3.26.0 Faz 5 (P2-b)
========================================
Pipeline event'lerini opsiyonel olarak Langfuse'a iletir.

Notlar:
  - Langfuse 4.x API'sini kullanır (start_observation / create_event /
    create_trace_id). 2.x'ten farkı: trace nesnesi yok, trace_id W3C-tarzı
    32-hex string, tüm observation'lar trace_context={'trace_id': ...}
    parametresi ile bağlanır.
  - SDK kurulu değilse veya keys boşsa NO-OP.
  - Thread-safe: client + trace_id mapping ayrı lock'larla.
  - DB-tabanlı pipeline_events her hâlükârda çalışmaya devam eder.

Public API:
    is_enabled() -> bool
    start_trace(run_id, *, user_id=None, company_id=None, metadata=None)
    end_trace(run_id, *, output=None, status=None, metadata=None)
    log_span(run_id, *, name, duration_ms, status, metadata)
    log_generation(run_id, *, name, prompt, completion, model, latency_ms, metadata)
    flush() -> None  # shutdown öncesi pending event'leri gönder
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Lazy SDK
try:
    from langfuse import Langfuse  # type: ignore
    _HAS_LANGFUSE = True
except Exception:
    _HAS_LANGFUSE = False

_CLIENT: Optional[Any] = None
_CLIENT_LOCK = threading.Lock()
# run_id (pipeline iç) -> langfuse_trace_id (32-hex W3C)
_TRACE_ID_CACHE: Dict[str, str] = {}
_TRACE_LOCK = threading.Lock()


def is_enabled() -> bool:
    """Langfuse aktif mi? SDK var + key'ler set edilmiş."""
    if not _HAS_LANGFUSE:
        return False
    try:
        from app.core.config import settings
    except Exception:
        return False
    return bool(getattr(settings, "LANGFUSE_PUBLIC_KEY", "") and
                getattr(settings, "LANGFUSE_SECRET_KEY", ""))


def _get_client() -> Optional[Any]:
    """Singleton Langfuse client (thread-safe). Hata → None döner."""
    global _CLIENT
    if not is_enabled():
        return None
    if _CLIENT is not None:
        return _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is not None:
            return _CLIENT
        try:
            from app.core.config import settings
            _CLIENT = Langfuse(
                public_key=settings.LANGFUSE_PUBLIC_KEY,
                secret_key=settings.LANGFUSE_SECRET_KEY,
                host=settings.LANGFUSE_HOST,
            )
            logger.info("[langfuse] client initialized host=%s", settings.LANGFUSE_HOST)
            return _CLIENT
        except Exception as e:
            logger.warning("[langfuse] client init failed: %s", e)
            _CLIENT = None
            return None


def _resolve_trace_id(run_id: str, *, create: bool = False) -> Optional[str]:
    """run_id ↔ langfuse_trace_id eşlemesi. create=True ise yoksa üretir."""
    if not run_id:
        return None
    with _TRACE_LOCK:
        tid = _TRACE_ID_CACHE.get(run_id)
        if tid or not create:
            return tid
    # Outside lock: client + trace_id üretimi
    client = _get_client()
    if client is None:
        return None
    try:
        tid = client.create_trace_id(seed=run_id)
    except Exception as e:
        logger.debug("[langfuse._resolve_trace_id] %s", e)
        return None
    with _TRACE_LOCK:
        # Race condition: bir başkası daha önce yazmış olabilir
        existing = _TRACE_ID_CACHE.get(run_id)
        if existing:
            return existing
        _TRACE_ID_CACHE[run_id] = tid
    return tid


def start_trace(
    run_id: str,
    *,
    user_id: Optional[Any] = None,
    company_id: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Pipeline başlangıcında trace_id üretir + ilk root span'i açar.

    Langfuse 4.x'te explicit "trace" nesnesi yok; trace_id ile bağlanan
    observation'lar otomatik bir trace oluşturur. Root span "pipeline" adıyla
    açılır ve `end_trace`'te update edilerek kapatılır.
    """
    client = _get_client()
    if client is None or not run_id:
        return
    trace_id = _resolve_trace_id(run_id, create=True)
    if not trace_id:
        return
    try:
        meta = {
            "company_id": company_id,
            "user_id": user_id,
            **(metadata or {}),
        }
        # Root span (pipeline) — start, end_trace'te update.end()
        client.start_observation(
            trace_context={"trace_id": trace_id},
            name="vyra.agentic_pipeline",
            as_type="span",
            input={"question_preview": (metadata or {}).get("question_preview")},
            metadata=meta,
        )
    except Exception as e:
        logger.debug("[langfuse.start_trace] %s", e)


def end_trace(
    run_id: str,
    *,
    output: Optional[Any] = None,
    status: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Pipeline sonunda kapanış event'i atar + trace_id cache'ten temizle."""
    client = _get_client()
    if client is None or not run_id:
        return
    trace_id = _resolve_trace_id(run_id)
    if not trace_id:
        return
    try:
        # 4.x'te "trace" objesi yerine event ile kapanış bildirebiliriz.
        client.create_event(
            trace_context={"trace_id": trace_id},
            name="pipeline_end",
            output=output,
            metadata={"status": status, **(metadata or {})} if metadata or status else None,
            status_message=status,
        )
    except Exception as e:
        logger.debug("[langfuse.end_trace] %s", e)
    finally:
        with _TRACE_LOCK:
            _TRACE_ID_CACHE.pop(run_id, None)


def log_span(
    run_id: str,
    *,
    name: str,
    duration_ms: Optional[int] = None,
    status: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Bir node yürütümünü Langfuse event olarak işler.

    Geçmiş (end-time'ı bilinen) bir node için `create_event` kullanırız;
    sürekli span'lar değil tek atışlık event'ler. Bu hem 4.x API'ye hem de
    bizim "node bittikten sonra logla" akışımıza uygun.
    """
    client = _get_client()
    if client is None or not run_id:
        return
    trace_id = _resolve_trace_id(run_id)
    if not trace_id:
        return
    try:
        meta = {"duration_ms": duration_ms, **(metadata or {})}
        client.create_event(
            trace_context={"trace_id": trace_id},
            name=f"node:{name}",
            metadata=meta,
            status_message=status,
            level=("ERROR" if status == "error" else "DEFAULT"),
        )
    except Exception as e:
        logger.debug("[langfuse.log_span] %s", e)


def log_generation(
    run_id: str,
    *,
    name: str,
    prompt: Optional[str] = None,
    completion: Optional[str] = None,
    model: Optional[str] = None,
    latency_ms: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """LLM çağrısını Langfuse generation observation olarak işler."""
    client = _get_client()
    if client is None or not run_id:
        return
    trace_id = _resolve_trace_id(run_id)
    if not trace_id:
        return
    try:
        obs = client.start_observation(
            trace_context={"trace_id": trace_id},
            name=name,
            as_type="generation",
            model=model,
            input=prompt,
            output=completion,
            metadata={"latency_ms": latency_ms, **(metadata or {})},
        )
        # Tek atışta kapatılmalı (start+end aynı anda)
        if obs is not None and hasattr(obs, "end"):
            try:
                obs.end()
            except Exception:
                pass
    except Exception as e:
        logger.debug("[langfuse.log_generation] %s", e)


def flush() -> None:
    """Pending event'leri Langfuse'a gönder (shutdown öncesi)."""
    client = _CLIENT
    if client is None:
        return
    try:
        if hasattr(client, "flush"):
            client.flush()
    except Exception as e:
        logger.debug("[langfuse.flush] %s", e)
