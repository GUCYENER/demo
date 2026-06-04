---
plan_id: error_logging_hardening
created: 2026-06-05
branch: hira
status: planned
version_target: v3.75.0
council_mod: 3
hebe_gate_required: false
---

# Hata Loglama Sağlamlaştırma — "Yutulan/Detaysız Hata Yok"

## 1. Context (Neden)

Kullanıcı talebi (2026-06-05): "Uygulama içinde TÜM hatalar türü ve detayları ile sistem loguna
eklenmeli. Yutulan ya da detaysız hata istemiyorum. Yoksa uygulamayı stabil hale getiremeyiz."

**Tetikleyen olay:** Akıllı Keşif SQL icrası `QueryCanceled: statement timeout` ile patladı; kullanıcıya
"beklenmeyen bir hata" gösterildi. Bu vakada hata ASLINDA loglanmıştı (safe_sql_executor:595) ama
genel endişe haklı: kodda `except: pass` / `except Exception: <generic mesaj, log YOK>` desenleri
hatayı yutuyor → production'da kör nokta → stabilizasyon imkânsız.

**Mevcut altyapı (kullanılacak):** `app/services/logging_service.py` `log_exception(e, module, context)`
zaten TAM traceback + request_id + redaksiyon ile `logs/errors.jsonl` + `system_logs`'a yazıyor
(v3.38.3). Eksik olan: TÜM except bloklarının bunu çağırması.

## 2. Mevcut Durum (Explore — ön tarama gerekli)

Audit edilecek desenler:
- `except ... : pass` (sessiz yutma) — sayı bilinmiyor, G1'de grep ile çıkarılacak
- `except Exception` + sadece generic mesaj return/raise (exception tipi+detay loglanmadan)
- `logger.warning/error(str(e))` ama traceback YOK (exc_info eksik)
- bare `except:` (tüm BaseException — KeyboardInterrupt dahil yutar, tehlikeli)

> NOT: Her `except: pass` kötü DEĞİL — bazıları kasıtlı (cleanup, best-effort cache).
> Audit "yutma niyeti meşru mu" ayrımı yapacak: meşru olanlar `# intentional: <sebep>` yorumu alır,
> gerçek hatalar log_exception'a bağlanır.

## 3. Faz/Gate Haritası

| Gate | İş | Konsey |
|---|---|---|
| G1 | **Audit:** grep ile tüm `except: pass` / bare except / log'suz generic except envanteri → kategorize (meşru vs riskli) | ARES + HERMES + TYCHE |
| G2 | **Standart helper teyidi:** `log_exception` imzası + "her except buradan geçer" kuralı; gerekiyorsa ince wrapper | HERMES |
| G3 | **Riskli except'leri bağla:** her gerçek-hata except'i `log_exception(e, module=..., context=...)` çağırsın; bare `except:` → `except Exception:` | HERMES + ARES |
| G4 | **Meşru yutmaları etiketle:** kasıtlı `except: pass` → `# intentional swallow: <sebep>` + en azından `logger.debug` | HERMES |
| G5 | **Lint guard (opsiyonel):** `ruff` BLE001 (blind-except) / `except: pass` için CI uyarısı — tekrarı önle | NIKE |
| G6 | **Doğrulama:** değişen modüllerde syntax+test; örnek hata enjekte → errors.jsonl'de tip+traceback görünüyor mu | TYCHE |

## 4. Critical Files (G1 audit ile netleşir — ön aday)
- `app/services/*.py`, `app/api/routes/*.py` — en yoğun except alanı
- `app/services/logging_service.py` — helper (değişmez, kullanılır)
- `pyproject.toml` — ruff BLE001 kuralı (G5)

## 5. Yeniden Kullanılacak
- `logging_service.log_exception()` — TEK kanal, yeniden yazma yok.
- `show_errors.py` / errors.jsonl — doğrulama aracı (G6).

## 6. Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Meşru cleanup'a gereksiz log eklenip gürültü | Orta | Düşük | G1 kategorize: meşru olanlar debug-level / etiketli |
| Geniş diff (yüzlerce except) | Yüksek | Orta | Modül-modül, paralel alt-ajan (disjoint dosya), her batch test |
| Hassas veri loglama (PII) | Düşük | Yüksek | log_exception zaten redaksiyon yapıyor (KAP 2 KVKK) |

## 7. Verification
- `git grep -nE "except.*:\s*pass|except\s*:" app/` envanteri G1 öncesi/sonrası
- Örnek hata enjekte → `python .agents/tools/show_errors.py --full` → tip+traceback var mı
- pytest regresyon (değişen modüller)

## 8. Out-of-scope
- Frontend JS hata yakalama (ayrı — bu plan backend Python)
- Alerting/SLO (gözlemlenebilirlik ayrı iş)

## İlerleme Kaydı
- [ ] G1 audit envanteri
- [ ] G2 helper teyidi
- [ ] G3 riskli except → log_exception
- [ ] G4 meşru yutma etiketleme
- [ ] G5 ruff BLE001 guard
- [ ] G6 doğrulama
