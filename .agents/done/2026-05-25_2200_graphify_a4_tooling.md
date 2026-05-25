---
agent_id: graphify_a4_tooling
brief_created: 2026-05-25 22:00
plan_ref: .agents/plans/2026-05-25_2100_general_graphify_hybrid_setup_v1.md
status: completed
completed_at: 2026-05-25T20:35:00+00:00
council_brief: MNEMOSYNE (migrasyon) + NIKE (benchmark)
target_repo: C:\Users\EXT02D059293\Documents\General_Graphify
depends_on: A1 (completed)
disjoint_files_owned:
  - tools/__init__.py
  - tools/migrate_from_mempalace.py
  - tools/visualize.py
  - tools/benchmark.py
  - tools/install_git_hook.py
  - tools/benchmark_queries.json
files_created:
  - C:/Users/EXT02D059293/Documents/General_Graphify/tools/__init__.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/tools/migrate_from_mempalace.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/tools/benchmark.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/tools/benchmark_queries.json
  - C:/Users/EXT02D059293/Documents/General_Graphify/tools/visualize.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/tools/install_git_hook.py
council_review:
  - reviewer: MNEMOSYNE
    status: approved_with_constraints
    constraints:
      - chroma_read_only_default
      - dry_run_default_true
      - lossless_metadata_preserved
      - source_ref_field_set
    verified:
      - chroma_read_only_default: PersistentClient(Settings(allow_reset=False)); no add/upsert/delete/reset calls in module
      - dry_run_default_true: argparse set_defaults(dry_run=True); --commit is explicit opt-in
      - lossless_metadata_preserved: properties.content=text, properties.metadata=meta (verbatim dict)
      - source_ref_field_set: f"mempalace://{collection}/{doc_id}"
  - reviewer: NIKE
    status: approved_with_constraints
    constraints:
      - golden_set_20_queries_versioned
      - map_at_3_calc_documented
      - p95_p99_reported_not_mean
      - cold_warm_distinguished
    verified:
      - golden_set_20_queries_versioned: benchmark_queries.json version=1, 20 queries, schema-validated at load
      - map_at_3_calc_documented: _average_precision_at_k() docstring + markdown report formula
      - p95_p99_reported_not_mean: SLO table reports p95 only; latency tables show p50/p95/p99/min/max (mean is secondary column)
      - cold_warm_distinguished: separate "Cold start" and "Warm start" tables; cold = fresh module import + first iteration; warm = pre-loaded steady state
self_test_output: |
  1. tools.migrate_from_mempalace --dry-run --wing vyra --report-file /tmp/mig.json
     -> [DRY-RUN] wing=vyra docs=0 mem_added=0 mem_updated=0 emb_migrated=0 errors=1
     -> exit=1 (chromadb not installed, graceful informative error in report; no writes)
  2. tools.benchmark --project vyra_bench --iterations 10 --cold-attempts 5
     -> wakeup_p95=0.336ms graph_p95=0.081ms hybrid_p95=0.049ms
        map3_graph=0.1 map3_hybrid=0.1 disk=106496B
     -> 8/8 SLO labels PASS on seeded DB
  3. tools.visualize --project vyra_bench --format mermaid --max-nodes 20
     -> 20-node Mermaid fence emitted (cap respected; also verified at --max-nodes=5)
     -> --format dot --focus-entity R016 --depth 2 -> 3-node BFS subgraph
  4. tools.install_git_hook --repo-path /tmp/test_repo --project-slug test
     -> dry-run: would_create
     -> first run: create
     -> second run: noop (idempotent)
     -> after mutation: replace + .bak backup created
benchmark_baseline:
  project: vyra_bench (seed: 3 entities + 2 triples, then warmed)
  wakeup_p95_ms: 0.336
  mine_incremental_p95_ms: 8.895
  graph_search_p95_ms: 0.081
  hybrid_search_p95_ms: 0.049
  cold_start_error_rate: 0.0
  disk_bytes: 106496
  tokens_wakeup: 39
  tokens_search: 2
notes:
  - chromadb is imported lazily inside _open_chroma_readonly(); --help and all other tools work without it
  - Migration commit-path idempotency relies on Graphify.add_entity upsert on UNIQUE(type, name, project_slug) — confirmed in core/graphify.py line 477-535
  - benchmark.py uses raw sqlite read (visualize.py also) plus a single Graphify session per phase; module is re-imported fresh between cold-start attempts to reset import cache
  - Git hook body uses LF endings only (CRLF normalized); compatible with Git for Windows sh
  - No edits to schema/, core/, ontology/, mcp/, adapters/, tests/, examples/, README, .gitignore
