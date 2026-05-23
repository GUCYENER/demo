---
task_id: 2026-05-23_plan_naming_steward
status: completed
agent_type: general-purpose
target_files:
  - .agents/plans/*.md
  - .agents/workflows/vyrazeus.md
started_at: 2026-05-23 14:30
completed_at: 2026-05-23
outcome: success
---

## Brief

`.agents/plans/` dizinindeki yeni plan dosyaları için bir naming convention kabul edildi:

**`YYYY-MM-DD_HHMM_<slug>_v1.md`**

Örnek: `2026-05-23_1430_bulk_enrichment_endpoints_v1.md`

Bu agent'ın görevleri:

### 1. Convention'ı vyrazeus.md workflow dökümanına ekle

`.agents/workflows/vyrazeus.md` içine (uygun bir bölüme — plan oluşturma / artifact yönetimi neresiyse) aşağıdaki kuralı yaz:

- Yeni plan dosyaları **mutlaka** `YYYY-MM-DD_HHMM_<slug>_v1.md` formatında olur
- Plan revize edilirse eski dosya silinmez; `_v2`, `_v3` olarak yeni dosya açılır (history korunur)
- Eski (tarih-prefix'i olmayan) dosyalar **retro-rename edilmez** — git log --follow ile bulunur
- Frontmatter `created:` field'ı ISO tarih taşımaya devam eder (filename ile redundant ama her ikisi de tutulur)

### 2. Eski plan dosyalarını listele (sadece RAPOR, RENAME ETME)

`.agents/plans/*.md` içinde tarih prefix'i olmayan dosyaların listesini çıkar. Bu bilgi gelecekte referans için lazım. Liste formatı:

```
- <filename> | git log first commit date | son güncellenme
```

### 3. Workflow file'a "Plan Naming Steward" rolünü ekle (opsiyonel)

Eğer vyrazeus.md'de council üyelerine yeni rol eklemek mantıklıysa, "HERA" (docs/process kapısı) altına bu kontrolü ekle: "Yeni plan dosyası convention'a uygun mu, değilse blokla".

## Expected artifacts

- `.agents/workflows/vyrazeus.md` içinde naming convention bölümü
- Eski plan dosyaları listesi (bu brief'in "Notes" kısmına yazılabilir)
- Convention'a uymayan yeni dosya commit'lerini engelleyecek pre-commit önerisi (varsa) — sadece öneri, otomatik kurma

## Notes

- User talebi: 2026-05-23 — plan oluştururken tarih+saat+v1 kodu olsun ki kronolojik takip yapılabilsin
- Bu agent retro-rename YAPMAZ; sadece kural yazar + envanter çıkarır
- İlk uygulama örneği: `2026-05-23_1430_bulk_enrichment_endpoints_v1.md` (bu brief yazılırken zaten convention'a uygun yaratıldı)

### Steward Execution Log (2026-05-23)

**Task 1 — Convention'ı vyrazeus.md'ye yazdım:** Bölüm 5d ("Dosya Adı Kuralı") tamamen yeniden yazıldı. Format `YYYY-MM-DD_HHMM_<slug>_v1.md`, revizyonlar `_v2/_v3`, eski dosyalar retro-rename edilmez. HERA naming guard regex'i ve opsiyonel pre-commit shell snippet (otomatik kurulmadı — sadece öneri) eklendi.

**Task 3 — HERA rolü güncellendi:** Bölüm 2 konsey tablosunda HERA satırına "plan dosyası naming guard" sorumluluğu eklendi (Bölüm 5d'ye referansla).

**Task 2 — Tarih-prefix'siz plan dosyaları envanteri (RETRO-RENAME YOK):**

`.agents/plans/` altında convention'a uymayan 13 dosya tespit edildi. `2026-05-23_1430_bulk_enrichment_endpoints_v1.md` zaten yeni formatta — envanter dışı.

| Dosya | İlk commit | Son güncelleme | Amaç (1 cümle) |
|-------|-----------|----------------|----------------|
| `Test_Senaryolari.md` | 2026-05-17 | 2026-05-17 | Faz sonu regresyon + E2E test senaryoları (TYCHE owner, canlı doküman). |
| `agentic_sql_copilot_master_plan.md` | 2026-05-17 | 2026-05-21 | Agentic SQL Copilot çok-fazlı master plan (LangGraph + multi-signal + RLS + CatBoost). |
| `mempalace_refresh_guard.md` | 2026-05-23 | 2026-05-23 | MemPalace `wakeup_context` bayat içerik dönüyor — boot-time freshness guard (CRAZYMEMPLC owner). |
| `poseidon_discovery_comment_audit.md` | 2026-05-17 | 2026-05-18 | Discovery pipeline'ın native DB comment metadata'sını (PG/Oracle/MSSQL/MySQL) okumadığı bulgusu ve fix planı. |
| `v3.19_ui_polish.md` | 2026-05-18 | 2026-05-18 | v3.17/v3.18 yetkilendirme modalı ve sistem panelini SaaS UX standartlarına çıkaran HEBE polish planı. |
| `v3.27_db_learning_loop.md` | 2026-05-18 | 2026-05-18 | DB Learning Loop (Faz A+B+C) — veritabanı tabanlı öğrenme döngüsü, completed. |
| `v3.28_faz5_kalani.md` | 2026-05-18 | 2026-05-18 | Master plan Faz 5'in 4 spesifik boşluğunu (G1-G4) kapatma planı, kısmi tamamlandı. |
| `v3.29.10_housekeeping_ve_bug_fix.md` | 2026-05-19 | 2026-05-19 | v3.29.10 housekeeping (36 dosya) + iki live bug fix, completed. |
| `v3.29.11_dedupe_pgvector_guard.md` | 2026-05-19 | 2026-05-19 | OnedeskTest'te FK loop poison-recovery + dedupe Layer-2 pgvector guard, completed (commit 88aed91). |
| `v3.29.7_faz6_eksik_implementasyon.md` | 2026-05-19 | 2026-05-19 | Faz 6 master planının 5 kritik boşluğunu kapatma (binary-hugging-bengio çerçevesi), done. |
| `v3.29.8_signal_weight_tuner.md` | 2026-05-19 | 2026-05-19 | `multi_signal_rank` 7-sinyal ağırlıkları için admin-gated 3-katmanlı oto-tuning, completed (5ad3828). |
| `v3.29.9_fk_inference.md` | 2026-05-19 | 2026-05-19 | FK Inference Layer — convention + sample validation, 4 dialect (PG/Oracle/MSSQL/MySQL), completed (1b4dced). |
| `v3.30.0_db_smart_wizard.md` | 2026-05-19 | 2026-05-21 | "Akıllı Veri Keşfi" wizard tarzı multi-DB SQL copilot (Prompt A-J) — 15 paralel subagent Wave1+2, in_progress. |

**Pre-commit önerisi:** Bölüm 5d içine shell snippet eklendi, OTOMATİK kurulmadı (brief talebine uygun). Kullanıcı isterse `.git/hooks/pre-commit`'e ekleyebilir.
