"""DB Smart — Interaction data retention runner (v3.30.0 FAZ 2 P30c).

Günlük tick ile:
1. partition_rotate() — yeni ay partition oluşturma
2. 90 günden eski partition'ları archive → dbsmart_interactions_archive
3. Prometheus counter (varsa)

Scheduler hook: app/main.py in-process scheduler'a wired edilir.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict

logger = logging.getLogger(__name__)


def run_daily_tick(cur) -> Dict[str, Any]:
    """Günlük retention tick. Cursor caller'a aittir (commit dışarıda).

    Returns: {"partitions": {...}, "archived": int, "errors": []}
    """
    from app.services.db_smart.learning_recorder import partition_rotate

    errors = []
    archived = 0

    # Step 1: Ensure current + next month partitions exist
    try:
        partition_result = partition_rotate(cur)
    except Exception as e:
        logger.warning("[retention] partition_rotate failed: %s", e)
        partition_result = {"created": [], "skipped": []}
        errors.append(f"partition_rotate: {e}")

    # Step 2: Archive old partitions (>90 days)
    try:
        archived = _archive_old_partitions(cur, max_age_days=90)
    except Exception as e:
        logger.warning("[retention] archive failed: %s", e)
        errors.append(f"archive: {e}")

    # Step 3: Prometheus counter
    _emit_metrics(archived, len(errors))

    return {
        "partitions": partition_result,
        "archived": archived,
        "errors": errors,
    }


def _archive_old_partitions(cur, max_age_days: int = 90) -> int:
    """90 günden eski partition'ları dbsmart_interactions_archive'e taşır.

    Strategy:
    - pg_class'tan dbsmart_interactions_YYYY_MM partition'larını bul
    - End date'i > max_age_days olanları INSERT...SELECT + DROP
    """
    cutoff = datetime.now() - timedelta(days=max_age_days)
    cutoff_str = cutoff.strftime("%Y_%m")
    archived_total = 0

    try:
        cur.execute("""
            SELECT c.relname
            FROM pg_class c
            JOIN pg_inherits i ON c.oid = i.inhrelid
            JOIN pg_class p ON i.inhparent = p.oid
            WHERE p.relname = 'dbsmart_interactions'
              AND c.relkind = 'r'
              AND c.relname LIKE 'dbsmart_interactions_%'
            ORDER BY c.relname
        """)
        partitions = [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.warning("[retention] list partitions failed: %s", e)
        return 0

    for part_name in partitions:
        # Extract YYYY_MM from partition name
        suffix = part_name.replace("dbsmart_interactions_", "")
        if suffix >= cutoff_str:
            continue  # Not old enough

        try:
            # Archive: INSERT into archive table
            cur.execute(f"""
                INSERT INTO dbsmart_interactions_archive (original_id, company_id, payload, archived_at)
                SELECT id, company_id, row_to_json(t.*)::jsonb, NOW()
                FROM {part_name} t
            """)
            archived_count = cur.rowcount or 0
            archived_total += archived_count

            # Detach + drop the partition
            cur.execute(f"ALTER TABLE dbsmart_interactions DETACH PARTITION {part_name}")
            cur.execute(f"DROP TABLE IF EXISTS {part_name}")
            logger.info("[retention] archived %d rows from %s", archived_count, part_name)
        except Exception as e:
            logger.warning("[retention] archive partition %s failed: %s", part_name, e)

    return archived_total


def _emit_metrics(archived: int, error_count: int):
    """Prometheus counter emit (graceful if missing)."""
    try:
        from app.services.observability.prometheus_metrics import get as _metric
        if archived > 0:
            _metric("retention_archived_total").inc(archived)
        if error_count > 0:
            _metric("retention_errors_total").inc(error_count)
    except Exception:
        pass


def schedule(scheduler_add_job_fn):
    """Register retention runner with the in-process scheduler.

    Usage in main.py:
        from app.services.db_smart.retention_runner import schedule as schedule_retention
        schedule_retention(scheduler.add_job)
    """
    try:
        scheduler_add_job_fn(
            run_daily_tick,
            trigger="cron",
            hour=3,
            minute=0,
            id="dbsmart_retention_daily",
            replace_existing=True,
        )
        logger.info("[retention] daily tick scheduled at 03:00 UTC")
    except Exception as e:
        logger.warning("[retention] schedule failed: %s", e)
