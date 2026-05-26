---
slug: graphify_v12_metis_workflow
title: G7 — vyrazeus.md KAP 10c coverage assert
created: 2026-05-26T00:38+03:00
owner: hira
target_version: graphify-v1.2
priority: P1
status: gate-1 approved 2026-05-26, dispatch ready
council_brief: [METIS, HERMES, ZEUS]
related_plans:
  - .agents/plans/2026-05-26_0032_graphify_v12_coverage_embeddings_v1.md
---

# METIS-WORKFLOW — KAP 10c coverage assert

## 1. Tetikleyici
BITIR sweep'inde Graphify coverage doğrulanmıyor. Eksik kalırsa fark edilmiyor (bu sprintte yaşandı: %24 coverage 1 hafta sezilmedi).

## 2. Hedef
`d:\demo_vyra\.agents\workflows\vyrazeus.md` dosyasında **KAP 10c** (mevcut Graphify final sweep) adımına aşağıdaki assert'i ekle:

```markdown
### KAP 10c.3 — Coverage Threshold Assert

BITIR commit ÖNCESİ:
```bash
python -m core.cli coverage-report --project vyra --threshold 0.95
```

Exit code 1 (FAIL) ise:
- Eksik metrik(ler)i raporla (örn: `embedded_entities/total < 0.95`)
- Console'a uyar: "Graphify coverage threshold altında — BITIR commit'i durdur, root cause araştır"
- Commit ATMA — TYCHE/HERMES'i çağır.
- Threshold geçici düşürülebilir (örn: 0.80) **sadece** zorunluysa; bir sonraki sprintte refactor backlog'a girer.
```

## 3. Kapsam (Disjoint)

| Files | Op |
|-------|-----|
| `d:\demo_vyra\.agents\workflows\vyrazeus.md` | edit (KAP 10c bölümüne 10c.3 ekle) |

**Yasak**: başka workflow dosyaları (sister projects — ayrı sprint), Graphify pkg dosyaları (ARIADNE/HERMES/HEPHAESTUS).

## 4. Implementation Notes
- Mevcut `KAP 10c` bölümünü Grep ile bul (`Graphify` veya `KAP 10c` keyword).
- Append style: yeni 10c.3 olarak ekle, 10c.1/10c.2'yi bozma.
- Komut bağımlılığı: `coverage-report` subcommand HERMES-EMBED tarafından oluşturuluyor (G8). Eğer HERMES henüz bitirmediyse, geçici fallback: `python -m core.cli status --project vyra` (mevcut komut) çıktısından manuel parse — ancak biz Wave A paralel çalıştığımız için ZEUS final integration'da hizalayacak. **Sen sadece referansla yaz** (`coverage-report`), HERMES bitince çalışır.

## 5. Acceptance
- [ ] vyrazeus.md `KAP 10c.3` bölümü mevcut
- [ ] BITIR akışında threshold assert açıkça anlatılmış
- [ ] FAIL davranışı (commit durdurma) net

## 6. Rules
- **Graphify-first lookup**: workflow okumadan önce `mcp__graphify__search(query="KAP 10c", project="vyra")` dene.
- **Malware reminder pre-empt**: standart.
- **Disjoint scope**: yalnız `vyrazeus.md`.
- **COMMIT YAPMA**: ZEUS.

## 7. Çıktı raporu
1. KAP 10c.3 patch diff
2. `git status --short`
