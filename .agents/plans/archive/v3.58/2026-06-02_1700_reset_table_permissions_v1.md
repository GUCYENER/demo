---
plan_id: reset_table_permissions
created: 2026-06-02
branch: hira
status: completed
version_target: v3.58.0
closed: 2026-06-02
closure_note: "system.py reset'e data_source_table_permissions + data_source_permissions (source-scoped, users'tan önce, guard+count) + frontend liste/onay 'Tablo Yetkilendirmeleri'. bundle rebuild. Code-review TEMİZ (FK sırası/scope/auth/transaction), 6 reset testi geçti. system_logs/sql_audit_log zaten reset'teydi (doğrulandı)."
council_mod: 2
hebe_gate_required: true
---

# Sistem Sıfırlama'ya tablo-yetki tablolarını ekle

## Context
Kullanıcı: Parametreler → Sistem Sıfırlama'da "tablo yetki ve sistem log tablolarını da sıfırlama
listesine al". İnceleme: system_logs (system.py:340) + sql_audit_log (335) ZATEN reset'te + display'de
(section_parameters.html:187/189). EKSİK olan: data_source_permissions + data_source_table_permissions
(tablo-yetki) — ne backend reset'te ne display'de → yetki grant'ları reset'i atlatıp kalıyor.

## Faz/Gate (HEPHAESTUS + ARES + ATHENA)
- **G1 (HEPHAESTUS):** system.py reset'e data_source_table_permissions + data_source_permissions
  DELETE (source-scoped: company_id varsa source_id IN company's sources). users silinmeden ÖNCE
  (FK subject_id→users ihlali önle). information_schema guard + count (mevcut desen).
- **G2 (ATHENA+HEBE):** section_parameters.html "Silinecek Veriler"e "Tablo Yetkilendirmeleri" satırı;
  system_manager.js:401 confirm mesajına "tablo yetkileri" ekle.
- **G3:** bundle rebuild (JS değişti).
- **G4 (TYCHE):** py_compile + reset testi (varsa) + node -c.
- **G5:** /code-review medium. **G6:** v3.58.0.

## Critical Files
- app/api/routes/system.py (reset perm-table block)
- frontend/partials/section_parameters.html (Silinecek liste)
- frontend/assets/js/system_manager.js (confirm mesajı) + dist (rebuild)
- app/core/config.py (versiyon)

## Risk
| Risk | Mit |
|---|---|
| FK ihlali (subject_id→users) | grant'lar users'tan ÖNCE silinir |
| data_sources silinir sanılır | KORUNUR — yalnız grant satırları silinir (data_sources'a dokunulmaz) |
| company-scoped cross-tenant | source_id IN (company's sources) filtresi |
| Güvenlik | reset zaten admin-only + destructive + geri-alınamaz uyarılı; grant reset tutarlı |

## Verification
- py_compile system.py + node -c system_manager.js + build exit 0.
- reset SQL: perm tablolar source-scoped, users'tan önce, count'lu.
- /code-review medium.

## Out-of-scope
- sistem log tabloları (zaten reset'te + display'de — değişiklik yok, doğrulandı).
</content>
