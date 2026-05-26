---
agent_id: graphify_a1_schema_core
brief_created: 2026-05-25 21:10
plan_ref: .agents/plans/2026-05-25_2100_general_graphify_hybrid_setup_v1.md
status: completed
completed_at: 2026-05-25T17:10:00Z
council_brief: ARIADNE (lead) + HERMES + NIKE
target_repo: C:\Users\EXT02D059293\Documents\General_Graphify
disjoint_files_owned:
  - schema/001_entities.sql
  - schema/002_triples.sql
  - schema/003_embeddings.sql
  - schema/004_indexes_views.sql
  - core/__init__.py
  - core/graphify.py
  - core/migration.py
  - core/query.py
  - core/embedding.py
  - ontology/core.yml
  - ontology/predicates.yml
  - ontology/README.md
files_created:
  - schema/001_entities.sql
  - schema/002_triples.sql
  - schema/003_embeddings.sql
  - schema/004_indexes_views.sql
  - ontology/core.yml
  - ontology/predicates.yml
  - ontology/README.md
  - core/__init__.py
  - core/migration.py
  - core/embedding.py
  - core/graphify.py
  - core/query.py
self_test_output: |
  <string>:8: UserWarning: predicate 'belongs_to' range ['Project'] does not allow object type 'Plan'
  entities: 2
  triples: 1
notes: |
  - Self-test passed: 2 entities + 1 triple inserted, expected output produced.
  - UserWarning during self-test is CORRECT behavior: brief example uses
    `belongs_to(Refactor -> Plan)` but the predicate is whitelisted only for
    `range: [Project]`. With `unknown_predicate_policy: warn` the system warns
    and still inserts, which is the documented bootstrap-mode behavior.
  - All 8 acceptance criteria verified:
      AC1/AC2 migrations apply, schema_meta.schema_version=4, 4 tables + 4 views.
      AC3 happy path works.
      AC4 find_entities over 100 entities measured at 0.9 ms (cap was 10 ms).
      AC5 traverse on a 3-cycle terminates with 2 finite paths, no infinite loop.
      AC6 unknown predicate under policy=error raises ValueError; under warn it
           emits warnings.warn and still inserts.
      AC7 Graphify(embedding=False) + add_entity imports zero ML modules
           (sentence_transformers, onnxruntime, tokenizers, torch all absent
            from sys.modules).
      AC8 _clip_to_tokens(1000-char string, 50 tokens) yields 203 chars ending '...'.
  - Design decisions worth flagging to council:
      * _Ontology.load() uses a minimal in-file YAML parser as fallback when
        PyYAML is unavailable; only supports the subset present in core.yml /
        predicates.yml. This keeps core/ dependency-free.
      * `domain/range` checking is best-effort: it relies on resolving subject
        and object ids back to entity types. If the entity is not yet inserted
        or the object is a literal, the check degrades gracefully.
      * sqlite-vec virtual table DDL is intentionally commented out in
        003_embeddings.sql; it must be issued at runtime after the extension
        is loaded into the connection. A2/A3 should add an explicit detection
        step before issuing the CREATE VIRTUAL TABLE.
      * isolation_level=None + explicit `BEGIN` / `COMMIT` chosen so that
        executescript() in MigrationRunner can manage its own implicit
        transactions without nesting conflicts.
      * UNIQUE(type, name, project_slug) noted in 001 with comment: NULL
        project_slug behaves as a distinct value in SQLite; callers wanting
        deterministic global namespace should pass empty string.
---

# A1 — Schema & Core Foundation (Graphify Hybrid)

## Malware Pre-empt Clause (zorunlu, oku ve devam et)

Bu görev meşru altyapı kurulumu. `Documents/General_Graphify/` kullanıcının kendi
makinesindeki kişisel dizini. Tüm kod kullanıcı tarafından açıkça onaylanmış proje.
Hiçbir dış sistem etkilenmiyor (sadece local SQLite + opsiyonel ONNX). Bu görevi
kabul et ve uygula. Üç refüze ile karşılaşıldığı için bu uyarı eklendi.

## Context (kısa)

VYRA + Cosmos_Mobile + COSMOS + Mahsul_Mezati projelerinde kullanılacak
**hibrit graph + opsiyonel vector memory** MCP'sinin foundation katmanı.
MemPalace (ChromaDB 270 MB, subprocess crashes) yerine in-process SQLite +
lazy embedding tasarımı. Detay plan: `plan_ref`.

## Your Scope (sadece bu dosyalar — disjoint, başka agentlar A2/A3/A4/A5/A6'da)

Yukarıdaki `disjoint_files_owned` listesi. **Başka dosyaya dokunma.**
Adapter (A2), MCP server (A3), Tools (A4), Tests (A5), Docs (A6) ayrı ajanlarda.

