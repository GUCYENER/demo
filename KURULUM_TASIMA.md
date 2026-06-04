# VYRA — Canlı Sunucuya Taşıma Rehberi (İnternetsiz / Elle Kopya)

> **Senaryo:** Canlı Windows sunucusunda internet YOK. Git clone yapılamıyor.
> Her şey bu makineden (`D:\demo_vyra`) **elle kopyalanıyor**.
> Bu yüzden "git'ten gelir" ayrımı geçersiz — uygulamanın diskte ihtiyaç
> duyduğu **her şey** taşınmalı.
>
> **Yöntem:** "Denylist" (şunlar HARİÇ tümünü kopyala) elle kopyada en güvenlisidir —
> tek tek seçmekten daha az hata riski taşır.

---

## 1. EN PRATİK YOL — Tüm klasörü kopyala, sadece şunları ATLA

`D:\demo_vyra` klasörünün tamamını kopyala, **aşağıdakileri hariç tut**:

### ⛔ KOPYALAMA (yeniden oluşur / gereksiz / çok büyük)
| Öğe | Neden atlanır |
|-----|---------------|
| `.git/` | Sürüm geçmişi — uygulamayı ÇALIŞTIRMAK için gerekmez (çok büyük) |
| `logs/` | Hedefte yeniden oluşur |
| `tmp/`, `temp/`, `Gecici_Dosyalar_Sil/` | Geçici |
| Tüm `__pycache__/`, `*.pyc`, `.pytest_cache/` | Derleme önbelleği, yeniden oluşur |
| `catboost_info/` | CatBoost eğitim logu — runtime'da gerekmez |
| `.claude/`, `.agents/state/`, `.mcp.json` | Claude/geliştirme — app runtime'ı için gereksiz |
| `node_modules/` + `.gstack/` | gstack QA (sadece TEST yapacaksan gerekli — bkz. §4) |

### 🔵 KULLANICININ AYRI HALLEDECEĞİ (bu kopyada DEĞİL)
| Öğe | Boyut | Not |
|-----|-------|-----|
| `pgsql/` | büyük | PostgreSQL — hedefte kur + veriyi `pg_dump`/data ile ayrı taşı |
| `python/` | büyük | Gömülü Python yorumlayıcı + bağımlılıklar — ayrı hallediyorsun. **DİKKAT: app bunsuz çalışmaz; hedefte birebir aynı env olmalı** (offline pip için bkz. §3) |

**Geriye kalan her şey kopyalanır.** Aşağıdaki §2 bunların ne olduğunu ve neden gerektiğini listeler (doğrulama için).

---

## 2. KOPYALANAN ÖĞELER (ne, neden) — doğrulama checklist'i

