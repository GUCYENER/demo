---
plan_id: remove_graphify_subsystem
created: 2026-06-02
branch: hira
status: completed
version_target: v3.48.0
council_mod: 3
hebe_gate_required: false
---

## Context (Neden bu değişiklik?)
Kullanıcı Graphify'ı projeden tamamen söküyor: "projedeki ayarları ve başladaki ve
bitirdeki graphify sürecini kaldır." Kapsam kullanıcı onayıyla **TAM SÖKÜM** seçildi —
hem proje ayarları (MCP server, izinler, hook'lar, enforcer agent) hem de `vyrazeus.md`
protokolündeki tüm Graphify izleri (BAŞLA, BİTİR, konsey üyesi, lookup-first kuralları).

## Mevcut Durum (Explore bulguları)
- `.mcp.json` — yalnızca `graphify` MCP server'ı (başka server yok; plugin MCP'leri ayrı)
- `.claude/settings.json` — 7 `mcp__graphify__*` izni + PreToolUse(Grep|Read|Glob) hook +
  PostToolUse(mcp__graphify__.*) hook; her iki hook da `_hook_entry.sh` → `graphify_guard.py`
- `.claude/settings.local.json` — ~25 graphify-spesifik allow entry (`enabledMcpjsonServers: []` zaten)
- `.claude/agents/graphify-enforcer.md` — Graphify-first enforcer alt-ajanı
- `.agents/hooks/_hook_entry.sh` + `graphify_guard.py` — tamamı graphify-guard
- `.agents/tools/graphify_db_{diag,indexes,maintenance}.py` — graphify DB bakım araçları
- `.agents/workflows/vyrazeus.md` — ~30 referans (Intent Routing, MCP tablo, MNEMOSYNE-GRAPH
  konsey üyesi, BAŞLA Adım 1, BİTİR KAP 10/10.3, 5e.3b/5e.3c lookup-first, raporlar, KRİTİK KURALLAR)
- `start.ps1` — graphify zaten v3.39.0'da çıkarılmış (yalnız yorum). `app/core/config.py`,
  CHANGELOG/README — yalnız tarihsel metin; DOKUNULMAZ.

## Faz/Gate Haritası
- **G1 — Proje ayarları (HERMES + ARES):** .mcp.json boşalt, settings.json graphify perm+hook
  kaldır, settings.local.json graphify entry'lerini filtrele
- **G2 — Ajan + hook + araç silme (HERMES):** graphify-enforcer.md, _hook_entry.sh,
  graphify_guard.py, graphify_db_*.py sil
- **G3 — vyrazeus.md protokol temizliği (HERA):** tüm graphify bölümlerini kaldır/yeniden yaz;
  §10 BAĞLAM ÇÜRÜMESİ'ni graphify_wakeup yerine plan.md/MEMORY.md re-read'e güncelle
- **G4 — Doğrulama (TYCHE):** JSON geçerliliği, vyrazeus.md aktif bölümlerinde sıfır graphify,
  hook kaldırıldı teyidi

## Critical Files to Modify / Create
- `.mcp.json`, `.claude/settings.json`, `.claude/settings.local.json` (modify)
- `.claude/agents/graphify-enforcer.md` (delete)
- `.agents/hooks/_hook_entry.sh`, `.agents/hooks/graphify_guard.py` (delete)
- `.agents/tools/graphify_db_diag.py`, `graphify_db_indexes.py`, `graphify_db_maintenance.py` (delete)
- `.agents/workflows/vyrazeus.md` (modify, ~30 site)

## Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| JSON bozulması (settings) | Orta | Hook/perm parse hatası | python json round-trip + sonrası json.load doğrulama |
| vyrazeus.md dangling ref | Orta | Tutarsız protokol | G4'te grep ile aktif bölüm taraması |
| MCP plugin server kaybı | Düşük | chrome/playwright düşer | Onlar plugin kaynaklı, .mcp.json'da değil → etkilenmez |

## Yeniden Kullanılacak Mevcut Fonksiyonlar
- Yok (saf silme/temizlik); plan persistence + MEMORY.md zaten oturum-arası bağlam için mevcut

## Verification (uçtan-uca)
- `python3 -c "import json; json.load(open('.mcp.json')); json.load(open('.claude/settings.json')); json.load(open('.claude/settings.local.json'))"` → OK
- `grep -ic graphify .agents/workflows/vyrazeus.md` → 0 (aktif metin; sadece silinmiş)
- Hook dosyaları yok; settings.json'da `hooks` anahtarı yok

## Out-of-scope
- CHANGELOG.md / README.md / config.py tarihsel metin (history korunur)
- .agents/reports/graphreport.md, .agents/plans/archive/graphify-* (arşiv)
- General_Graphify deposu (~/Documents/General_Graphify — proje dışı, kullanıcı kontrolünde)
</content>
</invoke>
<invoke name="Read">
<parameter name="file_path">/mnt/d/demo_vyra/.mcp.json