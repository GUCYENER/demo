"""VYRA v3.37.0 — Release version bump (system_settings.app_version).

Brief: .agents/in_flight/2026-05-25_2250_v3370_release_closeout.md

Tetikleyici:
    v3.37.0 release close-out. `system_settings` tablosundaki `app_version`
    kaydını '3.37.0' olarak normalize eder. Kod tarafı `app/core/config.py`
    içinde APP_VERSION = "3.37.0" olarak set edilmiştir; bu script DB'deki
    paralel kaydı senkron tutmak içindir.

Notlar:
    - Alembic chain'inin parçası DEĞİL — bu standalone bir bakım script'i
      (047b ile aynı kalıp). Alembic chain migration'ları
      `migrations/versions/` altında.
    - Idempotent: 2. çalıştırmada hiçbir satır etkilenmez (UPSERT pattern).
    - `system_settings` tablosu yoksa graceful no-op (eski kurulumlar için).

Özellikler:
    - Idempotent UPSERT: kayıt yoksa INSERT, varsa UPDATE.
    - Dry-run: `python 047_v3370_release_bump.py --dry-run`
      sadece mevcut değeri raporlar, UPDATE çalıştırmaz.
    - Tek transaction; hata olursa rollback.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional


logger = logging.getLogger("vyra.migrations.047")


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

_TARGET_VERSION = "3.37.0"
_SETTING_KEY = "app_version"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(cur, table_name: str) -> bool:
    """system_settings tablosu var mı? Eski kurulumlarda olmayabilir."""
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        (table_name,),
    )
    row = cur.fetchone()
    return bool(row[0]) if row else False


def _current_value(cur) -> Optional[str]:
    """Mevcut app_version değeri (None = kayıt yok)."""
    cur.execute(
        "SELECT setting_value FROM system_settings WHERE setting_key = %s",
        (_SETTING_KEY,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _apply_bump(cur) -> int:
    """Idempotent UPSERT — app_version = _TARGET_VERSION.

    Returns: etkilenen satır sayısı (0 = zaten güncel ya da no-op).
    """
    cur.execute(
        """
        INSERT INTO system_settings (setting_key, setting_value)
        VALUES (%s, %s)
        ON CONFLICT (setting_key) DO UPDATE
            SET setting_value = EXCLUDED.setting_value
            WHERE system_settings.setting_value IS DISTINCT FROM EXCLUDED.setting_value
        """,
        (_SETTING_KEY, _TARGET_VERSION),
    )
    return int(getattr(cur, "rowcount", 0) or 0)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def run(conn, dry_run: bool = False) -> dict:
    """Tek psycopg2 connection alır, transaction sarmalı bump yapar.

    Args:
        conn: aktif psycopg2 connection (autocommit OLMAMALI).
        dry_run: True ise sadece mevcut değeri döndürür, UPDATE atlanır.

    Returns:
        {"current": str|None, "target": str, "updated": int, "dry_run": bool,
         "skipped_reason": str|None}
    """
    cur = conn.cursor()
    try:
        if not _table_exists(cur, "system_settings"):
            logger.warning("[047] system_settings tablosu bulunamadi — no-op.")
            return {
                "current": None,
                "target": _TARGET_VERSION,
                "updated": 0,
                "dry_run": dry_run,
                "skipped_reason": "table_missing",
            }

        current = _current_value(cur)
        if dry_run:
            logger.info(
                "[047] dry-run: current=%r target=%r (UPDATE atlandi)",
                current, _TARGET_VERSION,
            )
            return {
                "current": current,
                "target": _TARGET_VERSION,
                "updated": 0,
                "dry_run": True,
                "skipped_reason": None,
            }

        updated = _apply_bump(cur)
        conn.commit()
        logger.info(
            "[047] bump complete: current=%r -> %r (rowcount=%d)",
            current, _TARGET_VERSION, updated,
        )
        return {
            "current": current,
            "target": _TARGET_VERSION,
            "updated": updated,
            "dry_run": False,
            "skipped_reason": None,
        }
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:  # pragma: no cover — rollback best-effort
            pass
        logger.exception("[047] bump failed; rollback uygulandi: %s", exc)
        raise
    finally:
        try:
            cur.close()
        except Exception:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="047_v3370_release_bump",
        description="VYRA v3.37.0 release bump — system_settings.app_version=3.37.0",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="UPDATE calistirma; sadece mevcut degeri raporla.",
    )
    return p


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _build_parser().parse_args(argv)

    try:
        from app.core.db import get_db_context
    except Exception as exc:  # pragma: no cover — CLI yolu
        logger.error("app.core.db import basarisiz: %s", exc)
        return 2

    with get_db_context() as conn:
        try:
            conn.autocommit = False
        except Exception:  # pragma: no cover
            pass
        result = run(conn, dry_run=args.dry_run)

    print(
        "047 result: current=%s target=%s updated=%d dry_run=%s skipped=%s"
        % (
            result["current"],
            result["target"],
            result["updated"],
            result["dry_run"],
            result["skipped_reason"],
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
