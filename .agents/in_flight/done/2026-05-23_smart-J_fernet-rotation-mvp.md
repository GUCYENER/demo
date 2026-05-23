---
status: done
agent: smart-J
version: v3.32.0
target_files:
  - migrations/versions/041_v3320_fernet_key_version.py
  - app/services/security/credentials.py
  - app/services/security/__init__.py
  - scripts/rotate_fernet_credentials.py
started_at: 2026-05-23
completed_at: 2026-05-23
defers_to: v3.33 (auto-scheduler / cron)
---

# Ajan-J — Fernet Credential Rotation Infrastructure (MVP)

## Brief

`data_sources.db_password_encrypted` Fernet ile şifreli, fakat key rotation
mekanizması yoktu. MVP olarak: kolon ekle + multi-key wrapper + manuel CLI
script. Otomatik scheduler v3.33'e ertelendi.

## Report

### Keşif Bulguları
- **Mevcut Fernet wrapper:** `app/core/encryption.py` (DB-stored single key,
  `system_settings.ENCRYPTION_KEY`). Bu modülün signature'ı korunmuştur,
  hiç değişiklik YAPILMAMIŞTIR (disjoint scope kuralı).
- **Brief'teki yol:** `app/services/security/credentials.py` mevcut değildi;
  Ajan-J **yeni bir paralel wrapper** olarak oluşturuldu. Env-based
  multi-key (`VYRA_FERNET_KEYS`) + legacy fallback (`VYRA_FERNET_KEY`).
- **Şifre kolonu:** Brief "password" diyor; gerçek isim
  `data_sources.db_password_encrypted` (mig 002'de tanımlı). Script bu
  ismi kullanır.
- **`deleted_at` yok:** Brief örneğinde `WHERE deleted_at IS NULL`
  geçiyor; `data_sources` tablosunda böyle bir kolon yok. Script
  `db_password_encrypted IS NOT NULL AND <> ''` filtresi kullanır.
- **Alembic head:** `038_v3320_fk_position` (zincir: 042 → 043 → 038 →
  041). Yeni migration `down_revision = "038_v3320_fk_position"`.

### Eklenen Dosyalar

1. **`migrations/versions/041_v3320_fernet_key_version.py`**
   - `ALTER TABLE data_sources ADD COLUMN key_version INTEGER NOT NULL DEFAULT 1`
   - `CREATE INDEX idx_data_sources_key_version ON data_sources(key_version)`
   - Downgrade: index + kolon drop.

2. **`app/services/security/credentials.py`** + `__init__.py`
   - `MultiFernet` lazy thread-safe singleton.
   - Env convention: `VYRA_FERNET_KEYS="OLD,NEW"` → SON eklenen = write key.
     (Internally MultiFernet listesi reverse edilir çünkü cryptography lib
     ilk elemanı write-key kabul eder.)
   - API: `encrypt(str) -> bytes`, `decrypt(bytes|str) -> str`,
     `current_key_version() -> int`, `rotate_token(token) -> bytes`,
     `reset_cache()`.
   - Backward compat: tek key (`VYRA_FERNET_KEY`) hâlâ çalışır.

3. **`scripts/rotate_fernet_credentials.py`**
   - CLI: `--dry-run`, `-v/--verbose`.
   - SELECT → per-row decrypt → encrypt(new) → UPDATE.
   - Per-row try/except; bir hata loop'u durdurmaz.
   - Legacy `b64:` fallback token'lar (data_sources_api.py'deki son çare)
     SKIP olarak loglanır, rotation yapılmaz.
   - Final log: `[ROTATE] total=N, rotated=X, skipped=Y, failed=Z`.
   - Exit code: 0 (clean), 1 (failures), 2 (fatal), 130 (Ctrl+C).

### Test/Validation
- `python -m py_compile` — 3 dosya da temiz.
- Runtime test yok (DB up değil, brief test yazma diyor).

### Ertelemeler (v3.33)
- Otomatik cron / scheduler.
- Per-DS key version validation (drift detection).
- Eski key'leri (env'den çıkarıldıktan sonra) güvenli temizleme prosedürü.
- API'de re-encrypt-on-read transparent rotation.

### Disjoint Scope Compliance
- `app/core/encryption.py` → TOUCH YOK.
- `app/api/routes/data_sources_api.py` → TOUCH YOK.
- Sadece 3 yeni dosya + 1 package `__init__.py` (services/security için
  zorunlu).
