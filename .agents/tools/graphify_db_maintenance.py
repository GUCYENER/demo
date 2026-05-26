"""Periodic Graphify DB maintenance — safe to run while MCP server is up.

Recommended cadence: weekly via Windows Task Scheduler or before BITIR.

Actions (all idempotent, all safe under WAL + busy_timeout):
  1. PRAGMA optimize  — incremental ANALYZE on changed indexes (cheap)
  2. PRAGMA wal_checkpoint(TRUNCATE)  — keep WAL file small
  3. ANALYZE  — full stats refresh (only if growth > 10%)
  4. Reclassify orphan 'closes' triples (entity → literal) if any
  5. Optional --vacuum  for monthly defrag

Exit code: 0 on success, non-zero if any step fails.
"""
from __future__ import annotations
import argparse, os, sqlite3, time, sys
from pathlib import Path

DB = Path(os.path.expanduser("~/.graphify/instances/vyra.db"))
GROWTH_THRESHOLD = 0.10  # 10%


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vacuum", action="store_true", help="Run VACUUM (slow, monthly).")
    ap.add_argument("--force-analyze", action="store_true",
                    help="Run full ANALYZE regardless of growth.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not DB.exists():
        print(f"ERR: DB not found at {DB}", file=sys.stderr)
        return 2

    log = (lambda *a: None) if args.quiet else print

    pre_size = DB.stat().st_size
    log(f"[graphify-maint] db={DB} size={pre_size:,} bytes")

    con = sqlite3.connect(str(DB), timeout=30.0, isolation_level=None)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.row_factory = sqlite3.Row

    try:
        # 1) PRAGMA optimize — cheap, recommended on every open per SQLite docs
        t0 = time.perf_counter()
        con.execute("PRAGMA optimize")
        log(f"  PRAGMA optimize         {(time.perf_counter()-t0)*1000:7.1f} ms")

        # 2) WAL checkpoint TRUNCATE
        t0 = time.perf_counter()
        res = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        log(f"  wal_checkpoint(TRUNC)   {(time.perf_counter()-t0)*1000:7.1f} ms  {tuple(res)}")

        # 3) Conditional ANALYZE
        last_size = _get_meta(con, "last_maint_size_bytes")
        do_analyze = args.force_analyze
        if last_size:
            try:
                growth = (pre_size - int(last_size)) / int(last_size)
                if abs(growth) >= GROWTH_THRESHOLD:
                    do_analyze = True
                    log(f"  growth={growth:+.1%} >= {GROWTH_THRESHOLD:.0%} -> ANALYZE")
            except (ValueError, ZeroDivisionError):
                do_analyze = True
        else:
            do_analyze = True
        if do_analyze:
            t0 = time.perf_counter()
            con.execute("ANALYZE")
            log(f"  ANALYZE                 {(time.perf_counter()-t0)*1000:7.1f} ms")

        # 4) Reclassify orphan closes/has_* triples (object_type entity -> literal)
        t0 = time.perf_counter()
        cur = con.execute("""
            UPDATE triples SET object_type = 'literal'
            WHERE object_type = 'entity'
              AND id IN (
                SELECT t.id FROM triples t
                LEFT JOIN entities e ON e.id = t.object
                WHERE e.id IS NULL AND t.object_type = 'entity'
              )
        """)
        n = cur.rowcount
        log(f"  reclassify orphans      {(time.perf_counter()-t0)*1000:7.1f} ms  rows={n}")

        # 5) Optional VACUUM
        if args.vacuum:
            t0 = time.perf_counter()
            con.execute("VACUUM")
            log(f"  VACUUM                  {(time.perf_counter()-t0)*1000:7.1f} ms")

        # Record last maintenance size + ts
        post_size = DB.stat().st_size
        _set_meta(con, "last_maint_size_bytes", str(post_size))
        _set_meta(con, "last_maint_ts", str(int(time.time())))
        log(f"[graphify-maint] post_size={post_size:,} delta={post_size-pre_size:+,}")
    finally:
        con.close()
    return 0


def _get_meta(con: sqlite3.Connection, key: str):
    row = con.execute("SELECT value FROM schema_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def _set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


if __name__ == "__main__":
    sys.exit(main())
