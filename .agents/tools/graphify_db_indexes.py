"""Apply DB-level index improvements to graphify SQLite.

Only adds indexes the SQLite planner will pick up WITHOUT any SDK code changes.
- Partial indexes on triples WHERE valid_to IS NULL (dominant filter)
- Expression index on entities for v_open_refactors view (literal json path)
- Covering composite on triples for predicate scans

Safe to re-run: uses IF NOT EXISTS. ANALYZE re-run at end.
"""
from __future__ import annotations
import os, sqlite3, time, argparse
from pathlib import Path

DB = Path(os.path.expanduser("~/.graphify/instances/vyra.db"))

INDEXES = [
    # Partial indexes — only active triples (~99% of queries filter valid_to IS NULL)
    ("idx_triples_subject_active",
     "CREATE INDEX IF NOT EXISTS idx_triples_subject_active "
     "ON triples(subject) WHERE valid_to IS NULL"),
    ("idx_triples_object_active",
     "CREATE INDEX IF NOT EXISTS idx_triples_object_active "
     "ON triples(object) WHERE valid_to IS NULL"),
    ("idx_triples_predicate_active",
     "CREATE INDEX IF NOT EXISTS idx_triples_predicate_active "
     "ON triples(predicate) WHERE valid_to IS NULL"),
    ("idx_triples_subject_pred_active",
     "CREATE INDEX IF NOT EXISTS idx_triples_subject_pred_active "
     "ON triples(subject, predicate) WHERE valid_to IS NULL"),

    # Covering composite for traverse: (subject, created_at) so ORDER BY uses index
    ("idx_triples_subject_created_active",
     "CREATE INDEX IF NOT EXISTS idx_triples_subject_created_active "
     "ON triples(subject, created_at DESC) WHERE valid_to IS NULL"),

    # Expression index for v_open_refactors view (literal json path → planner can use it)
    ("idx_entities_refactor_status",
     "CREATE INDEX IF NOT EXISTS idx_entities_refactor_status "
     "ON entities(type, json_extract(properties, '$.status')) "
     "WHERE type = 'Refactor'"),

    # Composite for find_entities(type='Decision') ORDER BY updated_at DESC (recent decisions view)
    ("idx_entities_type_updated",
     "CREATE INDEX IF NOT EXISTS idx_entities_type_updated "
     "ON entities(type, updated_at DESC)"),

    # Entity project_slug+updated_at for MCP scoped queries
    ("idx_entities_project_updated",
     "CREATE INDEX IF NOT EXISTS idx_entities_project_updated "
     "ON entities(project_slug, updated_at DESC) WHERE project_slug IS NOT NULL"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB), timeout=30.0, isolation_level=None)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.row_factory = sqlite3.Row

    # Existing index list
    existing = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    )}

    pre_size = DB.stat().st_size
    print(f"pre_size_bytes = {pre_size:,}")
    print()

    for name, sql in INDEXES:
        if name in existing:
            print(f"  SKIP   {name} (exists)")
            continue
        if args.dry_run:
            print(f"  DRY    {name}")
            print(f"         {sql}")
            continue
        t0 = time.perf_counter()
        try:
            con.execute(sql)
            print(f"  CREATE {name:42s} {(time.perf_counter()-t0)*1000:7.1f} ms")
        except sqlite3.OperationalError as e:
            print(f"  FAIL   {name}: {e}")

    # Re-ANALYZE after new indexes
    if not args.dry_run:
        t0 = time.perf_counter()
        con.execute("ANALYZE")
        print(f"\n  ANALYZE {(time.perf_counter()-t0)*1000:.1f} ms")

    post_size = DB.stat().st_size
    print(f"\npost_size_bytes = {post_size:,}")
    print(f"delta = {post_size - pre_size:+,} bytes")

    # Final index list
    print("\n===== ACTIVE NON-AUTO INDEXES =====")
    for r in con.execute(
        "SELECT name, tbl_name FROM sqlite_master "
        "WHERE type='index' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY tbl_name, name"
    ):
        print(f"  {r[1]:15s} {r[0]}")

    con.close()


if __name__ == "__main__":
    main()
