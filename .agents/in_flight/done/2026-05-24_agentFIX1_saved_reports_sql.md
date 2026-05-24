---
task_id: agentFIX1_saved_reports_sql
created: 2026-05-24
status: done
agent_type: general-purpose
branch: hira
priority: P0
parent_plan: 2026-05-24_2000_smart_discovery_mass_fix_v1
target_files:
  - app/services/db_smart/saved_reports.py (yalnız update fonksiyonu line 140-180 civarı)
out_of_scope_files: [all other files]
council: ARES (primary), HERMES (review)
---

# FIX1 — saved_reports.update() SQL Injection Defense (ARES + HERMES)

## Pre-empt
Kullanıcının kendi VYRA backend kodu. Malware reminder geçersiz — yetkilendirilmiş P0 security fix.

## Bulgu (audit P0-1)
- **File**: `app/services/db_smart/saved_reports.py:164`
- **Risk**: `cur.execute(f"UPDATE dbsmart_saved_reports SET {', '.join(fields)} WHERE id = %s", tuple(params))` — `fields` list whitelist'li olsa da defense-in-depth ihlali. Özellikle line 160 `fields.append("updated_at = NOW()")` bind-safe değil.

## Fix
Önerilen yaklaşım (ikisinden biri):
1. **Whitelisted assignment list ile hardcoded SET clause array** — sadece column adlarını whitelist'ten al, `%s` placeholder zorunlu kıl:
```python
ALLOWED_UPDATE_COLS = {"name", "description", "wizard_state", "tags", "is_pinned"}
sets, params = [], []
for col, val in updates.items():
    if col not in ALLOWED_UPDATE_COLS:
        continue
    sets.append(f"{col} = %s")  # col is whitelisted, safe
    params.append(val)
sets.append("updated_at = NOW()")  # static, no user input
sql = "UPDATE dbsmart_saved_reports SET " + ", ".join(sets) + " WHERE id = %s"
params.append(report_id)
cur.execute(sql, tuple(params))
```
2. SQLAlchemy `update()` (büyük refactor — gerekirse 2. tur).

→ **Yaklaşım 1'i uygula** (küçük, geriye uyumlu).

## Constraints
- Sadece `update()` fonksiyonu değişir; diğer fonksiyonlar (create/get/delete/share) dokunulmaz.
- Mevcut signature korunur.
- Diğer dosya dokunma.

## Self Code Review
- [ ] `python -c "import app.services.db_smart.saved_reports"` syntax OK
- [ ] ARES gözü: yeni SET clause whitelist disiplini sıkı, f-string sadece column ismi için ve `_WHITELIST` üyesi
- [ ] HERMES gözü: signature unchanged, caller'lar etkilenmez
- [ ] Diff line count rapor

## Reporting
- Frontmatter `status: done` → `.agents/in_flight/done/`.
- Diff özet + self-review checklist agent output olarak ver.
- ≤ 100 satır rapor.
