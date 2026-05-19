"""Post-migration verification. Reads DB credentials from .env."""
import os
import sys
import psycopg2

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(_HERE, "db_check.log")


def _load_env(path):
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


_ENV = _load_env(os.path.join(_HERE, ".env"))


def _g(key, default):
    return os.environ.get(key, _ENV.get(key, default))


DB = dict(
    host=_g("DB_HOST", "localhost"),
    port=int(_g("DB_PORT", "5005")),
    dbname=_g("DB_NAME", "vyra"),
    user=_g("DB_USER", "postgres"),
    password=_g("DB_PASSWORD", "postgres"),
)


def w(m):
    line = str(m)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


open(LOG, "w").close()
w(f"connecting to {DB['host']}:{DB['port']}/{DB['dbname']}")

try:
    conn = psycopg2.connect(**DB, connect_timeout=5)
except Exception as e:
    w(f"CONNECT FAIL: {e}")
    sys.exit(1)

conn.autocommit = True
cur = conn.cursor()

cur.execute("SELECT version_num FROM alembic_version")
ver = cur.fetchone()[0]
w(f"alembic_version: {ver}")

# Width check (we expand to 64 inside run_migrations.py if needed)
cur.execute("""
    SELECT character_maximum_length
    FROM information_schema.columns
    WHERE table_name='alembic_version' AND column_name='version_num'
""")
width = cur.fetchone()[0]
w(f"alembic_version.version_num width: {width}")

# Migration 023 (cardinality)
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='ds_db_relationships'
      AND column_name IN ('cardinality_from','cardinality_to','is_junction','path_weight','confidence_score','last_analyzed_at',
                          'is_inferred','inference_method','evidence_json','admin_verified','rejected_at')
    ORDER BY column_name
""")
cols = [r[0] for r in cur.fetchall()]
w(f"ds_db_relationships extension cols ({len(cols)}/11): {cols}")

# Migration 024
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='business_glossary' AND column_name IN ('term_type','admin_verified','usage_count','mapped_table','tsv')
    ORDER BY column_name
""")
w(f"business_glossary new cols: {[r[0] for r in cur.fetchall()]}")

# Tables
for tbl in ("ds_code_values", "learned_query_failures",
            "signal_weight_suggestions", "signal_weight_overrides", "signal_weight_audit_log"):
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{tbl}",))
    w(f"  {tbl}: {cur.fetchone()[0]}")

# fk_inference_deploy_ts
cur.execute("SELECT setting_value FROM system_settings WHERE setting_key='fk_inference_deploy_ts'")
row = cur.fetchone()
w(f"fk_inference_deploy_ts: {row[0] if row else 'NOT SET'}")

cur.close()
conn.close()
w("OK")