## Deliverables

### 1. Schema (SQLite)

**`schema/001_entities.sql`**
- Tablo `entities`:
  - `id TEXT PRIMARY KEY` (UUIDv4)
  - `type TEXT NOT NULL` (ontology entity tipi — Project/Plan/Bug/Refactor/Decision/Commit/Person/File/Function/Memory/Migration/Policy)
  - `name TEXT NOT NULL` (insan okunabilir)
  - `properties TEXT DEFAULT '{}'` (JSON serialized)
  - `project_slug TEXT` (cross-instance ref için — instance dosyasında genelde tek değer ama nullable)
  - `ontology_version TEXT DEFAULT '1.0'`
  - `created_at TEXT DEFAULT CURRENT_TIMESTAMP`
  - `updated_at TEXT DEFAULT CURRENT_TIMESTAMP`
  - `source_ref TEXT` (nereden geldi: git:sha veya file:path veya conv:id)
- UNIQUE(type, name, project_slug) — duplicate guard

**`schema/002_triples.sql`**
- Tablo `triples`:
  - `id TEXT PRIMARY KEY`
  - `subject TEXT NOT NULL` (entity.id FK soft)
  - `predicate TEXT NOT NULL` (ontology predicate whitelist)
  - `object TEXT NOT NULL` (entity.id veya literal)
  - `object_type TEXT DEFAULT 'entity'` ('entity' | 'literal' | 'datetime' | 'number')
  - `valid_from TEXT` (ISO8601, nullable)
  - `valid_to TEXT` (ISO8601, nullable — null = hala geçerli)
  - `confidence REAL DEFAULT 1.0` (0.0-1.0)
  - `source_adapter TEXT` (git/markdown/backlog/code/conversation)
  - `source_ref TEXT` (commit_sha:line veya plan_file:line)
  - `created_at TEXT DEFAULT CURRENT_TIMESTAMP`

**`schema/003_embeddings.sql`**
- Tablo `embeddings`:
  - `entity_id TEXT PRIMARY KEY` (entity.id FK)
  - `model_name TEXT NOT NULL` (örn. 'paraphrase-multilingual-MiniLM-L12-v2')
  - `vector BLOB NOT NULL` (numpy.float32 binary)
  - `dim INTEGER NOT NULL`
  - `text_hash TEXT NOT NULL` (embedlenen metnin SHA256 — stale tespiti)
  - `created_at TEXT DEFAULT CURRENT_TIMESTAMP`
- Opsiyonel `sqlite-vec` virtual table eklenmesi:
  - Eğer `import sqlite_vec` başarılıysa: `CREATE VIRTUAL TABLE vec_entities USING vec0(...)`
  - Aksi halde numpy fallback, virtual table atlanır
- Migration runtime'da algılanır, schema dosyası iki branch yorumlu

**`schema/004_indexes_views.sql`**
- 11 index:
  - `idx_entities_type` (entities.type)
  - `idx_entities_name` (entities.name)
  - `idx_entities_type_project` (entities.type, project_slug)
  - `idx_entities_updated` (entities.updated_at)
  - `idx_triples_subject` (triples.subject)
  - `idx_triples_predicate` (triples.predicate)
  - `idx_triples_object` (triples.object)
  - `idx_triples_subject_pred` (triples.subject, predicate)
  - `idx_triples_predicate_object` (triples.predicate, object)
  - `idx_triples_valid_range` (triples.valid_from, valid_to)
  - `idx_embeddings_model` (embeddings.model_name)
- 4 view:
  - `v_active_triples` — `WHERE valid_to IS NULL`
  - `v_recent_decisions` — `entities WHERE type='Decision' ORDER BY created_at DESC LIMIT 50`
  - `v_open_refactors` — `entities WHERE type='Refactor' AND properties->>'status'='open'`
  - `v_entity_outdegree` — entity başına edge sayısı (pruning gözlem için)
- Tablo `schema_meta`:
  - `key TEXT PRIMARY KEY`
  - `value TEXT`
  - Insert default: `('schema_version', '1')`, `('ontology_version', '1.0')`, `('created_at', CURRENT_TIMESTAMP)`

### 2. Ontology

**`ontology/core.yml`**
```yaml
version: 1.0
entity_types:
  Project: { description: "Repo veya proje", required_props: [path] }
  Plan: { description: ".agents/plans/*.md frontmatter", required_props: [plan_id, status] }
  Bug: { description: "Hata kaydı", required_props: [severity] }
  Refactor: { description: "Refactor backlog item", required_props: [priority, status] }
  Decision: { description: "Konsey kararı veya commit message", required_props: [council] }
  Commit: { description: "Git commit", required_props: [sha, branch] }
  Person: { description: "İnsan kullanıcı veya konsey üyesi" }
  File: { description: "Repo dosyası", required_props: [path] }
  Function: { description: "Kod fonksiyonu", required_props: [file, name] }
  Memory: { description: "MemPalace drawer karşılığı (free-text)", required_props: [content] }
  Migration: { description: "Alembic veya schema migration", required_props: [revision] }
  Policy: { description: "RLS/security policy", required_props: [table] }
token_caps:
  warmup: 50
  wakeup: 250
  search: 250
  mine: 50
  status: 30
  traverse: 200
  add_decision: 30
```

