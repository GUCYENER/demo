---
slug: graphify_v1_1_report_autogen
title: Graphify v1.1 — `core.cli report` auto-üretim + BITIR entegrasyonu
created: 2026-05-26T00:30+03:00
owner: hira
target_version: graphify-v1.1
status: pending
council_brief: [HERMES, ARIADNE, METIS, HERA, ZEUS]
related_plans:
  - .agents/plans/archive/v3.36/2026-05-25_2100_general_graphify_hybrid_setup_v1.md
related_briefs:
  - .agents/in_flight/done/2026-05-25_2350_graphify_workflow_integration_vyra.md
  - .agents/in_flight/done/2026-05-25_2359_graphify_workflow_integration_sisters.md
---

# Graphify v1.1 — `core.cli report` auto-üretim + BITIR entegrasyonu

## 1. Tetikleyici (Why)

v1.0 BITIR'inde kullanıcı `.agents/reports/graphify.htm` ve `graphreport.md` dosyalarını sordu — bunlar elle üretildi (visualize.py + manuel SQLite query). **Beklenti**: `pip install graphify` sonrası bu dosyalar otomatik üretilmeli.

Şu an:
- `tools/visualize.py` mermaid + d3 üretebiliyor ama tek tek çağrılıyor.
- `graphreport.md` adında dedicated bir generator yok — manuel yazıldı.
- BITIR sırasında her oturumda manuel komut çalıştırmak gerekiyor.

## 2. Hedef (What)

**v1.1 deliverable:**

1. `python -m core.cli report --project <slug>` komutu → tek seferde üç çıktı:
   - `.agents/reports/graphify.htm` (D3 force-directed, current ile aynı schema)
   - `.agents/reports/graphreport.md` (entity/predicate distribution + benchmark + last_mark)
   - `.agents/reports/graphify.mmd` (mermaid graph, max 80 nodes)

2. Çıktı yolu **proje root'una göre relatif** (`<project_root>/.agents/reports/`) — proje slug ile DB lookup, root path config'den.

3. **vyrazeus.md BITIR akışına** entegre (yeni KAP 13 veya KAP 10c son adımı):
   ```
   KAP 13 — Graphify Reports (MNEMOSYNE-GRAPH — BITIR taraflı)
   - Komut: python -m core.cli report --project vyra
   - Hedef: .agents/reports/graphify.htm + graphreport.md + graphify.mmd auto-refresh
   - Hata → bayat raporlarla devam, not düş; commit harici tut.
   ```

4. **Sister workflow** patch (3 proje): zeus.md / mobilzeus.md / Mahsul zeus.md → aynı BITIR adımı.

## 3. Kapsam (Disjoint File Scope)

| Subagent | Files | Sorumlu |
|----------|-------|---------|
| HERMES   | `core/cli.py` (yeni `report` subcommand), `core/report.py` (yeni — generator orchestrator) | report komutu + Click integration |
| ARIADNE  | `core/report.py` MD template + `tools/visualize.py` import → htm/mmd çağrısı | template + generator |
| METIS    | tests: `tests/unit/test_cli_report.py` (smoke: 3 file produced, valid JSON in htm), `tests/integration/test_report_e2e.py` (real DB + assert file sizes > 0) | TYCHE+ARES brief |
| HERA     | 4 workflow patch: `vyrazeus.md` (BITIR KAP 13) + `D:\COSMOS\.claude\commands\zeus.md` + `D:\Cosmos_Mobile\.agents\workflows\mobilzeus.md` + `D:\Mahsul Mezati\.claude\commands\zeus.md` | patch — disjoint dosya |
| ZEUS     | Brief review + 2-gate council approval (KAPI 1 yazım sonrası + KAPI 2 spec-vs-output) | gate |

## 4. Implementation Notes

- `core/report.py` minimal:
  ```python
  def generate_report(project: str, output_dir: Path) -> dict:
      """Returns {'htm': path, 'md': path, 'mmd': path, 'stats': {...}}"""
      stats = _query_db_stats(project)
      _write_htm(output_dir / "graphify.htm", stats)
      _write_md(output_dir / "graphreport.md", stats)
      _write_mmd(output_dir / "graphify.mmd", project, max_nodes=80)
  ```
- `--output-dir` flag opsiyonel; default: `<project_root>/.agents/reports/`
- HTM template: mevcut `graphify.htm` (D3 + side panel) — extract et, Jinja2 minimal placeholder
- MD template: mevcut `graphreport.md` yapı (8 bölüm + frontmatter) — last_git_mark + last_md_mark dinamik

## 5. Acceptance Criteria

- [ ] `python -m core.cli report --project vyra` 3 dosya üretiyor (existence + > 1 KB)
- [ ] HTM açıldığında D3 force graph render oluyor (manuel smoke)
- [ ] MD frontmatter `generated_at` doğru ISO timestamp
- [ ] Pytest smoke + e2e PASS
- [ ] 4 workflow KAP 13 patch'i merge edilmiş
- [ ] Existing manual artifacts ile diff < 5% (smoke)

## 6. 2-Gate Council Plan

**KAPI 1 (yazım sonrası, dispatch öncesi):** HERMES + ARIADNE + METIS + HERA brief review, signature gerekli.

**KAPI 2 (subagent bitince, spec-vs-output):**
| Spec madde | Verifikasyon | Karar |
|------------|--------------|-------|
| 3 file produced | ls + filesize > 0 | — |
| HTM D3 render | manual smoke | — |
| MD frontmatter geçerli | yaml.safe_load | — |
| 4 workflow KAP 13 mevcut | grep "KAP 13" each file | — |
| Tests PASS | pytest -x | — |

## 7. Backlog Bağlantısı

- Şu anki v1.0 manual workflow ile yaratılan artifacts (commit `8891f71` sonrası):
  - `.agents/reports/graphify.htm`
  - `.agents/reports/graphreport.md`
  - `.agents/reports/graphify.mmd`
- Bu brief done'a alındığında üstteki 3 dosya `core.cli report` ile yenilenebilir olacak.

## 8. Risk / Edge Cases

- Pruning v1.1 ile schema değişikliği olursa report query'leri kırılır → schema version check ekle, `schema_version != 4` → warn.
- Multi-project: report tek proje slug alır; tüm projeler için `--all` flag v1.2'ye ertelenebilir.
- Cross-instance (federated) v2 — bu brief kapsam dışı.
