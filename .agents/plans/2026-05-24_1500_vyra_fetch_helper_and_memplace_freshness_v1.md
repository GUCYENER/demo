---
plan_id: vyra_fetch_helper_and_memplace_freshness
created: 2026-05-24
branch: hira
status: in_progress
version_target: v3.34.0
council_mod: 3
hebe_gate_required: true
owner_zeus: true
last_commit_at_start: 6588a5e
last_commit_at_update: 897e62c
last_updated: 2026-05-24
wip_stash: "stash@{0}: WIP previous session: dialog_chat + deep_think + query_state + query_builder"
parallel_agents:
  - 2026-05-24_A1-bug-picker-limit
  - 2026-05-24_A2-vyrafetch-helper-and-login
  - 2026-05-24_A3-workflow-mempalace-freshness
  - 2026-05-24_A4-bug-wizard-empty-search-rca
phase_status:
  G1_vyrafetch_helper: completed       # bf4e11f
  G2_login_migration: completed         # bf4e11f (login.js + login.html a11y)
  G3_main_modules: completed            # f172836 — 5 dosya, -140 satır net
  G4_modules_phase_b: blocked           # WIP stash@{0} kullanıcı kararı bekliyor
  G5_side_modules: completed            # 7d10e2d + c1285e6 + 0bb0f7d + 897e62c — 42 dosya, ~108 site migre
  G6_workflow_update: completed         # 2aead30 (vyrazeus.md +28/-5)
  G7_mcp_server_mine_fix: completed     # mcp_servers.py B+A — HEAD-hash short-circuit + timeout 300→600s; backup: mcp_servers.py.bak-2026-05-24; helpers verify edildi (vyra HEAD=897e62c)
bonus_completed:
  - A1_picker_limit_cap: 4ff9c8b        # le=100 -> le=500
  - A4_wizard_empty_search: 8ebf9e0     # eligibility SQL yorumundaki bare %
---

## Context (Neden bu değişiklik?)

Üç ayrı ama ilişkili görev tek planda bundle ediliyor — hepsi "kullanıcı deneyimi + operasyonel sağlamlık" ekseninde.

### Tetikleyen olay (2026-05-24 oturumu)
Kullanıcı login ekranında **"Unexpected token '<', '<html> <h'... is not valid JSON"** raw JS hatası gördü
(Backend 8002 veya Nginx 8000 kapalıyken Nginx'in HTML 502 sayfasını `response.json()`'a yedirmek).
Bu raw parse hatası kullanıcıya saçma görünüyor — "hangi servis kapalı" bilgisi yok.

### Kök bulgular
1. `frontend/assets/js/login.js:171-179` düz `fetch + response.json()` kullanıyor.
   Helper `window.VYRA_API.request` mevcut (`api_client.js:20-62`) ama login.js ondan habersiz.
2. `api_client.js:42-48` text→JSON parse fallback'i var ama HTTP 502/503/504/network error için
   **kullanıcı dostu mesaj** üretmiyor; sadece `API error (${res.status})` döner.
3. Tüm projede `fetch(` çağrısı **54 dosyada** geçiyor; çoğu inline auth+JSON parse pattern.
   Bir 502/timeout durumunda her birinde benzer hata yüzeyi var.
4. MemPalace mining bu oturumda 2× 300s timeout aldı. Workflow `bitir` sürecinde mine yapar,
   `başla`'da freshness check **yok** — son commit'lerin (v3.33.0) MemPalace'a yansımadığını
   `search_memory` kontrolüyle ancak elle gördük.

## Mevcut Durum (Explore bulguları)