### 🔴 Kritik runtime (bunlar olmadan açılmaz)
- [ ] **`.env`** (2 KB) — JWT_SECRET, DB_PASSWORD, REDIS_URL, LANGFUSE anahtarları. **EN KRİTİK.** Güvenli kanalla taşı (§3).
- [ ] **`app/`** — tüm backend kodu (FastAPI). `app/core/schema.py` dahil (startup'ta CREATE/INDEX IF NOT EXISTS uygular).
- [ ] **`frontend/`** — UI. **`frontend/dist/bundle.min.*` derlenmiş bundle dahil** (nginx bunu servis eder → hedefte build GEREKMEZ). `frontend/node_modules/` atlanabilir (sadece yeniden build için).
- [ ] **`migrations/`** + kök `apply_migrations_*.py` — şema migrasyonları (manuel uygulanır).
- [ ] **`models/`** (**786 MB**) — embedding (`paraphrase-multilingual-MiniLM-L12-v2`) + `hf_model`. RAG/embedding bunsuz çalışmaz.
- [ ] **`ml_models/`** (2.5 MB) — CatBoost `.cbm` (enhancement sınıflandırma).
- [ ] **`redis/`** — `redis-server.exe` + `redis.windows.conf` (`requirepass VyraR3d1s_Sec2026`). Cache katmanı.
- [ ] **`nginx/`** — `nginx.exe` + `conf/conf.d/vyra.conf` + `conf/conf.d/security_headers.inc` (**güvenlik header fix burada**). Reverse-proxy + statik + güvenlik kapısı.

### 🟢 Başlatma / yardımcı
- [ ] **`canlida_calistir.bat`**, **`canlida_durdur.bat`**, **`start.ps1`**, **`start.sh`** — başlatma/durdurma.
- [ ] **`scripts/`** — proje yardımcıları (`backup_db.ps1`, `apply_*`, vb.). *Not: içinde venv'den kalma exe'ler de var (coverage.exe), zararsız.*
- [ ] **`requirements.txt`**, **`requirements-dev.txt`**, **`pyproject.toml`** — bağımlılık tanımı (offline kurulum için referans).
- [ ] **`deploy/`**, **`docs/`**, **`sss/`** — dağıtım/dokümantasyon (opsiyonel ama küçük, taşı).

### ⚪ Doğrula sonra karar ver
- [ ] **`Lib/`, `include/`, `share/`, kök `scripts/` exe'leri** — root'ta **ikincil bir Python venv**'in parçası gibi görünüyor (`Lib/site-packages`). Eğer runtime yalnız `python/` env'ini kullanıyorsa (test runner: `python/Scripts/python.exe`) bunlar **atlanabilir**. Emin değilsen `python/` ile birlikte değerlendir.

---

## 3. DİKKAT — Güvenlik & Python (internetsiz)

1. **`.env` güvenli taşınmalı** — USB/şifreli kanal. İçinde JWT_SECRET + DB/Redis şifreleri var. E-posta/açık paylaşım YAPMA.
2. **Gerçek canlıda dev sırlarını yenile** — `JWT_SECRET`, `DB_PASSWORD`, Redis `requirepass` prod'da yeni değer olmalı. `.env`'deki şifreler hedefteki **PostgreSQL ve Redis ile birebir eşleşmeli** (REDIS_URL şifresi = redis.windows.conf requirepass).
3. **Python bağımlılıkları (internetsiz):** Hedefte `pip install` internet ister. Seçenekler:
   - **(a)** Çalışan `python/` klasörünü olduğu gibi kopyala (bağımlılıklar zaten içinde) — en kolay.
   - **(b)** Offline wheel paketleri taşı: `setup/offline_packages/` veya `setup/windows/` (varsa) + `pip install --no-index --find-links=... -r requirements.txt`.

---

## 4. SADECE TEST yapacaksan EK kopyala
- [ ] **gstack QA**: `node_modules/` (17M) + `package.json` + `package-lock.json` + `.gstack/` + `gstack_komut_referansi.pdf` (Playwright browser QA). *İnternet olsaydı `npm install` yeterdi — internetsiz bu klasörleri taşı.*
- [ ] **`oracle_local_test/`** + **`oracledb/`** — Oracle-kaynak öğrenme testi yapacaksan.
- [ ] **`tests/`** — zaten §2'de kod ile geliyor.

---

## 5. KOPYA SONRASI — başlatma sırası ve doğrulama
1. **PostgreSQL** ayağa kalksın + veri restore edilsin (port 5005). `.env` DB_* ile eşleştiğini doğrula.
2. **Redis** başlat: `redis-server.exe redis.windows.conf --port 6380`. Şifreyle ping: `redis-cli -p 6380 -a <pass> ping → PONG`.
3. **Backend** (uvicorn, port 8002) — `canlida_calistir.bat` veya doğrudan uvicorn.
4. **Nginx** başlat (port 8000): `nginx.exe` → `nginx -t` ile config doğrula.
5. **Migrasyon**: `python apply_migrations_*.py` (idempotent).
6. **Sağlık kontrolü**: `http://localhost:8000/health` → `{"status":"ok"}`.
   - Cache'in gerçekten Redis'te olduğunu doğrula (memory fallback DEĞİL): backend logunda "Redis cache aktif" olmalı.

---

*Son güncelleme: 2026-06-04 — Redis auth fix (v3.73.0) + nginx güvenlik header fix dahildir.*
