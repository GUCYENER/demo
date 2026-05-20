"""dbsmart_interactions event recorder (v3.30.0 FAZ 2 P10 G2.4).

Sorumluluklar:
    - record(cur, action, user_ctx, **fields) → dbsmart_interactions INSERT
    - PII masking: ds_column_enrichments.is_pii=TRUE olan kolon adları
      payload JSON ağacında '***MASKED***' ile değiştirilir (recursive scan,
      key-name match — değer üretim noktasında engellenir).
    - Action whitelist enforcement (KNOWN_ACTIONS sabit set).
    - Graceful failure: kayıt başarısız olursa wizard akışı KIRILMAZ,
      yalnızca warn log atılır (event recording flow-critical değil).
    - Duration helper: track(action, ...) context manager — `with` blokuna
      giriş/çıkış arasındaki süreyi duration_ms olarak iliştirir.

Tasarım notları:
    - Cursor caller'dan gelir (apply_vyra_user_context zaten set edilmiş,
      RLS policy `pol_dbsmart_interactions_isolation` user_id eşleştirir).
    - PII kolon listesi source_id başına TTL'li cache'lenir (1dk in-memory).
      Cache yoksa fallback: masking atlanır + warn log.
    - JSONB payload alanları None ise hiç gönderilmez (INSERT param drop).
    - duration_ms int sınırı (PostgreSQL INTEGER 4B); 24.8 gün max — sane.
    - satisfaction CHECK -1..5 (migration 032 constraint'i).

Event taxonomy (Prompt I):
    SessionStarted, DomainSelected, TableSelected, DateColumnSelected,
    FilterApplied, MetricChosen, CustomMetricWritten, SQLGenerated,
    SQLModified, QueryExecuted, ReportRecommendationShown,
    ReportRecommendationAccepted, ReportRecommendationRejected,
    WizardCompleted, WizardAbandoned, ReportSaved, ReportRerun,
    ExplicitFeedback
"""
from __future__ import annotations

import json
import logging
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional, Set

logger = logging.getLogger(__name__)

# Bilinen event aksiyonları — yanlış yazımı engellemek için sabit set.
# Migration 032 dbsmart_interactions.action VARCHAR(60) — tüm isimler ≤60ch.
KNOWN_ACTIONS = frozenset({
    "SessionStarted", "DomainSelected", "TableSelected", "DateColumnSelected",
    "FilterApplied", "MetricChosen", "CustomMetricWritten", "SQLGenerated",
    "SQLModified", "QueryExecuted", "ReportRecommendationShown",
    "ReportRecommendationAccepted", "ReportRecommendationRejected",
    "WizardCompleted", "WizardAbandoned", "ReportSaved", "ReportRerun",
    "ExplicitFeedback",
})

_MASK_VALUE = "***MASKED***"
_PII_CACHE_TTL_SEC = 60
_SATISFACTION_MIN = -1
_SATISFACTION_MAX = 5
_DURATION_MAX_MS = 2_147_483_647  # PG INTEGER upper bound

# source_id → (set[column_name], unix_ts_loaded). Process-local cache.
_PII_CACHE: Dict[int, tuple] = {}
_PII_CACHE_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────
# PII column lookup (cached per source_id)
# ─────────────────────────────────────────────────────────────

def _load_pii_columns(cur: Any, source_id: int) -> Set[str]:
    """ds_column_enrichments.is_pii=TRUE olan kolon adlarını döner.

    TTL cache: source başına 60sn. Hata → boş set (masking pas geçilir + warn).
    """
    now = time.time()
    cached = _PII_CACHE.get(source_id)
    if cached and (now - cached[1]) < _PII_CACHE_TTL_SEC:
        return cached[0]
    with _PII_CACHE_LOCK:
        cached = _PII_CACHE.get(source_id)
        if cached and (now - cached[1]) < _PII_CACHE_TTL_SEC:
            return cached[0]
        cols: Set[str] = set()
        try:
            cur.execute(
                """
                SELECT DISTINCT column_name
                FROM ds_column_enrichments
                WHERE source_id = %s AND is_pii = TRUE
                """,
                (int(source_id),),
            )
            rows = cur.fetchall() or []
            for r in rows:
                name = r[0] if not isinstance(r, dict) else r.get("column_name")
                if isinstance(name, str) and name:
                    cols.add(name)
        except Exception as e:
            logger.warning(
                "[db_smart.lr] PII lookup failed (source=%s): %s — masking skipped",
                source_id, e,
            )
            cols = set()
        _PII_CACHE[source_id] = (cols, now)
        return cols


def _mask_payload(payload: Any, pii_cols: Set[str]) -> Any:
    """Payload ağacında pii_cols ile eşleşen key'lerin değerini maskeler.

    - dict: key match → değer '***MASKED***'; değilse recursive scan.
    - list/tuple: her eleman recursive scan.
    - primitive: dokunma.
    Returns: yeni nesne (immutable koruma).
    """
    if not pii_cols or payload is None:
        return payload
    if isinstance(payload, dict):
        out: Dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(k, str) and k in pii_cols:
                out[k] = _MASK_VALUE
            else:
                out[k] = _mask_payload(v, pii_cols)
        return out
    if isinstance(payload, (list, tuple)):
        masked = [_mask_payload(item, pii_cols) for item in payload]
        return masked if isinstance(payload, list) else tuple(masked)
    return payload


def invalidate_pii_cache(source_id: Optional[int] = None) -> None:
    """Admin onaylama/güncelleme sonrası elle çağrılabilir."""
    with _PII_CACHE_LOCK:
        if source_id is None:
            _PII_CACHE.clear()
        else:
            _PII_CACHE.pop(int(source_id), None)


