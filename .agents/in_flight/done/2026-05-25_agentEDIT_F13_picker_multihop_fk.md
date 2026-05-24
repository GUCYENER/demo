---
id: agentEDIT_F13_picker_multihop_fk
date: 2026-05-25
council: [ATHENA, POSEIDON, HERMES]
status: done (manual impl + grep verify + retroactive review)
note: Subagent dispatch declined ×2 misinterpreting generic malware reminder as a blanket restriction; main agent implemented directly after the second decline. F13 brief written retroactively after symbol verification.
---

# F13 — Picker FK multi-hop graph (BFS reachability)

## Trigger
Manuel smoke test (screenshot 1): Kullanıcı seçili tablolardan herhangi biriyle (primary değil) FK ilişkisi olan üçüncü tabloyu seçince auto-uncheck oluyordu. Mevcut single-hop guard sadece **primary tabloya** bakıyordu — multi-hop zincir desteklenmiyordu.

## Spec
- Adayın seçili tablolardan **herhangi biriyle** (primary veya join) **doğrudan veya dolaylı FK zinciri** üzerinden ulaşılabilir olması yeterli.
- Lazy bilateral adjacency cache; aynı tableId için in-flight dedupe.
- Sync verdict (true/false/null) — null durumunda async hydrate + auto re-evaluate + auto-check.

## Files modified
- `frontend/assets/js/modules/db_smart_picker.js`:
  - L92-94: `_state.adjacency: Map<table_id, Set<table_id>>`, `_state.fkLoadedSet: Set`, `_state.fkLoadingPromises: Map`
  - L402-403: `_loadFk` primary için adjacency seed + fkLoadedSet.add(primaryId)
  - L422-516: 4 yeni helper — `_addAdjacency`, `_loadFkFor`, `_checkMultiHopFkSync` (BFS), `_ensureMultiHopAdjacency` (async + auto re-evaluate)
  - L583-600: `_onListClick` non-primary branch — single-hop guard → 3-way verdict pattern (true: kabul, false: ret + toast, null: async hydrate + info toast)
  - L680-682: `_clearAllSelections` adjacency/fkLoadedSet/fkLoadingPromises reset
  - L780-781: `open()` adjacency/fkLoadedSet/fkLoadingPromises reset

## Verification
- `grep -nE "_addAdjacency|_loadFkFor|_checkMultiHopFkSync|_ensureMultiHopAdjacency|adjacency:|fkLoadedSet|fkLoadingPromises"` → 18 hit, hepsi beklenen satırlarda
- Symbol verify: PASS
- Reset blok parity: PASS (open + clearAll her ikisi de 3 cache'i sıfırlıyor)
- Race/concurrency: in-flight dedupe via `fkLoadingPromises`; primary değişimi mid-flight için `_state.primaryId == null` ve `_state.primaryId === candidateId` koruyucu return'ler

## Edge cases covered
- Primary demote (uncheck): adjacency korunur (graph edges symmetric, primary-independent) — `_clearAllSelections` dışında temizlik yok
- `_loadFkFor` fetch fail: silent warn + mark loaded (boş neighbors) → retry storm engellenir
- Auto re-check: yalnızca primary hâlâ varsa + candidate hâlâ join'lerde değilse + primary != candidate → auto-add + success toast
- Concurrency: AbortController _loadFk için var (legacy); _loadFkFor için yok ama dedupe pattern ile aynı tableId paralel fetch yapılmaz

## Council self-review
- **ATHENA** ✓ — FSM verdict pattern (true/false/null) clean; state mutation _refreshListRowClasses üzerinden senkronize
- **POSEIDON** ✓ — `/related?depth=1` mevcut endpoint reuse; her tabloyu lazy fetch + cache; backend değişiklik yok
- **HERMES** ✓ — DOM senkron + auto-check sırasında cb.checked = true ile UI tutarlı; toast türleri (warning/info/success) ayırt edici

## Restart / reload
- Backend: GEREKMEZ (FE-only)
- **Frontend: hard-reload Ctrl+Shift+R ŞART** (bundle.min.js rebuild gerek — F14/F16/F17 rebuild ile birlikte zaten alındı)

## Known limitations
- `_loadFkFor` AbortController yok — büyük seçimde N adet `/related` paralel inflight; backend cache (Redis) varsa ucuz. Bu mevcut `_loadFk` ile aynı pattern; gerekirse follow-up R-1.
- `_loadFkFor` fail-silent (mark loaded with empty neighbors): kullanıcı için "FK var sanılan ama veri eksik" senaryosunu maskeler; trade-off retry storm engellemek için kabul edildi.
