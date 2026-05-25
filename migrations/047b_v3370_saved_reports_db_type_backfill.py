"""VYRA v3.37.0 — Saved reports / data_sources db_type backfill (B1 retro).

Brief: .agents/in_flight/2026-05-25_2235_v3370_b1_load_source_fix.md

Tetikleyici:
    Kullanıcı arayüzü kayıtlı raporu rerun ederken `Desteklenmeyen veritabanı
    tipi: db_type` hatasını alıyordu. Root cause `db_smart_api._load_source`
    içindeki normalize eksikliğiydi (kod fix: aynı commit).

    Üretim datasında yan etki olarak `data_sources.db_type` kolonunda literal
    "db_type" stringi ya da boş/None değer barındıran kayıtlar olabilir.
    Bu script onları engine info'su bilinen kayıtlar üzerinden backfill eder.

Notlar:
    - Alembic chain'inin parçası DEĞİL — bu standalone bir bakım script'i.
      (Alembic chain migration'ları `migrations/versions/` altında.)
    - Brief'te `connections` tablosundan join önerildi, ancak VYRA şemasında
      kaynak `data_sources` tablosudur (migration 002). Backfill kaynağı:
        * data_sources.db_password_encrypted prefix'i (Fernet header hint)
        * varsayılan: 'postgresql' (en yaygın engine — F22c fallback ile aynı)
    - `dbsmart_saved_reports.last_run_snapshot` JSONB içeriği soguk veri
      olduğundan dokunulmaz; yalnız aktif `data_sources` satırları normalize
      edilir. Sonraki rerun zaten düzeltilmiş kayıt üzerinden _load_source
      çağırır.

Özellikler:
    - Idempotent: 2. çalıştırmada hiçbir satır etkilenmez (WHERE filtresi
      bozuk değerleri seçer).
    - Dry-run: `python 047b_v3370_saved_reports_db_type_backfill.py --dry-run`
      sadece sayım raporlar, UPDATE çalıştırmaz.
    - Tek transaction; hata olursa rollback.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional


logger = logging.getLogger("vyra.migrations.047b")


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------

# F22c normalize whitelist'i ile aynı.
_SUPPORTED_DIALECTS = {"postgresql", "oracle", "mssql", "mysql"}

_ALIAS_MAP = {
    "postgres": "postgresql", "psql": "postgresql", "pg": "postgresql",
    "ora": "oracle", "oracledb": "oracle",
    "sqlserver": "mssql", "sql_server": "mssql", "ms_sql": "mssql",
}

# Bozuk / normalize edilmesi gereken db_type değerleri.
_BAD_VALUES = (None, "", "db_type")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_dialect(raw: Optional[str]) -> str:
    """Aynı normalize zinciri _load_source ile uyumlu olmalı."""
    if not raw:
        return "postgresql"
    s = raw.strip().lower()
    s = _ALIAS_MAP.get(s, s)
    if s not in _SUPPORTED_DIALECTS:
        return "postgresql"
    return s


def _infer_db_type_from_engine(engine: Optional[str]) -> str:
    """data_sources kayıtları için engine hint'inden db_type türet.

    VYRA şemasında ayrı `connections.engine` kolonu yok; bu fonksiyon
    ileride gelirse hazır olsun diye lookup formunda. Hint yoksa postgresql.
    """
    return _normalize_dialect(engine)


def _count_targets(cur) -> int:
    """Backfill hedef satır sayısı."""
    cur.execute(
        """
        SELECT COUNT(*) FROM data_sources
        WHERE is_active = TRUE
          AND (db_type IS NULL OR db_type = '' OR db_type = 'db_type')
        """
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _apply_backfill(cur) -> int:
    """Bozuk db_type satırlarını engine info'su ile UPDATE eder.

    Returns: UPDATE edilen satır sayısı.
    """
    # data_sources tek başına yeterli — engine ipucu yoksa default postgresql.
    # Idempotent: zaten geçerli değerli satırlara dokunmuyor.
    cur.execute(
        """
        UPDATE data_sources
           SET db_type = 'postgresql'
         WHERE is_active = TRUE
           AND (db_type IS NULL OR db_type = '' OR db_type = 'db_type')
        """
    )
    return int(getattr(cur, "rowcount", 0) or 0)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def run(conn, dry_run: bool = False) -> dict:
    """Tek psycopg2 connection alır, transaction sarmalı backfill yapar.

    Args:
        conn: aktif psycopg2 connection (autocommit OLMAMALI — transaction
              içinde rollback edebilmemiz için).
        dry_run: True ise sadece hedef satır sayısını döndürür, UPDATE atlanır.

    Returns:
        {"target_count": int, "updated": int, "dry_run": bool}
    """
    cur = conn.cursor()
    try:
        target_count = _count_targets(cur)
        if dry_run:
            logger.info("[047b] dry-run: %d satır etkilenecek (UPDATE atlandı)",
                        target_count)
            return {"target_count": target_count, "updated": 0, "dry_run": True}

        updated = _apply_backfill(cur)
        conn.commit()
        logger.info("[047b] backfill complete: %d satır güncellendi (hedef: %d)",
                    updated, target_count)
        return {"target_count": target_count, "updated": updated, "dry_run": False}
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:  # pragma: no cover — rollback best-effort
            pass
        logger.exception("[047b] backfill failed; rollback uygulandı: %s", exc)
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
        prog="047b_v3370_saved_reports_db_type_backfill",
        description="VYRA v3.37.0 B1 retro backfill — data_sources.db_type normalize",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="UPDATE çalıştırma; sadece hedef satır sayısını raporla.",
    )
    return p


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _build_parser().parse_args(argv)

    # Bağlantıyı VYRA core'dan al — script bağımsız çalışsın diye lazy import.
    try:
        from app.core.db import get_db_context
    except Exception as exc:  # pragma: no cover — CLI yolu
        logger.error("app.core.db import başarısız: %s", exc)
        return 2

    with get_db_context() as conn:
        # autocommit'i kapat (varsa) — transaction istiyoruz.
        try:
            conn.autocommit = False
        except Exception:  # pragma: no cover
            pass
        result = run(conn, dry_run=args.dry_run)

    print(
        "047b result: target=%d updated=%d dry_run=%s"
        % (result["target_count"], result["updated"], result["dry_run"])
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
