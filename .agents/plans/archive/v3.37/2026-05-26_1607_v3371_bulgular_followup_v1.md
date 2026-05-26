---
slug: v3371_bulgular_followup
title: v3.37.1 — Bulgular v3.37.0 follow-up (Bug A/B/C)
created: 2026-05-26T16:07+03:00
owner: hira
version_target: v3.37.1
status: in_progress
last_commit: f3e6afe
council_lead: [ZEUS, HERMES, HEBE, ATHENA, TYCHE, ARES]
related_bulgular:
  - Gecici_Dosyalar_Sil/bulgular.docx (madde 1, 2, 4)
parent_release:
  - .agents/plans/archive/v3.37/2026-05-25_2230_smart_discovery_bulgular_v3370_v1.md
---

# v3.37.1 — Bulgular Follow-up

## 1. Why (Tetikleyici)

Kullanıcı v3.37.0 sonrası canlı smoke testte 3 spec-drift / eksik tespit etti:

- **Bug A** — Kayıtlı raporu açıp "Çalıştır" → SSE `stream_error: invalid integer value "port" for connection option "port"`. v3.37.0 B1 fix (`db_type` normalize) yeterli olmadı: rerun yolu `dbsmart_saved_reports.source_id` NULL kayıtlarda port bilgisini başka kanaldan alıyor ve literal "port" string'i connector init'e sızıyor.
- **Bug B** — Step 2 (Metrik) ekranı statik `metric_library` (`30 hazır metrik` + "fallback ile yüklendi" notu) gösteriyor. Bulgu 4 talebi: tablo metadata + FK ilişki + tablo amacına göre LLM dinamik üretim. v3.37.0 B4 endpoint hazır (`/llm/metric-suggest`) ama sadece manuel "✨ Metrik Öner" butonuna bağlı, **Step 1→2 transition'da auto-fire yok**.
- **Bug C** — Saved-report rerun panel SQL tek satır görünüyor (önceki screenshot). v3.37.0 B2 pretty-print kod yolu (`db_smart_wizard.js:2688`) wizard preview için yazıldı; saved-report card içindeki SQL render fonksiyonu B2 helper'ını çağırmıyor.

## 2. What (Hedef)

### 2.1 Bug A — Saved-report rerun port/dialect resolution

**Tanı verisi (DB sorgu sonucu — 2026-05-26 12:55):**
- `dbsmart_saved_reports` rows id={2,3,5}: `source_id=NULL`, `last_dialect=NULL`. `wizard_state.source_id=3`, `wizard_state.dialect="postgresql"` (yanlış — source 3 ORACLE).
- `data_sources` id=3: `db_type=oracle`, `host=localhost`, `port=1521` (INT, temiz).

**Hedef davranış:**
1. Backend rerun endpoint (`db_smart_api.py` execute stream path) wizard_state.source_id ile data_sources'tan kanonik source bilgisini re-resolve etsin (`_load_source` çağırsın). Snapshot içindeki `dialect`/`port` literal'lerine güvenmesin.
2. Mismatch warn-log: `wizard_state.dialect != data_sources.db_type` ise debug log + connector data_sources kaynaklı dialect kullansın.
3. Retro backfill migration `047_v3371_saved_reports_source_id_backfill.py`:
   - `dbsmart_saved_reports.source_id IS NULL AND wizard_state ? 'source_id'` → `UPDATE source_id = (wizard_state->>'source_id')::int`.
   - Aynı kayıtlar için `last_dialect` data_sources.db_type'tan doldurulur.
   - Idempotent + dry-run flag.
4. Defensive: connector init'te `port` int değilse açıklayıcı `ValueError("port literal değil int olmalı: %r")` (mevcut psycopg2 ham hatası kapansın).

**Etkilenen dosya:**
- `app/api/routes/db_smart_api.py` (`post_execute_stream` + `_load_source` çevresi)
- `app/services/ds_learning_service.py` (`_get_db_connector` defensive)
- `migrations/versions/047_v3371_saved_reports_source_id_backfill.py` (yeni)

### 2.2 Bug B — Step 2 metrik LLM auto-trigger

