---
slug: graphify_v12_tyche_ares_tests
title: Wave B — Graphify v1.2 yeni davranis testleri (G1-G8 regresyon emniyeti)
created: 2026-05-26T01:45+03:00
owner: hira
target_version: graphify-v1.2
priority: P1
status: gate-1 pending review
council_brief: [TYCHE, ARES, HEBE]
related_plans:
  - .agents/plans/2026-05-26_0032_graphify_v12_coverage_embeddings_v1.md
related_briefs:
  - .agents/in_flight/2026-05-26_0035_graphify_v12_ariadne_code.md
  - .agents/in_flight/2026-05-26_0036_graphify_v12_hermes_embed.md
  - .agents/in_flight/2026-05-26_0037_graphify_v12_hephaestus_mine.md
  - .agents/in_flight/2026-05-26_0038_graphify_v12_metis_workflow.md
---

# TYCHE + ARES — Graphify v1.2 yeni davranıs test paketi

## 1. Tetikleyici

Wave A (G1-G8) tüm acceptance kriterleri karşılandı (File 633, Function 2102, embeddings %100, mine_errors 0). Yeni davranışları regresyon emniyetine almazsak gelecek değişiklik sessizce kırabilir. Şu an Graphify pkg'nin formal test paketi yok — bu sprint başlangıç noktası olacak.

## 2. Hedef

