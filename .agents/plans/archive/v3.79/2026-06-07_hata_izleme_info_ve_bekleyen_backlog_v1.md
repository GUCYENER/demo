---
plan_id: hata_izleme_info_ve_bekleyen_backlog
created: 2026-06-07
branch: hira
status: completed
version_target: v3.77.9
council_mod: 2
hebe_gate_required: false
note: Hata İzleme'ye INFO seviyesi (filtre + rozet) + bu oturumun tamamladıklarının kaydı + bekleyen UI/observability backlog'u (3 aktif plandan konsolide). Kullanıcı: "INFO ekle, hata olmasın çalışanı bozma; G8 ve diğer bekleyeni bu plana ekle".
---

# Hata İzleme INFO Seviyesi + Bekleyen Backlog (konsolide)

## A. BU OTURUMDA YAPILAN — Hata İzleme INFO (v3.77.9)

**Kullanıcı isteği:** "Sistem Parametreleri → Hata İzleme" ekranına INFO seçeneğini hem filtre
listesine hem etiket (rozet) kısmına ekle; çalışanı bozma.

**Yapılan (7 nokta, TAMAMEN ADDITIVE — mevcut ERROR/CRITICAL/WARNING/ALL/default davranışı korundu):**
- `app/api/routes/system.py`:
  - `_build_errors_where` — izinli tekil seviye listesine `INFO` (artık `level=INFO` filtrelenir).
  - `/errors/stats` `by_level` sorgusu — `IN (...,'INFO')` → rozet INFO sayımı döner.
