---
slug: v3371_G_format_select_autorun
title: v3.37.1 G — Format Uygula → otomatik Çalıştır
created: 2026-05-26T20:22+03:00
owner: ZEUS
council: [HEBE (primary UI), APOLLO (UX flow), TYCHE (regression)]
related_audit: .agents/audits/v3371_bulgular_audit.md (Madde 8)
related_plan: .agents/plans/2026-05-26_1607_v3371_bulgular_followup_v1.md
gate_1_status: pending
gate_2_status: pending
dispatch_target: HERMES subagent
---

# v3.37.1 G — Format Seçim → Auto-Run

## Verbatim Spec (Madde 8)

> Önizleme'de Hazır Rapor Formatı Öner butonu + liste + LLM + seçim → çalıştır

Audit'te buton + LLM endpoint + liste + Uygula ✅. Eksik: **seçim → çalıştır** akışı.

## Sorun

`Uygula` butonu sadece `_state.format = card` set ediyor ve UI'da active mark koyuyor
([db_smart_wizard.js:3296-3310](frontend/assets/js/modules/db_smart_wizard.js#L3296-L3310)).
Kullanıcı sonra `▶️ Çalıştır`'a ayrıca tıklamalı. Verbatim spec "seçim → çalıştır" — uygula
basıldığında raporu doğrudan çalıştırması bekleniyor.

## Scope

**Tek dosya:** `frontend/assets/js/modules/db_smart_wizard.js`

### Değişiklik

`_renderFormatSuggestions` içinde Uygula click handler'ına `_runGeneratedReport()` çağrısı eklenir:

```javascript
btn.addEventListener('click', function () {
    const idx = parseInt(btn.getAttribute('data-format-apply'), 10);
    if (isNaN(idx)) return;
    const card = items[idx];
    if (!card) return;
    _state.format = card;
    _notify('Format uygulandı: ' + (card.title || card.chart_type || ''), 'success');
    host.querySelectorAll('.dsw-format-card').forEach(function (el) {
        el.classList.remove('active');
    });
    const target = host.querySelector('[data-format-idx="' + idx + '"]');
    if (target) target.classList.add('active');
    // v3.37.1 G: seçim → çalıştır
    try { _runGeneratedReport(); } catch (e) {
        console.error('[db_smart_wizard] format auto-run failed:', e);
    }
});
```

### Alternatif (APOLLO review beklemeli)

UX'i daha güvenli yapmak için iki ayrı buton ekleme seçeneği:
- `Uygula` — sadece format set
- `Uygula ve Çalıştır` — format set + run

User verbatim'i "seçim → çalıştır" diyor — tek buton + auto-run önerilen yol. APOLLO bu kararı doğrulayacak.

## Acceptance

1. ✨ Hazır Format Öner → liste açılır
2. Format kartında `Uygula` → toast "Format uygulandı: ..." + kart active mark + ardından rapor otomatik çalıştırılır
3. Rapor sonucu modal otomatik açılır (mevcut `_runGeneratedReport` davranışı)
4. Hata olursa `_runGeneratedReport` kendi error toast'ını göstersin, format-apply success toast'ı kalsın

## Gate-1 Self-Review

| Kontrol | Durum |
|---------|-------|
| Spec verbatim eşleşme | ✅ "seçim → çalıştır" tam |
| Tek dosya / izole | ✅ Tek handler patch |
| Council üyesi atandı | ✅ HEBE, APOLLO, TYCHE |
| UX risk | 🟡 Auto-run uyarısız çalışıyor — APOLLO 2 buton önerebilir; kullanıcı verbatim'i tek-buton işaret ediyor |
| Restart | Frontend bundle rebuild |

## Gate-2 Verification Plan

- HEBE çıktısı: tek handler değişikliği
- ZEUS verifies: build, smoke test (format seç → modal açılıyor mu)
- APOLLO: UX kararı onayı

## Restart Notes

- Frontend bundle rebuild
- Hard reload kullanıcı
- Backend yok

## Dispatch

HERMES — frontend-only.
