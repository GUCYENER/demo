"""
Manual Fernet Credential Rotation Tool — Ajan-J v3.32.0 MVP
============================================================
data_sources.db_password_encrypted alanındaki tüm şifreleri en yeni
Fernet key ile yeniden şifreler ve key_version sütununu günceller.

Kullanım
--------
::

    # Dry-run: SELECT + decrypt, UPDATE YAPMAZ — rapor üretir
    VYRA_FERNET_KEYS="OLD_KEY,NEW_KEY" python scripts/rotate_fernet_credentials.py --dry-run

    # Gerçek rotation
    VYRA_FERNET_KEYS="OLD_KEY,NEW_KEY" python scripts/rotate_fernet_credentials.py

Adımlar
-------
1. SELECT id, db_password_encrypted, key_version FROM data_sources
   WHERE db_password_encrypted IS NOT NULL AND db_password_encrypted <> '';
2. Decrypt (MultiFernet — tüm key'leri sırayla dener).
3. Re-encrypt (en yeni write key).
4. UPDATE db_password_encrypted, key_version (sadece --dry-run değilse).
5. Final audit: total / rotated / skipped / failed.

Notlar
------
- Per-row try/except → bir DS hata verirse loop devam eder.
- `db_password_encrypted` Fernet token DEĞİLSE (örn. legacy "b64:..."
  fallback) → skipped sayılır, log'a yazılır.
- Auto-scheduler v3.33'e ertelendi (bu script MANUEL çalıştırılır).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Repo root'u path'e ekle (script standalone çalışsın)
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.services.security.credentials import (  # noqa: E402
    current_key_version,
    decrypt,
    encrypt,
)

logger = logging.getLogger("rotate_fernet")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _get_conn():
    """app.core.db üzerinden bağlantı al (psycopg connection)."""
    from app.core.db import get_db_conn  # lazy import — env load için
    return get_db_conn()


def _is_b64_fallback(token: str) -> bool:
    """data_sources_api.py içindeki 'b64:' fallback prefix kontrolü."""
    return isinstance(token, str) and token.startswith("b64:")


def rotate(dry_run: bool = False) -> int:
    """
    Tüm data_sources satırlarını rotate eder.

    Returns:
        int: Process exit code (0 = success, 1 = at least one failure).
    """
    target_version = current_key_version()
    logger.info("[ROTATE] target key_version = v%d (dry_run=%s)", target_version, dry_run)

    total = rotated = skipped = failed = 0
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, db_password_encrypted, key_version
            FROM data_sources
            WHERE db_password_encrypted IS NOT NULL
              AND db_password_encrypted <> ''
            ORDER BY id
            """
        )
        rows = cur.fetchall()
        total = len(rows)
        logger.info("[ROTATE] %d data_source rows fetched", total)

        for row in rows:
            # psycopg row → dict-like ya da tuple olabilir; her ikisini destekle
            try:
                ds_id = row["id"] if hasattr(row, "__getitem__") and not isinstance(row, tuple) else row[0]
                token = row["db_password_encrypted"] if hasattr(row, "__getitem__") and not isinstance(row, tuple) else row[1]
                cur_ver = row["key_version"] if hasattr(row, "__getitem__") and not isinstance(row, tuple) else row[2]
            except (KeyError, IndexError, TypeError):
                # Fallback: tuple sırasını dene
                ds_id, token, cur_ver = row[0], row[1], row[2]

            # Zaten en yeni versiyondaysa atla
            if cur_ver == target_version:
                skipped += 1
                logger.debug("[ROTATE] id=%s already at v%d → skip", ds_id, target_version)
                continue

            # Legacy b64 fallback token → rotate edilemez
            if _is_b64_fallback(token):
                skipped += 1
                logger.warning(
                    "[ROTATE] id=%s legacy b64 fallback token → skip (manuel re-encrypt gerekli)",
                    ds_id,
                )
                continue

            try:
                plain = decrypt(token)
                new_token = encrypt(plain).decode("utf-8")
            except Exception as exc:
                failed += 1
                logger.error(
                    "[ROTATE] id=%s decrypt/encrypt FAILED: %s: %s",
                    ds_id, type(exc).__name__, exc,
                )
                continue

            if dry_run:
                rotated += 1  # dry-run'da "rotate edilebilir" sayar
                logger.info("[ROTATE] id=%s would rotate v%s → v%d (dry-run)",
                            ds_id, cur_ver, target_version)
                continue

            try:
                cur.execute(
                    """
                    UPDATE data_sources
                    SET db_password_encrypted = %s,
                        key_version = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (new_token, target_version, ds_id),
                )
                rotated += 1
                logger.info("[ROTATE] id=%s rotated v%s → v%d", ds_id, cur_ver, target_version)
            except Exception as exc:
                failed += 1
                logger.error(
                    "[ROTATE] id=%s UPDATE FAILED: %s: %s",
                    ds_id, type(exc).__name__, exc,
                )
                conn.rollback()
                continue

        if not dry_run:
            conn.commit()
            logger.info("[ROTATE] COMMIT done")
        else:
            conn.rollback()
            logger.info("[ROTATE] dry-run ROLLBACK done (no DB changes)")

    finally:
        try:
            conn.close()
        except Exception:
            pass

    logger.info(
        "[ROTATE] total=%d, rotated=%d, skipped=%d, failed=%d",
        total, rotated, skipped, failed,
    )
    return 0 if failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="VYRA Fernet credential rotation (Ajan-J v3.32.0 MVP)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="SELECT + decrypt yap, UPDATE yapma (raporlama amaçlı)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="DEBUG seviye log",
    )
    args = parser.parse_args()

    _setup_logging(args.verbose)
    try:
        return rotate(dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.warning("[ROTATE] interrupted by user")
        return 130
    except Exception as exc:
        logger.exception("[ROTATE] fatal error: %s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
