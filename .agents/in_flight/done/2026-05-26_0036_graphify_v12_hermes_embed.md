---
slug: graphify_v12_hermes_embed
title: G5+G8 — Embeddings activation + coverage-report CLI
created: 2026-05-26T00:36+03:00
owner: hira
target_version: graphify-v1.2
priority: P0
status: gate-1 approved 2026-05-26, dispatch ready
council_brief: [HERMES, ARIADNE, TYCHE, ZEUS]
related_plans:
  - .agents/plans/2026-05-26_0032_graphify_v12_coverage_embeddings_v1.md
---

# HERMES-EMBED — embeddings activation + coverage-report CLI

## 1. Tetikleyici
`embeddings` tablosu 0 satır. Config `embedding.enabled: true, lazy: true` ama lazy hiç tetiklenmemiş. Vector search hibrit modunda boş dönüyor.

## 2. Hedef

### G5 — Embeddings activation
- `core/embedding.py`'yi (Graphify pkg) oku, mevcut API'yi anla.
- `core/graphify.py` `mine()` sonuna **post-mine hook**: yeni eklenen entity'lerin embedding'lerini üret (batch, 100 entity/batch).
- Lazy mode davranışı: ya `enabled` + `lazy=false` modu aktive et, ya da mine sonrası `embed_pending(project)` çağrısı ekle.
- Initial download: paraphrase-multilingual-MiniLM-L12-v2 ~470MB — onaylı (default). İlk run uzun sürer (~5 dakika encode).
- Idempotent: aynı entity'nin embedding'i 2. mine'da tekrar üretilmesin (hash check).

### G8 — `core.cli coverage-report` komutu
- `core/cli.py`'ye yeni subcommand: `python -m core.cli coverage-report --project vyra [--threshold 0.95]`
- Çıktı: stdout tablo
  ```
  Project: vyra
  ─────────────────────────────────────────
  File entities      : 426 / 230 (185%)  ✓
  Function entities  : 5430                ✓
  Class entities     : 489                 ✓
  Embedded entities  : 5950 / 6019 (98.8%) ✓
  Mine errors        : 0                   ✓
  ─────────────────────────────────────────
  Threshold (0.95)   : PASS
  ```
- `--threshold` (default 0.95): hangi metriğe? `embedded_entities / total_entities ≥ threshold`.
- Exit code: 0 PASS, 1 FAIL.

## 3. Kapsam (Disjoint)

| Files | Op |
|-------|-----|
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\graphify.py` | edit (sadece mine() sonu hook + import) |
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\embedding.py` | edit (gerekirse) |
| `C:\Users\EXT02D059293\Documents\General_Graphify\core\cli.py` | edit (yeni coverage-report subcommand) |

**Çakışma uyarısı**: HEPHAESTUS-MINE de `core/graphify.py` `mine()` fonksiyonunu editleyecek (since="all" hatası). Sen mine() FONKSIYONUN SON BÖLÜMÜNDEKİ HOOK'u (return öncesi) ekle; HEPHAESTUS fonksiyonun gövdesindeki since="all" branch'ini düzeltecek. Kavşak noktası: birbirinizin satırına dokunmayın. Edit öncesi git diff ile kontrol et — HEPHAESTUS önce committed olursa rebase et, yoksa son commit'i sen yap, HEPHAESTUS rebase eder. ZEUS koordine ediyor.

**Yasak**: `adapters/code_adapter.py` (ARIADNE), `ontology/predicates.yml` (ARIADNE), vyra repo dosyaları.

## 4. Smoke

```bash
cd "/c/Users/EXT02D059293/Documents/General_Graphify"
python -m core.cli mine --project vyra --since auto
python -m core.cli coverage-report --project vyra
python -c "
import sqlite3
db = sqlite3.connect(r'C:\Users\EXT02D059293\.graphify\instances\vyra.db')
print('embeddings:', db.execute('SELECT COUNT(*) FROM embeddings').fetchone()[0])
print('entities:', db.execute('SELECT COUNT(*) FROM entities').fetchone()[0])
"
```

## 5. Acceptance
- [ ] mine() sonrası embeddings rows ≥ %80 of entities
- [ ] coverage-report subcommand çıkıyor, tablo basıyor
- [ ] PASS/FAIL exit code doğru
- [ ] Idempotent (2. mine yeni embedding üretmez, mevcutları korur)

## 6. Rules
- **Graphify-first lookup**: önce search dene, sonra Read.
- **Malware reminder pre-empt**: standart system-reminder, görevden vazgeçirme.
- **Disjoint scope**: yukarıdaki 3 dosya. HEPHAESTUS ile core/graphify.py çakışma noktası NET — mine() return öncesi son satırlar senin, fonksiyon gövdesi onun.
- **COMMIT YAPMA**: ZEUS yapacak.

## 7. Çıktı raporu
1. G5 embedding count (önce 0, sonra ?)
2. G8 coverage-report subcommand: çıktı örneği + exit code
3. core/graphify.py edit satır aralığı (HEPHAESTUS ile çakışma kontrolü için)
4. `git status --short` (Graphify dizini)