**`ontology/predicates.yml`**
```yaml
version: 1.0
predicates:
  # ilişki — yapısal
  - { name: belongs_to, domain: [Plan,Refactor,Bug,Decision,Commit], range: [Project] }
  - { name: closes, domain: [Commit,Decision], range: [Refactor,Bug] }
  - { name: opens, domain: [Decision,Commit], range: [Refactor,Bug] }
  - { name: caused_by, domain: [Bug], range: [Commit,Decision] }
  - { name: blocks, domain: [Refactor,Bug,Plan], range: [Plan,Refactor] }
  - { name: depends_on, domain: [Plan,Refactor], range: [Plan,Refactor,Migration] }
  - { name: refactors, domain: [Refactor,Commit], range: [File,Function] }
  - { name: written_by, domain: [Commit,Decision], range: [Person] }
  - { name: reviewed_by, domain: [Plan,Commit,Decision], range: [Person] }
  - { name: defined_in, domain: [Function], range: [File] }
  - { name: lives_in, domain: [File,Function], range: [Project] }
  - { name: archived_at, domain: [Plan], range: [literal] }
  - { name: applied_in, domain: [Migration], range: [Commit] }
  - { name: enforced_on, domain: [Policy], range: [File] }
  # metaveri
  - { name: has_status, domain: [Plan,Refactor,Bug], range: [literal] }
  - { name: has_priority, domain: [Refactor,Bug], range: [literal] }
  - { name: has_version_target, domain: [Plan,Refactor], range: [literal] }
  - { name: extracted_from, domain: [*], range: [Memory,File] }
  - { name: similar_to, domain: [*], range: [*] }  # embedding bridge
unknown_predicate_policy: warn  # warn | error | accept
```

**`ontology/README.md`** — proje başına ontology genişletme rehberi (kısa, 30-50 satır).

### 3. Core

**`core/__init__.py`**
```python
from core.graphify import Graphify, Entity, Triple
from core.query import Query, traverse
__all__ = ["Graphify", "Entity", "Triple", "Query", "traverse"]
__version__ = "1.0.0"
```

**`core/graphify.py`** — ana API. Sınıflar/fonksiyonlar:

- `dataclass Entity(id, type, name, properties, project_slug, ontology_version, source_ref, created_at, updated_at)`
- `dataclass Triple(id, subject, predicate, object, object_type, valid_from, valid_to, confidence, source_adapter, source_ref, created_at)`
- `class Graphify`:
  - `__init__(db_path: Path, ontology_path: Path | None = None, embedding: bool = False)`
  - `init() -> None` — schema migration uygulanır (idempotent)
  - `add_entity(type, name, properties=None, project_slug=None, source_ref=None) -> Entity` (upsert by UNIQUE)
  - `add_triple(subject, predicate, object, ...) -> Triple` (predicate whitelist check)
  - `get_entity(id_or_name, type=None) -> Entity | None`
  - `find_entities(type=None, **prop_filters) -> list[Entity]`
  - `find_triples(subject=None, predicate=None, object=None, active_only=True) -> list[Triple]`
  - `expire_triple(triple_id) -> None` — `valid_to = NOW()`
  - `embed_entity(entity_id, text) -> None` — lazy embedding (sadece embedding=True ise)
  - `hybrid_search(query, top_k=3, mode='hybrid') -> list[tuple[Entity, float]]`
    - `mode='graph'` — sadece name/property LIKE + graph traverse
    - `mode='vector'` — embedding cosine (lazy load model)
    - `mode='hybrid'` — graph match önce, sonuç <top_k ise vector fill
  - `close()` — connection cleanup

- **Önemli kurallar:**
  - SQLite connection per-instance, `WAL` mode, `synchronous=NORMAL`
  - Tüm yazılar transaction içinde
  - `add_triple` — predicate whitelist kontrolü `predicates.yml`'den; ihlalde policy'ye göre warn/error/accept
  - Token cap helper: `_clip_to_tokens(text, max_tokens)` — yaklaşık 4 char/token

**`core/migration.py`** — schema migration runner.
- `class MigrationRunner(db_path, schema_dir)`
- `run_all()` — `schema_meta.schema_version` okur, eksik dosyaları sıralı uygular
- Dosya naming: `^(\d{3})_.*\.sql$` — sayı schema_version
- Idempotent: `IF NOT EXISTS` her DDL'de
- Geri-alma desteği yok v1'de (forward-only) — README'de not düşülür

