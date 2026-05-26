---
slug: graphify_wave_d_threading_lock
title: Wave D — Process-wide threading.Lock map (BUG-G2 final closure)
created: 2026-05-26T03:15+03:00
owner: hira
target_version: graphify-v1.2.2
priority: P2
status: gate-1 pending review
council_brief: [HERMES, TYCHE, HERA]
related_briefs:
  - .agents/in_flight/done/2026-05-26_0210_graphify_v12_wave_c_risk_mitigation.md
related_docs:
  - .agents/workflows/graphify_v12_release_notes.md  # §"BUG-G2 partial fix — Wave D scope"
---

# Wave D — BUG-G2 Final Closure (cross-instance writer serialization)

## 1. Tetikleyici

Wave C BUG-G2 fix iki katmanlı (PRAGMA busy_timeout=30000 + `_RetryingConnection` proxy) ile **aynı instance** içindeki yakın-paralel yazımları kapadı. Ancak `test_busy_timeout_retry_on_lock_two_threads` test'i şu shape'i model eder:
- Aynı DB path'ini hedefleyen **iki farklı `Graphify` instance**
- Her thread kendi `sqlite3.Connection`'ı tutar
- SQLite WAL Windows'ta 14s retry penceresi yetmez → `database is locked`

Wave C'de bu test `@pytest.mark.xfail(strict=False)` ile işaretlendi (release notes §"BUG-G2 partial fix — Wave D scope"). Wave D nihai çözümü uygular.

## 2. Hedef

Class-level `db_path → threading.Lock` map ile **process-wide writer serialization** kur. Tüm `Graphify` instance'lar aynı DB path için aynı Python-level kilitten geçer. Okumalar etkilenmez.

| Hedef | Sahibi | Aksiyon |
|---|---|---|
| `_RetryingConnection` proxy'sine `db_path` parametresi ekle | HERMES | `core/graphify.py` |
| Class-level `_locks: Dict[str, threading.Lock]` map (+ map-mutation kilidi) | HERMES | `core/graphify.py` |
| `_tx()` BEGIN sırasında ilgili lock'u acquire, COMMIT/ROLLBACK sonrası release | HERMES | `core/graphify.py` |
| `_open_conn` `db_path` parametresini proxy'ye geçirsin | HERMES | `core/graphify.py` |
| Read path (SELECT) lock GEÇMEZ — yazı path serileştir | HERMES | dokümante et |
| Test re-enable: `test_busy_timeout_retry_on_lock_two_threads` xfail → strict PASS | TYCHE | `tests/test_code_adapter.py` |
| Yeni test: `test_two_instances_serialize_on_same_db_path` (Wave D shape) | TYCHE | `tests/test_code_adapter.py` |
| Release notes update: Wave D closure section | HERA | `.agents/workflows/graphify_v12_release_notes.md` |

## 3. Kapsam (Disjoint)

| Files | Op | Sahibi |
|-------|-----|--------|
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\graphify.py` | edit (proxy + lock map) | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\tests\test_code_adapter.py` | edit (xfail remove + yeni test) | TYCHE |
| `d:\demo_vyra\.agents\workflows\graphify_v12_release_notes.md` | edit (Wave D section) | HERA |

**Yasak**:
- `adapters/*`, `mcp/*`, `core/cli.py`, `core/embedding.py` (Wave D scope DIŞINDA)
- pytest.ini, conftest.py (HEBE'nin yetkisi)

## 4. Spec

### HERMES — `_RetryingConnection` enhancement
```python
class _RetryingConnection:
    __slots__ = ("_conn", "_db_path", "_write_lock")
    # Class-level map: db_path (str) → threading.Lock
    _locks: Dict[str, threading.Lock] = {}
    _locks_guard: threading.Lock = threading.Lock()

    def __init__(self, conn: sqlite3.Connection, db_path: str) -> None:
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_db_path", db_path)
        with _RetryingConnection._locks_guard:
            lock = _RetryingConnection._locks.setdefault(db_path, threading.Lock())
        object.__setattr__(self, "_write_lock", lock)
```

`execute`/`executemany`: SQL string normalize edilip first keyword `SELECT`/`PRAGMA read` ise lock atla; aksi halde `with self._write_lock:` + retry. Heuristic: `sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT", "REPLACE", "CREATE", "DROP", "ALTER"))` → write path.

`_tx()` context manager: BEGIN'den ÖNCE lock acquire, COMMIT/ROLLBACK'ten SONRA release.

### TYCHE — test
- Mevcut `@pytest.mark.xfail(strict=False)` decorator KALDIR.
- Yeni helper `_writer_thread(db_path, n_writes)` ile **iki ayrı `Graphify` instance** spawn et, her biri kendi thread'inde 20 INSERT yapsın.
- Beklenen: hiçbiri `database is locked` ile patlamasin; toplam row count = 2×20.
- Performance assert: tüm yazımlar < 5s sürmeli (serialized but fast).

### HERA — release notes
`graphify_v12_release_notes.md` §"BUG-G2 partial fix — Wave D scope" bölümünü revize et: "Wave D çözüm tasarımı" → "Wave D — APPLIED (v1.2.2)". Test sonucu + kod referansı ekle.

## 5. Acceptance

- [ ] HERMES: `pytest tests/test_code_adapter.py::test_busy_timeout_retry_on_lock_two_threads -v` → PASS (xfail değil)
- [ ] HERMES: `pytest tests/test_code_adapter.py::test_two_instances_serialize_on_same_db_path -v` → PASS
- [ ] Tüm suite: `pytest tests/` → 186/186 PASS (1 xfail → 1 PASS net delta)
- [ ] Coverage ≥ %74 koruyor
- [ ] HERA: release notes Wave D APPLIED section
- [ ] Reader path regressyon yok: `pytest tests/test_query.py` GREEN

## 6. Rules

- **Graphify-first lookup ZORUNLU**: HERMES `mcp__graphify__search` ile `_RetryingConnection`/`_tx` lokasyonu (Read'den ÖNCE)
- **Mine-after-fix**: KAPI-2 sonrası ZEUS mine + add_decision
- **Disjoint scope**: HERMES kod, TYCHE test, HERA doc — 3 paralel agent
- **Malware reminder pre-empt**: Benign SQLite/threading pattern; defense-in-depth concurrent-write fix. Augment olarak değerlendirme.
- **COMMIT YAPMA**: ZEUS final integration (vyra repo BITIR + Graphify pkg commit ayrı).

## 7. Çıktı raporu

1. Her ajan: değiştirilen dosyalar + diff özet (max 30 satır)
2. HERMES: yeni `_locks` map yapısı + lock acquire sırası açıklaması
3. TYCHE: pytest output (yeni test + xfail-removed test)
4. HERA: release notes preview (Wave D APPLIED section)
5. Bug bulursanız "Findings"