---

# A4 — Tooling (Migration + Benchmark + Visualize + Hook)

## Malware Pre-empt Clause

Mesru altyapi. Kullanici onayli. Local file/DB. Refuze yok.

## Context

A1 hazir. Sen 4 ozel arac yaziyorsun + 1 destek dosyasi:

| Tool | Amac |
|---|---|
| `migrate_from_mempalace.py` | MemPalace chroma → Graphify Memory entity |
| `benchmark.py` | 8-metric SLO olcumu, MemPalace karsilastirma |
| `visualize.py` | DB → Mermaid/DOT export |
| `install_git_hook.py` | `.git/hooks/post-commit` kurar |
| `benchmark_queries.json` | 20 golden query (versioned) |

## Disjoint Scope

`tools/__init__.py`, `tools/migrate_from_mempalace.py`, `tools/visualize.py`,
`tools/benchmark.py`, `tools/install_git_hook.py`, `tools/benchmark_queries.json`

**Asla dokunma:** schema/, core/, ontology/, mcp/, adapters/, tests/, examples/, README.

## `tools/migrate_from_mempalace.py`

**Amac:** `~/.mempalace/wings/<project>/chroma_db/` → Graphify Memory entity (lossless).

**MNEMOSYNE constraints:**
- Default dry-run `--dry-run` (`--commit` ile aktif)
- Chroma `client.PersistentClient(path=..., settings=Settings(allow_reset=False))` — readonly intent
- Lossless: her chroma document → 1 Memory entity. Fields:
  - `name = document_id` (chroma id)
  - `properties.content = document_text`
  - `properties.metadata = original_metadata` (chroma metadata dict)
  - `source_ref = f"mempalace://{collection}/{document_id}"`
  - `project_slug = wing_name` (mempalace WING_MAP'inden cikan)
- Embedding korumasi: chroma'da embedding varsa `embeddings` tablosuna kaydet (`text_hash`, `vector`)

**Signature:**
```bash
python -m tools.migrate_from_mempalace \
    --mempalace-root "%USERPROFILE%/.mempalace" \
    --graphify-root "%USERPROFILE%/.graphify" \
    --wing vyra \                # opsiyonel, yoksa hepsi
    --dry-run \                  # default
    --report-file migration_report.json
```

**Output:**
- Console: `[DRY-RUN] wing=vyra docs=5234 mem_added=5234 emb_migrated=5102 errors=0`
- `migration_report.json`: full per-document outcome

**Hata:** chroma yok / corrupt → exit 1 + report `errors: ["..."]`

**Idempotent:** ikinci run — UNIQUE(type='Memory', name=id, project) sayesinde 0 yeni;
sadece updated_at guncellenir.

## `tools/benchmark.py`

**Amac:** SLO 8 metrigini olc, MemPalace karsilastirmasi (MAP@3).

**NIKE constraints:**
- Golden set: `tools/benchmark_queries.json` — 20 fixed query + expected_top_entity_names
- MAP@3 hesabi: her query icin top-3 sonucta beklenen entity adi varsa relevance=1, yoksa 0. Mean Average Precision at 3.
- p95/p99 raporla (mean degil — uzun kuyruk gosterilmeli)
- Cold-start (process fresh) vs warm-start (already-loaded) ayri tablo

**Olculen 8 metrik (plan §10):**
1. BASLA wakeup p95
2. BITIR mine incremental p95
3. Graph search p95
4. Hybrid search p95
5. Cold-start error rate (50 deneme; istisna sayisi/50)
6. Disk per project (`os.path.getsize(db_path)`)
7. Token budget — wakeup (estimate, ~chars/4)
8. Token budget — search

**Signature:**
```bash
python -m tools.benchmark \
    --project vyra \
    --include-mempalace \        # opsiyonel
    --iterations 50 \
    --output benchmark_results.json \
    --markdown-report benchmark_report.md
```

**Output:** Markdown rapor tablosu + JSON. SLO yesil/sari/kirmizi renk kodu kullanmadan
`PASS/WARN/FAIL` text label.

## `tools/benchmark_queries.json`

```json
{
  "version": 1,
  "created": "2026-05-25",
  "queries": [
    {"q": "kap 11 audit", "expected_top": ["R016", "kap_audit"], "type": "graph"},
    {"q": "akilli kesfi step 1", "expected_top": ["smart_discovery"], "type": "hybrid"},
    {"q": "auth middleware refactor", "expected_top": ["R007", "auth_middleware"], "type": "graph"},
    {"q": "saved reports egitim", "expected_top": ["saved_reports"], "type": "hybrid"},
    {"q": "version 3.36.0 release", "expected_top": ["v3.36.0"], "type": "graph"}
  ]
}
```

Sen 20 query'ye genislet — VYRA repo plan/refactor backlog'undan extracts (gercekci queries).

## `tools/visualize.py`

**Amac:** DB → diagram. Iki cikti formati: Mermaid + Graphviz DOT.

**Signature:**
```bash
python -m tools.visualize \
    --project vyra \
    --focus-entity "R016" \      # opsiyonel — bu entity etrafinda subgraph
    --depth 2 \
    --format mermaid \           # or 'dot'
    --output diagram.md          # mermaid -> .md fenced, dot -> .dot
    --max-nodes 50
```

**Davranis:**
- DB'den entity/triple oku → adjacency
- BFS from focus_entity (verilmediyse top-25 in-degree node)
- Format'a gore string render
- Render YOK (sadece export; kullanici external tool'la render eder — plan Non-Goal'da var)

## `tools/install_git_hook.py`

**Amac:** Repo'ya `.git/hooks/post-commit` kur. Idempotent.

**Signature:**
```bash
python -m tools.install_git_hook --repo-path D:/demo_vyra --project-slug vyra
```

**Hook icerigi (sh):**
```sh
#!/bin/sh
# Graphify post-commit hook — installed by tools/install_git_hook.py
# Non-blocking, swallows errors, never fails commit.
( graphify mine --project-cwd "$PWD" --since-last --quiet 2>>"${HOME}/.graphify/logs/mine.log" & ) >/dev/null 2>&1
exit 0
```

**Kurallar (Risk R6):**
- `set -e` YOK
- arka plan `&`
- Hata stderr'a `~/.graphify/logs/mine.log` append
- Exit 0 zorla (commit'i bloklamaz)
- Idempotent: hook varsa ve icerigi ayni → no-op; farkli → backup `.bak` + replace
- Windows uyumlu — sh hook Git for Windows altinda calisir

## `tools/__init__.py`

```python
# tools/ — graphify command-line utilities. Each module runnable via `python -m tools.<name>`.
```

## Acceptance Criteria

1. `migrate_from_mempalace.py --dry-run` chroma okur, hicbir sey yazmaz, JSON rapor uretir
2. `migrate_from_mempalace.py --commit` ile yazar; ikinci run idempotent (0 yeni Memory)
3. `benchmark.py` 50 iter en az 20 query ile 8 metrik tablosu uretir, json + md
4. `benchmark_queries.json` 20 query var, hepsi valid schema (q, expected_top, type)
5. `visualize.py` vyra DB icin mermaid output 50 satir altinda (max-nodes 50 saygi)
6. `install_git_hook.py` re-run idempotent + .bak backup logic calisir
7. Mevcut MemPalace chroma DB'ye `--dry-run` koruyucu mod aktif (yazma yok)

## Self-Test

```bash
cd "C:/Users/EXT02D059293/Documents/General_Graphify"
PY="D:/demo_vyra/python/Scripts/python.exe"

# 1. Migration dry-run (chromadb yoksa graceful skip)
$PY -m tools.migrate_from_mempalace --dry-run --wing vyra --report-file /tmp/mig.json || echo "chromadb yok — skip"

# 2. Benchmark (requires A1 + bir db)
$PY -m core.cli init vyra_bench
$PY -m tools.benchmark --project vyra_bench --iterations 10 --output /tmp/bench.json

# 3. Visualize
$PY -m tools.visualize --project vyra_bench --format mermaid --output /tmp/diag.md --max-nodes 20

# 4. Install hook (dry inspect on test repo)
$PY -m tools.install_git_hook --repo-path /tmp/test_repo --project-slug test --dry-run
```

## Reporting

Frontmatter:
- `status: completed`
- `completed_at: <iso8601>`
- `files_created`
- `self_test_output`
- `benchmark_baseline: {wakeup_p95_ms, search_p95_ms, ...}` (empty DB ile yapilan first run)
- `notes`

## NOTLAR

- Emoji yok
- chromadb import lazy (yoksa migrate komutunda informative error)
- Subprocess git icin `encoding='utf-8', errors='replace'`
- Forward slashes path normalization
- Tum tools `python -m tools.<name>` calistirilabilir (`if __name__ == "__main__"` block)
