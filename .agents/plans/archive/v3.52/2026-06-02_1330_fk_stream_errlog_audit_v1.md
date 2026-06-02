---
plan_id: fk_stream_errlog_audit
created: 2026-06-02
branch: hira
status: completed
version_target: v3.52.0
closed: 2026-06-03
closure_note: "KALAN madde (declared-FK okuma görünürlüğü) v3.61.0'da tamamlandı: detect_objects 4 dialekt declared-FK okuma hatası log_exception(ds_learning.fk_declared)'a bağlandı (PG/Oracle logger.error→system_logs; MSSQL/MySQL try/except'siz→sarıldı, non-blocking). SS5 scope-deny diagnostic v3.52.0 G4'te zaten yapılmıştı. FK inference görünürlüğü + matching ise v3.60.0'da. Plan tüm fazlarıyla kapandı."
progress: "v3.52.0: G2 named cursor + G1 error-logging + G4 bg-job-failed (77 test). v3.53.0: G3 cancel multi-worker 404 DB-backed (sql_query_jobs + mig 054 + deep_think DB-poll + 6 test). v3.61.0: declared-FK okuma 4 dialekt log_exception. TAMAM."
council_mod: 3
hebe_gate_required: false
---

# Keşif/Ara hata avı: named cursor + scope-deny + cancel + sample + FK + ERROR-LOG görünürlüğü

## Context (kullanıcı, 5 görsel + metin)
Local Oracle'da sorun yok; canlı PG'de (ONEDESKPG) çok sayıda hata. Kullanıcı: "varsayım yapma,
tüm hataları try/except'e uygun yap, parametreleri HATA LOG ekranında görmek istiyorum —
hataları göremezsek çözemeyiz." Ekiple plan + code-review + çöz.

## Kanıtlanmış kök nedenler (4 Explore ajanı + ZEUS doğrulaması)

### KÖK-1 (SS4) named cursor — CONFIRMED, kod bug
`_get_db_connector` PG → `conn.autocommit = True` (ds_learning_service.py:81). Streaming
`_stream_callable` PG branch `conn.cursor(name=...)` (sql_executor_stream.py:157) → psycopg2:
**"can't use a named cursor outside of transactions"**. Oracle'da autocommit yok + standart cursor → sorun yok.
→ FIX: PG streaming connection autocommit=False (named cursor öncesi); read-only, finally close.

