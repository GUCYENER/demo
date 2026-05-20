"""Apply pending migrations 023-031 directly via psycopg2, bypassing alembic.

Strategy: each migration's upgrade() uses only op.execute(raw_sql).
We monkey-patch alembic.op with a recorder, import each migration module,
call upgrade() to collect SQL, then execute it inside a transaction.
"""
import os
import sys
import importlib.util
import traceback
import types
import re

# Log dosyasi scriptin bulundugu klasore yazilir (canlida E:\VYRA, dev'de d:\demo_vyra).
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migration_run.log")

def w(m):
    line = str(m)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()

with open(LOG, "w", encoding="utf-8") as f:
    f.write("=== migration run ===\n")

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
            v = v.strip().strip('"').strip("'")
            out[k.strip()] = v
    return out


_HERE = os.path.dirname(os.path.abspath(__file__))
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
MIG_DIR = os.path.join(_HERE, "migrations", "versions")

# Fake alembic.op recorder
class _FakeBoundConn:
    """SQLAlchemy benzeri Connection — text() + named params alır, psycopg2 cursor'a çevirir.

    Kullanım: migration `conn = op.get_bind(); conn.execute(text("...:p..."), {"p": ...})`
    Bu wrapper :name placeholder'larını %(name)s formatına çevirir ve cursor'a iletir.
    """
    def __init__(self, cursor):
        self._cursor = cursor
    def execute(self, stmt, params=None):
        sql = stmt.text if hasattr(stmt, "text") else str(stmt)
        # :name → %(name)s (parametrik psycopg2 formatı). '::' (PG cast) korunur.
        sql_pg = re.sub(r'(?<!:):(\w+)', r'%(\1)s', sql)
        if params is None:
            self._cursor.execute(sql_pg)
        else:
            self._cursor.execute(sql_pg, params)


class _FakeOp:
    def __init__(self):
        self.statements = []
        self._bound_conn = None  # _FakeBoundConn — get_bind() döndürür
    def execute(self, sql):
        # Accept str or sqlalchemy text(); we only need .text or str
        if hasattr(sql, "text"):
            sql = sql.text
        self.statements.append(str(sql))
    def get_bind(self):
        """Migration data-DML için bound connection (sqlalchemy.text + named params destekler)."""
        return self._bound_conn

fake_op = _FakeOp()

# Inject fake alembic module to avoid importing real alembic
fake_alembic = types.ModuleType("alembic")
fake_alembic.op = fake_op
sys.modules["alembic"] = fake_alembic
sys.modules["alembic.op"] = fake_op

try:
    import psycopg2
    w("psycopg2 imported")

    # Pending migration files in order
    pending_files = [
        "023_v3290_relationship_cardinality.py",
        "024_v3290_business_glossary_v2.py",
        "025_v3290_code_value_dictionary.py",
        "026_v3290_template_versioning.py",
        "027_v3290_pii_flag.py",
        "028_v3290_query_failure_log.py",
        "029_v3298_signal_weight_suggestions.py",
        "030_v3298_signal_weight_overrides.py",
        "031_v3299_fk_inference_metadata.py",
        "032_v3300_db_smart_core_tables.py",
        "033_v3300_metric_library_seed.py",
    ]

    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    cur = conn.cursor()

    # _FakeBoundConn'u live cursor'a sarıp _FakeOp.get_bind() için hazır tut.
    # 033+ data-DML migration'ları sqlalchemy.text() + named params üzerinden bu wrapper'ı kullanır.
    fake_op._bound_conn = _FakeBoundConn(cur)

    cur.execute("SELECT version_num FROM alembic_version")
    current = cur.fetchone()[0]
    w(f"current revision: {current}")
    conn.commit()

    # Migrations 023-031 use revision IDs longer than alembic's default VARCHAR(32).
    # Expand the column once so the chain can be persisted.
    cur.execute("""
        SELECT character_maximum_length
        FROM information_schema.columns
        WHERE table_name='alembic_version' AND column_name='version_num'
    """)
    width = cur.fetchone()[0]
    if width is not None and width < 64:
        w(f"expanding alembic_version.version_num from {width} to 64")
        cur.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(64)")
        conn.commit()

    # Build a quick lookup: revision_id -> (filename, down_revision)
    # and figure out where to resume from.
    head_revision = pending_files[-1].replace(".py", "")
    if current == head_revision:
        w(f"DB already at head ({head_revision}) — nothing to do.")
        cur.close()
        conn.close()
        w("=== done ===")
        sys.exit(0)

    # If current matches any revision in the pending list, resume after it.
    skip_until_applied = None
    revision_ids_in_order = [f.replace(".py", "") for f in pending_files]
    if current in revision_ids_in_order:
        idx = revision_ids_in_order.index(current)
        files_to_apply = pending_files[idx + 1:]
        w(f"Resuming from {current}, will apply {len(files_to_apply)} migration(s).")
    else:
        files_to_apply = pending_files
        w(f"current ({current}) is before this chain — applying all {len(files_to_apply)} migration(s).")

    for fname in files_to_apply:
        path = os.path.join(MIG_DIR, fname)
        w(f"\n--- {fname} ---")

        # Reset recorder
        fake_op.statements = []

        # Load module fresh
        spec = importlib.util.spec_from_file_location(fname.replace(".py", ""), path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            w(f"  IMPORT FAIL: {e}")
            w(traceback.format_exc())
            sys.exit(1)

        revision_id = getattr(mod, "revision", None)
        down_revision = getattr(mod, "down_revision", None)
        w(f"  revision={revision_id} down={down_revision}")

        if down_revision != current:
            w(f"  ABORT: chain broken (current={current}, this migration expects down_revision={down_revision})")
            sys.exit(2)

        # Call upgrade() to capture SQL
        try:
            mod.upgrade()
        except Exception as e:
            w(f"  upgrade() call failed: {e}")
            w(traceback.format_exc())
            break

        sqls = list(fake_op.statements)
        w(f"  {len(sqls)} SQL statements captured")

        # Execute in single transaction
        try:
            for i, s in enumerate(sqls):
                preview = re.sub(r"\s+", " ", s).strip()[:120]
                w(f"    [{i+1}/{len(sqls)}] {preview}")
                cur.execute(s)
            # Update alembic_version
            cur.execute("UPDATE alembic_version SET version_num = %s", (revision_id,))
            conn.commit()
            current = revision_id
            w(f"  OK applied {revision_id}")
        except Exception as e:
            conn.rollback()
            w(f"  EXEC FAIL: {type(e).__name__}: {e}")
            w(traceback.format_exc())
            cur.close()
            conn.close()
            sys.exit(3)

    # Final state
    cur.execute("SELECT version_num FROM alembic_version")
    final = cur.fetchone()[0]
    w(f"\nFINAL revision: {final}")
    cur.close()
    conn.close()
except Exception as e:
    w(f"FATAL: {type(e).__name__}: {e}")
    w(traceback.format_exc())
    sys.exit(99)

w("=== done ===")
