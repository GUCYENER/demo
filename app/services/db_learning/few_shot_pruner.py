"""VYRA v3.27.0 — Few-Shot Pruner (G4.3).

LRU temizlik: Her (source_id, intent) bucket için en çok kullanılan TOP_N
örnek korunur, kalanlar silinir.

Stratejı:
  1) Her bucket → (company_id, source_id, intent)
  2) Bucket içinde sırala: usage_count DESC, last_used_at DESC NULLS LAST, created_at DESC
  3) İlk TOP_N tut; kalanları DELETE
  4) Eski (created_at < cutoff) ve usage_count=0 satırlar koşulsuz silinir

Cron önerisi: günde 1 kez (gece, düşük trafik).

Idempotent: bir gün içinde N defa çalışırsa zarar vermez (sadece zaten silinmiş
veya zaten ilk N içindeki satırları yeniden değerlendirir).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

TABLE_NAME = "few_shot_examples"
DEFAULT_TOP_N = 1000
DEFAULT_STALE_DAYS = 90  # usage_count=0 + bu kadar günden eskiyse sil


@dataclass
class PruneSummary:
    buckets_scanned: int = 0
    deleted_lru: int = 0
    deleted_stale: int = 0
    company_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _list_buckets(cur, company_id: Optional[int]) -> List[Dict[str, Any]]:
    """Distinct (company_id, source_id, intent) bucket listesi."""
    if company_id is not None:
        cur.execute(
            f"""
            SELECT company_id, source_id, intent, COUNT(*) AS cnt
            FROM {TABLE_NAME}
            WHERE company_id = %s
            GROUP BY company_id, source_id, intent
            HAVING COUNT(*) > 0
            """,
            (company_id,),
        )
    else:
        cur.execute(
            f"""
            SELECT company_id, source_id, intent, COUNT(*) AS cnt
            FROM {TABLE_NAME}
            GROUP BY company_id, source_id, intent
            HAVING COUNT(*) > 0
            """
        )
    rows = cur.fetchall() or []
    out = []
    for r in rows:
        if hasattr(r, "get"):
            out.append({
                "company_id": r.get("company_id"),
                "source_id": r.get("source_id"),
                "intent": r.get("intent"),
                "cnt": int(r.get("cnt") or 0),
            })
        else:
            out.append({
                "company_id": r[0], "source_id": r[1], "intent": r[2],
                "cnt": int(r[3] or 0),
            })
    return out


def _prune_bucket(
    cur,
    *,
    company_id: int,
    source_id: Optional[int],
    intent: Optional[str],
    top_n: int,
) -> int:
    """Bir bucket içinde ilk top_n hariç tümünü sil. Sayıyı döndür."""
    src_clause = "source_id = %s" if source_id is not None else "source_id IS NULL"
    intent_clause = "intent = %s" if intent is not None else "intent IS NULL"

    params: List[Any] = [company_id]
    if source_id is not None:
        params.append(source_id)
    if intent is not None:
        params.append(intent)

    # Top N içine girenlerin id'lerini bul
    sql_top = f"""
        SELECT id FROM {TABLE_NAME}
        WHERE company_id = %s AND {src_clause} AND {intent_clause}
        ORDER BY usage_count DESC,
                 last_used_at DESC NULLS LAST,
                 created_at DESC NULLS LAST
        LIMIT %s
    """
    cur.execute(sql_top, params + [top_n])
    keep_ids = [
        (r.get("id") if hasattr(r, "get") else r[0])
        for r in (cur.fetchall() or [])
    ]
    if not keep_ids:
        return 0

    # Bucket içindeki KALANI sil
    sql_del = f"""
        DELETE FROM {TABLE_NAME}
        WHERE company_id = %s AND {src_clause} AND {intent_clause}
          AND id <> ALL(%s::bigint[])
    """
    cur.execute(sql_del, params + [keep_ids])
    return cur.rowcount or 0


def _delete_stale_zero_usage(
    cur, company_id: Optional[int], stale_days: int
) -> int:
    """usage_count=0 + created_at < NOW() - INTERVAL 'N days' satırları sil."""
    interval_lit = f"{int(stale_days)} days"
    if company_id is not None:
        cur.execute(
            f"""
            DELETE FROM {TABLE_NAME}
            WHERE company_id = %s
              AND usage_count = 0
              AND created_at < NOW() - %s::interval
            """,
            (company_id, interval_lit),
        )
    else:
        cur.execute(
            f"""
            DELETE FROM {TABLE_NAME}
            WHERE usage_count = 0
              AND created_at < NOW() - %s::interval
            """,
            (interval_lit,),
        )
    return cur.rowcount or 0


def prune(
    cur,
    *,
    company_id: Optional[int] = None,
    top_n: int = DEFAULT_TOP_N,
    stale_days: int = DEFAULT_STALE_DAYS,
) -> PruneSummary:
    """Few-shot LRU pruning. Caller commit sorumlu.

    Args:
        cur: psycopg2 DictCursor (RLS scoped — company_id verilirse o tenant)
        company_id: None → tüm tenantlar (admin job); int → yalnız o tenant
        top_n: Her bucket için korunacak en çok kullanılan örnek sayısı
        stale_days: usage_count=0 + bu kadar günden eski satırlar silinir
    """
    s = PruneSummary(company_id=company_id)
    try:
        buckets = _list_buckets(cur, company_id)
        s.buckets_scanned = len(buckets)
        for b in buckets:
            try:
                deleted = _prune_bucket(
                    cur,
                    company_id=int(b["company_id"]),
                    source_id=b.get("source_id"),
                    intent=b.get("intent"),
                    top_n=top_n,
                )
                s.deleted_lru += deleted
            except Exception as e:
                logger.warning("[few_shot.prune.bucket] %s: %s", b, e)
        try:
            s.deleted_stale = _delete_stale_zero_usage(cur, company_id, stale_days)
        except Exception as e:
            logger.warning("[few_shot.prune.stale] %s", e)
    except Exception as e:
        logger.exception("[few_shot.prune] hata: %s", e)
    return s


__all__ = [
    "PruneSummary",
    "prune",
    "DEFAULT_TOP_N",
    "DEFAULT_STALE_DAYS",
]
