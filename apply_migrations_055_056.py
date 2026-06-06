"""VYRA — Canlı DB'ye 055/056 migration'larını DOĞRUDAN uygula (alembic-bypass).

NEDEN: Bu kurulumda `alembic upgrade head` güvenilmez (stale alembic_version + env import
asılması). Bu script alembic'i BYPASS edip migration SQL'ini doğrudan psycopg2 ile çalıştırır;
tamamı IDEMPOTENT (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS) → defalarca güvenle koşturulabilir.

KAPSAM (Tema-1 kapalı-döngü gözlemlenebilirlik):
  055_v3770_fk_diagnostics   → ds_fk_diagnostics tablosu + 2 index   [FK çözülemeyen kök-neden]
  056_v3771_enrich_coverage  → ds_table_enrichments.columns_enriched + columns_total  [enrich kapsama rozeti]

  + 054_v3530_sql_query_jobs → ZİNCİR GÜVENCESİ. 055'in down_revision'ı 054; önceki apply
    (051_053) alembic_version'ı 053'te bıraktı. 054'ün tablosu startup SCHEMA_SQL'de mevcut
    (canlıda olmalı) ama head'i 056'ya damgalamadan önce idempotent olarak garanti ederiz ki
    damga DÜRÜST olsun (054 atlanmış sanılmasın). DDL idempotent → zaten varsa no-op.
  + alembic_version → '056_v3771_enrich_coverage' (stale '053'/'050_v3390' de düzelir)

NOT (056 zorunlu): columns_enriched/columns_total schema.py SCHEMA_SQL'de YOK → startup eklemiyor;
yalnız bu migration ekler. (Mevcut DB'de yoksa get_all_tables_status rollback-guard ile zarif düşer.)

KULLANIM (canlı sunucuda, proje kökünde — Windows python):
  python apply_migrations_055_056.py            # uygula
  python apply_migrations_055_056.py --dry-run  # yalnız mevcut durumu RAPORLA, DEĞİŞTİRME

DB bağlantısı .env'den okunur (DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD). Çıktı ASCII (Windows
cp1252 konsol güvenli). Hata olursa o migration kendi transaction'ında rollback edilir, diğerleri
etkilenmez; sonunda net özet basar.
"""
import os
import sys


def _load_env(path=".env"):
    env = dict(os.environ)
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        pass
    return env


# (revision, human_label, idempotent_upgrade_sql)
MIGRATIONS = [
    (
        "054_v3530_sql_query_jobs",
        "sql_query_jobs (zincir guvencesi; muhtemelen mevcut)",
        """
        CREATE TABLE IF NOT EXISTS sql_query_jobs (
            job_id VARCHAR(64) PRIMARY KEY,
            owner_user_id INTEGER NOT NULL,
            dialog_id INTEGER,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            started_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_sql_query_jobs_status ON sql_query_jobs(status);
        CREATE INDEX IF NOT EXISTS idx_sql_query_jobs_started ON sql_query_jobs(started_at);
        """,
    ),
    (
        "055_v3770_fk_diagnostics",
        "ds_fk_diagnostics + 2 index",
        """
        CREATE TABLE IF NOT EXISTS ds_fk_diagnostics (
            id SERIAL PRIMARY KEY,
            source_id INTEGER NOT NULL REFERENCES data_sources(id) ON DELETE CASCADE,
            from_schema VARCHAR(100),
            from_table VARCHAR(200) NOT NULL,
            from_column VARCHAR(200) NOT NULL,
            reason VARCHAR(40) NOT NULL,
            root VARCHAR(200),
            head VARCHAR(200),
            evidence_json JSONB,
            is_fixed BOOLEAN NOT NULL DEFAULT FALSE,
            first_seen_at TIMESTAMP DEFAULT NOW(),
            last_seen_at TIMESTAMP DEFAULT NOW(),
            fixed_at TIMESTAMP
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ds_fk_diag_unique
            ON ds_fk_diagnostics(source_id, COALESCE(from_schema,''), from_table, from_column);
        CREATE INDEX IF NOT EXISTS idx_ds_fk_diag_open ON ds_fk_diagnostics(source_id, is_fixed);
        """,
    ),
    (
        "056_v3771_enrich_coverage",
        "ds_table_enrichments.columns_enriched + columns_total",
        """
        ALTER TABLE ds_table_enrichments ADD COLUMN IF NOT EXISTS columns_enriched INTEGER DEFAULT 0;
        ALTER TABLE ds_table_enrichments ADD COLUMN IF NOT EXISTS columns_total INTEGER DEFAULT 0;
        """,
    ),
]