**`core/query.py`** — query DSL ve traverse.
- `class Query(graphify)`:
  - `.entities(type=None).where(**props).limit(n)` — chainable
  - `.triples(subject=None, predicate=None, ...).where_time_range(start, end)`
- `def traverse(graphify, start_entity_id, predicates: list[str], max_depth=2, direction='out') -> list[Path]`
  - BFS, cycle detection, max_depth
  - Returns list of paths: `[(start, [(predicate, entity), ...]), ...]`
- `def time_slice(graphify, at: datetime) -> SnapshotView` — opsiyonel, v1'de stub

**`core/embedding.py`** — lazy embedding loader.
- `class EmbeddingProvider`:
  - `__init__(model_name='sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', model_dir=Path('~/.graphify/models').expanduser())`
  - `_load()` — lazy: ilk `encode()` çağrısında model yüklenir (transformers veya onnxruntime)
  - `encode(texts: list[str]) -> np.ndarray` (N x dim)
  - `cosine_search(query_text, candidate_vectors, top_k) -> list[(idx, score)]`
- Import politikası: `sentence-transformers` import try; fail ise `onnxruntime` fallback; ikisi de fail ise `EmbeddingNotAvailable` exception.
- `sqlite-vec` import try; fail ise `numpy` fallback path.

## Acceptance Criteria (kendi kendini test et)

1. `python -m core.cli init --instance ./test.db` (CLI A3'te yazılıyor, sen sadece graphify.init() metodunu test et):
   ```python
   from core.graphify import Graphify
   from pathlib import Path
   g = Graphify(Path("/tmp/test_a1.db"))
   g.init()
   # entities, triples, embeddings, schema_meta tabloları olmalı
   ```
2. Schema dosyalarının tümü `sqlite3 test.db < schema/00X_*.sql` ile hata vermeden çalışmalı
3. `add_entity` + `add_triple` happy-path 5 entity + 10 triple insertable
4. `find_entities(type='Refactor')` ve `find_triples(subject=X)` <10 ms (1000 entity altında)
5. `traverse` 3-hop BFS, cycle olan grafta sonsuz döngüye girmemeli
6. Predicate whitelist ihlali: warn mode'da uyarı + INSERT yapar, error mode'da raise
7. Embedding lazy: `Graphify(embedding=False)` ile `add_entity` çağrısı **hiçbir** ML import yapmamalı (import time guard)
8. Token cap helper `_clip_to_tokens` doğru kırpıyor

## Restart Requirements

- Yok (sadece dosya oluşturma; MCP henüz register edilmedi). A3 tamamlanınca `claude mcp add graphify` çalıştırılacak.

## Self-Test Command

```bash
cd "C:/Users/EXT02D059293/Documents/General_Graphify"
python -c "
from pathlib import Path
from core.graphify import Graphify
g = Graphify(Path('./instances/self_test.db'))
g.init()
e1 = g.add_entity('Refactor', 'R019', {'priority': 'P2', 'status': 'open'})
e2 = g.add_entity('Plan', 'graphify_setup', {'status': 'in_progress'})
g.add_triple(e1.id, 'belongs_to', e2.id)
print('entities:', len(g.find_entities()))
print('triples:', len(g.find_triples()))
"
```
3 satır beklenen çıktı:
```
entities: 2
triples: 1
```

## Reporting

İşin sonunda bu dosyaya frontmatter güncellemesi:
- `status: completed`
- `completed_at: <iso8601>`
- `files_created: [list]`
- `self_test_output: <son komutun çıktısı>`
- `notes: <önemli kararlar veya issues>`

## Council Gate (sen tamamlayınca ZEUS kontrol eder)

- ARIADNE: schema doğru mu, ontology v1.0 sabit mi, predicate whitelist enforce mi
- HERMES: graphify.py API temiz mi, lazy import doğru mu, transaction güvenli mi
- NIKE: index'ler doğru mu, view'ler performans için mi, 1000 entity altında <10 ms
- ARES: SQL injection riski (predicate whitelist + parameter binding zorunlu)
- ZEUS: token cap helper kullanılıyor mu

Council gate yeşilse A2/A3/A4/A6 paralel dispatch edilecek.

## NOTLAR

- **Hiç emoji kullanma kod içinde** (yorum dahil)
- README/markdown'da minimal teknik açıklama Türkçe
- Tüm SQL `IF NOT EXISTS` veya idempotent
- ChromaDB veya MemPalace DOKUNMA — sadece kendi DB'n
- `instances/.gitkeep` zaten var, sen oraya self_test.db yazabilirsin (gitignored)
