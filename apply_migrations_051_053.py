"""VYRA — Canlı DB'ye 051/052/053 migration'larını DOĞRUDAN uygula (alembic-bypass).

NEDEN: Bazı kurulumlarda alembic_version stale bir id taşıyor (ör. '050_v3390_ds_jobs_progress'
— dosyalarda yok; 050'nin revision id'si sonradan '050_v3430'a değişti). Bu durumda
`alembic upgrade head` "Can't locate revision 050_v3390" ile patlar ve alembic env (app import
edip embedding modeli yüklediği için) asılabilir. Bu script alembic'i BYPASS edip 3 migration'ın
SQL'ini doğrudan psycopg2 ile çalıştırır; tamamı IDEMPOTENT (IF NOT EXISTS / DROP POLICY IF EXISTS)
→ defalarca güvenle koşturulabilir.

KAPSAM:
  051_v3440_few_shot_origin       → few_shot_examples.origin + is_active (+indeksler)   [P1 few-shot terfi]
  052_v3460_synthetic_error_kind  → ds_synthetic_query_runs.error_kind (+kısmi indeks)  [P3a hata sınıflandırma]
  053_v3470_ds_jobs_rls           → ds_discovery_jobs company-scoped RLS policy         [P3b job state]
  + alembic_version → '053_v3470_ds_jobs_rls' (stale '050_v3390' de düzelir)

KULLANIM (canlı sunucuda, proje kökünde):
  python apply_migrations_051_053.py            # uygula
  python apply_migrations_051_053.py --dry-run  # yalnız mevcut durumu RAPORLA, DEĞİŞTİRME

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
        "051_v3440_few_shot_origin",
        "few_shot_examples.origin + is_active",
        """
        ALTER TABLE few_shot_examples ADD COLUMN IF NOT EXISTS origin VARCHAR(16) DEFAULT 'user';
        ALTER TABLE few_shot_examples ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
        CREATE INDEX IF NOT EXISTS idx_few_shot_origin ON few_shot_examples(origin);
        CREATE INDEX IF NOT EXISTS idx_few_shot_active ON few_shot_examples(is_active) WHERE is_active = TRUE;
        """,
    ),
    (
        "052_v3460_synthetic_error_kind",
        "ds_synthetic_query_runs.error_kind",
        """
        ALTER TABLE ds_synthetic_query_runs ADD COLUMN IF NOT EXISTS error_kind VARCHAR(24);
        CREATE INDEX IF NOT EXISTS idx_synth_runs_error_kind
            ON ds_synthetic_query_runs(source_id, error_kind) WHERE error_kind IS NOT NULL;
        """,
    ),
    (
        "053_v3470_ds_jobs_rls",
        "ds_discovery_jobs company-scoped RLS",
        """
        ALTER TABLE ds_discovery_jobs ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS rls_company_scoped ON ds_discovery_jobs;
        CREATE POLICY rls_company_scoped ON ds_discovery_jobs FOR ALL
          USING (
            current_setting('app.current_company_id', true) IS NULL
            OR current_setting('app.current_company_id', true) = ''
            OR current_setting('app.bypass_rls', true) = 'on'
            OR company_id::text = current_setting('app.current_company_id', true)
          )
          WITH CHECK (
            current_setting('app.current_company_id', true) IS NULL
            OR current_setting('app.current_company_id', true) = ''
            OR current_setting('app.bypass_rls', true) = 'on'
            OR company_id::text = current_setting('app.current_company_id', true)
          );
        """,
    ),
]

TARGET_HEAD = "053_v3470_ds_jobs_rls"

# (tablo, kolon) — uygulama sonrası doğrulama
_VERIFY_COLS = [
    ("few_shot_examples", "origin"),
    ("few_shot_examples", "is_active"),
    ("ds_synthetic_query_runs", "error_kind"),
]


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
        for tbl, col in _VERIFY_COLS:
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s", (tbl, col))
            print(f"[ONCE]   {tbl}.{col}: {'VAR' if cur.fetchone() else 'YOK'}")
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
        for tbl, col in _VERIFY_COLS:
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s", (tbl, col))
            print(f"[SONRA]   {tbl}.{col}: {'VAR' if cur.fetchone() else 'YOK'}")
        cur.execute("SELECT relrowsecurity FROM pg_class WHERE relname='ds_discovery_jobs'")
        r = cur.fetchone()
        print(f"[SONRA]   ds_discovery_jobs RLS: {r[0] if r else 'tablo yok'}")
        conn.rollback()

        print(f"[OZET] {ok} migration OK, {fail} hata.")
        return 0 if fail == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
