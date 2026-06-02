---
plan_id: ldap_save_error_visibility
created: 2026-06-02
branch: hira
status: completed
version_target: v3.59.0
closed: 2026-06-02
closure_note: "FAZ1: create boş bind_password → net 400; LDAP CRUD dördü try/except+log_exception → Hata İzleme görünürlüğü. FAZ2 (canlı traceback geldi): GERÇEK kök UniqueViolation ldap_settings_domain_key — domain UNIQUE soft-delete'i kapsamaz, pre-check is_deleted=FALSE → soft-silinmiş TURKCELL INSERT'te 500. FIX: create'te soft-deleted domain varsa CANLANDIR (revive UPDATE), + UniqueViolation→400 defans. FAZ3 (kullanıcı isteği): list include_deleted + POST /{id}/restore endpoint + frontend 'Silinenleri göster' toggle + line-through/muted satır + 'Geri Yükle' butonu. Code-review HIGH bulgu: onclick domain JS-string kaçışı yoktu (_esc HTML-only) → _jsAttr helper eklendi (delete+restore). 7 test geçti. bundle rebuild."
council_mod: 2
hebe_gate_required: false
---

# LDAP kaydetme 500 + Hata İzleme görünürlüğü

## Context
Kullanıcı LDAP sunucu kaydederken konsola hata aldı (görsel düşük çözünürlüklü, metin okunamadı).
Kod incelemesi (varsayım yapmadan):
- `ldap_settings` tablosunda company_id **var** (schema.py:744 ALTER startup'ta ekler; app çalıştığından
  koşmuş) → company_id sorunu DEĞİL.
- KÖK aday: `create_ldap_setting` try/except'siz; boş bind_password → `encrypt()` ValueError
  (encryption.py:85 "boş olamaz") → yakalanmamış 500.
- LDAP CRUD'un hiçbiri `log_exception` kullanmıyordu → hata Hata İzleme'ye düşmüyor, yalnız konsolda
  kalıyor (kullanıcının standing kuralı: "hataları göremezsek çözemeyiz" — v3.52.0).

## Faz/Gate (HEPHAESTUS + ARES)
- **G1 (HEPHAESTUS):** create'te boş/whitespace bind_password → encrypt'ten ÖNCE net 400.
- **G2 (HEPHAESTUS):** create/update/delete/test → try/except + log_exception (module=ldap_settings,
  request_path/method/user_id + context). HTTPException re-raise (4xx/404/400 korunur). generic → 500 detail.
- **G3 (ARES):** şifre context'e konmaz; log_exception zaten redact_sensitive uygular → sızıntı yok.
- **G4 (TYCHE):** py_compile + 5 odaklı test (boş-pwd 400 / db-error log+500 / http-exc swallow yok).
- **G5:** /code-review. **G6:** v3.59.0.

## Critical Files
- app/api/routes/ldap_settings.py (import + 4 endpoint try/except + boş-pwd guard)
- tests/test_ldap_settings_api.py (yeni)
- app/core/config.py (versiyon)

## Risk
| Risk | Mit |
|---|---|
| Şifre log'a sızar | context'e şifre konmaz + log_exception redact_sensitive |
| Bilinçli 4xx 500'e döner | except HTTPException: raise (ilk yakalama) |
| Anonymous bind isteyen kullanıcı | net 400 yönlendirir; anonymous bind ayrı feature (kapsam dışı) |

## Verification
- py_compile (ldap_settings + config + test).
- pytest tests/test_ldap_settings_api.py.
- /code-review.

## Out-of-scope
- company_id (zaten mevcut — değişiklik yok).
- Anonymous bind desteği (ayrı feature).
- Frontend (backend 500 + log görünürlüğü sorunuydu; FE değişmedi).
