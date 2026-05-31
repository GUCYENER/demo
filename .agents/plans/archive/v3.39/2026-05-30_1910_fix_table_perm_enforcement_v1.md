---
plan_id: fix_table_perm_enforcement
created: 2026-05-30
branch: hira
status: completed
version_target: v3.39.0
completed: 2026-05-30
result: |
  G1-G4 tamam. KÖK bug (RealDictCursor tuple-unpack) + admin-honors-grants (Opsiyon A)
  + execute/stream gate. Ampirik: scope artık 3 gerçek tablo (önce çöp). FATURALAR rerun
  403, MUSTERILER geçer, unmanaged admin ALL. 27 ilgili test yeşil, 0 yeni regresyon
  (5 pre-existing hata: mark_run snapshot kwarg + columns/explain — bu işle ilgisiz).
  Picker (search_tables) G1+G2 ile otomatik düzeldi. Backend restart gerekir (canlıya).
council_mod: 3
hebe_gate_required: false
---

# Tablo-bazlı yetki uygulaması — KÖK fix (v3.38.0 regression + execute/stream gate)

## 1. Context (Neden bu değişiklik?)
Kullanıcı raporu (2026-05-30, 2 ekran görüntüsü):
1. Admin'e ORACLE-LOCAL-TEST'te yalnız 3 tablo (ABONELIKLER/ADRESLER/MUSTERILER) `restricted`
   yetki verilmiş; ama **eski kayıtlı rapor** (VYRA_TEST.FATURALAR) "Çalıştır" deyince sonuç döndürüyor.
   Beklenti: yetkisiz tablo varsa "şu tablolarda yetkiniz yok" de, sonucu gösterme.
2. **Tablo seçme ekranında (picker)** yetkisiz tablolar görünüyor — görünmemeli.

## 2. Mevcut Durum (kanıtlı bulgular)
- **KÖK BUG (RealDictCursor):** `app/services/data_source_access.py:173,188` tuple-unpack
  (`for subject_type, subject_id, scope_mode in grants`). `get_db_context` RealDictCursor
  döndürür (db.py:43,126) → satır dict → unpack KOLON ADLARINI verir.
  Ampirik kanıt: `user_accessible_tables(1, 3, can_view)` → `tables=[('schema_name','table_name')]`
  (gerçek 3 tablo yerine kolon adları). → v3.38.0 tablo-yetkisi **herkes için bozuk**:
  restricted non-admin çöp scope (hiçbir şey eşleşmez), admin bypass.
- **Admin bypass:** `table_scope.resolve_scope:46` + `user_accessible_tables:139` → admin her zaman
  `all_tables=True`. Kullanıcı kararı (Opsiyon A): açık grant varsa admin de bağlansın.
- **execute/stream gate YOK:** `db_smart_api.post_execute_stream:1155` → `stream_safe_sql(..., allowed_tables=None)`.
  Saved-report rerun whitelist'i hiç uygulamıyor (generate_report uyguluyor: resolve_scope + allows + allowed_tables).
- **picker:** `search_tables:1816-1821` zaten `resolve_scope` ile filtreliyor — KÖK bug + admin bypass
  düzelince otomatik doğru çalışır (ek değişiklik gerekmez).

## 3. Faz/Gate Haritası
- **G1 (HEPHAESTUS+ARES):** `data_source_access.user_accessible_tables` RealDictCursor satır okuma fix
  (dict|tuple uyumlu) + admin grant'a bağlanma (admin yalnız HİÇ grant yokken ALL; "managed admin" helper).
- **G2 (ARES+HERMES):** `table_scope.resolve_scope` admin'i user_accessible_tables'a yönlendir (Opsiyon A).
- **G3 (ARES+HERMES+ORACLE):** `db_smart_api.post_execute_stream` — resolve_scope(can_execute) +
  check_table_whitelist gate; yetkisiz tablo → 403 "şu tablolarda yetkiniz yok", sonuç YOK.
- **G4 (TYCHE):** pytest — user_accessible_tables dict-row, admin-with-grant, admin-no-grant,
  execute/stream unauthorized-table 403, authorized happy-path.

| Gate | Sorumlu Konsey | Dosya |
|---|---|---|
| G1 | HEPHAESTUS + ARES | app/services/data_source_access.py |
| G2 | ARES + HERMES | app/services/db_smart/table_scope.py |
| G3 | ARES + HERMES + ORACLE | app/api/routes/db_smart_api.py |
| G4 | TYCHE | tests/ |

## 4. Critical Files to Modify
- app/services/data_source_access.py  (G1 — KÖK)
- app/services/db_smart/table_scope.py (G2)
- app/api/routes/db_smart_api.py        (G3 — post_execute_stream)
- tests/...                             (G4)

## 5. Yeniden Kullanılacak Mevcut Fonksiyonlar
- `check_table_whitelist` (safe_sql_executor.py:164) — SQL'den tablo çıkarımı + whitelist reddi (reuse).
- `AccessScope.allows()` — per-tablo kontrol.
- generate_report (db_smart_api:2641-2731) — enforcement deseni (allowed_tables build + boş→reddet).

## 6. Risk Özeti
| Risk | Olasılık | Etki | Mitigasyon |
|---|---|---|---|
| Admin-honors-grants tüm çağrı noktalarını etkiler | Yüksek | Orta | Unmanaged admin (grant yok) davranışı DEĞİŞMEZ (hâlâ ALL); yalnız grant'lı admin kısıtlanır |
| RealDictCursor fix tuple-test'leri bozar | Düşük | Düşük | dict|tuple ikisini de destekle |
| execute/stream 403 FE'de stale sonuç gösterir | Orta | Orta | FE non-2xx handling teyit (mevcut 404/400 raise'leri zaten var) |

## 7. Verification (uçtan-uca)
- `_diag_perm.py` tekrar → scope = 3 gerçek tablo (admin grant'lı).
- pytest yeni testler yeşil.
- FE rerun (FATURALAR raporu) → 403 "yetkiniz yok", sonuç yok; izinli tablo raporu → çalışır.

## 8. Out-of-scope
- `schedule_runner.py` otomatik saved-report koşumu (aynı gate gerekebilir — ayrı follow-up, backlog'a).
- Diğer RealDictCursor dict(zip) latent siteleri (RB-v3.38.8 backlog).
