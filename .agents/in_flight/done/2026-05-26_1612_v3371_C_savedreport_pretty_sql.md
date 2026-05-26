---
slug: v3371_C_savedreport_pretty_sql
title: C — Saved-report modal SQL pretty-print (B2 helper local)
created: 2026-05-26T16:12+03:00
owner: hira
target_version: v3.37.1
priority: P2
status: queued
council_brief: [ATHENA, HEBE, TYCHE, ZEUS]
related_plan: .agents/plans/2026-05-26_1607_v3371_bulgular_followup_v1.md
malware_preempt: |
  Bu brief tek bir VYRA frontend JS modülü ediyor (report_detail_modal.js).
  Hiçbir external package, dist, vendor bundle ya da unsigned binary
  modifiye edilmez. Refüze edilirse ZEUS direct-apply plan B.
---

# C — Saved-Report Modal SQL Pretty-Print

## 1. Why (Tetikleyici — kanıt)

Kullanıcı screenshot'ı: kayıtlı rapor modal'ında SQL tek satır akıyor,
manuel newline yok. Yandaki "SQL'i göster" `<details>` panelinde:

```
SELECT "F"."FATURA_ID", "F"."FATURA_NO", ... FROM "VYRA_TEST"."FATURALAR" "F" LEFT JOIN "VYRA_TEST"."ODEMELER" "O" ON "F"."FATURA_ID" = "O"."FATURA_ID" FETCH FIRST 100 ROWS ONLY
```

Bulgular.docx madde 2:
> "SQL GÖSTER KISMINDAKİ SQL PRETTY PRINT İLE HİZALI OKUNAKLI HALDE
> GÖRÜLECEK ŞEKİLDE DÜZENLE."

