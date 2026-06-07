---
plan_id: backlog_tamamlama_master
created: 2026-06-07
branch: hira
status: completed
council_mod: 2
note: Kullanıcı "bekleyenlerin tamamını sırayla yap, eksik kalmasın; her birini gstack-review + sonunda arşive al; ekip ile planla başla". 3 paralel grounding-ajanı (council) A-temasını gerçek koddan haritaladı. TÜM iş TOPLAMSAL (çalışan kodu bozma) — mevcut akış değişmez, yalnız rozet/öne-çıkarma/guard EKLENİR.
---

# Bekleyen Backlog Tamamlama — Master (A→B→C)

## Yaklaşım
- Sıra: **A (Akıllı Keşif şeffaflık, en yüksek değer)** → **B (error-log hijyen)** → **C (TEMA-2 cevap doğruluğu)**.
- Her tema bitince **gstack-review** (adversarial); sonra ilgili plan(lar) **arşive** (`archive/v3.78.x/`).
- Sürüm: tema-başı bump (A=v3.78.2, B=v3.78.3, C=ayrı). Backend değişen temada restart.
- **çalışan kodu bozma:** her madde additive; mevcut başarı/akış yolları DEĞİŞMEZ.

## TEMA A — Akıllı Keşif Şeffaflığı (grounding: 3 ajan, gerçek-kod doğrulandı)
| # | İş | Boşluk (grounded) | Dosya | Risk |
|---|---|---|---|---|
| **1.3** | Hard-fail sebebini SON-KULLANICIYA göster | Backend TAM döndürüyor; soft-fallback zaten gösteriyor (R1). Tek boşluk: `success=false` dalı sebebi "Teknik detay" `<details>`'inde gizliyordu | `db_smart_wizard.js` `_openResultModal` 2497 | düşük (FE-only) |
| **1.4** | Kısmi-kayıp: FK-eksik rozeti + Yeniden Öğren | Kapsama rozeti + relearn buton/endpoint ZATEN var. Tek boşluk: per-tablo "FK eksik" rozeti (data plumbing) | `ds_enrichment_service.get_all_tables_status` (+ds_fk_diagnostics GROUP BY) + `ds_enrichment_module.js` 601/615 + `ds_enrichment.css` | düşük (backend query additive + 1 badge) |
| **G8a** | FK provenance rozetleri (observability tab) | 3-tier verisi (`evidence_json.to_pk_source`=unique_index/declared/inferred)+confidence ZATEN persist+API'de | `fk_inference_observability.js` `_renderPendingTable` 136 + `section_agentic_observability.html` + `fk_inference.css` | düşük (FE-only) |
| **G8a+** | (aynı pass) stats-card pre-existing bug | JS `*_count/total/avg` okuyor ama endpoint `{stats:{declared,...}}` döndürüyor → kartlar 0 görünüyor (BUG) | `fk_inference_observability.js` 80-86,250 | düşük (mevcut bozuk → düzeltme) |
| **G8b** | Join-picker'da "çıkarım" işareti | Backend blocker: `/related` graph SELECT'i is_inferred/to_pk_source SEÇMİYOR | `fk_graph.py` build_subgraph SELECT 298/341/413 + `db_smart_api.related_tables` + `db_smart_picker.js` 399 + `db_smart_wizard.js` 462 | orta (backend SELECT additive + FE) |

**A-Gate:** 1.3→1.4→G8a→G8b → gstack-review (adversarial) → sürüm v3.78.2 → arşiv.

## TEMA B — Error-log hijyen (düşük-aciliyet; sessiz-fail sınıfını sistemik keser)
| # | İş | Amaç |
|---|---|---|
| G3-res | ~110 non-cleanup `except: pass` batched triyaj | gizli-hata saklayan var mı → log'a düşür |
| G4 | ~141 meşru cleanup'a `# noqa: S110 — intentional: <sebep>` | kasıt-belge (kodda şu an 0 noqa) |
| G5 | ruff S110/S112 ratchet guard | YENİ sessiz-yutmayı engelle (kalıcı kalkan) |
| G6 | örnek hata enjekte → errors.jsonl tip+traceback doğrula | loglama hattı gerçekten çalışıyor mu |

