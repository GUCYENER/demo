---
task_id: 2026-05-23_plan_naming_steward
status: queued
agent_type: general-purpose
target_files:
  - .agents/plans/*.md
  - .agents/workflows/vyrazeus.md
started_at: 2026-05-23 14:30
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