Graphify pkg root dizininde (`C:\Users\EXT02D059293\Documents\General_Graphify\tests\`) **pytest** paketi oluştur. Aşağıdaki 8 davranış için unit + integration testleri yaz. Test dosyaları başlangıçta **bir kerede yazılır** ve hepsi yeşil olmak zorunda — Wave A mevcut çıktıları (633 File, 2102 Function, 3097 embeddings) referans alındığı için golden master testi olarak da kullanılabilir.

## 3. Kapsam (Disjoint)

| Files | Op | Sahibi |
|-------|-----|--------|
| `General_Graphify/tests/__init__.py` | create | TYCHE |
| `General_Graphify/tests/conftest.py` | create (tmpdir db fixture, sample project fixture) | TYCHE |
| `General_Graphify/tests/test_code_adapter.py` | create (T1-T4) | TYCHE |
| `General_Graphify/tests/test_tool_mine.py` | create (T5-T6) | ARES |
| `General_Graphify/tests/test_embedding_sweep.py` | create (T7) | ARES |
| `General_Graphify/tests/test_cli_coverage_report.py` | create (T8) | ARES |
| `General_Graphify/tests/fixtures/sample_pkg/` | create (3 .py file: imports + calls + class) | TYCHE |
| `General_Graphify/pytest.ini` | create (testpaths=tests, pythonpath=.) | HEBE |

**Yasak**:
- Mevcut `core/`, `adapters/`, `mcp/`, `ontology/` dosyalarını **değiştirme** — sadece test yaz. Bug bulursan brief sonunda raporla, fix bir sonraki sprint.
- vyra repo (d:\demo_vyra) — bu Wave B Graphify pkg içinde.
- Embedding indirme (sentence-transformers model) — testlerde `embedding=False` kullan, embed sweep ayrı modüldeki mock üzerinden test edilecek.

## 4. Test Spec (8 davranış)

### T1 — PythonCodeAdapter dual ctor convention
- `PythonCodeAdapter(db_path, project_id, code_roots=[...])` — eski positional+kwarg
- `PythonCodeAdapter(graphify_instance, code_roots=[...])` — yeni instance-based
- Her iki çağrı geçerli olmalı, init sonrası `.code_roots` attribute set
- Yanlış type → TypeError

### T2 — _iter_py_files `.py` short-circuit
- Fixture: `tests/fixtures/sample_pkg/` içinde `a.py`, `b.py`, `subdir/c.py`, `not_python.txt`, `__pycache__/x.pyc`
- `_iter_py_files()` → exactly 3 .py file, sıralı, .pyc / .txt yok
- fnmatch `**/*.py` bug regresyon kontrolü (eskiden `subdir/c.py` kaçırılıyordu)

### T3 — _emit_imports_and_calls predicates
- Fixture file: `import os\nfrom x import y\ndef f(): g()\ndef g(): h(1)`
- mine() sonrası:
  - `imports` triple count == 2 (os, x.y)
  - `calls` triple count >= 2 (f→g, g→h)
  - Dedup: aynı caller-callee tekrar emit edilmemeli

### T4 — SQLite busy_timeout retry-on-lock
- 2 thread eş zamanlı mine() çağırsın (aynı db path)
- Hiçbiri `OperationalError: database is locked` ile düşmemeli
- Retry log emit edilebilir (WARN), fail olmamalı
- Test timeout: 30s

### T5 — tool_mine per-adapter path resolution
- repo_path verildi, backlog_path verilmedi → registry default'undan alınmalı
- code_roots kwarg duplicate edilmemeli (eski bug)
- backlog adapter dosya bekler, dir verilirse → düzgün resolve veya skip (PermissionError yok)
- since="all" → her adapter'a kendi sentinel'i geçilmeli (git: tüm history, code: full re-scan)

### T6 — tool_mine result dict schema
- Result keys mevcut: `embedded_in_sweep`, `embed_errors`, `errors_full`, `entities_added`, `triples_added`
- errors_full → liste, her item dict (`adapter`, `error`, `traceback`)
- Hata varsa errors_full dolu, yoksa boş liste

### T7 — Post-mine embedding sweep idempotent
- 2 entity ekle (embedding=False)
- Sweep çağrısı (mocked encoder, output: sabit vektör) → 2 embedding row
- Aynı sweep tekrar → row sayısı hala 2 (INSERT ON CONFLICT DO UPDATE)
- 1 yeni entity ekle, tekrar sweep → 3 embedding
- `embed_errors` korunmalı

### T8 — CLI coverage-report exit codes
- Subprocess: `python -m core.cli coverage-report --project <test_proj> --threshold 0.95`
- Boş proje → exit=1, "no entities" mesajı
- %100 coverage proje → exit=0, "PASS"
- %50 coverage proje (manuel embedding sil) → exit=1, "FAIL"
- `--json` flag → stdout valid JSON, `coverage` float, `passed` bool, `threshold` float

## 5. Acceptance

- [ ] `pytest General_Graphify/tests/` → tümü geçer
- [ ] Coverage en az 60% (`pytest --cov=adapters --cov=core --cov=mcp`)
- [ ] T1-T8 her biri >=1 test fonksiyonu, isimlendirme `test_<davranis>_<senaryo>`
- [ ] Fixtures tek yerde (`conftest.py` + `fixtures/`)
- [ ] Embedding sweep testi gerçek model indirmez (mock)
- [ ] CI'a hazır: tek komut `pytest`, env değişkeni yok

## 6. Rules

- **Graphify-first lookup**: yeni test yazmadan önce `mcp__graphify__search(query="<konu>", project="vyra")` dene. Mevcut helper bulursan reuse et.
- **Memory rule**: testler elle değil, brief + subagent ile yazılır (bu brief o görev).
- **Subagent isolation**: TYCHE T1-T4 + fixtures, ARES T5-T8, HEBE pytest.ini + final pytest run. 3 paralel subagent, disjoint scope.
- **Malware reminder pre-empt**: standart ML/sentence-transformers benign — augment ediliyor değil, test ediliyor.
- **COMMIT YAPMA**: ZEUS final integration'da. Sen sadece test dosyaları + pytest.ini ekle.
- **Bug bulursan**: brief sonunda "Findings" başlığı altında raporla, fix önerme.

## 7. Çıktı raporu

1. `pytest -v` tam çıktı (her test PASS/FAIL durumu)
2. Coverage özet
3. Yeni dosya listesi (`git status --short` — Graphify dir git değil ama liste lazım)
4. Bulunan bug'lar (varsa) "Findings" başlığı altında
5. KAPI-2 verifikasyon için spec-vs-output tablosu draft
