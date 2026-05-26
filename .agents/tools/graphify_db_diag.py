"""Graphify SQLite DB diagnostic + bench harness.

Read-only by default. Writes only with --apply flag.
"""
from __future__ import annotations
import argparse, os, sqlite3, time, json
from pathlib import Path

DB = Path(os.path.expanduser("~/.graphify/instances/vyra.db"))


def _open(readonly: bool = True) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{DB.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=5.0)
    else:
        con = sqlite3.connect(str(DB), timeout=30.0, isolation_level=None)
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
    con.row_factory = sqlite3.Row
    return con


def _bench(con: sqlite3.Connection, n_iter: int = 5):
    """Run representative queries that mimic MCP graphify_search/traverse."""
    queries = [
        # name 1: _graph_match LIKE pattern (most common)
        ("graph_match_like", '''
            SELECT * FROM entities
            WHERE name LIKE ? OR properties LIKE ?
            ORDER BY updated_at DESC LIMIT 10
        ''', ('%search%', '%search%')),
        # name 2: vector_match - load all vectors
        ("vector_load_all", '''
            SELECT entity_id, vector, dim FROM embeddings
        ''', ()),
        # name 3: find_triples by subject (traverse step)
        ("triples_by_subject", '''
            SELECT * FROM triples WHERE subject = ? AND valid_to IS NULL
            ORDER BY created_at DESC
        ''', None),  # subject filled later
        # name 4: find_entities with json prop filter (open refactors)
        ("entities_status_open", '''
            SELECT * FROM entities
            WHERE type = ? AND json_extract(properties, ?) = ?
            ORDER BY updated_at DESC
        ''', ('Refactor', '$.status', 'open')),
        # name 5: get_entity by id (per-row lookup in traverse)
        ("get_entity_by_id", "SELECT * FROM entities WHERE id = ?", None),
        # name 6: predicates filter — calls predicate (heaviest)
        ("triples_calls_predicate", '''
            SELECT * FROM triples WHERE predicate = ? AND valid_to IS NULL
            LIMIT 100
        ''', ('calls',)),
    ]

    # Pick a real subject id for #3 and #5
    subj_row = con.execute(
        "SELECT id FROM entities WHERE type='Function' ORDER BY RANDOM() LIMIT 1"
    ).fetchone()
    subj_id = subj_row["id"] if subj_row else None

    results = []
    for name, sql, p in queries:
        params = p
        if params is None:
            params = (subj_id,)
        # warmup
        try:
            con.execute(sql, params).fetchall()
        except Exception as e:
            results.append((name, None, str(e)))
            continue
        ts = []
        for _ in range(n_iter):
            t0 = time.perf_counter()
            con.execute(sql, params).fetchall()
            ts.append((time.perf_counter() - t0) * 1000)
        ts.sort()
        median = ts[len(ts) // 2]
        results.append((name, median, ts))
    return results


def _explain(con: sqlite3.Connection):
    plans = []
    targets = [
        ('graph_match_like',
         "SELECT * FROM entities WHERE name LIKE '%x%' OR properties LIKE '%x%' "
         "ORDER BY updated_at DESC LIMIT 10"),
        ('triples_by_subject',
         "SELECT * FROM triples WHERE subject = 'X' AND valid_to IS NULL "
         "ORDER BY created_at DESC"),
        ('json_status_open',
         "SELECT * FROM entities WHERE type='Refactor' "
         "AND json_extract(properties,'$.status')='open' ORDER BY updated_at DESC"),
        ('triples_predicate',
         "SELECT * FROM triples WHERE predicate='calls' AND valid_to IS NULL LIMIT 100"),
        ('vector_load',
         "SELECT entity_id, vector, dim FROM embeddings"),
    ]
    for label, sql in targets:
        rows = con.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
        plans.append((label, [dict(r) for r in rows]))
    return plans


def _maintenance(con: sqlite3.Connection):
    """Apply DB-level maintenance: ANALYZE, REINDEX, optimize, WAL checkpoint, VACUUM."""
    actions = []
    # Pre-size
    pre_size = DB.stat().st_size
    actions.append(("pre_size_bytes", pre_size))

    # 1. ANALYZE - populate sqlite_stat1
    t0 = time.perf_counter()
    con.execute("ANALYZE")
    actions.append(("ANALYZE_ms", round((time.perf_counter() - t0) * 1000, 1)))

    # 2. PRAGMA optimize (modern; uses analysis_limit by default)
    t0 = time.perf_counter()
    con.execute("PRAGMA optimize")
    actions.append(("PRAGMA_optimize_ms", round((time.perf_counter() - t0) * 1000, 1)))

    # 3. REINDEX - rebuild indexes (defragments btrees)
    t0 = time.perf_counter()
    con.execute("REINDEX")
    actions.append(("REINDEX_ms", round((time.perf_counter() - t0) * 1000, 1)))

    # 4. WAL checkpoint TRUNCATE - reset WAL
    t0 = time.perf_counter()
    res = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    actions.append(("wal_checkpoint_ms", round((time.perf_counter() - t0) * 1000, 1)))
    actions.append(("wal_checkpoint_result", tuple(res) if res else None))

    # 5. VACUUM - defragment + reclaim free pages
    t0 = time.perf_counter()
    con.execute("VACUUM")
    actions.append(("VACUUM_ms", round((time.perf_counter() - t0) * 1000, 1)))

    post_size = DB.stat().st_size
    actions.append(("post_size_bytes", post_size))
    actions.append(("size_delta_bytes", post_size - pre_size))
    return actions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", action="store_true")
    ap.add_argument("--explain", action="store_true")
    ap.add_argument("--maintenance", action="store_true",
                    help="Apply ANALYZE/REINDEX/VACUUM (writes!)")
    ap.add_argument("--iter", type=int, default=5)
    args = ap.parse_args()

    if args.maintenance:
        con = _open(readonly=False)
        actions = _maintenance(con)
        con.close()
        print("===== MAINTENANCE =====")
        for k, v in actions:
            print(f"  {k:30s} = {v}")
        return

    con = _open(readonly=True)
    if args.bench:
        print("===== BENCH =====")
        res = _bench(con, args.iter)
        for name, median, raw in res:
            if median is None:
                print(f"  {name:30s} ERROR: {raw}")
            else:
                print(f"  {name:30s} median={median:8.2f}ms  samples={[round(x,2) for x in raw]}")
    if args.explain:
        print()
        print("===== EXPLAIN QUERY PLAN =====")
        plans = _explain(con)
        for label, rows in plans:
            print(f"\n[{label}]")
            for r in rows:
                print(f"  id={r.get('id')} parent={r.get('parent')} detail={r.get('detail')}")
    con.close()


if __name__ == "__main__":
    main()
