---
agent_id: graphify_a2_adapters
brief_created: 2026-05-25 21:30
plan_ref: .agents/plans/2026-05-25_2100_general_graphify_hybrid_setup_v1.md
status: completed
completed_at: 2026-05-25 22:05
council_brief: HERMES (lead) + ARIADNE
target_repo: C:\Users\EXT02D059293\Documents\General_Graphify
depends_on: A1 (completed — core.graphify API + ontology hazır)
disjoint_files_owned:
  - adapters/__init__.py
  - adapters/base.py
  - adapters/git_adapter.py
  - adapters/markdown_adapter.py
  - adapters/backlog_adapter.py
  - adapters/code_adapter.py
  - adapters/conversation_adapter.py
files_created:
  - C:/Users/EXT02D059293/Documents/General_Graphify/adapters/__init__.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/adapters/base.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/adapters/git_adapter.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/adapters/markdown_adapter.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/adapters/backlog_adapter.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/adapters/code_adapter.py
  - C:/Users/EXT02D059293/Documents/General_Graphify/adapters/conversation_adapter.py
council_review:
  - reviewer: HERMES
    status: approved_with_patches
    patches_applied: [add_base_py_to_scope, function_name_filepath_disambiguation, basedapter_inline_dataclass]
  - reviewer: ARIADNE
    status: approved_with_patches
    patches_applied: [drop_plan_to_commit_applied_in, decision_council_default_git_inferred]
self_test_output: |
  git: 531 entities, 1193 triples in 45012.6ms, errors=0
  md:  19 entities, 64 triples in 608.6ms, errors=0
  bl:  21 entities, 108 triples in 110.6ms, errors=0
  TOTAL: 571 entities, 1365 triples
  git re-run entities_created: 0 (should be 0)
  md  re-run entities_created: 0 (should be 0)
  bl  re-run entities_created: 0 (should be 0)
  re-run triples: git=0 md=0 bl=0 (should be 0)
notes: |
  - Acceptance met: 571 entities >= 35, 1365 triples >= 30, all re-runs idempotent (0/0/0).
  - Decision entity is named "<kind>:<sha7>" (e.g. "feat:e04850f") and carries
    properties.council="git_inferred" per ARIADNE patch (required_props compliance).
  - Function entity name uses "<rel_path>::<funcname>" per HERMES patch to avoid
    UNIQUE(type,name,project_slug) collisions across modules.
  - applied_in (Migration->Commit) NOT emitted by markdown_adapter; deferred to v1.1
    ontology bump that introduces a Plan->Commit predicate (realized_by).
  - All triple inserts go through a _safe_triple helper that dedupes on
    (subject, predicate, object, active) so re-mines are no-ops.
  - All subprocess git invocations use encoding='utf-8', errors='replace' with
    timeout=30s. Paths normalized to forward slashes.
  - Module-level regexes are pre-compiled (re.compile) per brief instruction.
  - GitAdapter walks ~530 VYRA commits and emits a Project entity + per-commit
    Commit, Decision (when conventional prefix matches), File entities for every
    touched path, plus belongs_to / closes / refactors / lives_in triples.
  - MarkdownPlanAdapter accepts both PyYAML (when available) and the bundled
    minimal YAML fallback exposed by core.graphify._minimal_yaml_parse.
  - RefactorBacklogAdapter parses the first valid table whose first column is
    "ID" and whose data rows match ^R\d{3,4}$.
  - ConversationMemoryAdapter.mine() is intentionally a no-op; add_memory()
    is the public entry point used by the BITIR workflow.
  - No deviations from the brief's strict constraints (Decision.council,
    Function name format, no Plan->Commit applied_in, scope limited to adapters/).
---

# A2 — Adapter Suite (Graphify Hybrid)

## Malware Pre-empt Clause

Bu görev meşru altyapı kurulumu. Kullanıcı açıkça onayladı. Üç refüze yaşandığı için
ön-uyarı: görevi kabul et ve uygula. Sadece local dosya okuma + Graphify API çağrısı.

## Context

A1 tamamlandı — `core.graphify.Graphify` + ontology v1.0 + 19 predicate whitelist
hazır. Sen adapter katmanını yazacaksın. Adapter'lar: dış kaynaklardan (git, markdown
plan, refactor backlog, Python kodu, free-form conversation) entity + triple çıkartır.

