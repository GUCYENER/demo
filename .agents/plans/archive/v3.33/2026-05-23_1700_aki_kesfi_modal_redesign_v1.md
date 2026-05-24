---
plan_id: aki_kesfi_modal_redesign
title: Akıllı Veri Keşfi — modal-first dynamic report studio redesign
created: 2026-05-23
branch: hira
status: completed
completed_at: 2026-05-23
version_target: v3.33.0
council_mod: 3
hebe_gate_required: true
hebe_gate_completed: true
owner_zeus: true
last_commit_at_start: 2fd24d1
last_commit: f2a58b5
parallel_agents:
  - aki-kesfi-A_modal-wrapper
  - aki-kesfi-B_saved-reports-grid
  - aki-kesfi-C_filter-modal
  - aki-kesfi-D_backend-sources-fix
---

## Context (Neden bu değişiklik?)

Kullanıcı, "Akıllı Veri Keşfi" sekmesinin **dinamik rapor stüdyosu** olarak
konumlanmasını istedi. Mevcut durumda:

- Sekmeye girince boş "Merhaba" karşılaması + inline wizard paneli açılıyor.
- Wizard inline (sayfanın altında) — modal değil; kullanıcı dikkati dağılıyor.
- Tasarlanan raporlar (`dbsmart_saved_reports`) listelenmiyor; kullanıcı geçmiş
  tasarımına ulaşamıyor.
- Step indicator alanında `wizard.step.indicator` ham i18n key görünüyor
  → i18n bundle yüklü ama loader init edilmemiş.
- Step 3 (Filtre) display-only; chip-based filter builder yok.
- `/sources` endpoint boş döner (P0 bloker) → wizard hiçbir kaynağı seçemez.
- Alt sohbet input bar (textarea+attach+mic+send) Akıllı Veri Keşfi modunda
  semantik olarak alakasız ama görünmeye devam ediyor.

Kullanıcı kararları (alignment):
1. Karşılama mesajı kaldırılacak — mod seçilince doğrudan saved reports grid.
2. Wizard modal: merkezli 1100×720, mobile full-screen.
3. "Geçmiş Çözümler" sekmesi ayrı kalacak — Akıllı Veri Keşfi raporları
   orada GÖZÜKMEYECEK; ayrı bir kütüphanedir.
4. Kart action'ları: **Tekrar Çalıştır**, **Düzenle (wizard'da aç)**,
   **Kopyala (Farklı Kaydet)**, **Sil**, **Paylaş**.
5. Alt input bar bu modda gizlenecek.

## Hedef Akış (UX)

```
Ana Sayfa
  └─ "Akıllı Veri Keşfi" mode card tıklanır
       ├─ #dialogMessages temizlenir (karşılama yok)
       ├─ #dbSmartWizardPanel inline kullanılmaz (artık modal)
       ├─ .n-input-zone gizlenir
       └─ SavedReportsGrid main alana mount edilir
            ├─ Üst: arama input + kategori chip + "+ Yeni Keşif" CTA (sağ üst Yeni Soru Sor da tetikler)
            ├─ Boş: .vyra-empty-state ("Henüz keşif yapmadınız")
            └─ Kart × N (skeleton iken .skel-card)
                 ├─ başlık + 2 satır açıklama + metric badge
                 ├─ son çalıştırma: relative time + tooltip absolute ISO
                 └─ Tıklanınca → ReportDetailModal
                      ├─ Üst: ad + tarih + metric + tag
                      ├─ Orta: cached preview + SQL accordion
                      └─ Alt: Çalıştır · Düzenle · Kopyala · Paylaş · Sil

"+ Yeni Keşif" / "Yeni Soru Sor" → DbSmartWizardModule.openAsModal({onSave})
  └─ 5 adım modal (1100×720, mobile full-screen)
       ├─ ESC, overlay click, focus trap, return-focus
       └─ Bitir → POST /save-report → modal kapat → grid refresh
```

## Disjoint Paralel Dispatch (kontratlar)

