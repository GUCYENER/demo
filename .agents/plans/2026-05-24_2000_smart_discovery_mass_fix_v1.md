---
plan_id: 2026-05-24_2000_smart_discovery_mass_fix_v1
created: 2026-05-24 20:00
branch: hira
version_target: v3.35.0
parent_audit: 2026-05-24_smart_discovery_findings.md
council_mod: 3 (multi-agent parallel implementation)
hebe_gate_required: true
status: dispatching
---

# Plan — Akıllı Veri Keşfi Mass Fix Sprint (v3.35.0)

## 0. Bağlam

Audit raporu ([`.agents/audits/2026-05-24_smart_discovery_findings.md`](../audits/2026-05-24_smart_discovery_findings.md)) 65 bulgu çıkardı: 4 P0, 21 P1, 26 P2, 14 P3.

Kullanıcı talebi: "herbir sorunu detaylı incele ekip ile düzeltme planı hazırla alt ajana ver. hepsini bu şekilde düzenle ve tamamla. bekleyen iş kalmasın. code review yapsın hepsi."

→ **11 paralel fix ajan** (P0 + P1 = 25 madde) + **1 refactor-tracker** (P2 + P3 = 40 madde → backlog R019-R058). Tüm ajanlar disjoint file scope (§5e.2). Her ajan self code review zorunlu.

## 1. Gate-Konsey Eşleştirme Tablosu (§5e.2b zorunlu)

| Gate | Sorumlu Konsey | Brief | Disjoint Dosyalar |
|---|---|---|---|
| **G1 — FIX1** | ARES (primary), HERMES (review) | agentFIX1_saved_reports_sql.md | `app/services/db_smart/saved_reports.py` |
| **G2 — FIX2** | METIS + PROMETHEUS (primary), ARES (review) | agentFIX2_deep_think_p0_cluster.md | `app/services/deep_think_service.py` |
| **G3 — FIX3** | HERMES + ORACLE (primary), ARES (review) | agentFIX3_db_smart_api_cluster.md | `app/api/routes/db_smart_api.py` |
| **G4 — FIX4** | ORACLE + POSEIDON (primary), HERMES (review) | agentFIX4_dialect_dictionary.md | `app/services/db_smart/dialect_dictionary.py` |
| **G5 — FIX5** | ATHENA + HEBE (primary), TYCHE (review) | agentFIX5_wizard_state_cluster.md | `frontend/assets/js/modules/db_smart_wizard.js`, `db_smart_ast_editor.js`, `db_smart_ast_history.js` |
| **G6 — FIX6** | ATHENA + HEBE (primary), NIKE (review) | agentFIX6_picker_abort.md | `frontend/assets/js/modules/db_smart_picker.js` |
| **G7 — FIX7** | HEBE + ATHENA (primary) | agentFIX7_filter_modal.md | `frontend/assets/js/modules/db_smart_filter_modal.js` |
| **G8 — FIX8** | HEBE + ATHENA (primary) | agentFIX8_css_polish.md | `frontend/home.html` (sadece Akıllı Keşif bölgesi), `frontend/assets/css/modules/_db_smart_wizard.css` |
| **G9 — FIX9** | TYCHE + ARES (primary) | agentFIX9_tests.md | `tests/db_smart/test_rls_integration.py` (NEW), `test_ast_round_trip.py` (NEW), `test_session_cache_isolation.py` (NEW), `test_migration_032_rls.py` (NEW) |
| **G10 — FIX10** | NIKE + HEPHAESTUS (primary), ARES (review) | agentFIX10_perf_infra.md | `app/services/db_smart/fk_graph.py`, `learning_recorder.py`, `migrations/versions/046_*.py` (NEW) |
| **G11 — FIX11** | METIS + NIKE (primary) | agentFIX11_llm_resilience.md | `app/core/llm.py` |
| **G12 — REFACTOR-TRACKER** | HERA + (refactor-tracker subagent) | (otomatik) | `.agents/refactor/REFACTOR_BACKLOG.md` (append R019-R058) |
| **G13 — Bundle + Commit** | ZEUS | (orchestrator) | `frontend/dist/*` rebuild + commit |

## 2. Disjoint Scope Doğrulama Matrisi

