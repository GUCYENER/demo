"""DB Smart — Scheduled Report Runner (v3.30.0 FAZ 3 P17 / G3.3 Schedule).

Periyodik olarak `dbsmart_saved_reports.schedule_cron IS NOT NULL` ve
`schedule_next_run <= NOW()` koşulunu sağlayan raporları yeniden çalıştırır,
sonucu `last_run_snapshot` JSONB'ye in-app olarak yazar (e-mail/PDF KAPSAM DIŞI),
croniter ile bir sonraki `schedule_next_run` hesaplar.

Tasarım:
- in-process scheduler hook'undan (`_run_schedule_checker`) tick counter ile çağrılır
- DBSMART_SCHEDULE_INTERVAL_MULT × SCHEDULER_INTERVAL_SECONDS aralığında
- Tick başına `DBSMART_SCHEDULE_MAX_PER_TICK` rapor (varsayılan 20)
- Her rapor: SafeSQLExecutor(timeout, max_rows) + RLS scope per company
- Hata: snapshot içine `{"error": ...}` yazılır, akış kırılmaz
- Reentrancy: schedule_next_run koşullu UPDATE öncesinde aday set sabitlenir (FOR UPDATE SKIP LOCKED)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now().astimezone()


def find_due_reports(cur: Any, limit: int) -> List[Dict[str, Any]]:
    """schedule_next_run <= NOW() olan raporları FOR UPDATE SKIP LOCKED ile kilitle.

    T-4 fix: NULL schedule_next_run yalnızca first-run (last_run_at IS NULL)
    için eligible. Önceki davranış: invalid cron sonrası NULL'da kalmış
    record her tick'te re-run ediyordu (sonsuz döngü).
    SKIP LOCKED: aynı tick'te birden fazla worker (gelecekte) ayni satıra
    çarpmasın diye. Mevcut single-process scheduler için no-op ama future-proof.
    """
    cur.execute(
        """
        SELECT id, user_id, company_id, source_id,
               last_sql, last_dialect, schedule_cron,
               run_count
          FROM dbsmart_saved_reports
         WHERE schedule_cron IS NOT NULL
           AND last_sql IS NOT NULL
           AND (
                (schedule_next_run IS NULL AND last_run_at IS NULL)
                OR schedule_next_run <= NOW()
               )
         ORDER BY schedule_next_run NULLS FIRST
         LIMIT %s
         FOR UPDATE SKIP LOCKED
        """,
        (int(limit),),
    )
    cols = ["id", "user_id", "company_id", "source_id",
            "last_sql", "last_dialect", "schedule_cron", "run_count"]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _verify_owner_auth(cur: Any, user_id: Any, source_id: Any) -> tuple:
    """A-4: rapor çalışmadan ÖNCE owner'ın hâlâ aktif + source'a erişimi var mı?

    Returns: (ok: bool, reason: Optional[str])
    - reason 'user_not_found' | 'user_inactive' | 'access_revoked' | 'missing'
    """
    if not user_id or not source_id:
        return (False, "missing")
    cur.execute(
        "SELECT is_active FROM users WHERE id = %s LIMIT 1",
        (int(user_id),),
    )
    row = cur.fetchone()
    if not row:
        return (False, "user_not_found")
    if not bool(row[0]):
        return (False, "user_inactive")
    # can_execute on source: user-direct OR org-membership
    cur.execute(
        """
        SELECT 1
          FROM data_source_permissions p
          LEFT JOIN user_organizations uo
                 ON uo.user_id = %s
                AND p.subject_type = 'org'
                AND uo.org_id = p.subject_id
         WHERE p.source_id = %s
           AND p.can_execute = TRUE
           AND ((p.subject_type = 'user' AND p.subject_id = %s)
                OR (p.subject_type = 'org' AND uo.id IS NOT NULL))
         LIMIT 1
        """,
        (int(user_id), int(source_id), int(user_id)),
    )
    if cur.fetchone() is None:
        return (False, "access_revoked")
    return (True, None)


def _auto_pause(cur: Any, report_id: int, snapshot: Dict[str, Any]) -> None:
    """A-4/T-4 fix: schedule_cron=NULL ile raporu otomatik durdur.

    Snapshot içine 'error' alanı yazılır; ileride UI 'paused' badge gösterir.
    """
    try:
        cur.execute(
            """
            UPDATE dbsmart_saved_reports
               SET schedule_cron     = NULL,
                   last_run_snapshot = %s::jsonb,
                   last_run_at       = NOW(),
                   updated_at        = NOW()
             WHERE id = %s
            """,
            (json.dumps(snapshot, default=str), int(report_id)),
        )
    except Exception as e:  # pragma: no cover - DB failure path
        logger.exception("[schedule_runner] _auto_pause fail report=%s: %s", report_id, e)


def _load_source_for_schedule(cur: Any, source_id: int) -> Optional[Dict[str, Any]]:
    """data_sources kaydını schedule context için yükle (system-level)."""
    cur.execute(
        """
        SELECT id, db_type, host, port, db_name, db_user, db_password_encrypted
          FROM data_sources
         WHERE id = %s AND is_active = TRUE
         LIMIT 1
        """,
        (int(source_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    src = {"id": row[0], "db_type": row[1], "host": row[2], "port": row[3],
           "db_name": row[4], "db_user": row[5]}
    encrypted = row[6]
    if encrypted:
        try:
            from app.api.routes.data_sources_api import _decrypt_stored_password
            src["password"] = _decrypt_stored_password(encrypted) or ""
        except Exception as e:
            logger.warning("[schedule_runner] decrypt fail source=%s: %s", source_id, e)
            src["password"] = ""
    else:
        src["password"] = ""
    return src


def _compute_next_run(cron_expr: str, base: Optional[datetime] = None) -> Optional[datetime]:
    """Croniter ile bir sonraki çalışma zamanını hesapla. Hata olursa None."""
    try:
        from croniter import croniter
        b = base or _utcnow()
        return croniter(cron_expr, b).get_next(datetime)
    except Exception as e:
        logger.warning("[schedule_runner] croniter fail cron=%s: %s", cron_expr, e)
        return None


def run_one(cur: Any, report: Dict[str, Any]) -> Dict[str, Any]:
    """Tek bir rapor çalıştır → snapshot + next_run hesapla + DB güncelle.

    Returns: {"ok": bool, "report_id": int, "row_count": int|None, "error": str|None}
    """
    from app.services.safe_sql_executor import SafeSQLExecutor

    rid = int(report["id"])
    sql = report["last_sql"]
    dialect = (report.get("last_dialect") or "postgresql").lower()
    source_id = report.get("source_id")

    snapshot: Dict[str, Any] = {"executed_at": _utcnow().isoformat(), "dialect": dialect}
    ok = False
    row_count: Optional[int] = None
    err_msg: Optional[str] = None

    # A-4: auth re-check — query çalışmadan ÖNCE owner'ın aktif + erişimi var mı?
    auth_ok, auth_reason = _verify_owner_auth(cur, report.get("user_id"), source_id)
    if not auth_ok:
        err_msg = f"auth_revoked:{auth_reason}"
        snapshot["error"] = err_msg
        _auto_pause(cur, rid, snapshot)
        return {"ok": False, "report_id": rid, "row_count": None, "error": err_msg}

    src: Optional[Dict[str, Any]] = None
    try:
        src = _load_source_for_schedule(cur, int(source_id)) if source_id else None
        if not src:
            err_msg = "source_not_found_or_inactive"
            snapshot["error"] = err_msg
        else:
            executor = SafeSQLExecutor(
                timeout=int(settings.DBSMART_SCHEDULE_QUERY_TIMEOUT_S),
                max_rows=int(settings.DBSMART_SCHEDULE_MAX_ROWS),
            )
            result = executor.execute(sql, src, dialect, use_result_cache=False)
            if not result.success:
                err_msg = result.error or "execute_failed"
                snapshot["error"] = err_msg
            else:
                ok = True
                row_count = int(result.row_count or 0)
                snapshot.update({
                    "columns": result.columns or [],
                    "row_count": row_count,
                    "truncated": bool(result.truncated),
                    "elapsed_ms": float(result.elapsed_ms or 0.0),
                    # Veri payload'ı boyut sınırı: ilk 500 satır snapshot'a girer (UI önizleme)
                    "rows": (result.data or [])[:500],
                })
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        snapshot["error"] = err_msg
        logger.exception("[schedule_runner] run_one fail report=%s", rid)
    finally:
        # A-5: defense-in-depth — execute sonrası password'ü dict'ten temizle
        # (snapshot'a sızmasın, log/repr'da görünmesin).
        if isinstance(src, dict) and "password" in src:
            src["password"] = ""

    next_run = _compute_next_run(report["schedule_cron"])

    # T-4: invalid cron → auto-pause (schedule_cron NULL, run_count++)
    if next_run is None:
        if "error" not in snapshot:
            snapshot["error"] = "invalid_cron"
        snapshot["cron"] = report.get("schedule_cron")
        try:
            cur.execute(
                """
                UPDATE dbsmart_saved_reports
                   SET schedule_cron     = NULL,
                       last_run_snapshot = %s::jsonb,
                       last_run_at       = NOW(),
                       run_count         = COALESCE(run_count, 0) + 1,
                       schedule_next_run = NULL,
                       updated_at        = NOW()
                 WHERE id = %s
                """,
                (json.dumps(snapshot, default=str), rid),
            )
        except Exception as e:
            logger.exception("[schedule_runner] T-4 auto-pause UPDATE fail report=%s: %s", rid, e)
        return {"ok": ok, "report_id": rid, "row_count": row_count, "error": err_msg or "invalid_cron"}

    try:
        cur.execute(
            """
            UPDATE dbsmart_saved_reports
               SET last_run_snapshot = %s::jsonb,
                   last_run_at       = NOW(),
                   run_count         = COALESCE(run_count, 0) + 1,
                   schedule_next_run = %s,
                   updated_at        = NOW()
             WHERE id = %s
            """,
            (json.dumps(snapshot, default=str), next_run, rid),
        )
    except Exception as e:
        logger.exception("[schedule_runner] UPDATE fail report=%s: %s", rid, e)

    return {"ok": ok, "report_id": rid, "row_count": row_count, "error": err_msg}


def check_dbsmart_scheduled_reports(cur: Any) -> Dict[str, int]:
    """Scheduler tick entry — due raporları işle. Cursor caller'a aittir (commit dışarıda).

    Returns: {"due": N, "ok": K, "err": E}
    """
    limit = int(settings.DBSMART_SCHEDULE_MAX_PER_TICK)
    due = find_due_reports(cur, limit)
    ok_count = 0
    err_count = 0
    for report in due:
        res = run_one(cur, report)
        if res["ok"]:
            ok_count += 1
        else:
            err_count += 1
    return {"due": len(due), "ok": ok_count, "err": err_count}


# ─────────────────────────────────────────────────────────────
# P39 — Cron validation helper
# ─────────────────────────────────────────────────────────────

_TR_DESCRIPTIONS = {
    "minute": "dakikada bir",
    "hour": "saatte bir",
    "day": "günde bir",
    "month": "ayda bir",
    "year": "yılda bir",
}


def validate_cron(expr: str) -> Dict[str, Any]:
    """Cron ifadesini doğrular, TR açıklama + sonraki 3 çalışma zamanını döner.

    Returns:
        {"valid": bool, "error": str | None, "description": str,
         "next_3_runs": list[str]}
    """
    if not expr or not isinstance(expr, str) or not expr.strip():
        return {
            "valid": False,
            "error": "Cron ifadesi boş olamaz.",
            "description": "",
            "next_3_runs": [],
        }

    expr = expr.strip()

    try:
        from croniter import croniter
    except ImportError:
        return {
            "valid": False,
            "error": "croniter kütüphanesi yüklü değil.",
            "description": "",
            "next_3_runs": [],
        }

    if not croniter.is_valid(expr):
        return {
            "valid": False,
            "error": f"Geçersiz cron ifadesi: '{expr}'",
            "description": "",
            "next_3_runs": [],
        }

    try:
        base = _utcnow()
        cron = croniter(expr, base)
        next_runs = [cron.get_next(datetime).isoformat() for _ in range(3)]

        # Simple TR description
        parts = expr.split()
        desc = _build_cron_description_tr(parts)

        return {
            "valid": True,
            "error": None,
            "description": desc,
            "next_3_runs": next_runs,
        }
    except Exception as e:
        return {
            "valid": False,
            "error": f"Cron hesaplama hatası: {e}",
            "description": "",
            "next_3_runs": [],
        }


def _build_cron_description_tr(parts: List[str]) -> str:
    """5-field cron parçalarından basit TR açıklama oluşturur."""
    if len(parts) < 5:
        return "Özel zamanlama"

    minute, hour, dom, month, dow = parts[:5]

    if minute == "0" and hour == "0" and dom == "1" and month == "*":
        return "Her ayın 1'inde gece yarısı UTC"
    if minute == "0" and hour == "0" and dom == "*" and month == "*" and dow == "*":
        return "Her gün gece yarısı UTC"
    if minute == "0" and hour != "*" and dom == "*" and month == "*" and dow == "*":
        return f"Her gün {hour}:00 UTC"
    if minute != "*" and hour == "*" and dom == "*":
        if minute.startswith("*/"):
            interval = minute[2:]
            return f"Her {interval} dakikada bir"
    if minute == "0" and hour == "0" and dow in ("1", "MON"):
        return "Her Pazartesi gece yarısı UTC"

    return f"Cron: {' '.join(parts)}"