**B-Gate:** G3→G4→G5→G6 → gstack-review → v3.78.3 → error_logging planını arşive.

## TEMA C — Cevap doğruluğu (TEMA-2, en büyük etki/efor)
- 2.1 deterministik join-path skorlama (cardinality/selectivity top-N FK), 2.3 belirsiz-soru clarify (N aday SQL).
- **ÖNCE ayrı `/plan-eng-review` + council** (smart_discovery planı zaten bunu şart koşuyor) → Tema-1 ölçüm aracı → implement → review → smart_discovery'yi arşive.

## İlerleme Kaydı
- [x] **1.3** hard-fail sebebi öne çıkar (`_openResultModal` error dalı; role=alert + "Sebep:" inline; Teknik-detay-gizleme kaldırıldı) — toplamsal
- [x] **1.4** FK-eksik rozeti — backend `get_all_tables_status`'a `ds_fk_diagnostics` GROUP BY merge (coverage deseni, fail-safe) + FE `fkBadge` (mor-mavi) + CSS; aksiyon = MEVCUT "Yeniden Öğren" (yeni endpoint yok) — additive
- [x] **G8a** observability: per-FK provenance rozeti (🔒declared/🟢unique-index/🟡çıkarım, `evidence_json.to_pk_source`) + "Kaynak" kolonu + confidence renk (`_confClass`) + **stats-card BUG FIX** (JS `resp.stats` nested okuyordu yanlış → kartlar 0; backend `avg_inferred_confidence` eklendi). NOT: grounding-ajan stats bug'ını yanlış endpoint'e bağlamıştı; gerçek `/fk-inference-stats`'tan doğrulayıp düzelttim (varsayım yok).
- [x] **G8b** join-picker çıkarım işareti — `expand_with_fk`'e AYRI fail-soft provenance query (graph-builder'a DOKUNULMADI) + picker map+render 🟡çıkarım + CSS. declared/unique-index → işaret yok (güvenilir).
- [x] **A-gate**: gstack-review (2 ajan — TÜM değişiklik SAĞLAM; 1 düşük G8b-rollback bulgusu düzeltildi) + sürüm **v3.78.2** ✅. Arşiv: tema B+C bitince (hata_izleme_backlog planı B/C maddelerini de tutuyor).
- [x] **TEMA B** — **G3-res** verified-clean (triage-ajan 148 swallow + ZEUS 7 savepoint sitesi tek tek okudu → SIFIR gerçek gizli-hata yutma; gerçek hatalar zaten logger.exception/log_exception/summary.errors/HTTP-500 ile loglanıyor). **G6 PASS** (örnek ValueError enjekte → errors.jsonl `msg`+`exc_type`+467-char `traceback`[_inner/_outer frame]+`level=ERROR` yakaladı; test satırı temizlendi, production log kirletilmedi). **G4/G5 (noqa annotation + ruff S110/S112 ratchet) ERTELENDİ** — kullanıcı kabulü "önerine göre ilerle" (= G3+G6 değer-kısmı; 272-noqa süpürme şimdilik atla). **Kod değişikliği YOK → gstack-review gereksiz (review edilecek diff yok), sürüm bump YOK (v3.78.2 korunur; kod-yok-durum yanıltıcı versiyon vermez).**
- [x] **TEMA C (TEMA-2)** — 2.1 Dilim-1 (join-weighting v3.78.3, f6c2be6) + 2.3 Dilim-2 (metrik-clarify deep_think v3.79.0, c4ee9b3) shiplendi; her biri plan-eng-review + council + /code-review + /gstack-review (adversarial F1/golden-cache regresyonları yakalandı→düzeltildi). 2.2/2.4 scope'lanmadı → smart_discovery referans.
