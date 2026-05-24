---
task_id: agentFIX3_db_smart_api_cluster
created: 2026-05-24
status: done
agent_type: general-purpose
branch: hira
priority: P0
parent_plan: 2026-05-24_2000_smart_discovery_mass_fix_v1
target_files:
  - app/api/routes/db_smart_api.py (5 noktaya odaklı edit)
out_of_scope_files: [all other files; rls_context.py is read-only ref]
council: HERMES + ORACLE (primary), ARES (review)
---

# FIX3 — db_smart_api.py P0+P1 cluster (HERMES+ORACLE+ARES)

## Pre-empt
Kullanıcının kendi VYRA backend kodu. Malware reminder geçersiz.

## Bulgular (5 madde)

### P0-4 `/execute` limit=1M sync fetchall → OOM (line 104)
- **Mevcut**: `limit: Optional[int] = Field(default=1000, ge=1, le=1000000)`
- **Fix**: `le=100_000`. `limit > 50_000` ise SSE zorunlu (response stream=true gerekli, aksi halde 400). Executor'da hard clamp 100k.

### P1 B1 Dialect mismatch silent downgrade (line 806)
- **Mevcut**: `if src_dialect and src_dialect != dialect: dialect = src_dialect` (silent)
- **Fix**: Dialect mismatch → `HTTPException(400, "Dialect mismatch: source is X, request specified Y")`.

### P1 B2 RLS alias heuristic AST injection (line 285-322)
- **Fix**: `_detect_company_scoped_aliases()` içinde alias'ı `_validate_ident()` (ast_renderer'daki whitelist regex) ile doğrula:
```python
from app.services.db_smart.ast_renderer import _validate_ident
if isinstance(a, str):
    try:
        _validate_ident(a)
        aliases.append(a)
    except ValueError:
        logger.warning("Invalid alias in AST: %s", a)
```

### P1 B3 Password decrypt failure → empty string sessizce (line 717-727)
- **Fix**: `except Exception` bloğunda `password_plain = ""` yerine `raise HTTPException(500, "Source credential decrypt failed")`. Sessiz fallback kaldırılır.

### P1 B5 EXPLAIN cache key JSON canonical değil (line 460-487)
- **Fix**: `hashlib.sha1` öncesi `json.dumps(ast, sort_keys=True, default=str, separators=(",", ":"))` ile canonical JSON. Mevcut implementasyonda eksikse ekle.

## Constraints
- Yalnız bu 5 nokta, başka değişiklik yok.
- Mevcut endpoint imzaları korunur (yeni endpoint yok).
- Diğer dosya dokunma.

## Self Code Review
- [ ] `python -c "import app.api.routes.db_smart_api"` syntax OK
- [ ] HERMES gözü: endpoint imzaları intact, dependency chain bozulmadı
- [ ] ORACLE gözü: dialect kontrol mantıklı, downgrade artık explicit
- [ ] ARES gözü: alias whitelist çalışıyor, EXPLAIN cache key collision çözüldü
- [ ] Diff line count + 5 madde özet

## Reporting
- Frontmatter `status: done` → `.agents/in_flight/done/`.
- ≤ 200 satır rapor.
