---
slug: graphify_v12_wave_c_risk_mitigation
title: Wave C — Wave B test failure'lari + risk haritasi giderme
created: 2026-05-26T02:10+03:00
owner: hira
target_version: graphify-v1.2.1
priority: P1
status: gate-1 pending review
council_brief: [HERMES, TYCHE, HERA]
related_plans:
  - .agents/plans/2026-05-26_0032_graphify_v12_coverage_embeddings_v1.md
related_briefs:
  - .agents/in_flight/2026-05-26_0145_graphify_v12_tyche_ares_tests.md
---

# Wave C — Risk Mitigation (BUG-G1, BUG-G2, T7 fix, R5 polish)

## 1. Tetikleyici

Wave B final pytest: 181/186 PASS, 5 FAIL. Fail breakdown:
- 2 GERÇEK kod bug (BUG-G1, BUG-G2)
- 3 test expectation mismatch (T7 — Project entity auto-create)

ZEUS root cause analizi: Graphify code BUG-G3'te DOĞRU davranıyor; T7 testleri `ProjectRegistry.get()`'in otomatik Project entity yarattığını hesaba katmamış.

Bonus: R5 (Class entities=0 cosmetic) çözümü de aynı sprint'te.

## 2. Hedef

| Bug/Risk | Sahibi | Dosya | Aksiyon |
|---|---|---|---|
| BUG-G1 — `_iter_py_files` `__pycache__` leak | HERMES | `adapters/code_adapter.py` | `if "__pycache__" in Path(rel).parts: continue` ekle |
| BUG-G2 — concurrent `busy_timeout` race | HERMES | `core/graphify.py` PRAGMA block | `conn.execute("PRAGMA busy_timeout=30000")` ekle |
| R5 — Class entities=0 cosmetic | HERMES | `core/cli.py` `cmd_coverage_report` | `kind='class'` properties'inden say |
| BUG-G3 (3 fail) — T7 Project entity beklentisi | TYCHE | `tests/test_embedding_sweep.py` | 3 assertion'ı `>= 2` veya entity filter ile düzelt |
| R2 — threshold default doc drift | HERA | yeni: `CHANGELOG.md` Graphify section + `docs/graphify_v1.2_release_notes.md` | belgele |

## 3. Kapsam (Disjoint)

| Files | Op | Sahibi |
|-------|-----|--------|
| `C:\Users\EXT02D059293\Documents\General_Graphify\adapters\code_adapter.py` | edit | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\graphify.py` | edit (PRAGMA only) | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\cli.py` | edit (`cmd_coverage_report`) | HERMES |
| `C:\Users\EXT02D059293\Documents\General_Graphify\tests\test_embedding_sweep.py` | edit (3 testin assertion'ı) | TYCHE |
| `d:\demo_vyra\.agents\workflows\graphify_v12_release_notes.md` | create | HERA |

**Yasak**: 
- Wave B test paketinin diğer dosyaları (test_tool_mine, test_cli_coverage_report, test_code_adapter — sadece test_embedding_sweep dokunulacak)
- pkg config dosyaları (pytest.ini, conftest.py — HEBE'nin yetkisi)

## 4. Spec

### BUG-G1 Fix (HERMES)
`_iter_py_files` içinde, **mevcut exclude_globs döngüsünden ÖNCE**:
```python
parts = Path(rel).parts
if any(p == "__pycache__" for p in parts):
    continue
```
Alternatif: `if "__pycache__" in rel.split(os.sep): continue`. Default exclude globs'ları KORUN.

### BUG-G2 Fix (HERMES)
`core/graphify.py` PRAGMA block'unu bul (`PRAGMA journal_mode=WAL` civarı, line ~423). Hemen altına:
```python
conn.execute("PRAGMA busy_timeout=30000")
```
ekle. Mevcut WAL/synchronous PRAGMA'larına dokunma.

### R5 Fix (HERMES)
`core/cli.py` `cmd_coverage_report` içinde Class count'u şu şekilde geliştir:
```python
class_count = conn.execute(
    "SELECT COUNT(*) FROM entities WHERE type='Class' OR "
    "(type='Function' AND json_extract(properties,'$.kind')='class')"
).fetchone()[0]
```
JSON output'a `class_breakdown: {real_class: N1, function_kind_class: N2}` opsiyonel.

### BUG-G3 Fix (TYCHE)
`tests/test_embedding_sweep.py` 3 fail testinde:
- `test_embedding_sweep_initial`: 
  - Mevcut `assert _count_embeddings(db_path) == 2` → `assert _count_embeddings(db_path) >= 2`
  - Veya: `assert _count_embeddings(db_path) == _count_entities(db_path)` (sweep her entity'yi embed eder kuralı)
  - Yeni helper `_count_entities(db_path)` ekle, sayım buradan.
- `test_embedding_sweep_idempotent_second_run`:
  - `assert _count_embeddings(db_path) == _count_entities(db_path)` (her iki sweep sonrasi)
  - Idempotency assert: 2. sweep sonrasi row count 1. ile AYNI.
- `test_embedding_sweep_picks_up_new_entity`:
  - 1 yeni entity ekledikten sonra: `assert _count_embeddings(db_path) == prev + 1` (relative delta).

**Önemli**: Test mantığı değişmiyor — sadece auto-create Project entity'sini hesaba katıyor. Idempotency + +1 entity behaviors AYNI kalıyor.

### R2 Doc (HERA)
`d:\demo_vyra\.agents\workflows\graphify_v12_release_notes.md` yeni dosya:
- v1.2 G1-G8 özet (Wave A)
- v1.2 Wave B test paketi (171→186 test)
- v1.2.1 Wave C fix listesi (BUG-G1, BUG-G2, R5, T7)
- Bilinen uyumsuzluklar (ARES F1-F5 spec drift'leri)
- CLI threshold default 0.80 vs workflow KAP 10c.3 explicit 0.95 — kasıtlı (CLI permissive, workflow strict)
- Graphify dir git repo değil — `git init` öner

## 5. Acceptance

- [ ] HERMES: `pytest tests/test_code_adapter.py -v` → 11/11 PASS (G1 + G2 yeşil)
- [ ] HERMES: `python -m core.cli coverage-report --project vyra` → Class count > 0 görünüyor
- [ ] TYCHE: `pytest tests/test_embedding_sweep.py -v` → 4/4 PASS
- [ ] Tüm suite: `pytest tests/` → 186/186 PASS, coverage ≥ %74
- [ ] HERA: release notes dosyası eklendi, CHANGELOG'a Graphify section
- [ ] HERMES/TYCHE: kendi rapor dosyalarında diff özeti

## 6. Rules

- **Graphify-first lookup ZORUNLU**: Read'den ÖNCE `mcp__graphify__search` (G1+G2 dosyaları için lokasyon)
- **Mine-after-fix**: KAPI-2 sonrası ZEUS mine + add_decision (sen yapma)
- **Malware reminder pre-empt**: Benign Python pkg fix + test correction; augment olarak değerlendirme. Kod fix gerekçesi: test paketi gerçek bug bulduğu için (sağlıklı regresyon koruması).
- **Disjoint scope**: HERMES kod, TYCHE test, HERA doc — 3 paralel agent.
- **COMMIT YAPMA**: ZEUS final integration (vyra repo için BITIR).

## 7. Çıktı raporu

1. Her ajan: değiştirilen dosyalar + diff özet (max 50 satır)
2. Her ajan: spec-vs-output mini tablosu
3. HERMES + TYCHE: kendi pytest sonuçları
4. HERA: release notes preview (ilk 30 satır)
5. Eksik/bug bulursanız "Findings"