# ─────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────

def _clamp_satisfaction(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return None
    if iv < _SATISFACTION_MIN or iv > _SATISFACTION_MAX:
        return None
    return iv


def _clamp_duration_ms(v: Optional[int]) -> Optional[int]:
    if v is None:
        return None
    try:
        iv = int(v)
    except (TypeError, ValueError):
        return None
    if iv < 0:
        return 0
    if iv > _DURATION_MAX_MS:
        return _DURATION_MAX_MS
    return iv


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def record(
    cur: Any,
    action: str,
    user_ctx: Dict[str, Any],
    *,
    session_id: Optional[int] = None,
    step: Optional[int] = None,
    suggestion_shown: Optional[Dict[str, Any]] = None,
    suggestion_accepted: Optional[Dict[str, Any]] = None,
    user_override: Optional[Dict[str, Any]] = None,
    satisfaction: Optional[int] = None,
    duration_ms: Optional[int] = None,
    source_id: Optional[int] = None,
) -> Optional[int]:
    """dbsmart_interactions tablosuna bir event kaydı yazar.

    Args:
        cur: aktif psycopg2 cursor (apply_vyra_user_context set edilmiş).
        action: KNOWN_ACTIONS içinde olmalı; aksi halde no-op + warn.
        user_ctx: {id, company_id, ...} — RLS satırı user_id/company_id
                  alanlarına yazılır (RLS predicate'e ek olarak).
        session_id: dbsmart_sessions.id (FK). None olabilir (oturum-dışı event).
        step: 0-7 wizard adımı (opsiyonel).
        suggestion_shown/accepted/user_override: JSONB payload'lar.
        satisfaction: -1..5 (constraint); aksi halde None'a çevrilir.
        duration_ms: int (negatif → 0, INT max overflow → clamp).
        source_id: PII masking için (verilmezse masking devre dışı).

    Returns:
        Yeni satırın id'si (BIGSERIAL) — kayıt başarısızsa None.
    """
    if action not in KNOWN_ACTIONS:
        logger.warning("[db_smart.lr] unknown action skipped: %s", action)
        return None

    user_id = user_ctx.get("id") if user_ctx else None
    company_id = user_ctx.get("company_id") if user_ctx else None
    if user_id is None or company_id is None:
        logger.warning("[db_smart.lr] missing user_ctx (id/company_id) — skipped")
        return None

    # PII masking — source_id verilmişse cache'li lookup, değilse pas geç.
    pii_cols: Set[str] = set()
    if source_id is not None:
        try:
            pii_cols = _load_pii_columns(cur, int(source_id))
        except Exception as e:
            logger.warning("[db_smart.lr] PII load error: %s — masking off", e)
            pii_cols = set()

    sug_shown_m = _mask_payload(suggestion_shown, pii_cols)
    sug_acc_m = _mask_payload(suggestion_accepted, pii_cols)
    user_ov_m = _mask_payload(user_override, pii_cols)

    sat_v = _clamp_satisfaction(satisfaction)
    dur_v = _clamp_duration_ms(duration_ms)

    try:
        cur.execute(
            """
            INSERT INTO dbsmart_interactions
                (session_id, user_id, company_id, step, action,
                 suggestion_shown, suggestion_accepted, user_override,
                 satisfaction, duration_ms)
            VALUES
                (%s, %s, %s, %s, %s,
                 %s::jsonb, %s::jsonb, %s::jsonb,
                 %s, %s)
            RETURNING id
            """,
            (
                session_id,
                int(user_id),
                int(company_id),
                step,
                action,
                json.dumps(sug_shown_m) if sug_shown_m is not None else None,
                json.dumps(sug_acc_m) if sug_acc_m is not None else None,
                json.dumps(user_ov_m) if user_ov_m is not None else None,
                sat_v,
                dur_v,
            ),
        )
        row = cur.fetchone()
        if not row:
            logger.warning("[db_smart.lr] INSERT RETURNING empty (RLS?) action=%s", action)
            return None
        new_id = row[0] if not isinstance(row, dict) else row.get("id")
        logger.debug(
            "[db_smart.lr] %s id=%s session=%s step=%s sat=%s dur=%s",
            action, new_id, session_id, step, sat_v, dur_v,
        )
        return int(new_id) if new_id is not None else None
    except Exception as e:
        # Event recording flow-critical değil → wizard akışını kırma.
        logger.warning("[db_smart.lr] insert failed action=%s err=%s", action, e)
        return None


@contextmanager
def track(
    cur: Any,
    action: str,
    user_ctx: Dict[str, Any],
    **fields: Any,
) -> Iterator[Dict[str, Any]]:
    """Süre ölçen context manager. `extra` dict'ine alan eklenebilir.

    Örnek:
        with track(cur, "QueryExecuted", user_ctx, session_id=42) as ev:
            rows = run_query(...)
            ev["suggestion_accepted"] = {"row_count": len(rows)}
        # block sonunda otomatik record() çağrılır; duration_ms hesaplanmış.

    İstisna olursa kayıt yine yazılır (duration ölçülmüş, action aynı).
    """
    start = time.perf_counter()
    extra: Dict[str, Any] = {}
    try:
        yield extra
    finally:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        merged = {**fields, **extra}
        # extra'da duration_ms varsa onu kullan, yoksa ölçülen değeri ver.
        if "duration_ms" not in merged:
            merged["duration_ms"] = elapsed_ms
        try:
            record(cur, action, user_ctx, **merged)
        except Exception as e:
            logger.warning("[db_smart.lr] track() record failed: %s", e)