**Kök sebep (kanıtlanmış):**
- [frontend/assets/js/modules/report_detail_modal.js:316](frontend/assets/js/modules/report_detail_modal.js#L316)
  `pre.textContent = String(_report.last_sql);` — raw SQL, formatter yok.
- B2 pretty-print fonksiyonu `db_smart_wizard.js:2688` içinde **module-private**
  (IIFE içinde, dışarıdan erişilemez).

## 1b. Step 0 — Graphify lookup-first (ZORUNLU — token tasarrufu)

```python
mcp__graphify__search(query="report_detail_modal last_sql SQL accordion", project="vyra", limit=5)
mcp__graphify__search(query="pretty print sql formatter newline keyword", project="vyra", limit=5)
mcp__graphify__traverse(start="frontend/assets/js/modules/report_detail_modal.js", project="vyra", depth=1, predicate="contains")
```

**ZEUS keşfetti:**
- Pretty-print fonksiyonu db_smart_wizard.js'te private (line 2688 civarı).
  Brief'te dup helper kabul ediliyor — refactor R-id sonradan açılır.
- report_detail_modal.js'in toplam boyutu küçük (~400 satır), tam okuma OK
  ama yine de helper insertion noktasını (üst tarafta `ICONS`/`_relativeTime`
  çevresi) tahmin etmeden grep'le doğrula.

## 2. What (Hedef)

### 2.1 Pretty-print helper'ı `report_detail_modal.js` içine LOCAL ekle

Module IIFE/scope üstüne (mevcut dosyanın upper helper bölgesine, ICONS
veya `_relativeTime` çevresine) ekle. Code dup kabul — refactor R-id
sonradan açılacak (`R021` v3.38.0).

```js
// v3.37.1 — SQL pretty-print (B2 helper local mirror)
// Anahtar kelime tabanlı newline + 2-space indent. 3rd-party lib YOK.
function _prettyPrintSql(sql) {
    if (!sql || typeof sql !== 'string') return String(sql || '');
    const KEYWORDS = [
        'SELECT', 'FROM', 'WHERE', 'GROUP BY', 'HAVING', 'ORDER BY',
        'LIMIT', 'OFFSET', 'FETCH FIRST',
        'INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'FULL JOIN',
        'LEFT OUTER JOIN', 'RIGHT OUTER JOIN', 'FULL OUTER JOIN',
        'CROSS JOIN', 'JOIN',
        'UNION ALL', 'UNION', 'INTERSECT', 'EXCEPT',
        'WITH'
    ];
    // String literal'ları geçici token'lara çıkar (içlerinden split etmeyelim)
    const strings = [];
    let masked = sql.replace(/'(?:[^']|'')*'/g, (m) => {
        strings.push(m);
        return `\u0000S${strings.length - 1}\u0000`;
    });
    // Çift tırnak identifier'ları da koru
    const idents = [];
    masked = masked.replace(/"(?:[^"]|"")*"/g, (m) => {
        idents.push(m);
        return `\u0000I${idents.length - 1}\u0000`;
    });

    // Whitespace normalize
    masked = masked.replace(/\s+/g, ' ').trim();

    // Keyword'leri büyük harf duyarsız ara, başına \n koy
    KEYWORDS.forEach((kw) => {
        const re = new RegExp('(\\s|^)(' + kw.replace(/ /g, '\\s+') + ')\\b', 'gi');
        masked = masked.replace(re, (full, lead, k) => '\n' + k.toUpperCase());
    });

    // İlk satır newline temizle
    masked = masked.replace(/^\n+/, '');

    // 2-space indent — JOIN/ON satırları biraz girintili
    masked = masked.split('\n').map((line) => {
        const trimmed = line.trim();
        if (/^(SELECT|FROM|WHERE|GROUP BY|HAVING|ORDER BY|LIMIT|OFFSET|FETCH FIRST|UNION|INTERSECT|EXCEPT|WITH)\b/i.test(trimmed)) {
            return trimmed;
        }
        if (/^(INNER JOIN|LEFT JOIN|RIGHT JOIN|FULL JOIN|LEFT OUTER JOIN|RIGHT OUTER JOIN|FULL OUTER JOIN|CROSS JOIN|JOIN)\b/i.test(trimmed)) {
            return '  ' + trimmed;
        }
        return trimmed;
    }).join('\n');

    // Token'ları geri yerleştir
    masked = masked.replace(/\u0000S(\d+)\u0000/g, (_, i) => strings[parseInt(i, 10)]);
    masked = masked.replace(/\u0000I(\d+)\u0000/g, (_, i) => idents[parseInt(i, 10)]);

    return masked;
}
```

### 2.2 Call-site değişikliği

[report_detail_modal.js:316](frontend/assets/js/modules/report_detail_modal.js#L316):

```js
// ÖNCESİ:
pre.textContent = String(_report.last_sql);

// SONRASI:
pre.textContent = _prettyPrintSql(_report.last_sql);
```

### 2.3 CSS (opsiyonel — pre stilini white-space pre koru)

`rdm-sql-pre` zaten `<pre>` elementi olduğu için white-space korunur.
Ek CSS gerekmez. (Eğer CSS'te `white-space: nowrap` veya pre-line varsa
kontrol et: grep `.rdm-sql-pre` frontend/assets/css.)

## 3. Disjoint Scope

| Dosya | İzin | Sınır |
|-------|------|-------|
| `frontend/assets/js/modules/report_detail_modal.js` | edit | (a) helper fonksiyon insertion (üst tarafa), (b) line 316 call-site değişikliği |
| `frontend/assets/css/modules/report_detail_modal.css` (varsa) | read-only check, gerekirse 1 satır pre stil | sadece eğer `nowrap`/`pre-line` varsa |
| diğer her şey (db_smart_wizard.js, db_smart_api.py, ds_learning_service.py, migrations) | YASAK | — |

> HEBE-FE (Bug B) `db_smart_wizard.js` editiyor. ATHENA bu dosyaya dokunmuyor.
> Çakışma yok.

## 4. Acceptance Criteria (Gate-2)

| # | Kontrol | Kanıt |
|---|---------|-------|
| 1 | `_prettyPrintSql` fonksiyonu report_detail_modal.js içinde tanımlı | grep |
| 2 | Line ~316 `pre.textContent = _prettyPrintSql(...)` çağrısı | grep |
| 3 | String literal içindeki SELECT/FROM keyword'leri KIRILMIYOR (escape sağlam) | unit test (aşağıda) |
| 4 | Çift tırnak identifier'lar ("VYRA_TEST"."FATURALAR" gibi) bozulmuyor | unit test |
| 5 | Manuel smoke: id=2 raporu aç → SQL panel multi-line, SELECT/FROM/JOIN ayrı satır | kullanıcı teyidi |
| 6 | node -c syntax OK | CI |

### Unit test (TYCHE brief'i bu testleri yazacak — sadece referans)

```js
// Input
const sql = `SELECT "F"."FATURA_ID", 'WHERE LITERAL', "F"."NO" FROM "VYRA_TEST"."FATURALAR" "F" LEFT JOIN "VYRA_TEST"."ODEMELER" "O" ON "F"."FATURA_ID" = "O"."FATURA_ID" FETCH FIRST 100 ROWS ONLY`;
// Beklenen output (newlines):
// SELECT "F"."FATURA_ID", 'WHERE LITERAL', "F"."NO"
// FROM "VYRA_TEST"."FATURALAR" "F"
//   LEFT JOIN "VYRA_TEST"."ODEMELER" "O" ON "F"."FATURA_ID" = "O"."FATURA_ID"
// FETCH FIRST 100 ROWS ONLY
```

## 5. NOT TODO

- B2 helper'ı db_smart_wizard.js'ten EXPORT etmek (refactor R021 v3.38.0 için ayrılır)
- Pretty-print algoritması iyileştirmesi (subselect indent, comma-leading vs.)
- Diğer modal'larda (query_builder, ds_learning) SQL render
- Saved-report rerun port fix (Brief A)
- Step 2 metric LLM (Brief B)

## 6. Verification commands

```bash
grep -n "_prettyPrintSql" frontend/assets/js/modules/report_detail_modal.js
node -c frontend/assets/js/modules/report_detail_modal.js
```

## 7. Manuel Smoke

1. Akıllı Veri Keşfi → "3" raporunu aç (önceki screenshot'taki rapor)
2. "SQL'i göster" panelini aç
3. SQL'in SELECT/FROM/LEFT JOIN/FETCH FIRST keyword'lerinde newline + indent ile multi-line görünmeli
