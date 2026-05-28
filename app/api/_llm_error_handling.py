"""Bulgular3 / Review fix #6 — Shared LLM HTTP error wrapper.

llm_metric_api, llm_format_api, llm_column_api, llm_report_meta_api icindeki
identik try/except + HTTPException mapping patternini tek decorator'a indirir.

Kullanim:
    @router.post("/...", response_model=...)
    @limiter.limit("...")
    @handle_llm_errors(logger)
    def endpoint(...):
        return service.do_something(...)
"""
from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from fastapi import HTTPException

from app.core.llm import LLMConfigError, LLMConnectionError, LLMResponseError


def handle_llm_errors(logger: logging.Logger) -> Callable:
    """Decorator: LLM exception turlerini standart HTTP status'lara cevirir.

    - LLMConnectionError / LLMConfigError -> 503
    - LLMResponseError                    -> 502
    - HTTPException                       -> re-raise (passthrough)
    - Diger                               -> 500 (logger.error + generic detail)
    """
    def _decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return fn(*args, **kwargs)
            except (LLMConnectionError, LLMConfigError) as e:
                logger.warning("[%s] LLM connection/config error: %s", fn.__name__, e)
                raise HTTPException(status_code=503, detail=f"LLM servisine ulasilamadi: {e}")
            except LLMResponseError as e:
                logger.warning("[%s] LLM response parse error: %s", fn.__name__, e)
                raise HTTPException(status_code=502, detail=f"LLM gecersiz cevap dondu: {e}")
            except HTTPException:
                raise
            except Exception as e:
                logger.error("[%s] unexpected LLM error: %s", fn.__name__, e, exc_info=True)
                raise HTTPException(
                    status_code=500,
                    detail="LLM islemi sirasinda beklenmeyen hata olustu.",
                )
        return _wrapped
    return _decorator