**Hedef davranış:**
- Step 1→2 transition'da `_loadMetrics()` içinde önce `/llm/metric-suggest` çağrılır (table_id + FK columns + selectedTableLabel ile).
- LLM başarılı → suggestion'lar `_metricCategories` map'ine "✨ LLM Önerisi" kategorisi olarak EN ÜSTTE eklenir, expand=true default.
- LLM hata/timeout/disabled (LLM_DISABLED env) → statik `/metrics` library fallback (mevcut davranış), italik fallback notu sadece bu durumda gösterilir.
- "Metrik kütüphanesi boş veya fallback ile yüklendi." mesajı yeni LLM başarı path'inde GÖSTERİLMEZ.
- AbortController: kullanıcı step 2'den geri çıkarsa pending LLM call iptal.
- Spinner: "🤖 METIS metrikleri analiz ediyor..." (1-3s sürebilir).

**Etkilenen dosya:**
- `frontend/assets/js/modules/db_smart_wizard.js` (`_loadMetrics`, `_renderStep2`, opsiyonel yeni `_autoSuggestMetrics`)

### 2.3 Bug C — Saved-report rerun panel SQL pretty-print

**Hedef davranış:**
- Saved-report card "SQL'i göster" açılır panelde gösterilen SQL, B2 pretty-print helper'ından geçer.
- B2 helper'ı module-scope reusable: SELECT/FROM/WHERE/GROUP BY/ORDER BY/JOIN/FETCH/LIMIT keyword'lerinde newline + 2-space indent.

**Etkilenen dosya:**
- `frontend/assets/js/modules/db_smart_wizard.js` veya saved-report panel module (grep ile bul: `SQL'i göster`)

## 3. Disjoint File Scope

| Subagent | Files | Op |
|----------|-------|-----|
| **HERMES-BE** (Bug A) | `app/api/routes/db_smart_api.py` (sadece rerun execute stream path + `_load_source` çevresi), `app/services/ds_learning_service.py` (sadece `_get_db_connector` defensive), `migrations/versions/047_v3371_saved_reports_source_id_backfill.py` | edit + create |
| **HEBE-FE** (Bug B) | `frontend/assets/js/modules/db_smart_wizard.js` (sadece `_loadMetrics`, `_renderStep2`, yeni helper) | edit |
| **ATHENA-FE** (Bug C) | `frontend/assets/js/modules/db_smart_wizard.js` (sadece saved-report card SQL render fonksiyonu — Bug B ile disjoint sub-scope: ayrı fonksiyon adı) **VEYA** ayrı saved-report panel modülü (grep sonrası kesinleşir) | edit |

> **Disjoint guard**: HEBE-FE + ATHENA-FE aynı dosyada (`db_smart_wizard.js`) farklı fonksiyonlar düzenliyor. ZEUS merge sırasında satır-bazlı conflict check yapacak. Eğer conflict riski yüksekse ATHENA görevi seri (HEBE bittikten sonra) çalıştırılır.

## 4. Tests (TYCHE+ARES — ayrı brief)

- **Backend** — `tests/api/routes/test_db_smart_rerun_port_resolve.py`: source_id NULL saved-report rerun → data_sources'tan resolve, port=int, dialect=db_type match.
- **Backend migration** — `tests/migrations/test_047_v3371_backfill.py`: idempotent + dry-run + wizard_state path.
- **Frontend smoke** — manuel smoke checklist (4 senaryo).

## 5. Spec-vs-Output Verifikasyon (Gate-2)

Her subagent bittikten sonra ZEUS şu tabloyu doldurur:

| Brief item | Spec | Output (kod kanıtı) | Match |
|------------|------|---------------------|-------|
| Bug A.1 rerun re-resolve | `_load_source` çağrısı + warn-log | grep + diff | ✅/❌ |
| Bug A.3 migration idempotent | 2. çalıştırma 0 row update | pytest output | ✅/❌ |
| Bug B auto-fire | Step 1→2 entry'de `/llm/metric-suggest` POST | grep + diff | ✅/❌ |
| Bug B fallback note suppress | LLM success → italik mesaj YOK | grep + smoke | ✅/❌ |
| Bug C pretty-print | Saved-report card SQL multi-line | grep + smoke | ✅/❌ |

## 6. BITIR