### KÖK-2 (SS3) cancel 404 — CONFIRMED, multi-worker
`_SQL_JOB_REGISTRY` in-memory worker-local dict (safe_sql_executor.py:299). Canlıda 3 worker
(8002-8004); cancel isteği işi ÇALIŞTIRAN worker'a düşmezse → "Job bulunamadı" 404. (v3.47.0
ds_discovery_jobs DB-backed yapıldı; SQL job registry hâlâ in-memory.)
→ FIX: cancel sinyalini DB-backed yap (ds_sql_jobs/redis cancel flag) VEYA cross-worker sinyal;
  net mesaj (başka worker'da çalışıyor olabilir).

### KÖK-3 (cross-cutting) ERROR-LOG görünürlüğü — CONFIRMED, kullanıcının ASIL isteği
`log_exception` (logging_service.py:295, errors.jsonl + system_logs + Hata İzleme UI
`GET /api/system/errors`) YALNIZ main.py global handler'da çağrılıyor. Şu yollar log_exception'a
GİTMİYOR (logger.warning/error veya except:pass → traceback/param KAYBI):
- streaming_execute.py:130 (stream error SSE'ye yield, log YOK)
- sql_executor_stream.py:189 (logger.warning, log_exception yok)
- data_sources_api.py:1373 _bg_collect (logger.error, traceback yok)
- ds_learning_service.py:1374 collect_samples per-tablo (logger.error)
- fk_graph.py:200,317 + db_smart_api.py:1979 related_tables (logger.warning)
- table_guard.enforce_sql_scope DENY (hiç log yok → scope neden boş görünmüyor)
→ FIX: bu noktalara `log_exception(exc, module=, context={parametreler})` ekle; scope-deny'ye
  diagnostic log (scope.tables, SQL'den parse edilen tablolar, admin durumu, permission).
  errors.jsonl format tutarlılığı (zengin format).

### KÖK-4 (SS2) sample "yapıldı dedi ama yok" — data + swallow
_bg_collect (data_sources_api.py:1373) ve collect_samples per-tablo (ds_learning_service.py:1374)
hatayı yutuyor (log_exception yok) → örnekleme sessiz fail → "örnek veri yok" ama sebep görünmez.
Kontrol sorgusu (data_sources_api.py:1236-1254) doğru. → FIX: log_exception + per-tablo fail raporu.

### KÖK-5 (SS5) scope false-deny — KOD BUG DEĞİL, veri-bağımlı
check_table_whitelist parse DOĞRU (quoted/uppercase/schema dequote+lowercase, schema.table+bare
karşılaştırır — safe_sql_executor.py:200-237). user_accessible_tables mantığı DOĞRU
(data_source_access.py:170-243, v3.39.0 RealDictCursor fix'leri yerinde). Deny → scope.tables BOŞ:
ya admin'in `can_execute` grant'ı yok (yalnız can_view → managed-admin empty scope, satır 201-203),
ya da table_permissions kaydı kaydedilmemiş (SS2 ile bağlantılı). → veri-bağımlı; **diagnostic log**
canlıda nedeni gösterir (KÖK-3 kapsamında).

### KÖK-6 (SS1) FK bulunamadı — picker fk_graph yolu, data-bağımlı
Picker /related → expand_with_fk → fk_graph.build_subgraph/_fallback (db_smart_api.py:1916-1988).
**v3.48.0 EXISTS değişikliğim BURADA DEĞİL** (o fk_synthetic_generator._fetch_relationships'te,
sentetik loop). fk_graph case handling LOWER() ile OK. → "FK yok": ya declared FK keşfi PG'de
ds_db_relationships'i doldurmadı (sessiz fail), ya source'ta gerçekten FK yok. → log_exception
(fk_graph + related_tables) canlıda gösterir.

## Faz/Gate Haritası
- **G1 — Error-log hardening (HERMES + ARES) [KULLANICININ ASIL İSTEĞİ, ÖNCE]:** log_exception +
  context{params} → streaming_execute, sql_executor_stream, _bg_collect, collect_samples, fk_graph,
  related_tables, enforce_sql_scope DENY diagnostic. Tümü Hata İzleme'de görünür.
- **G2 — named cursor (HERMES + POSEIDON):** PG streaming autocommit=False (named cursor öncesi).
- **G3 — cancel multi-worker (NIKE + HERMES):** DB-backed cancel flag VEYA net mesaj.
- **G4 — sample bg fail görünürlüğü (HEPHAESTUS):** G1 kapsamı + per-tablo fail raporu.
- **G5 — Test + Code review (TYCHE):** pytest (stream/scope/sample), /code-review medium.
- **G6 — Versiyon (HERA):** v3.52.0.

## Critical Files
- app/services/db_smart/sql_executor_stream.py (named cursor + log)
- app/services/pipeline/streaming_execute.py (stream error log)
- app/services/ds_learning_service.py (_get_db_connector? hayır — connection stream-local; collect_samples log)
- app/api/routes/data_sources_api.py (_bg_collect log)
- app/services/db_smart/table_guard.py (enforce_sql_scope diagnostic log)
- app/services/db_smart/fk_graph.py + app/api/routes/db_smart_api.py (FK log)
- app/services/safe_sql_executor.py (cancel registry)
- app/core/config.py (versiyon)

## Risk
| Risk | Mit |
|---|---|
| autocommit=False streaming conn'u bozar | conn stream-local + read-only SELECT + finally close; PG-only branch |
| log_exception PII sızıntısı | logging_service zaten redaksiyon yapıyor (v3.38.3); context'e SQL/param eklerken hassas alan yok (tablo adı/scope) |
| cancel DB-backed büyük değişiklik | minimal: cancel flag tablosu/sütunu + running job poll; veya faz olarak net-mesaj önce |

## Verification
- Canlı: hata oluştur → Hata İzleme'de tam traceback + param görünür (kullanıcı teyidi).
- named cursor: PG stream → "named cursor" hatası gitmeli (kullanıcı canlı test).
- pytest stream/scope/sample yeşil + /code-review.

## Out-of-scope (ayrı faz, gerekirse)
- FK declared keşfinin PG'de ds_db_relationships'i neden doldurmadığı (canlı DB inceleme; G1 log'u
  yön gösterecek).
- Tam DB-backed SQL job orchestration (cancel için minimal çözüm; tam mimari ayrı sprint).
</content>
