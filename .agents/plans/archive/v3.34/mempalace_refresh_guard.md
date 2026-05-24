---
plan_id: mempalace_refresh_guard
title: MemPalace boot-time freshness guard
created: 2026-05-23
branch: hira
status: completed
version_target: v3.34.0
council_mod: 1
hebe_gate_required: false
owner_agent: CRAZYMEMPLC
trigger: every BAŞLA routine until acknowledged-fresh
completed_at: 2026-05-24
completion_notes: |
  v3.34.0 paketi içinde freshness gate gerçeklendi:
  - vyrazeus.md §2/§3.1/§8 (2aead30): BAŞLA freshness gate + 🧠 MemPalace raporu
  - mcp_servers.py: mine_project HEAD-hash short-circuit + MINE_TIMEOUT 600s
    (idempotent re-mine, .mempalace/state/<wing>_last_mined_commit.txt)
---

## Context (Neden bu değişiklik?)

Kullanıcı 2026-05-23 BAŞLA oturumunda CRAZYMEMPLC raporundan
şunu gözlemledi: `wakeup_context(vyra)` çıktısı çok eski bağlam
içeriyor (L1 essential story canlida_calistir_linux.py gibi
güncel olmayan ipuçları döndü; son commit hash'leri yoktu).

Bu durum, bir önceki oturum kapanışında `mine_project()` çağrısının
başarısız geçmiş ya da hiç yapılmamış olabileceğine işaret ediyor.
Sonuçta MemPalace `vyra` wing drawer'ları en güncel kodu yansıtmıyor —
yeni oturumda yanlış varsayımlara, ezbere fix denemelerine yol açabilir.

## Mevcut Durum (snapshot)

- `palace_status()` (2026-05-23): vyra/general 7393 drawers, vyra/agentic_sql_plan 1 drawer
- `wakeup_context(vyra)` L1 çıktısı son commit hash'lerini (4a2bb21, aa8004b) içermiyor
- Git HEAD: 4a2bb21 (fix(v3.30.0): migration schema alignment + session timeout 60dk)
- Önceki BİTİR rutininde mine başarı durumu BİLİNMİYOR

## Boot-Time Görev (her BAŞLA'da çalış, OK alınana kadar)

**Sorumlu: 🧠 CRAZYMEMPLC** (Bölüm 3 Adım 1 sırasında)

Adımlar:
1. `warmup()` + `wakeup_context(wing="vyra")` — normal akış
2. **EK kontrol:** wakeup_context çıktısında HEAD commit hash (veya son 3 commit hash'inden biri) görünüyor mu?
   - Görünüyorsa → `acknowledged-fresh` say, bu plan dosyasını `status: completed` işaretle, başka bir şey yapma
   - Görünmüyorsa → MemPalace bayat, aşağıya devam
3. `palace_status()` → drawer sayısını `[başlangıç_N]` olarak not al
4. **Bayat durumda refresh:** `mine_project(wing="vyra")` çağır (bunu BAŞLA'da çağırmak normalde yapılmaz, ama bu guard görevin gereği)
   - Mine başarısız ise (Timeout/Hata) → kullanıcıya bildir, plan açık kalsın
   - Mine başarılı (Files processed > 0) ise → `palace_status()` ile drawer delta hesapla
5. Delta ≥ 1 ve `wakeup_context()` yeniden çağrılınca güncel commit hash'leri görünüyorsa → `status: completed` + sonuç hash'i `last_commit` alanına yaz
6. Aksi halde planı `status: in_progress` bırak, kullanıcıya rapor et:
   ```
   🧠 CRAZYMEMPLC Bayat Bağlam Uyarısı:
      Mine sonuç     : [N dosya / HATA]
      Drawer delta   : başlangıç_N → bitiş_N (+delta)
      Hash kontrol   : [✅ güncel / ⚠️ hâlâ bayat]
      Sonraki adım   : [tamam / manuel mine_project gerekli]
   ```

## Tamamlama Kriteri

- `wakeup_context(vyra)` çıktısı en az bir current/recent commit hash'i (HEAD veya son 3) içeriyor
- Plan `status: completed` + `last_commit: <hash>` ile kapanır

## Out-of-scope

- cosmos_mobile veya diğer wing'lerin mine durumu (her wing kendi guard'ını yönetir)
- Drawer içeriği semantik doğruluk denetimi (bu görev sadece freshness)

## Notlar

- BİTİR rutininde KAP 10 zaten mine'ı çağırır; bu guard "BİTİR atlanmış / mine başarısız geçmiş" senaryosu için backup'tır
- Tekrar tetiklenmemesi için tamamlandığında `status: completed` kritik