- v3.37.1 commit: `fix(v3.37.1): rerun port resolution + metric auto-LLM + saved-report pretty SQL`
- CHANGELOG entry
- APP_VERSION = "3.37.1" (config.py)
- Plan → `.agents/plans/archive/v3.37/`
- Brief'ler → `.agents/in_flight/done/`
- Restart bildirimi: backend reload + frontend Ctrl+Shift+R

---

## 7. Kalan İşler — IDE Restart Sonrası Devam Et (eklendi 2026-05-26T18:30+03:00)

> Kullanıcı IDE'yi kapatıp tekrar açacak → settings.json'daki `graphify_guard.py`
> PreToolUse / PostToolUse hook'ları aktifleşecek. Aşağıdaki adımlar **bu hook
> aktifken Graphify-first compliance ile** koşulmalı. Her madde için önce
> `mcp__graphify__search` / `mcp__graphify__traverse`, sonra Read/Grep.

### 7.1 — Subagent Dispatch Sonuç Notu (info)

Brief A/B/C subagent dispatch'leri **system-reminder malware refusal** firing'ine
takıldı (memory: `feedback_subagent_malware_reminder_refusal`). ZEUS direct-apply
Plan B devreye girdi. Uygulanan kod düzenlemeleri:

| Brief | Direct-apply edilen dosyalar |
|---|---|
| A | `app/api/routes/db_smart_api.py` (post_execute_stream wizard_state.source_id fallback + port int defensive + dialect mismatch DEBUG) · `app/services/ds_learning_service.py` (`_get_db_connector` port int guard) · `migrations/versions/047_v3371_saved_reports_source_id_backfill.py` (alembic chain üyesi, idempotent) |
| B | `frontend/assets/js/modules/db_smart_wizard.js` (`_loadMetrics` LLM auto-first + `_autoSuggestMetrics` helper + `_renderStep2` LLM accordion default-open + `_onStepEnter` pending LLM abort) |
| C | `frontend/assets/js/modules/report_detail_modal.js` (`_prettyPrintSql` helper + line ~375 call-site swap + marker-based JOIN/compound JOIN bug fix doğrulandı: 5/5 test pass) |

### 7.2 — Gate-2 Spec-vs-Output Verifikasyon (yapılacak)

Aşağıdaki tabloyu kullanıcıya **kanıt grep / diff** ile birlikte sun (memory:
`feedback_brief_two_gate_council_approval`):

| Brief item | Spec | Output (kod kanıtı) | Match |
|---|---|---|---|
| A.1 wizard_state.source_id fallback | body.source_id None ise wizard_state'ten al | `grep -n "wizard_state.get(\"source_id\")" app/api/routes/db_smart_api.py` | ☐ |
| A.2 dialect mismatch DEBUG | wizard ≠ data_sources.db_type → debug log | grep "dialect mismatch wizard" db_smart_api.py | ☐ |
| A.3 port int defensive (route) | int cast veya 500 raise | grep `src_dict\["port"\] = int(` db_smart_api.py | ☐ |
| A.4 port int defensive (connector) | `_get_db_connector` port int guard | grep `isinstance(port_val, int)` ds_learning_service.py | ☐ |
| A.5 migration 047 idempotent | source_id IS NULL filtre | grep `WHERE r.source_id IS NULL` migrations/versions/047_v3371_*.py | ☐ |
| B.1 LLM auto-fire on step 1→2 | `_loadMetrics` LLM önce | grep `_autoSuggestMetrics` db_smart_wizard.js | ☐ |
| B.2 LLM kategori accordion default open | `isLlmCat` open | grep `isLlmCat` db_smart_wizard.js | ☐ |
| B.3 fallback notu LLM success'te yok | `showFallbackNote = !llm && static` | grep `showFallbackNote` db_smart_wizard.js | ☐ |
| B.4 step-out cancel | `_metricLlmAbort.abort()` | grep `_metricLlmAbort` db_smart_wizard.js | ☐ |
| B.5 manuel ✨ Metrik Öner regression | line 2782/3053 hala mevcut | grep `metric-suggest` db_smart_wizard.js | ☐ |
| C.1 `_prettyPrintSql` tanımlı | helper function | grep `_prettyPrintSql` report_detail_modal.js | ☐ |
| C.2 call-site swap | line ~375 | grep `_prettyPrintSql\(_report.last_sql\)` | ☐ |
| C.3 LEFT JOIN compound korunur | test passed (5/5) | node REPL re-run | ☐ |