### Frontend fetch landscape
- **Merkezi helper:** `frontend/assets/js/api_client.js` (117 satır, IIFE)
  - `VYRA_API.request(path, {method, body, auth})` → otomatik Bearer header, JSON parse, hata fırlatma
  - `VYRA_API.login/registerUser/refreshToken` mevcut ama login.js bunları kullanmıyor (signature uyumsuzluğu: `login(phone, password)` vs login.js'in `{username, password, domain}`)
- **Raw fetch kullanan dosyalar:** 54 (ana Grep sonucu)
  - **Kritik (auth + ilk yüzey):** `login.js`, `home_page.js`, `authorization.js`, `system_manager.js`
  - **Çok kullanılan modüller:** `dialog_chat.js`, `query_builder.js`, `ds_enrichment_module.js`, `saved_reports_grid.js`, `data_sources_module.js`, `db_smart_picker.js`, `db_smart_wizard.js`
  - **Yan modüller (~40):** `rag_*`, `ldap_settings.js`, `theme_*`, `param_tabs.js`, `widget_module.js`, …

### Login error pattern (kritik)
```js
// login.js:171-179 (mevcut)
const response = await fetch(`${API_BASE}/api/auth/login`, { ... });
const data = await response.json();  // ← HTML 502'de patlar: SyntaxError
if (!response.ok) throw new Error(data.detail || "Giriş başarısız");
```

Catch bloğu sadece `Failed to fetch` (network) için Türkçe mesaj veriyor (line 205-207); HTML parse hatası catch'e SyntaxError olarak düşüyor → `error.message` raw JS hatası kullanıcıya gidiyor.

### MemPalace MCP config
- `.mcp.json`: server path `C:\Users\EXT02D059293\Documents\mcp_servers\mcp_servers.py` (proje dışı)
- `mine_project(wing="vyra")` 2× 300s timeout (bu oturum) — vyra wing ~7394 drawers, full re-mine yapıyor olabilir
- Çözüm vektörleri: (a) timeout artır, (b) incremental mining (sadece son commit'ten sonraki değişiklik), (c) async chunked mining + progress, (d) BAŞLA staleness gate ile gereksiz mine'ı önle (hash karşılaştırması)

### Workflow
- `vyrazeus.md §3.1` BAŞLA: `warmup → wakeup_context → palace_status` (freshness yok)
- `§2 CRAZYMEMPLC` sorumluluk: "Bağlam yükleme, mine kapsam, drawer delta, stale context, wing izolasyonu (vyra)" — staleness gate açık yazılmamış
- `§8 Hazır raporu`: `🧠 MemPalace` satırı yok

## Faz/Gate Haritası

### G1 — `vyraFetch` Helper (api_client.js güçlendirme)
**Dosya:** `frontend/assets/js/api_client.js` (mevcut request fonksiyonu güçlendirilir)

**Eklemeler:**
1. **Content-type sniff:** Response 2xx olmayıp `content-type` JSON değilse (HTML/text/empty) → friendly Turkish error
2. **HTTP status mapping:**
   - `502`/`503`/`504` → "Backend servisi yanıt vermiyor (HTTP {status}). Sistem yöneticinize bildirin."
   - `0` veya `TypeError: Failed to fetch` → "Sunucuya bağlanılamadı. Proxy (Nginx) çalışmıyor olabilir."
   - `401` → "Oturum sona erdi. Lütfen yeniden giriş yapın." (mevcut detail varsa override etmez)
   - `403` → "Bu işlem için yetkiniz yok."
   - `5xx` (genel) → "Sunucu hatası ({status}). Lütfen tekrar deneyin."
3. **Service health detection:** Önce `/api/health` ping; başarısızsa hangi alt-servisin durduğunu bildiren bir health summary (opsiyonel; backend `/api/health` mevcut)
4. **Public API:** `window.vyraFetch(path, options)` — `VYRA_API.request`'in alias'ı (geri uyum için VYRA_API korunur)
5. **`window.VYRA_API.login`** signature düzeltilir: `login({username, password, domain})` — gerçek backend kontratına uyum

**Çıktı:** `api_client.js` ~117 → ~200 satır. Eski caller'lar bozulmaz (`VYRA_API.request` aynı argümanlar).

### G2 — Login Sayfası Migrasyonu
**Dosya:** `frontend/assets/js/login.js`

**Değişiklikler:**
1. `handleLogin` → düz `fetch` yerine `window.vyraFetch('/auth/login', {method:'POST', body:{...}, auth:false})`
2. `handleRegister` → benzer
3. `loadVersion`, `loadLdapDomains`, `checkExistingAuth`, `loadLoginVideo` → `vyraFetch` veya inline `safeFetch` (HEAD istekleri için)
4. Catch bloğu sadeleşir — friendly mesaj artık helper'dan geliyor

**Beklenen:** Login.js ~564 satırdan ~510 civarına (kod sadeleşmesi).

### G3 — Ana JS Modülleri Migrasyonu (Faz A)
**Dosyalar (öncelik sırasıyla):**
- `frontend/assets/js/home_page.js`
- `frontend/assets/js/authorization.js`
- `frontend/assets/js/system_manager.js`
- `frontend/assets/js/org_module.js`
- `frontend/assets/js/org_utils.js`

**Strateji:** Her dosyada düz `fetch(${API_BASE}/api/...)` çağrılarını `window.vyraFetch('/...')`'a çevir.
Davranış parity korunur (response ok kontrol akışı aynı; sadece error mesajları zenginleşir).

### G4 — Ana JS Modülleri Migrasyonu (Faz B — modules/)
**Dosyalar (top 10 — kullanım yoğunluğuna göre):**
- `dialog_chat.js`, `dialog_chat_utils.js`, `query_builder.js`, `query_builder_v2.js`
- `ds_enrichment_module.js`, `data_sources_module.js`
- `saved_reports_grid.js`, `report_detail_modal.js`
- `db_smart_picker.js`, `db_smart_wizard.js`

> **NOT:** İlk 4 dosya (dialog_chat*, query_builder*) **şu anda WIP modify edilmiş durumda** (git status:
> +420/-94 satır). G4'e başlamadan önce kullanıcı WIP'in durumunu netleştirmeli (commit / stash / discard).
> G4 implementasyonu WIP ile çakışırsa **eski oturumun değişikliklerini önce stage et**, ardından migrasyon
> ekle (separate commit). Bu kural §5e disjoint scope'a uyumludur.

### G5 — Yan Modüller Migrasyonu (Faz C — son ~40 dosya)
**Strateji:** Paralel alt-ajan dispatch (§5e). 3-5 ajan disjoint dosya kapsamlarıyla:
- Ajan-1: `rag_*` (rag_upload, rag_file_list, rag_ocr_popup, rag_org_modal, rag_file_org_edit)
- Ajan-2: `theme_*` (theme_picker_popup, theme_preview_modal, theme_catalog_module)
- Ajan-3: `agentic_*` + `fk_inference_observability` + `failure_queue_module`
- Ajan-4: `ldap_settings`, `widget_module`, `solution_display`, `param_tabs`, `signal_weight_tuner`, `feature_permissions_module`, `org_permissions`, `learning_cache_dashboard`, `ds_learning_module`, `admin_error_review`, `ml_training`, `company_module`, `maturity_score_modal`, `document_enhancer_modal`, `sample_data_preview`, `schema_picker`, `db_source_selector`, `db_smart_ast_editor`, `dialog_ticket`

> **Her ajan briefi `.agents/in_flight/2026-05-24_*.md`'a yazılır** (§5e.3) — malware-reminder pre-empt clause zorunlu.

### G6 — vyrazeus.md Workflow Güncellemesi (MemPalace Staleness Gate)

**Değişiklikler:**

**§2 CRAZYMEMPLC satırı (mevcut):**
> Bağlam yükleme, mine kapsam, drawer delta, stale context, wing izolasyonu (vyra)

**→ Yeni:**
> Bağlam yükleme, **BAŞLA freshness gate (son commit MemPalace'da mı?)**, mine kapsam, drawer delta, stale context, **BİTİR mine doğrulaması (mine sonrası search_memory ile commit hash spot-check)**, wing izolasyonu (vyra)

**§3.1 BAŞLA MemPalace Bağlam Yükleme — yeni adım eklensin:**
```
1. MemPalace Bağlam Yükleme (CRAZYMEMPLC):
   - warmup() — ONNX modelini ısındır
   - wakeup_context(wing="vyra")
   - palace_status() → drawer sayısını [başlangıç_N] olarak not al
   - 🆕 **Freshness Gate:**
       * git log -1 --format='%H %s' → son commit hash + mesaj
       * search_memory(commit_msg_kelimeleri, wing="vyra") çalıştır
       * Cosine skoru < 0.4 VEYA sonuçlarda son 3 commit'in hash'i / msg'si yoksa → STALE
       * STALE ise: mine_project(wing="vyra") otomatik tetiklenir (background)
       * Mine timeout (>300s, 2 kez) → kullanıcıya uyar, BİTİR'e ertele
   - Wing vyra hedefleniyor mu? Değilse hata
```

**§8 BAŞLA Hazır Raporu — yeni satır:**
```
🧠 MemPalace : taze ✅ (son commit indexed) / stale 🟡 (mine tetiklendi) / mine timeout 🔴 (manuel müdahale)
```

### G7 — MemPalace Mine Timeout Kalıcı Çözümü
**Dosya:** `C:\Users\EXT02D059293\Documents\mcp_servers\mcp_servers.py` (proje dışı, kullanıcı onayı gerekli)

**Olası çözüm yaklaşımları (kullanıcı kararıyla):**

| # | Yaklaşım | Avantaj | Dezavantaj |
|---|----------|---------|-----------|
| A | Timeout 300s → 600s | Trivial | Sadece erteleme, root cause çözmez |
| B | Incremental mining: son commit hash'ini DB'de tut, sadece `git diff` dosyalarını mine et | Kalıcı çözüm; mine süresi <30s | mcp_servers.py refactor gerekir |
| C | Async background mining + progress raporu | Kullanıcı bekletilmiyor | Race conditions; daha karmaşık |
| D | Mine'ı parça parça (her room ayrı) çalıştır + checkpoint | Timeout'a karşı dayanıklı | Mevcut subprocess pipeline değişir |

**Önerilen:** **B (incremental)** + fallback **A (timeout 600s)**. mcp_servers.py'da `mine` komutu:
1. `D:\demo_vyra\.git\refs\heads\hira` HEAD hash'i oku
2. `.mempalace/state/vyra_last_mined_commit.txt` ile karşılaştır
3. Eşitse: "already up-to-date" döner (no-op)
4. Farklıysa: `git diff --name-only <last_commit>..HEAD` ile değişen dosyaları al, sadece bunları yeniden chunk + embed
5. State dosyasını HEAD'e güncelle

## Critical Files to Modify / Create

### G1 — vyraFetch helper
- `frontend/assets/js/api_client.js` (MODIFY)
- `frontend/build.mjs` (CHECK: api_client.js bundle'da olduğundan emin ol)

### G2 — Login
- `frontend/assets/js/login.js` (MODIFY)

### G3 — Ana app dosyaları
- `frontend/assets/js/home_page.js` (MODIFY)
- `frontend/assets/js/authorization.js` (MODIFY)
- `frontend/assets/js/system_manager.js` (MODIFY)
- `frontend/assets/js/org_module.js` (MODIFY)
- `frontend/assets/js/org_utils.js` (MODIFY)

### G4 — Ana modüller (WIP-bekleyen)
- `frontend/assets/js/modules/dialog_chat.js` (MODIFY — WIP çakışma riski!)
- `frontend/assets/js/modules/dialog_chat_utils.js` (MODIFY — WIP)
- `frontend/assets/js/modules/query_builder.js` (MODIFY — WIP)
- diğerleri (MODIFY)

### G5 — Yan modüller
- ~40 dosya (paralel ajan dispatch)

### G6 — Workflow
- `.agents/workflows/vyrazeus.md` (MODIFY — §2, §3.1, §8)

### G7 — MCP server
- `C:\Users\EXT02D059293\Documents\mcp_servers\mcp_servers.py` (MODIFY — kullanıcı onayı)
- (yeni) `C:\Users\EXT02D059293\.mempalace\state\vyra_last_mined_commit.txt`

## Yeniden Kullanılacak Mevcut Fonksiyonlar

- `window.VYRA_API.request` → genişletilip `window.vyraFetch` alias'ı eklenir
- `window.getAuthHeader` → korunur (geri uyum)
- `api_client.js` IIFE yapısı korunur
- Login.js'deki `showError`/`hideAllMessages` UI helper'ları aynen kullanılır

## Risk Özeti

| Risk | Olasılık | Etki | Mitigasyon |
|------|----------|------|------------|
| api_client.js eski caller'ları bozar (signature regression) | Düşük | Yüksek | Mevcut `VYRA_API.request` imzası aynen korunur; yeni davranış sadece error path'inde |
| login.js migrasyonu auth akışını bozar | Düşük | Kritik | G2 sonrası manuel smoke test: lokal admin, LDAP domain, yanlış şifre, backend down |
| WIP dosyaları (G4) → merge çakışması | Yüksek | Orta | Kullanıcı G4'e geçmeden önce WIP'i commit/stash etmeli; ZEUS uyarır |
| Paralel ajanlar disjoint kapsam ihlali (G5) | Orta | Orta | Brief frontmatter `target_files:` kesişim denetimi; §5e.2 |
| Workflow §3.1 freshness gate her BAŞLA'da gecikme (mine 30+ s) | Düşük | Düşük | Mine arka planda; rapor "stale 🟡 (background)" olarak gösterir, kullanıcı beklemez |
| MCP server (G7) edit proje dışı dosya | Orta | Düşük | Kullanıcı onayı; backup; rollback yolu (timeout 600s sadece) |
| Bundle olmadan vyraFetch erişilemez | Orta | Yüksek | `build.mjs` ile api_client.js bundle'da olduğunu doğrula; değilse her HTML'de `<script>` ekle |

## Verification (uçtan-uca test)

### G1+G2 sonrası (auth smoke)
1. **Backend kapalı:** uvicorn'u durdur → login.html'i aç → `admin/admin` ile giriş → beklenen: **"Backend servisi yanıt vermiyor (HTTP 502)"** veya **"Sunucuya bağlanılamadı"** (Nginx kapalıysa)
2. **Backend açık, yanlış şifre:** → backend `{detail: "Geçersiz kimlik bilgileri"}` döner → kullanıcı **"Geçersiz kimlik bilgileri"** görür (helper detail'i geçirir)
3. **Backend açık, başarılı login:** → home.html'e redirect
4. **LDAP domain dropdown:** sayfa açılınca domain polling çalışıyor (loadLdapDomains)
5. **Token expire:** access_token bozuk → home_page.js auth guard → login'e döner, version_mismatch mesajı

### G3-G5 sonrası (modül smoke)
- Home page yüklensin, sidebar modülleri kalkış-iniş yapsın
- Bir DB source list isteği at, network panel'de istek headers Bearer ile gönderiliyor mu?
- Backend'i killer'ken bir modülde fetch tetikle → kullanıcı dostu hata mesajı mı, raw JS hatası mı?

### G6 sonrası (workflow)
- Yeni BAŞLA komutu → `🧠 MemPalace` satırı raporda görünmeli
- Stale ise auto-mine tetiklenmeli; timeout'ta uyarı

### G7 sonrası (mine)
- mine_project(vyra) ilk çağrı: full → 30s-2min
- 2. çağrı (commit yok): "already up-to-date" → <2s
- Bir test commit'inden sonra 3. çağrı: incremental, sadece değişen dosyalar → <10s

## Out-of-scope

- **Geri uyum kırma:** `VYRA_API.request` imzası DEĞİŞMEZ (sadece error mesajı zenginleşir)
- **Backend `/api/health` genişletme:** Şu an health endpoint'i hangi alt-servisin durduğunu detaylı söylemiyor. Gelecek faz (v3.35.0?).
- **Service worker / retry logic:** Otomatik retry mantığı eklenmiyor — kullanıcı tekrar denemeli
- **Toast → modal upgrade:** Login.js'deki inline `.error-message` korunur (HEBE onayı: bu pattern proje standardına uyumlu)
- **Backend tarafında log format değişikliği:** N/A
- **Widget (`frontend/widget/widget.src.js`)**: ayrı bir bundle; bu plan kapsamında değil — gelecek sprint

## HEBE Pre-Plan UI/UX Polish Gate

```
💎 HEBE Pre-Plan UI/UX Polish Gate
───────────────────────────────────
A. Bildirim/Diyalog : ✅ Mevcut .error-message inline pattern korunur; alert/confirm yok
B. Tooltip/Aria     : ⚠️ login-error div'ine role="alert" + aria-live="assertive" eklenmeli (smoke item)
C. Loading          : ✅ Submit button .loading class mevcut
D. Empty State      : N/A (login form)
E. Marka/Renk       : ✅ error border rengi #ef4444 → CSS variable'a çekilmeli (R-track maddesi olabilir)
F. A11y             : ⚠️ login-error role="alert" zorunlu
G. FOUC             : ✅ login.html `[data-theme="dark"]` document seviyesinde

→ Plana eklenecek: login-error elementine role="alert" + aria-live (G2'de tek satır)
```

## ZEUS Notu — Yürütme Stratejisi (Onay sonrası)

- **Faz 0 (bu plan)**: Yazıldı, kullanıcı onayı bekliyor
- **Faz 1 (G1+G2)**: Tek commit — `feat(v3.34.0): vyraFetch helper + login.js migration`
- **Faz 2 (G3)**: Tek commit — `refactor(v3.34.0): main app JS modules to vyraFetch`
- **Faz 3 (G6)**: Tek commit — `feat(workflow): MemPalace BAŞLA freshness gate` (vyrazeus.md)
- **Faz 4 (G4)**: WIP karar sonrası — `refactor(v3.34.0): core modules (dialog_chat, query_builder) to vyraFetch`
- **Faz 5 (G5)**: Paralel ajan dispatch — son ~40 dosya, 3-5 ajan
- **Faz 6 (G7)**: Kullanıcı onayı sonrası — `feat(mempalace): incremental mining + state tracking` (MCP server)

Her faz sonrası TYCHE + ARES post-implementation review (§5b). G6 sonrası bir test BAŞLA çalıştırılır.

**Test BAŞLA:** Faz 3'ten sonra simülasyon — workflow yüklenir, freshness gate çalışır mı?

## Açık Sorular (kullanıcıya)

1. **WIP karar:** Halihazırda 6 modify dosya (deep_think_service.py + dialog_chat*.js + query_builder.js + ...) +420/-94 satırlık değişiklik içeriyor. Bu önceki oturumdan kalmış. G4'e geçmeden:
   - (a) WIP'i ayrı bir commit'le sakla (`feat: <önceki oturum işi>`)? Hangi konuda olduğunu biliyor musunuz?
   - (b) `git stash` yapıp G4 sonrası geri al?
   - (c) WIP'i discard et?
2. **G5 paralel ajan dispatch:** 3 ajan mı 5 ajan mı? Ben varsayılan 4 ajan disjoint kapsamla planladım.
3. **G7 (MCP server)**: Proje-dışı dosya editi için onayınız var mı? Yoksa sadece `başla`/`bitir`'de timeout uyarısıyla yetinelim?
4. **Versiyon:** v3.34.0 mı yoksa v3.33.1 (patch) mi? Login bug-fix tek başına patch olur; helper introduction minor.
5. **Bundle:** `build.mjs` api_client.js'i bundle'a alıyor mu? Kontrol etmem gerek (Faz 1 öncesi spot check).

---

**Plan hazır. Yukarıdaki 5 soruya cevap + onay sonrası Faz 1'den başlarım.**