| Ajan | Dosyalar | API kontratı (window globals) |
|------|----------|-------------------------------|
| **A** modal-wrapper | `frontend/assets/js/modules/db_smart_wizard.js`, `frontend/assets/css/modules/_db_smart_wizard.css`, `frontend/assets/js/i18n/loader.js` (bootstrap fix) | `DbSmartWizardModule.openAsModal({reportId?, onClose, onSave}) → Promise`, `closeModal()`, `init({mode:'modal'\|'panel'})` |
| **B** saved-reports-grid (YENİ) | `frontend/assets/js/modules/saved_reports_grid.js`, `frontend/assets/js/modules/report_detail_modal.js`, `frontend/assets/css/modules/_saved_reports_grid.css` | `SavedReportsGrid.mount(rootEl, {onOpenReport, onNewReport}) → instance`, `refresh()`, `unmount()`; `ReportDetailModal.open(reportId, {onEdit, onDuplicate, onDeleted, onRan}) → Promise` |
| **C** filter-modal (YENİ) | `frontend/assets/js/modules/db_smart_filter_modal.js`, `frontend/assets/css/modules/_db_smart_filter_modal.css` | `DbSmartFilterModal.open(columns, currentFilters) → Promise<filters\|null>` |
| **D** backend-fix | `app/api/routes/db_smart_api.py` (yalnızca `/sources`, `POST /saved-reports/{id}/duplicate`, listing kontrolü) | `GET /api/db-smart/sources` → `{items:[{id,name,db_type,connection_status}],count}`; `POST /api/db-smart/saved-reports/{id}/duplicate {name?}` → 201 `{id,name,...}` |
| **ZEUS** | `frontend/home.html`, `frontend/assets/js/i18n/aki_kesif_tr.json`, `_en.json`, `frontend/assets/js/app.js` (selectChatMode aki_kesif branch) | mode-card → modal trigger, input bar hide, grid mount, header "Yeni Soru Sor" wiring |

## Disjoint Garantisi

- Hiçbir ajan başka ajanın dosyasına dokunmaz.
- ZEUS `db_smart_wizard.js`'e dokunmaz (Ajan A'nın); sadece dışarıdan `openAsModal()` çağırır.
- `home.html` sadece ZEUS tarafından düzenlenir.
- Yeni CSS modülleri build pipeline'a (esbuild + dist bundle) ZEUS tarafından bağlanır.

## Kabul Kriterleri (TYCHE)

- [ ] Akıllı Veri Keşfi mod kartına tıkla → karşılama yok, alt input gizli, grid görünür
- [ ] Boş kullanıcıda `.vyra-empty-state` + CTA görünür
- [ ] Kart tıkla → detay modal açılır; Çalıştır/Düzenle/Kopyala/Paylaş/Sil çalışır
- [ ] "Yeni Soru Sor" (header) → wizard modal açılır; ESC ile kapanır; focus döner
- [ ] Wizard modal 1100×720 merkezli; viewport <768px full-screen
- [ ] Step indicator "Adım 1 / 5" olarak çevrilir — ham key görünmez
- [ ] Step 3 filtre modal: chip ekle/sil, operator seç, value gir, Uygula
- [ ] `GET /api/db-smart/sources` gerçek liste döner (RLS + permission filter)
- [ ] Kopya endpoint 201 + yeni report id döner; "Kopya - <ad>" pattern
- [ ] `dbsmart_saved_reports` Geçmiş Çözümler'de **görünmüyor**
- [ ] HEBE: modal aria-modal, role=dialog, focus trap, ESC, overlay click, return-focus
- [ ] Hiçbir hex sabit renk yok (var(--*) kullanımı)
- [ ] py_compile ve esbuild build başarılı

## Council Gate (post-merge)

- ARES: SQL injection (duplicate endpoint), XSS (kart render textContent), token leak yok
- TYCHE: regression — diğer 3 mod hâlâ çalışıyor
- HERMES: endpoint sözleşme; openAsModal Promise resolve garantisi
- HEBE: focus trap + ESC + return-focus manuel doğrulama
- HERA: README v3.33.0 entry + CHANGELOG

## Risk

- esbuild bundle rebuild gerekli — Ajan'ların değişikliği `dist/bundle.min.js`'e
  yansıyana kadar tarayıcıda görünmez. ZEUS dispatch sonrası rebuild eder.
- i18n loader fix Ajan A sorumluluğunda; başarısızsa step indicator hâlâ ham key.
