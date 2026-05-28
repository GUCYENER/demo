---
plan_id: wsl_basla_rutini
created: 2026-05-28
branch: hira
status: completed
version_target: v3.37.5
council_mod: 2
hebe_gate_required: false
---

# WSL BAŞLA Rutini + Graphify Liveness Düzeltmesi (HERMES + NIKE + MNEMOSYNE-GRAPH)

## Context (Neden bu değişiklik?)

Kullanıcı geri bildirimi (2026-05-28):
> "başa rutininde, start.ps1 ve graphify wsl de sağlıklı çalışacak şekild düzelt.
> '[SKIP] Graphify zaten ayakta - warmup atlandi' hep düzelttim diyorsun bir bok ettiğin yok."

İki bağımsız ama bağlantılı sorun var:

1. **WSL'de BAŞLA rutini servisleri ayağa kaldırmıyor** — `vyrazeus.md §3.2` `powershell -File D:\demo_vyra\start.ps1` diyor; Linux shell bunu çalıştıramaz. Sonuç: WSL Claude Code BAŞLA'da servisler kalkmamış görünüyor (kullanıcı manuel başlatmak zorunda).

2. **`[SKIP] Graphify zaten ayakta` yalancı pozitif** — `start.ps1:65` `python -m core.cli status --project vyra` exit kodunu kontrol ediyor. Bu sadece `~/.graphify/instances/vyra.db` dosyası var mı der; **MCP server'ın Claude Code'a gerçekten stdio üzerinden bağlanabilirliğini test etmiyor**. Sonuçta DB dosyası varsa "SKIP" diyor ama MCP server gerçekten ölü olabiliyor. Ayrı bir katman: WSL Claude Code `.mcp.json`'daki Windows path'lerini çalıştıramadığından MCP araçları hiç bağlanamıyor — yine de start.ps1 "SKIP" diyor.

Memory referansı: [[feedback_transparency]] — "yaptım/temiz/geçti" denmeden önce icra+kanıt zorunlu.

## Mevcut Durum (Explore bulguları)

- `/mnt/d/demo_vyra/start.ps1:48-83` — Graphify warmup bloğu, sadece `status` exit kodu kontrol eder
- `/mnt/d/demo_vyra/mcp_warmup.bat` — `python -m core.cli wakeup --project vyra`, `errorlevel 1` halinde devam
- `/mnt/d/demo_vyra/.mcp.json` — Windows Python313 path'i + Windows cwd; WSL Claude Code bunu çalıştıramaz
- `/mnt/d/demo_vyra/.agents/workflows/vyrazeus.md:125-131` — BAŞLA Bölüm 3 Adım 2 sadece PowerShell komutu önerir
- `/mnt/c/Users/EXT02D059293/Documents/General_Graphify/core/cli.py` — Graphify CLI, WSL'den okunabilir
- `powershell.exe` WSL'de PATH'te (`/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe`), PS 5.1 yanıt veriyor
- WSL `/usr/bin/python3` (3.14.4) — Graphify deps (mcp, duckdb, sqlalchemy, networkx) MISSING; Linux-native Graphify çalıştırılamaz mevcut env'de
- Tüm servis portları (5005/6379/8002/8000/1521) WSL ortamı açıldığında KAPALI — Windows tarafında start.ps1 son çalıştırılmamış

## Faz/Gate Haritası

| Gate | Sorumlu Konsey | Brief |
|---|---|---|
| G1 | HERMES + NIKE | start.sh yaz (WSL → powershell.exe köprüsü + Linux-tarafı port healthcheck) |
| G2 | MNEMOSYNE-GRAPH + HERMES | start.ps1 Graphify liveness check sertleştirme (yalancı SKIP düzeltme) |
| G3 | MNEMOSYNE-GRAPH | .mcp.json'u dual-environment yap (WSL + Windows aynı dosyadan çalışsın) |
| G4 | HERMES + HERA | vyrazeus.md Bölüm 3 Adım 2 platform-aware (Linux'tan `bash start.sh`, Windows'tan `start.ps1`) |
| G5 | TYCHE | Verify: WSL'den `bash start.sh` çalıştırıldığında portlar yeşil + MCP wakeup test |
| G6 | HERA | README versiyon (v3.37.4 → v3.37.5) + commit (conventional fix) |

## Critical Files to Modify / Create