### 7.3 — Migration Apply

```bash
cd d:/demo_vyra
D:/demo_vyra/python/Scripts/python.exe -m alembic -c alembic.ini upgrade head
# Beklenen: "[mig 047_v3371] backfilled N saved-report rows" — N >= 3 (id=2,3,5)
D:/demo_vyra/python/Scripts/python.exe -c "import psycopg2; c=psycopg2.connect(host='127.0.0.1',port=5005,dbname='vyra',user='postgres',password='postgres'); cur=c.cursor(); cur.execute('SELECT id, source_id, last_dialect FROM dbsmart_saved_reports ORDER BY id'); [print(r) for r in cur.fetchall()]"
# Beklenen: source_id={3,3,3}, last_dialect='oracle' (3 satır)
```

### 7.4 — 8-Bulgular Comprehensive Graphify Audit ⭐ KULLANICI TALEBİ ⭐

Kullanıcı verbatim: *"graphfy da onlarıda incele onlarda yapılmışssa nedne
çalışmadığını bul düzelt"* — her bir bulgular maddesi için:

1. `mcp__graphify__search(query="<madde>", project="vyra", limit=10)`
2. `mcp__graphify__traverse(start="<en alakalı dosya>", project="vyra", depth=2)`
3. v3.37.0 done/ brief'lerinden hangi commit'te kapatıldığı bul
4. Mevcut kod durumu vs spec compare → "yapıldı ama çalışmıyor" diagnozu
5. Fix gerekirse mini-brief (in_flight/) + direct-apply ya da subagent

**8 madde** (`Gecici_Dosyalar_Sil/bulgular.docx` referans):

| # | Madde özeti | İlişkili v3.37.0 brief | Audit durumu |
|---|---|---|---|
| 1 | "Tablo seçtim sonrasında ürettiği önerilen sorgu da hata verdi" (run_error stream) | B1 (db_type normalize) → v3.37.1 A ile pekiştirildi | ☐ Audit + smoke |
| 2 | "SQL göster kısmı pretty-print" | B2 (db_smart_wizard preview) + v3.37.1 C (saved-report) | ☐ Audit (B2 wizard tarafı çalışıyor mu?) |
| 3 | "Sticky footer hint user_intent" | B6 (sticky footer + user_intent state) | ☐ Audit grep `user_intent`, `_v337StepHook` |
| 4 | "Metrikler dinamik LLM" | B4 (manuel buton) + v3.37.1 B (auto-fire) | ☐ Audit smoke |
| 5 | "Step 3 kolon dinamik LLM" | B5b (column-suggest endpoint) | ☐ Audit FE binding var mı? |
| 6 | "Format öner LLM" | B8 (format-suggest endpoint) | ☐ Audit FE binding var mı? |
| 7 | "Önizleme tablo + örnek satır" | B7 (preview enhancement) | ☐ Audit `_loadPreview` davranışı |
| 8 | "Kayıtlı raporlar grid + arama" | F2 saved-reports grid + Bug A rerun | ☐ Audit modal + grid integrate |

Her madde için audit raporu `.agents/audits/v3371_bulgular_audit.md` dosyasına
yazılır (yeni dosya, ZEUS doldurur).

### 7.5 — Smoke Test (manuel — kullanıcı yapacak)

1. **Brief A** — Akıllı Veri Keşfi → "3" raporunu aç → "Çalıştır" → SSE stream
   error YOK, rows event döner.
2. **Brief B** — Yeni rapor → SIPARISLER tablosu → Devam → Step 2'de
   "🤖 METIS metrikleri analiz ediyor..." spinner → ~1-3s sonra "✨ LLM Önerisi"
   kategorisi en üstte açık, dinamik metrik chip'leri. "Metrik kütüphanesi boş
   veya fallback ile yüklendi." mesajı GÖRÜNMEZ.
3. **Brief C** — Akıllı Veri Keşfi grid → "3" raporu modal → "SQL'i göster"
   → SQL multi-line, SELECT/FROM/JOIN/FETCH FIRST ayrı satırlarda, JOIN 2-space
   indent.