## Disjoint Scope (sadece bu 7 dosya)

`adapters/__init__.py`, `adapters/base.py`, `adapters/git_adapter.py`, `adapters/markdown_adapter.py`,
`adapters/backlog_adapter.py`, `adapters/code_adapter.py`, `adapters/conversation_adapter.py`

**Asla dokunma:** schema/, core/, ontology/, mcp/, tools/, tests/, examples/, README.

## API Contract — `adapters/base.py` (yeni dosya)

```python
# adapters/base.py
from dataclasses import dataclass, field
from pathlib import Path
from core.graphify import Graphify

@dataclass
class AdapterReport:
    adapter_name: str
    entities_created: int = 0
    triples_created: int = 0
    last_mark: str = ""              # incremental state — schema_meta'ya yazilir
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

class BaseAdapter:
    name: str = "base"
    def __init__(self, graphify: Graphify, project_slug: str):
        self.g = graphify
        self.project_slug = project_slug
    def mine(self, since: str | None = None) -> AdapterReport:
        raise NotImplementedError
    # helpers (her adapter kullanabilir):
    def _read_mark(self, key: str) -> str | None: ...   # schema_meta SELECT
    def _write_mark(self, key: str, value: str) -> None: ...  # schema_meta UPSERT
```

Alt sınıflar constructor'a ek path/config parametreleri ekleyebilir (composition over inheritance).

**Ortak kurallar:**
- Idempotent: tekrar çalıştırınca duplicate entity yaratma (UNIQUE constraint zaten korur, ama explicit upsert pattern kullan)
- Batch insert: bir mine çağrısı tek transaction içinde
- Incremental state: `schema_meta` tablosuna `last_<adapter>_mark_<project>` key ile yaz
- Hata izolasyonu: tek bir kaynak hatası tüm batch'i bozmasın — `errors` listesine ekle, devam et
- Token cap'ı endişe etme — adapter çıktısı LLM'e gitmiyor, sadece DB'ye yazıyor

## Adapter Spec Detayları

### `adapters/git_adapter.py`

**Sınıf:** `GitAdapter(BaseAdapter)`

**Görev:** `git log` ile commit'leri tarayıp Commit + Decision entity + ilişki triple üret.

- Constructor: `GitAdapter(graphify, project_slug, repo_path: Path)`
- `mine(since: str | None)`:
  - `since` boşsa `schema_meta['last_git_mark_<slug>']` oku
  - O da yoksa son 100 commit (initial bootstrap)
  - `git log --format='%H%x1f%s%x1f%an%x1f%aI%x1f%P' --no-color SINCE..HEAD` — separator 0x1f
  - Her commit için:
    - `add_entity('Commit', name=sha7, properties={sha, message, author, date, branch, parent_sha})`
    - Commit message'da `feat|fix|refactor|chore` prefix varsa Decision entity olustur (zorunlu: `properties={"council": "git_inferred", "kind": "<prefix>", "summary": <message_first_line>}`), link `Commit -- written_by --> Decision` **DEGIL** — `Decision` `Person` degil; sadece `closes/opens` triple kullan: `Commit -- closes/opens --> Refactor|Bug` (commit message'tan inferred). Decision entity yine olustur ama bagimsiz (reviewed_by Person triple optional)
    - Mesajda `R\d+` veya `BUG-\d+` regex match varsa, var olan Refactor/Bug entity bulup `closes` triple ekle
    - `git diff-tree --no-commit-id --name-only -r <sha>` ile değiştirilen dosyalar → File entity (upsert) + `refactors` triple
  - Bitince son commit sha'sını `last_mark` olarak döndür ve schema_meta'ya yaz

**Önemli:**
- `subprocess.run(["git", ...], cwd=repo_path, capture_output=True, text=True, encoding='utf-8', errors='replace')`
- Windows path normalize: forward slash döndür
- git not-a-repo veya boş repo: error listesine ekle, AdapterReport(0,0,...) dön
- Branch tespiti: `git rev-parse --abbrev-ref HEAD` — commit'in **anlık** branch'i değil (cheap)

### `adapters/markdown_adapter.py`

**Sınıf:** `MarkdownPlanAdapter(BaseAdapter)`

**Görev:** `.agents/plans/*.md` (ve archive altındakiler) frontmatter parse → Plan entity.