- **YENİ** `/mnt/d/demo_vyra/start.sh` — WSL/Linux wrapper (~50-80 satır)
- **EDIT** `/mnt/d/demo_vyra/start.ps1` — liveness check (satır 58-83 bölgesi)
- **EDIT** `/mnt/d/demo_vyra/.mcp.json` — `command` cmd.exe köprüsü (⚠️ **gitignored** — `.gitignore`: "MCP server config (local machine paths)"; commit'e dahil edilmez, local-only değişiklik. Aynı pattern'i Windows tarafı yeniden uygulamak isterse README v3.37.5 entry'sinden referans alabilir)
- **EDIT** `/mnt/d/demo_vyra/.agents/workflows/vyrazeus.md` — Bölüm 3 Adım 2 (satır 121-131)
- **EDIT** `/mnt/d/demo_vyra/README.md` — versiyon başlığı + versiyon geçmişi bloğu

## Yeniden Kullanılacak Mevcut Fonksiyonlar

- `start.ps1` mevcut PG/Redis/Backend/Nginx/Oracle/Frontend başlatma adımları **aynen** korunacak — sadece §0 Graphify bloğu sertleştirilecek
- `mcp_warmup.bat` aynen kalır (Windows tarafı warmup standart yolu)
- `core.cli wakeup`, `core.cli status`, `core.cli search` — Graphify Linux'ta da çalışan komutlar (cli.py Python-only, `--project vyra` parametresi her iki ortamda eş)

## Risk Özeti

| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| `.mcp.json`'un powershell.exe köprüsü Windows-native Claude Code'da regresyon yapar | Düşük | Yüksek | `powershell.exe` Windows'ta da PATH'te; cwd korunur (`-Command "Set-Location ...; & python.exe ..."`); test edilecek |
| start.ps1 sertleştirilmiş check her seferinde 1+ sn ekstra harcar | Yüksek | Düşük | search query tek commit hash + `--limit 1` — milisaniye seviyesinde |
| WSL'de Windows binary spawn rate-limit'lenir (defender, AV) | Düşük | Orta | start.sh'de zaten tek `powershell.exe` çağrısı var (servis loop'u Windows tarafında); ek spawn yok |
| `Set-Location` PS5.1 ile escape sorunu yaratır | Düşük | Yüksek | Tek tırnak Windows path'i koruyor; test edilecek (sanity check `command -v` + bir gerçek MCP handshake) |
| Eski "SKIP" davranışına bağlı muhtemel script var | Yok | — | grep -r ile kontrol edildi (sadece start.ps1:73 ve docstring); başka tüketici yok |

## Verification (uçtan-uca test)

```bash
# G1 — start.sh syntax + Windows binary köprüsü
bash -n /mnt/d/demo_vyra/start.sh  # syntax 0
bash /mnt/d/demo_vyra/start.sh     # exit 0 + portları sıralı aç (timeout 60s)

# G2 — start.ps1 Graphify liveness
# Senaryo A: DB yok → FORCE warmup tetiklenir
mv ~/.graphify/instances/vyra.db ~/.graphify/instances/vyra.db.bak  # (Windows-tarafından sim)
powershell.exe -File "D:\demo_vyra\start.ps1"  # "[WARM] Graphify isindirma gerekli" çıkmalı

# Senaryo B: DB var ama son commit indexed değil → FORCE warmup
git commit --allow-empty -m "test"
powershell.exe -File "D:\demo_vyra\start.ps1"  # "[WARM]" — commit indexed değildi

# Senaryo C: DB var + son commit indexed → SKIP (gerçekten)
powershell.exe -File "D:\demo_vyra\start.ps1"  # "[OK SKIP] son commit graphify'da indexed" (yeni mesaj)

# G3 — .mcp.json çift ortam
# Windows: Claude Code restart → graphify MCP araçları list'e gelsin
# WSL: Claude Code restart → graphify MCP araçları list'e gelsin (tools/list)

# G5 — Port healthcheck (start.sh sonunda)
curl -sS http://localhost:8000/login.html >/dev/null && echo "Nginx OK"
curl -sS http://localhost:8002/health >/dev/null && echo "Backend OK"
nc -z localhost 5005 && echo "PG OK"
```

## Out-of-scope

- WSL'de Linux-native Graphify kurulumu (python3 -m venv + deps) — kullanıcı "WSL → Windows köprüsü" seçti, native kurulum sonraki sprintte
- `.mcp.json`'a başka MCP server eklemek (mempalace vb.) — şu an yalnız graphify
- start.ps1'in `5/7 Oracle Docker` adımına dokunma — kullanıcı şikayeti Graphify ve start.ps1 genel; Oracle bloku stable
- Auto-memory'ye yeni feedback ekleme — implementasyon biterse [[feedback_basla_wsl_bridge]] memory yazılabilir (kullanıcı talep ederse)
- CHANGELOG.md güncelleme — README versiyon geçmişi proje konvansiyonu, ayrı CHANGELOG yok

---

**Status flow:** planned → in_progress → completed (her gate ✅ + commit hash)