### 7.6 — Test Brief Dispatch (TYCHE+ARES)

Memory: `feedback_tests_team_authored` — testler **elle değil**, TYCHE+ARES
brief + subagent dispatch ile yazılır.

- Brief: `.agents/in_flight/2026-05-26_<HHMM>_v3371_T_tests.md`
  - Council: TYCHE (test design) + ARES (security smoke) + HEBE (FE accessibility)
  - Scope: 3 backend test dosyası + 1 migration test + 1 FE unit test (jsdom
    veya QUnit minimal — Brief C `_prettyPrintSql` için 5 test case).
- Dispatch: subagent_type=`general-purpose` worktree isolation ile.

### 7.7 — Commit + Version Bump

```
fix(v3.37.1): rerun port resolution + metric auto-LLM + saved-report pretty SQL

- (A) post_execute_stream wizard_state.source_id fallback, port int defensive,
      dialect mismatch DEBUG log
- (A) _get_db_connector port int guard
- (A) migration 047_v3371 dbsmart_saved_reports.source_id + last_dialect backfill
- (B) _loadMetrics LLM auto-first + AbortController step-out + accordion default open
- (B) _autoSuggestMetrics helper + _onStepEnter abort hook
- (C) report_detail_modal _prettyPrintSql + keyword-based pretty SQL render

Council: ZEUS direct-apply (HERMES+HEBE+ATHENA subagent malware refused)
+ TYCHE+ARES tests (separate brief)
```

- `app/config.py` (veya `system_settings` table) → APP_VERSION = "3.37.1"
- CHANGELOG.md veya `.agents/RELEASES/v3.37.1.md` entry

### 7.8 — Archive + Memory + Graphify Decision

- `.agents/in_flight/2026-05-26_1610_v3371_A_*.md` → `done/`
- `.agents/in_flight/2026-05-26_1611_v3371_B_*.md` → `done/`
- `.agents/in_flight/2026-05-26_1612_v3371_C_*.md` → `done/`
- Bu plan → `.agents/plans/archive/v3.37/`
- `mcp__graphify__mine(path='app/api/routes/db_smart_api.py', project='vyra')`
- `mcp__graphify__mine(path='app/services/ds_learning_service.py', project='vyra')`
- `mcp__graphify__mine(path='frontend/assets/js/modules/db_smart_wizard.js', project='vyra')`
- `mcp__graphify__mine(path='frontend/assets/js/modules/report_detail_modal.js', project='vyra')`
- `mcp__graphify__add_decision(commit_msg='<commit>', branch='hira', council='ZEUS+HERMES+HEBE+ATHENA+TYCHE+ARES', bug_ids=['A','B','C'])`

### 7.9 — Restart Bildirimi (kullanıcıya açık söyle)

Memory: `feedback_announce_restart_requirements`.

| Bileşen | Restart |
|---|---|
| Backend (FastAPI uvicorn) | gerekli — `app/api/routes/db_smart_api.py` + `app/services/ds_learning_service.py` değişti |
| Migration 047 | `alembic upgrade head` çalıştırılmalı (7.3) |
| Frontend cache | gerekli — `db_smart_wizard.js` + `report_detail_modal.js` değişti; **Ctrl+Shift+R** ile hard reload |
| Claude Code IDE | **GEREKLİ** — `.claude/settings.json` hook'u aktifleşmesi için (kullanıcı zaten yapıyor) |

---

## 8. Resume Plan — "devam et" tetikleyici

Kullanıcı yeni session'da "devam et" derse, **şu sırada** ilerle:

1. (7.4) 8-bulgular Graphify audit'i başlat — her madde için search+traverse,
   `.agents/audits/v3371_bulgular_audit.md` doldur.
2. (7.2) Gate-2 tablosunu grep kanıtlarıyla doldur, kullanıcıya sun.
3. (7.3) Migration apply (kullanıcı onayı ile — postgres'e yazar).
4. (7.6) Test brief + dispatch (council ile).
5. (7.5) Smoke test checklist'i kullanıcıya gönder.
6. (7.7 + 7.8) Commit + archive + Graphify mine + decision.