| Dosya | FIX1 | FIX2 | FIX3 | FIX4 | FIX5 | FIX6 | FIX7 | FIX8 | FIX9 | FIX10 | FIX11 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| saved_reports.py | ✅ | — | — | — | — | — | — | — | — | — | — |
| deep_think_service.py | — | ✅ | — | — | — | — | — | — | — | — | — |
| db_smart_api.py | — | — | ✅ | — | — | — | — | — | — | — | — |
| dialect_dictionary.py | — | — | — | ✅ | — | — | — | — | — | — | — |
| db_smart_wizard.js | — | — | — | — | ✅ | — | — | — | — | — | — |
| db_smart_ast_editor.js | — | — | — | — | ✅ | — | — | — | — | — | — |
| db_smart_ast_history.js | — | — | — | — | ✅ | — | — | — | — | — | — |
| db_smart_picker.js | — | — | — | — | — | ✅ | — | — | — | — | — |
| db_smart_filter_modal.js | — | — | — | — | — | — | ✅ | — | — | — | — |
| home.html (Akıllı Keşif) | — | — | — | — | — | — | — | ✅ | — | — | — |
| _db_smart_wizard.css | — | — | — | — | — | — | — | ✅ | — | — | — |
| tests/db_smart/ (NEW) | — | — | — | — | — | — | — | — | ✅ | — | — |
| fk_graph.py | — | — | — | — | — | — | — | — | — | ✅ | — |
| learning_recorder.py | — | — | — | — | — | — | — | — | — | ✅ | — |
| migrations/046_*.py (NEW) | — | — | — | — | — | — | — | — | — | ✅ | — |
| app/core/llm.py | — | — | — | — | — | — | — | — | — | — | ✅ |

**Disjoint OK** — hiçbir dosya 2 ajan tarafından düzenlenmiyor.

## 3. Self Code Review Çıktısı (her ajan zorunlu)

Her ajan brief sonunda **Self Code Review** bölümünü doldurur:
- ✅ Lint/syntax check geçti (`python -c` veya `node --check`)
- ✅ Etkilenen fonksiyon başına test (varsa) çalıştırıldı
- ✅ Konsey rolü (ARES/HEBE/TYCHE vb.) perspektifinden bulguları kontrol etti
- ✅ Yeni bir P0/P1 issue ekledi mi (regression risk)
- ✅ XSS/SQL injection/auth bypass kontrol (uygulanabilirse)
- ✅ A11y/aria/focus kontrol (frontend ise)
- ✅ Diff line count + dosya listesi

## 4. Bundle + Commit Stratejisi

- Her fix ajanı bitince frontmatter `status: done` + `.agents/in_flight/done/` taşı.
- Tüm 11 fix bittikten sonra ZEUS:
  1. `node frontend/build.mjs` (bundle rebuild)
  2. `git diff --stat` ile değişiklik özeti
  3. Tek commit: `feat(v3.35.0): smart discovery P0+P1 mass fix (11 ajan)` veya gerekirse 2-3 commit (FE / BE / tests)
  4. Refactor-tracker output'u ayrı commit (`chore: REFACTOR_BACKLOG R019-R058`)

## 5. Out-of-Scope

- P2/P3 40 madde → refactor-tracker'a devredildi, **bu sprint kod değişikliği yok**, sadece backlog'a yazılıyor.
- AGENT-B picker enhancements (önceki deferred) → bu sprint kapsamı değil, ayrı plan.
- Versiyon bump (`v3.34.2 → v3.35.0`) commit message'da işaretlenir.

## 6. Risk

- 11 paralel ajan → yüksek concurrent, ancak disjoint dosya scope ile çakışma yok.
- Malware-reminder refusal riski (özellikle deep_think_service.py 3731 LOC) → tüm brief'lerde pre-empt clause var.
- ROI: P0 fix'leri olmadan production'a çıkamayız (SQL injection + prompt injection + token overflow).

## 7. Council Gate Review (G13 öncesi)

ZEUS her ajan output'una konsey gözüyle bakar:
- ARES: SQL/XSS/auth bypass regression yok mu?
- HEBE: a11y/aria koruması kaldı mı?
- TYCHE: var olan testler hâlâ yeşil mi?
- NIKE: perf regresyonu (cache miss, N+1) yok mu?

Bulunursa → ajana feedback ile re-dispatch (1 retry).

## 8. Rollback

Her FIX#'in dosya listesi farklı — bir ajan başarısız olursa **sadece o ajanın dosyaları** revert edilir, diğerleri ship'lenir.
```bash
git checkout HEAD -- <ilgili dosyalar>
```