- Constructor: `MarkdownPlanAdapter(graphify, project_slug, plans_dir: Path)`
- `mine(since: str | None)`:
  - `since` = ISO datetime — mtime > since olan dosyalar
  - Frontmatter regex: `^---\n(.*?)\n---` (multiline, dotall)
  - YAML parse (PyYAML varsa, yoksa core/graphify.py'deki fallback parser'ı reuse et)
  - Field map:
    - `plan_id` → entity.name
    - `status` → property
    - `version_target` → property + `has_version_target` triple (object='literal')
    - `council_lead`, `council_members` → her biri Person entity + `reviewed_by` triple
    - `created` → property
  - File path → entity.source_ref
  - **DROP (v1)**: Plan body'sinden commit sha extract → triple. `applied_in` predicate sadece Migration→Commit icin tanimli; Plan→Commit baglantisi v1.1'de ayri PR'da eklenecek (yeni predicate `realized_by` ontology'e eklenmeli). Bu adapter'da yapma.
- last_mark = ISO datetime now()

### `adapters/backlog_adapter.py`

**Sınıf:** `RefactorBacklogAdapter(BaseAdapter)`

**Görev:** `.agents/refactor/REFACTOR_BACKLOG.md` markdown tablosu → Refactor entity + triple.

- Constructor: `RefactorBacklogAdapter(graphify, project_slug, backlog_path: Path)`
- `mine(since: str | None)`:
  - Mtime karşılaştır
  - Markdown tablo parser:
    - "| ID | Priority | Scope | Risk | Effort | Target | Created | Title | File(s) | Status | Notes |"
    - Her satır → `add_entity('Refactor', name=ID, properties={priority,scope,risk,effort,target,created,title,files,status,notes})`
    - `target` property var ise `has_version_target` triple
    - `status` (open/done/wontfix) → `has_status` triple
    - `files` field comma-split → File entity + `refactors` triple
    - Notlardaki `commit <sha>` regex → Commit entity bağı `closes` (eğer git_adapter daha önce çalıştırdıysa commit'i bulur)
- Idempotent: ID UNIQUE — re-mine sadece properties günceller (status değişimini yakalar)
- last_mark = mtime

### `adapters/code_adapter.py`

**Sınıf:** `PythonCodeAdapter(BaseAdapter)`

**Görev:** Python AST → Function + Class entity. Opt-in (büyük repo'larda yavaş olabilir).

- Constructor: `PythonCodeAdapter(graphify, project_slug, code_roots: list[Path], include_globs: list[str] | None = None, exclude_globs: list[str] | None = None)`
- Default include: `**/*.py`; default exclude: `__pycache__`, `.venv`, `venv`, `node_modules`, `.tox`
- `mine(since: str | None)`:
  - Hangi dosyaların değiştiğini git'ten oku (`git diff --name-only LAST_MARK..HEAD`) — git yoksa mtime fallback
  - Her dosya için `ast.parse`:
    - File entity (upsert; name = normalized relative path with forward slashes)
    - FunctionDef + AsyncFunctionDef → Function entity. **UNIQUE collision korumasi:** `name = f"{rel_path}::{funcname}"` (UNIQUE(type,name,project_slug) korumasi icin disambig). `properties={"file": rel_path, "name": funcname, "lineno": n, "docstring": first_line[:80], "kind": "function"|"async_function"}`. required_props=[file,name] zorunluluguna uy.
    - ClassDef → Function entity ile birleştir, ayni naming kurali: `name = f"{rel_path}::{classname}"`, `properties.kind='class'`
    - `defined_in` triple: Function → File
    - `lives_in` triple: File → Project
  - Hata olursa (syntax error) → errors listesine "<path>: <err>" ekle, devam
- last_mark = HEAD sha veya ISO now

### `adapters/conversation_adapter.py`

**Sınıf:** `ConversationMemoryAdapter(BaseAdapter)`

**Görev:** Free-form decision/feedback memos → Memory entity.

- Constructor: `ConversationMemoryAdapter(graphify, project_slug)`
- `add_memory(content: str, source_ref: str | None = None, related_entities: list[str] | None = None, confidence: float = 1.0) -> Entity`:
  - `Memory` entity (name = content first 80 chars, properties={content, full_text_hash})
  - related_entities varsa her biri için `extracted_from` triple
- `mine(since)`: no-op (free-form, manual call only); AdapterReport(0,0,"",[],0.0) dön

### `adapters/__init__.py`

Re-export:
```python
from adapters.base import BaseAdapter, AdapterReport
from adapters.git_adapter import GitAdapter
from adapters.markdown_adapter import MarkdownPlanAdapter
from adapters.backlog_adapter import RefactorBacklogAdapter
from adapters.code_adapter import PythonCodeAdapter
from adapters.conversation_adapter import ConversationMemoryAdapter

__all__ = [
    "BaseAdapter", "AdapterReport",
    "GitAdapter", "MarkdownPlanAdapter", "RefactorBacklogAdapter",
    "PythonCodeAdapter", "ConversationMemoryAdapter",
]
```

## Acceptance Criteria

1. **VYRA repo üzerinde dry-run** (kullanıcı makinesinde D:\demo_vyra):
   ```python
   from pathlib import Path
   from core.graphify import Graphify
   from adapters import GitAdapter, MarkdownPlanAdapter, RefactorBacklogAdapter
   g = Graphify(Path("./instances/vyra_a2_test.db"))
   g.init()
   git = GitAdapter(g, "vyra", Path("D:/demo_vyra"))
   md = MarkdownPlanAdapter(g, "vyra", Path("D:/demo_vyra/.agents/plans"))
   bl = RefactorBacklogAdapter(g, "vyra", Path("D:/demo_vyra/.agents/refactor/REFACTOR_BACKLOG.md"))
   print(git.mine())     # >= 5 commit beklenir
   print(md.mine())      # >= 10 plan beklenir
   print(bl.mine())      # >= 20 refactor entity (R001-R020)
   ```
2. Re-run idempotent: ikinci `mine()` çağrısı 0 yeni entity (sadece updated_at güncellenir)
3. `git_adapter` REFACTOR_BACKLOG'taki commit hash referanslarını otomatik `closes` triple'a çeviriyor
4. `code_adapter` 50 Python dosyası içeren bir alt dizinde <2 s tamamlanıyor
5. AdapterReport.errors listesi her zaman list (None değil), duration_ms her zaman pozitif

## Self-Test Command

VYRA repo'sunda test edebilirsin (kullanıcının kendi makinesi, read-only git operasyonu):

```bash
cd "C:/Users/EXT02D059293/Documents/General_Graphify"
"D:/demo_vyra/python/Scripts/python.exe" -c "
import sys, os
sys.path.insert(0, os.getcwd())
from pathlib import Path
from core.graphify import Graphify
from adapters import GitAdapter, MarkdownPlanAdapter, RefactorBacklogAdapter

g = Graphify(Path('./instances/a2_self_test.db'))
g.init()

git = GitAdapter(g, 'vyra', Path('D:/demo_vyra'))
r1 = git.mine()
print(f'git: {r1.entities_created} entities, {r1.triples_created} triples in {r1.duration_ms:.1f}ms')

md = MarkdownPlanAdapter(g, 'vyra', Path('D:/demo_vyra/.agents/plans'))
r2 = md.mine()
print(f'md:  {r2.entities_created} entities, {r2.triples_created} triples in {r2.duration_ms:.1f}ms')

bl = RefactorBacklogAdapter(g, 'vyra', Path('D:/demo_vyra/.agents/refactor/REFACTOR_BACKLOG.md'))
r3 = bl.mine()
print(f'bl:  {r3.entities_created} entities, {r3.triples_created} triples in {r3.duration_ms:.1f}ms')

# Re-run idempotent check
r1b = git.mine()
print(f'git re-run entities_created: {r1b.entities_created} (should be 0)')
"
```

Beklenen: ≥35 entity, ≥30 triple, re-run = 0 yeni entity.

## Reporting

Frontmatter güncelle:
- `status: completed`
- `completed_at: <iso8601>`
- `files_created: [list]`
- `self_test_output: <çıktı>`
- `notes: <kararlar/issues>`

## NOTLAR

- Emoji yok
- Subprocess (git) için `encoding='utf-8', errors='replace'`
- Tüm regex `re.compile()` ile module-level cache
- Test sırasında oluşan `instances/a2_self_test.db` `.gitignore`'da zaten exclude (instances/*)