TARGET_HEAD = "056_v3771_enrich_coverage"

# uygulama oncesi/sonrasi dogrulama
_VERIFY_TABLES = ["sql_query_jobs", "ds_fk_diagnostics"]
_VERIFY_COLS = [
    ("ds_table_enrichments", "columns_enriched"),
    ("ds_table_enrichments", "columns_total"),
]


def _report_state(cur, tag):
    """Tablolarin/kolonlarin mevcut durumunu RAPORLA (degistirmez)."""
    for tbl in _VERIFY_TABLES:
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name=%s", (tbl,))
        print(f"[{tag}]   tablo {tbl}: {'VAR' if cur.fetchone() else 'YOK'}")
    for tbl, col in _VERIFY_COLS:
        cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s", (tbl, col))
        print(f"[{tag}]   {tbl}.{col}: {'VAR' if cur.fetchone() else 'YOK'}")


def main():
    dry = "--dry-run" in sys.argv
    env = _load_env()
    try:
        import psycopg2
    except ImportError:
        print("[HATA] psycopg2 bulunamadi. Proje venv'inde calistirin "
              "(or: python -m pip install psycopg2-binary).")
        return 2

    host = env.get("DB_HOST", "localhost"); port = env.get("DB_PORT", "5005")
    name = env.get("DB_NAME", "vyra"); user = env.get("DB_USER", "postgres")
    pw = env.get("DB_PASSWORD", "")
    print(f"[DB] {host}:{port}/{name} user={user}  mode={'DRY-RUN' if dry else 'APPLY'}")

    try:
        conn = psycopg2.connect(host=host, port=port, dbname=name, user=user,
                                password=pw, connect_timeout=10)
    except Exception as e:
        print(f"[HATA] Baglanti basarisiz: {type(e).__name__}: {str(e)[:200]}")
        return 2

    try:
        cur = conn.cursor()
        # Mevcut durum
        try:
            cur.execute("SELECT version_num FROM alembic_version")
            ver = [r[0] for r in cur.fetchall()]
        except Exception:
            conn.rollback(); ver = ["(alembic_version tablosu yok)"]
        print(f"[ONCE] alembic_version: {ver}")
        _report_state(cur, "ONCE")
        conn.rollback()

        if dry:
            print("[DRY-RUN] Degisiklik yapilmadi. Uygulamak icin --dry-run'siz calistirin.")
            return 0

        # Her migration kendi transaction'inda
        ok, fail = 0, 0
        for rev, label, sql in MIGRATIONS:
            try:
                cur.execute(sql)
                conn.commit()
                print(f"[OK] {rev}  ({label})")
                ok += 1
            except Exception as e:
                conn.rollback()
                print(f"[HATA] {rev}: {type(e).__name__}: {str(e)[:200]}")
                fail += 1

        # alembic_version -> head (stale id de duzelir). alembic_version tek satir tutar.
        try:
            cur.execute("SELECT COUNT(*) FROM alembic_version")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO alembic_version (version_num) VALUES (%s)", (TARGET_HEAD,))
            else:
                cur.execute("UPDATE alembic_version SET version_num = %s", (TARGET_HEAD,))
            conn.commit()
            print(f"[OK] alembic_version -> {TARGET_HEAD}")
        except Exception as e:
            conn.rollback()
            print(f"[UYARI] alembic_version guncellenemedi: {str(e)[:150]} "
                  f"(kolonlar uygulandi; alembic_version'i elle {TARGET_HEAD} yapin)")

        # Dogrulama
        print("[SONRA] dogrulama:")
        _report_state(cur, "SONRA")
        conn.rollback()

        print(f"[OZET] {ok} migration OK, {fail} hata.")
        return 0 if fail == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