- `frontend/partials/section_parameters.html` — `<option value="INFO">Yalnız INFO</option>` (WARNING ile Tümü arasına).
- `frontend/assets/js/modules/error_monitor.js`:
  - `_lvlClass` — `INFO → 'em-lvl-info'` (eskiden 'em-lvl-error'a düşüp turuncu/yanlış görünüyordu = düzeltme).
  - `_loadStats` — `bl.INFO` rozeti (WARNING'den sonra).
- `frontend/assets/css/modules/error_monitor.css` — `.em-stat.em-lvl-info` + `.em-badge.em-lvl-info` (mavi #4da3ff, hata değil nötr).
- `frontend/dist/bundle.min.*` — rebuild (build.mjs exit 0).

**Doğrulama:** backend compile + ruff 0; bundle rebuild OK. Render/görsel canlıda teyit edilmeli.
**Risk notu:** INFO en yüksek-hacim seviye → stats sayımı zaman-penceresi (since_hours, default 24s) ile sınırlı,
mevcut ERROR/CRITICAL/WARNING sayımıyla aynı tarama; ölçekte yavaşlarsa pre-existing (yeni risk değil).

---

## B. BU OTURUMDA TAMAMLANAN (bekleyen planları günceller)

- ✅ **G9 — PK-hem-FK (table-per-type)** [fk_inference_robustness planında "ertelendi, ayrı PR"]:
  v3.77.4 `extension` tier ile YAPILDI. `PartyId→T_ORG_PARTY` / `WFINSTANCEID→T_WF_INSTANCE` çıkarılıyor,
  test edildi (`test_pk_extension_edge` case A). → fk_inference_robustness planında **G9 ✅** işaretlenmeli.
- ✅ **TEMA 3.3 (keşifte statement_timeout) + 4.5 (result-set streaming OOM)** [smart_discovery_gelisim planı]:
  v3.77.8 SQL-hardening ile KISMEN kapandı (stream path C1 statement_timeout + C2 `apply_row_limit`).

---

## C. BEKLEYEN BACKLOG (3 aktif plandan konsolide — öncelik sırası)

| # | İş | Kaynak plan | Tür | Efor | Durum |
|---|---|---|---|---|---|
| **G8** | FK provenance UI rozetleri (`fk_inference_observability.js`: 🔒declared / 🟢unique-index / 🟡çıkarım + confidence renk + join-picker "çıkarım" işareti) | fk_inference_robustness | frontend | S-M | 🟡 KISMEN (2026-06-07 doğrulandı): declared/inferred **sayım + ort. güven** VAR (`dc58725`); KALAN: per-FK **3-tier rozet** (🔒/🟢unique-index/🟡 — unique-index tier yok) + **join-picker "çıkarım" işareti** |
| **1.3** | Failure-lineage'i SON-KULLANICIYA göster ("sorun şu yüzden cevaplanamadı") + db_smart wizard outcome kaydı (agentic dışı yol) | smart_discovery (Tema-1 residual) | full-stack | S-M | ⏳ backend büyük oranda var (learned_query_failures/pipeline_traces), dar boşluk hedefli doğrulanmalı |
| **1.4** | Kısmi-kayıp UI rozeti (enrichment `columns_enriched==0` + FK-eksik "Yeniden Öğren") | smart_discovery (Tema-1 residual) | frontend | S | 🟡 KISMEN (2026-06-07 doğrulandı): enrichment **kapsama rozeti VAR** (`ds_enrichment_module.js`, `columns_enriched`, v3.77.1); KALAN: FK-eksik "Yeniden Öğren" tetikleyici |
| **EL-G3..G6** | Error-log: ~110 non-cleanup `except: pass` batched triyaj + ~141 cleanup'a `# noqa: S110 — intentional` + ruff S110/S112 ratchet + doğrulama | error_logging_hardening | backend temizlik | M | ⏳ düşük-aciliyet (audit: "kriz değil, nokta-atışı") |
| **TEMA 2** | Cevap doğruluğu: 2.1 deterministik join-path skorlama (cardinality/selectivity ile top-N FK), 2.3 belirsiz-soru clarify akışı (N aday SQL) | smart_discovery (Tema-2) | büyük | M+ | ✅ TAMAM: 2.1 Dilim-1 (v3.78.3) + 2.3 Dilim-2 (v3.79.0, deep_think) shiplendi; 2.2/2.4 smart_discovery'de |

**Notlar (planlardan):**
- Her madde ayrı /plan-eng-review + council ile scope'lanır (yeni tablo/migration → ARES+METIS).
- smart_discovery planı bir TEŞHİS dokümanıdır (iş listesi değil); residual'lar KÖR yapılmadan ÖNCE hedefli doğrulama ister.
- error_logging düşük-aciliyet; sistemik guard (bare-except=0, ruff E722) zaten mevcut.

## D. İlerleme Kaydı
- [x] INFO filtre (backend `_build_errors_where`)
- [x] INFO rozet sayımı (backend stats by_level)
- [x] INFO option (frontend select) + `_lvlClass` + `_loadStats` rozet + CSS + bundle rebuild
- [x] Backend compile + ruff 0
- [x] Code-review (1 finder + enum-completeness): SQL-safety CLEAN, XSS CLEAN, filter↔stats↔list↔export ALIGNED, default ERROR+CRITICAL korundu. Kozmetik docstring INFO eklendi. Perf-not aşağıda.
- [x] (bookkeeping) fk_inference_robustness planında G9 ✅ işaretlendi
- [x] Görsel teyit (canlı — img_150430'da "360 INFO" rozeti + "Yalnız INFO" filtresi çalışıyor) + commit (`0f855cf`)

### Perf notu (code-review bulgusu, blokör değil)
INFO en yüksek-hacim seviye (her API isteği bir INFO satırı, `main.py` log_requests) ve `system_logs` **retention'sız**
(yalnız elle tam-silme). all-time stats (`since_hours` boş) by_level sayımı artık INFO'yu da tam-tablo tarar → büyük
tabloda yavaş. **UI hep `since_hours=24` gönderiyor (bounded)** → normal kullanımda sorun yok; risk yalnız doğrudan
admin-çağrısı. **İnfra follow-up (ayrı):** `system_logs` retention job + `(level, created_at)` kısmi/covering index.
→ C-tablosuna ek backlog: **`system_logs` retention + index** (infra, M, düşük-aciliyet).

## E. Out-of-scope (bu plan)
- G8 ve C-tablosundaki diğer maddeler BU oturumda yapılmıyor — backlog olarak KAYDEDİLDİ (kullanıcı isteği).
- Frontend JS hata yakalama (error_logging planının out-of-scope'u).
