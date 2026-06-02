"""
VYRA L1 Support API - Configuration Module
==========================================
Merkezi konfigürasyon yönetimi. PostgreSQL bağlantısı ve uygulama ayarları.
"""

from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

# Proje kök dizini (vyra_l1_fastapi klasörü)
BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """
    Uygulama ayarları.
    
    Tüm ayarlar .env dosyasından veya environment variable'lardan okunabilir.
    """
    
    # -------------------------------------------------
    #  Genel API ayarları
    # -------------------------------------------------
    app_name: str = "VYRA"
    debug: bool = True
    APP_VERSION: str = "3.59.0"  # v3.59.0: LDAP kaydetme 500 fix + Hata İzleme görünürlüğü. KÖK: create_ldap_setting'te try/except YOKtu → boş bind_password verilince encrypt() ValueError fırlatır (encryption.py:85 "boş olamaz") → yakalanmamış 500, üstelik LDAP CRUD hiç log_exception kullanmadığından Hata İzleme'ye DÜŞMÜYORDU (kullanıcı yalnız ham konsolu görebiliyordu — "hataları göremezsek çözemeyiz" kuralına aykırı). İKİ fix: (1) create'te boş/whitespace bind_password → encrypt'e gitmeden net 400 "Bind password zorunludur". (2) LDAP CRUD'un DÖRDÜ de (create/update/delete/test) try/except + log_exception'a sarıldı → her hata TAM traceback + request_id ile Hata İzleme'de görünür; HTTPException re-raise (4xx/404/400 korunur), generic Exception → log + 500 detail. company_id ZATEN mevcut (schema.py:744 ALTER startup'ta ekliyor, app çalıştığından koşmuş) — sorun o değildi. Şifre context'e KONMAZ + log_exception redact_sensitive uygular. + GERÇEK KÖK (canlı Hata İzleme traceback'iyle teyit): UniqueViolation "ldap_settings_domain_key Key (domain)=(TURKCELL) already exists" — domain UNIQUE constraint'i soft-delete'i KAPSAMAZ (schema.py:560), duplicate pre-check ise WHERE is_deleted=FALSE → soft-silinmiş TURKCELL satırı pre-check'i atlatıp INSERT'te 500 veriyordu (liste de is_deleted=FALSE filtrelediğinden ekranda görünmüyordu). FIX: create'te soft-deleted aynı domain varsa INSERT yerine CANLANDIR (un-delete + yeni değerlerle UPDATE, company/created_by yeniden atanır) → "yeniden etkinleştirildi". Defans: psycopg2 UniqueViolation → ham 500 yerine net 400 (yarış). + UI görünürlük (kullanıcı isteği "is_deleted=TRUE olanları UI'da göreyim"): list_ldap_settings include_deleted param (aktifler önce ORDER BY is_deleted,domain), yeni POST /{id}/restore endpoint (aktif-duplicate UNIQUE guard + try/except+log), frontend "Silinenleri göster" toggle + soft-deleted satır line-through/muted + "Geri Yükle" butonu (ldap_settings.js/.css + section_parameters.html, bundle rebuild). + Düzenle modalında firma ön-seçili gelmiyordu ("Firma seçin..." kalıyordu): _safe_setting_dict company_id DÖNDÜRMÜYORDU → openEdit setting.company_id=undefined → seçilmiyordu; _safe_setting_dict'e company_id eklendi (frontend zaten setting.company_id'yi populateCompanySelect'e geçiriyordu). 7 backend test (boş-pwd/db-log/http-swallow/revive/uniqueviolation+company_id). ÖNCEKİ v3.58.0: Sistem Sıfırlama'ya TABLO-YETKİ tabloları eklendi (data_source_table_permissions + data_source_permissions) — eskiden yetki grant'ları reset'i atlatıp kalıyordu (kullanıcılar silinince orphan). source-scoped (company_id varsa source_id IN company sources), users silinmeden ÖNCE (granted_by→users FK), data_sources KORUNUR. system_logs/sql_audit_log ZATEN reset'teydi. Frontend: "Silinecek Veriler" listesi + onay mesajına "Tablo Yetkilendirmeleri" (section_parameters.html + system_manager.js, bundle rebuild). Code-review temiz, 6 reset testi geçti. ÖNCEKİ v3.57.0: text_to_sql format_schema_for_llm defansif hardening — c['name']/c['data_type']/t['name'] doğrudan key erişimi → bozuk/eski columns_json kaydında KeyError ile şema formatı çökerdi (text_to_sql ŞEMASIZ kalır, halüsinasyon yasağı şemaya dayanır). non-dict guard + .get + boş-ad skip. NOT: text_to_sql kolon-tipi grounding ZATEN vardı (col_dtype + temporal öncelik + halüsinasyon ban + _check_column_hallucination) — bu yalnız defansif hardening, yeni grounding değil. 21 test (2 yeni). ÖNCEKİ v3.56.0: FK inference KÖK fix (picker "FK ilişkisi yok" + "FK İLİŞKİLERİ 29" çok düşük). DB'de ~29 declared FK var (normal); inference boşluğu dolduracaktı ama prefixed şemada (T_WF_*/T_ORG_*) ~0 üretiyordu. İKİ bug: (1) _iter_fk_candidates root'u TAM tablo adına eşliyordu → "instance"≠"t_wf_instance" → candidate yok; fix: by_last_token (son "_"-token) prefix-tolerant fallback + deterministik tie-break. (2) is_pk vs is_primary_key uyumsuzluğu (detect_objects is_pk yazar, inference is_primary_key okuyordu) → pk_cols boş → hedef PK 'id'ye düşer ama PK 'XxxId' → candidate yok; fix: is_pk öncelik+fallback. 51 test (yeni prefixed/is_pk senaryosu). NOT: CANLI'da kaynağı YENİDEN KEŞFET (inference detect_objects'te koşar → inferred FK populate). ÖNCEKİ v3.55.0: generate-report LLM kolon GROUNDING (halüsinasyon fix) — kayıtlı rapor Çalıştır'da 'column "CreatedDate" does not exist' (LLM olmayan tarih kolonu uydurmuştu). KÖK: llm_generate_report._build_prompt LLM'e tablo ADI + kullanıcı-seçili kolonları veriyordu, GERÇEK kolon envanterini DEĞİL. Fix: _fetch_table_columns (ds_db_objects.columns_json) → primary+join tabloların gerçek kolonları (ad+tip) prompt'a "Tablo kolonları (GERÇEK şema)" bloğu olarak (per-table cap 80, token) + sertleştirme "listede OLMAYAN kolonu UYDURMA; uygun tarih yoksa hesaplama, rationale'da belirt". Backward-compat (columns yoksa eski davranış), fail-soft. 4 test. NOT: named-cursor (v3.52.0) AYRI ve fixliydi — bu SQL-üretim doğruluğu sorunu. ÖNCEKİ v3.54.0: DB Keşif "Örneklenecek Şemaları Seçin" adımına şema arama kutusu (.ds-scope-search reuse — magnifier+input+clear×, Yetkilendirme ile tutarlı) + "Seçilenleri Göster" toggle eklendi (ds_learning_module.js _renderSchemaSelect + ds_learning.css). _applySchemaFilter: ad (TR-aware) + show-selected birleşik görünüm filtresi; seçim/örnekleme etkilenmez (count tüm-checked sayar); boş-durum mesajı; a11y (aria-label/aria-hidden/hidden). bundle rebuild. ÖNCEKİ v3.53.0: "İptal Et" 404 (SS3) KÖK fix — multi-worker (8002-8004). _SQL_JOB_REGISTRY in-memory worker-local idi → cancel işi çalıştırmayan worker'a düşünce "Job bulunamadı" 404 (aktif sorguda bile). DB-backed cross-worker cancel: sql_query_jobs tablosu (schema.py + mig 054); register/unregister/cancel DB'ye de yazar (best-effort, in-memory fast-path korunur); cancel başka worker'da çalışan job için status='cancel_requested' yazar; deep_think TICK döngüsü (10sn) is_cancel_requested ile DB'yi poll edip local cancel_event'i set eder. Owner check kod-tarafı (RLS gereksiz). Stale-cleanup (>2h) register'da fırsatçı. 6/6 cross-worker test. ÖNCEKİ v3.52.0: Keşif/Ara hata avı (canlı PG). (1) KÖK FIX named cursor — _get_db_connector PG autocommit=True + stream conn.cursor(name=...) → "can't use a named cursor outside of transactions"; sql_executor_stream PG branch named cursor öncesi autocommit=False (conn stream-local, salt-okuma SELECT, finally close). Local Oracle etkilenmez. (2) ERROR-LOG görünürlüğü (kullanıcı isteği "hataları göremezsek çözemeyiz"): stream/_bg_collect/collect_samples per-tablo/related_tables yutma noktalarına MERKEZİ log_exception(context=params) eklendi → Hata İzleme'de tam traceback+parametre. (3) _bg_collect fail → job FAILED işaretlenir (asılı 'running' kalmaz; SS2 "yaptım dedi ama yapmadı"). (4) enforce_sql_scope RED → diagnostic WARNING log (scope tabloları/parse/admin/SQL) → "yetki var ama red" canlıda görünür (Hata İzleme level=WARNING/ALL). 77 test geçti. NOT: cancel multi-worker 404 (SS3) ayrı faz. ÖNCEKİ v3.51.0: (R022) test_api_db_smart.py 8 pre-existing failure giderildi — 7'si stale test (F17 graceful explain, v3.38 scope gate, v3.40 enforce_sql_scope, v3.41.5 name_exact, v3.38.7 snapshot, v3.39.2 mesaj) güncel doğru davranışa hizalandı; 1'i GERÇEK kod bug'ı: post_explain_ast _select_empty yalnız ast.get("select") bakıyordu → kanonik "columns"-keyed AST (ast_renderer dual-key, satır 437) has_ast:false'a düşüp EXPLAIN/cost hiç hesaplanmıyordu → columns||select dual-key fix (EXPLAIN normal AST'ler için RESTORE; 5sn cache). 72/72 test geçti. ÖNCEKİ v3.50.0: Admin NULL company_id → tanımlı İLK firmaya (companies ORDER BY id LIMIT 1, aktif) RUNTIME sabitlenir — rls_context._first_company_id + resolve_effective_company_id (admin: önce kaynağın firması, yoksa ilk firma) + apply_vyra_user_context (sentinel 0 yerine ilk firma; firma yoksa 0). Kaynaksız FK keşif/arama akışlarında admin NULL→400/403 hatası biter. is_admin='true' RLS bypass DEĞİŞMEZ (mig 032) → çapraz-tenant erişim KORUNUR; NON-admin+NULL → None (fail-closed KORUNUR). DB-level UPDATE YAPILMADI (v3.43.1 admin-NULL tasarımı korunur). 7/7 sahte-cursor smoke. ÖNCEKİ v3.49.0: (1) Yetkilendirme ekranı yalnız KEŞFEDİLEN (örneklenmiş, ds_db_samples JOIN) schema/tablolar listeler — get_source_schema_tree, get_all_tables_status ile tutarlı (ham 269 katalog yerine örneklenmiş alt küme; fallback: sample yoksa tümü). (2) Akıllı Keşif "Tablo Seç" picker arama kutusu: büyüteç ikonu eklendi + clear (×) input-field içine absolute hizalandı (eskiden flex item olarak dışarı kayıyordu; _db_smart_wizard.css + home.html + db_smart_picker.js). (3) Picker /tables GET Cache-Control:no-store — admin yetki verdikten sonra picker ilk açılışta stale liste gelmesin (yetki-scope'lu GET tarayıcıda cache'lenmemeli; canlı teyit gerekir). ÖNCEKİ v3.48.0: FK Loop sentetik SQL YALNIZ keşfedilen tablolar için üretilir — fk_synthetic_generator._fetch_relationships SELECT'ine iki NULL-tolerant EXISTS(ds_db_objects) eklendi (her iki FK ucu ds_db_objects'te kayıtlı olmalı); keşfedilmemiş tabloya giden FK çiftleri (gürültü) elenir. EXISTS açık o.source_id=...source_id korelasyonu taşır → RLS-aktif (mig 007/008 rls_source_scoped) ve production superuser-bypass modunda doğru, daraltma-only parity (48 test). + Graphify alt-sistemi projeden tamamen söküldü (.mcp.json/settings hook'ları + vyrazeus protokol BAŞLA/BİTİR + MNEMOSYNE-GRAPH konsey üyesi). ÖNCEKİ v3.47.1 HOTFIX: Akıllı Keşif wizard admin'de create_session 400 ("user_id ve company_id zorunlu") KÖK fix — db_smart_wizard.js _init'te _ensureSession() KAYNAK SEÇİLMEDEN (source_id:null) çağrılıyordu; admin company_id NULL olduğundan backend company'yi kaynaktan çözemiyor (resolve_effective_company_id source_id=None→None) → 400. v3.43.4 backend fix kaynaksız çağrıda devreye giremiyordu (yalnız backend'di). Fix (frontend): _ensureSession kaynak yoksa no-op (if !sourceId return null) + kaynak seçilince (_openPicker/_searchTables) session KAYNAKLA açılır → admin company çözülür. non-admin etkilenmez. bundle rebuild. v3.47.0 (DEVAM EDEN — FK Loop ops P3b, plan: .agents/plans/2026-06-01_1830_fk_loop_fewshot_integration_v1.md) P3b FK Loop job state DB-backed (multi-worker): in-memory _jobs dict → ds_discovery_jobs (job_type='fk_synthetic'/'incremental_integration'); canlıda 3 process (8002-8004) in-memory state'i paylaşmadığından /synthetic-status başka worker'a düşünce boş dönüyordu. ds_learning_service.create_or_get_running_job (advisory-lock TOCTOU, (id,created) bayrağı → yalnız yeni açıldıysa thread) + complete_job + mevcut check_running_job (any-type preflight mutual-exclusion + 30dk stuck reaper) reuse; mig 053 ds_discovery_jobs company-scoped RLS (mig 017 deseni, defense-in-depth; asıl gate _ensure_source_visible). /synthetic-status cross-tenant sızıntı fix (önceki sürüm görünürlük gate'siz salt source_id okuyordu → apply_company_scope + _ensure_source_visible eklendi). Konsey (NIKE/TYCHE/ARES/HERMES) onayı: Redis GEREKSİZ (DB yeterli), B2 periyodik cron ertelendi (keşif-sonrası tetik incremental_schema_integrator'da event-driven zaten var). code-review: ayrı reaper redundant (check_running_job 30dk zaten reap'liyor) → kaldırıldı, her iki endpoint'e preflight (simetrik mutual-exclusion + create_job type-collision shield), bg success complete ayrı try (complete hatası işi failed yapmasın), SET LOCAL/commit scope etkileşimi (job lifecycle izole connection). ÖNCEKİ v3.46.0 P3a sentetik hata sınıflandırma + ops metrik: synthetic_errors.classify_synthetic_error (ham 4-dialect ORA-/MSSQL/MySQL/PG hatası → permission/not_found/type_mismatch/syntax/timeout/infra/empty/unknown; substring öncelik infra>timeout>permission>type>not_found>syntax) + mig 052 ds_synthetic_query_runs.error_kind (kısmi index); _audit_run error_kind'i INSERT'e ekler (yalnız success=False, tek statement → savepoint-poison yok, graceful kolon kontrolü); /synthetic-failures endpoint'i error_kind/label/action per satır + stats bloğu (toplam/başarı/başarısız + hata sınıfı dağılımı) döndürür; frontend failures paneli renk-kodlu rozet + dağılım özeti (bundle rebuild). code-review: follow-up UPDATE→INSERT (poison fix), empty success'e error_kind yazma, bare 'relation'/'deadlock' yanlış-sınıflama, frontend görünürlük. P3b (Redis job tracker + cron oto-tetik) ertelendi (altyapı-bağımlı). ÖNCEKİ v3.45.0 P2a tip-farkında + 4-dialect template'ler: synthetic_dialect.py (classify_data_type numeric/temporal/text/boolean/other 4-dialect + string_agg/to_day/current_date dialect helper'ları); synthetic_templates 2 YENİ per-FK template — AGGREGATE_STATS (child sayısal ölçünün SUM/AVG/MIN/MAX'i per parent, INNER JOIN deterministik, TOP/FETCH/LIMIT) + EXISTS_ANTI_JOIN (çocuğu olmayan parent'lar, NOT EXISTS + ORDER BY pk); generator tip-keşfi (_load_table_columns ds_db_objects.columns_json + is_pk; _pick_numeric_measure: FK/PK/keyish/patolojik-ad eler, temiz ölçü yoksa skip → skipped_no_column); default kinds 2→4 (1:N FK; 1:1'de yalnız LOOKUP_JOIN); col_ctx dispatch. code-review: TR kolon adı over-filter fix (is_safe_identifier ASCII-only → unicode-toleranslı _safe_measure_name), is_pk-farkında ölçü (anlamsız SUM(id) önlenir), INNER JOIN NULL-sıra fix, anti-join determinizm. P2b TAMAM: atıl PG-only template'ler kurtarıldı — WINDOW_RUNNING_TOTAL 4-dialect + FK-partition (per-parent koşan toplam) default'a eklendi (5 fonksiyon), STRING_AGG_DETAILS oryantasyon fix (parent=rel.to) + LISTAGG/GROUP_CONCAT, DISTINCT_COUNT yeni, TIME_SERIES PG-gate; _KIND_COL_REQUIREMENTS + _build_col_ctx (numeric/temporal/text picker); code-review: test fix (16/16), WINDOW global→FK-partition, tablo-dedup execute-sonrası, STRING_AGG ORDER BY, text picker serbest-metin eleme. P3 (ops) devam. ÖNCEKİ v3.44.0 P0 gürültü temizliği: fk_synthetic_generator._fetch_relationships artık sistem/extension şemaları (pg_catalog/information_schema/partman/sys/mysql/... SSOT _EXCLUDED_SCHEMAS) + düşük-confidence (<0.85) admin-doğrulanmamış inferred FK + admin-reddedilen FK'leri sentetik üretimden DIŞLAR (pg_partman.part_config TEXT↔TEXT anlamsız JOIN'leri → 2 hata+16 boş deneme gürültüsü giderildi). declared FK + admin_verified inferred KORUNUR. P1 (few-shot terfi) TAMAM: FK Loop sentetiği few_shot_examples'a terfi (origin='synthetic_fk', mig 051) — few_shot_auto_populator.promote_synthetic mevcut dedup(L1+L2)/embedding/signature altyapısını yeniden kullanır (çift insert yolu yok); select_few_shots origin SELECT + is_active filtre + SYNTHETIC_WEIGHT 0.85 + PRIORITY_FLOOR 0.30 + cap 1; intent=None (yapay mismatch cezası önlenir); _has_origin_columns yalnız-pozitif cache (graceful). code-review: REUSE mimari fix (upsert_example revert) + intent çift-ceza + cache kilidi + _picked id()→DB id. P2 (tip-farkında çok-dialect template), P3 (ops) devam. v3.43.4 Akıllı Keşif admin KÖK fix: admin company_id NULL (tasarımca) db-smart wizard'da create_session (400 "company_id zorunlu") + generate-report (403 "Şirket bağlamı tanımlı değil") veriyordu. v3.43.1 RLS context'i açtı (GET'ler), ama bu 2 endpoint + save AYRI company_id NOT NULL gerektiriyordu. Fix: resolve_effective_company_id(cur, user_ctx, source_id) — admin+NULL ise KAYNAĞIN firması (data_sources.company_id, NOT NULL); create_session/generate-report/save eff_ctx ile (tenant izolasyonu korunur: oturum/rapor kaynağın gerçek firmasına atanır; non-admin+NULL fail-closed). NOT: pre-existing tasarım açığı (v3.30.0/v3.36.0), v3.43.1 wizard'ı derinleştirince yüzeye çıktı. saved_reports CRUD (list/get/update/mark-run/share/revoke) de admin'e açıldı: _require_user_ctx admin için company_id istemez (dbsmart_saved_reports RLS user_id+is_admin tabanlı, company ile filtrelemez), save() net-400 guard'ı korur (INSERT NOT NULL ihlali yerine). v3.43.3 Frontend cache-bust KÖK fix: home.html bundle ?v= ELLE bump ediliyordu, v3.41.3'te kalmıştı → nginx immutable+30d cache eski bundle'ı servis ediyor, v3.43.0-3.43.2 frontend değişiklikleri (progress UI, Yetkilendirme "Tümünü Temizle"/"Seçilenleri Göster", Etiketleme filtre) cache'li tarayıcıda GÖRÜNMÜYORDU (kullanıcı raporu: "Tümünü Temizle gelmedi"). build.mjs artık ?v='yi bundle içerik-hash'iyle OTOMATİK günceller (drift tekrar etmez). v3.43.2 Keşif/Yetki UX 4 fix: (1) Yetkilendirme schema-tree artık VIEW'ları da listeler (object_type IN table,view — keşfedilmiş view aratınca gelmiyordu, Etiketleme paneliyle tutarsızdı 245 vs 388); (2) aynı fix "yalnız keşfedilmiş listelensin" isteğini karşılar (liste zaten ds_db_objects-only, artık tam); (3) Etiketleme paneli "Onaylıları Göster" seçiliyken keşif-bekleyen (enrichment_id NULL) tablolar artık GİZLENİR — yalnız "Düşük Skor/İsimsizleri Göster" veya Keşif Bekleyenler sekmesinde görünür (discoveryMatch); (4) Yetkilendirme "Seçili tablolar" moduna global "Tümünü Temizle" + "Seçilenleri Göster" kontrolleri (HEBE: aria-label/tooltip/focus-visible/marka renkleri). v3.43.1 (hotfix) Admin kullanıcı db-smart 500 KÖK fix: admin'ler tasarımca NULL company_id'li (schema.py:764 backfill yalnız non-admin'i doldurur), apply_vyra_user_context ise NULL company_id'de RLSContextError fırlatıp /sources /saved-reports /sessions vb. TÜM db-smart endpoint'lerini 500'lüyordu (localde admin company_id dolu→çalışıyor, canlıda NULL→500). Fix: is_admin company_id'den ÖNCE hesaplanır; admin+NULL→sentinel 0 (RLS is_admin='true' bypass'ı erişimi açar), non-admin+NULL fail-closed KORUNUR (cross-tenant guard). v3.43.0 DB keşif sertleştirme: (P0-A) re-keşif admin onaylarını artık silmiyor — detect_objects koşulsuz enrichment DELETE'i kaldırıldı, diff-tabanlı selektif invalidation (_invalidate_enrichments_on_diff: silinen→arşiv, değişen→schema_hash NULL re-enrich, geri-eklenen→reaktivasyon, kaldırılan kolon→orphan temizliği); (P0-B) collect_samples boyut-farkında RASTGELE örnekleme (TABLESAMPLE/SAMPLE/ORDER BY random) + per-statement timeout + hata sonrası rollback; (P1-C) enrich_tables_batch ThreadPoolExecutor(max_workers=4) sınırlı eşzamanlılık (worker başına get_db_conn); (P1-D) ds_discovery_jobs progress_* (mig 050) + update_job_progress + frontend X/N göstergesi; (P2-E) create_job advisory-lock TOCTOU + _auto_invalidate content_type-agnostic orphan; (prod fix) get_pending_approvals/get_approved_enrichments RealDictCursor dict(zip) çöp→dual-mode; (prod fix) system_logs.request_id SCHEMA_SQL'de index ÖNCESİ ADD COLUMN IF NOT EXISTS (Alembic timeout'ta UndefinedColumn crash önleme); (prod fix) LLM JSON parse _coerce_llm_json çok-stratejili (extract_json_obj+güvenli onarım) + prompt sertleştirme; get_active_llm finally connection iade. v3.42.1 İki frontend duplicate fix: (1) deep_think DB-Only ÇİFT YANIT — websocket db_query_complete push'u (v3.42.0 import fix'iyle aktifleşti) kullanıcı sohbet ekranındayken SSE on-screen render'la çakışıyordu: scope-denial'da SSE bubble message_id'siz→dedup kaçar (çift Yetki Notu); success'te content[:200] narrative'i TABLO yerine. Fix handleDbQueryComplete !statusEl guard (dbqs_jobId DOM'daysa SSE'ye bırak; ekran dışıysa render — cross-screen bildirim korunur). (2) Akıllı Keşif WHERE 2× — AST editör _flushPatch base_ast'e optimistic-SONRASI state.ast (filtreyi içeren) gönderince backend session-boşken (base_ast fallback db_smart_api.py:474) add_filter'ı TEKRAR uyguluyordu → WHERE çift (chip+önizleme/assemble SQL; PRE-EXISTING v3.38.4, v3.42.0 önizleme-filtresi GÖRÜNÜR kıldı; execution LLM dedup→doğruydu). Fix base_ast: rollbackAst (pending[0].prevAst optimistic-ÖNCESİ; 409-guard korunur). v3.42.0 Akıllı Keşif WHERE/ORDER BY uçtan uca: önizleme/kaydet SQL'i WHERE(AST editör chip)+ORDER BY(SIRALAMA chip) yansıtır (_buildWizardState filters/order_by→query_assembler/ast_renderer {expr,op,value}/{expr,dir}, _orderByToRenderer/_orderByToChip köprü; kaydet persist+rehydrate); icra (/generate-report LLM) filters/order_by'ı _build_prompt'a ZORUNLU kısıt → üretilen+çalıştırılan SQL WHERE/ORDER BY içerir (assemble dış-kaynak icrada KULLANILAMAZ — inject_rls non-admin'e company_id enjekte eder, Oracle tablosunda o kolon yok → LLM+SafeSQLExecutor, tenant izolasyonu source-level+whitelist); query_assembler.inline_binds deterministik display SQL'de %(v_1)s→gerçek değer (Oracle :name/MSSQL @name prefix-overlap safe, injection-safe _literal quote-escape); SQL modal boş-talepte yalnız deterministik üst (nihai LLM gizli); rapor export xlsx/docx/pdf (/api/db/export/{fmt} reuse, pozisyonel→dict) + Üretilen SQL kopyala; deep_think Faz1 _is_followup golden/cache short-circuit skip ("bu siparişin müşteri detayı" artık tüm müşteri getirmez) + join_planner (FK grafiği deterministik join, bridge-leak guard); infra ORA-12170 _is_infra_db_error fast-fail + safe_sql_executor ORA/DPY/TNS-kod koru (Fortify-safe host/port'suz) + websocket ws_manager import fix + EmbeddingManager SINGLETON (__new__+RLock per-call cold-load hang fix). code-review 2 tur 10+ bulgu: inline_binds Oracle prefix-overlap, prompt _literal (O'Brien), finalSql cache key, fallback uyarısı, bridge-leak, init-race, narrative dead-flag, dup/dead temizlik — hepsi fix+smoke. v3.41.6 Veritabanında Ara & Akıllı Keşif tutarlılık: wizard generate_report whitelist'i picker yerine TAM can_execute scope'tan (_execute_scope_whitelist) → not'tan gelen yetkili-ama-seçilmemiş tablo (ör. ADRESLER) yanlış reddedilmez; red mesajları reddedilen tabloyu can_view-gated adlandırır (site1 403 picker + site2 200 üretilen-SQL, _parse_denied_ref); deep_think 'Yetki Notu' yalnız GERÇEK scope reddinde (_is_scope_denial_error — parse/LLM hatası yetkili tabloyu yanlış reddetmez); DIAGNOSTIC/yorum-only LLM çıktısı (text_to_sql._is_comment_only_sql + llm_generate_report._extract_diagnostic) generic 'Yalnızca SELECT'/sessiz SELECT* yerine açıklamayı yüzeye çıkarır (geçerli SQL varsa override yok — code-review fix); SQL önizleme modalı .dsw-sql-modal geniş+sabit 85vh+iç scroll; kayıtlı rapor Sil → close() _opts'u sıfırlamadan ÖNCE onDeleted yakalanır (kart anında kaybolur, F5 gereksiz). v3.41.5 Rapor kaydet "aynı isimde var" YANLIŞ POZİTİF KÖK fix: GET /saved-reports endpoint'i frontend'in gönderdiği name_exact query param'ını KABUL ETMİYORDU → FastAPI bilinmeyen param'ı düşürür, isimden bağımsız EN SON rapor dönerdi → kullanıcının ≥1 raporu varsa HER kayıtta (isim değişse de) "aynı isimde var" + Üzerine yaz alakasız raporu ezer / Vazgeç hiç kaydetmez. Servis (saved_reports.list_for_user) name_exact'i (WHERE LOWER(name)=LOWER(%s)) ZATEN destekliyordu — yalnız endpoint wiring eksikti. name_exact: Optional[str]=Query(None) eklendi + list_for_user'a geçirildi (RLS korunur, parametreli sorgu). Sahte-cursor ile kanıt: farklı isim→0, aynı isim/farklı case→1, filtresiz→tam liste. v3.41.4 "Veritabanında Ara" follow-up: SQL doğru üretiliyor ama bağlantı hatasında YANLIŞ mesaj. process_stream_db_only hata dallarında timeout/cancelled için özel mesaj vardı ama BAĞLANTI/ALTYAPI hatası (ORA-12537 TNS:connection closed / DPY-4011) için dal yoktu → generic "sorunuzu farklı şekilde ifade edin"e düşüyordu (yanlış yönlendirme: soruyu değiştirmek bağlantıyı düzeltmez, kullanıcı boşuna uğraşır). _is_infra_db_error final exec_result.error üzerinde yeniden değerlendirilip net "🔌 Veritabanına ulaşılamıyor — sorunuzu değiştirmenize gerek yok, birkaç dk sonra deneyin" mesajı (error_kind=infra_error). NOT: ORA-12537 kök neden veritabanı tarafı (listener'a bağlanılıyor ama servis/PDB devri başarısız) — kod SQL'i doğru üretir+net raporlar, gerçek veri Oracle bağlantısı sağlıklı olunca gelir. v3.41.3 Akıllı Keşif "Aynı isimde rapor var" onayı görünmüyor/kaydetmiyor KÖK fix: VyraModal overlay (uygulama genelindeki TEK global onay diyaloğu) z-index 10000 idi; wizard kaydet modalı .dsw-save-modal z:11100 (fixed/inset:0 tam-ekran) ARKASINDA kalıyordu → onay diyaloğu görünmüyor + kaydet overlay'i "Üzerine yaz/Vazgeç" tıklamalarını yutuyor (isim değişse de kaydetmiyor). modal.css 10000→11500 (save/chart/result/session_timeout üstünde, lightbox/document_enhancer tam-ekran görüntüleyiciler altında, 400 headroom). v3.41.2 BİTİR code-review fix (4 bulgu): (B-1) generate_report ÜRETİLEN SQL'i de whitelist'e doğrular — per-tablo 403 yalnız PICKER'da SEÇİLEN tabloları kontrol eder, LLM çıktısı seçilmemiş YETKİSİZ FK-komşu tablo ekleyebilir → restricted kullanıcıya o SQL'i (tablo adıyla) GÖSTERME/çalıştırma (generate_only + execute öncesi, sızıntısız mesaj). (B-2) post_execute_stream saved-report rerun gate'i manuel check_table_whitelist + sızdıran _bad mesajı yerine merkezi enforce_sql_scope (leak-free, Faz B ile tutarlı). (F-1) wizard _onShowSqlClick stale-DOM race — VyraModal tek overlay reuse eder → modal kapanıp yeniden açılırsa eski yavaş LLM .then()'i yeni modal'ın #dswSqlFinalPre'sine yazıyordu; per-open token (_sqlModalSeq). (F-2) SQL kopyala butonu LLM hatasında HATA mesajını kopyalıyordu → _finalSqlText ayrı tutulur, kopyala gerçek SQL'i (veya boş) verir. v3.41.1 "Veritabanında Ara" perf+dialect: (1) Oracle connect-timeout — _get_db_connector'da DSN descriptor CONNECT_TIMEOUT=15 (PG/MySQL/MSSQL'de vardı, Oracle'da YOKtu → erişilemez listener'da connect ~430s asılıyordu; manuel kanıt 430.7s→32.5s ORA-12170). (2) Self-heal bağlantı/altyapı hatasında (ORA-28547/12xxx/TNS) tetiklenmiyor — _is_infra_db_error guard, LLM-regenerate+reconnect LOOP'u (285s) yerine fail-fast. (3) post_preview base SQL dialect'i KAYNAKTAN çözüyor (FE hardcoded 'postgresql' → Oracle'da base LIMIT yanlıştı; artık FETCH FIRST). v3.41.0 Wizard SQL önizleme: SEÇİM vs NİHAİ SQL yan yana — modal üstte seçimlerden oluşan deterministik SQL (assemble), altta talebinizle oluşan NİHAİ SQL (LLM, generate-report yeni generate_only=true ile ÇALIŞTIRMADAN üretilir); Çalıştır nihaiyi koşar. Kullanıcı "ne istedim / ne üretildi"yi görüp sürecin LLM ile çalıştığına emin olur. + generate_only bayrağı (execute atla, scope gate korunur). v3.40.0 Tablo-yetki TÜM execute yüzeylerinde FAIL-CLOSED (Faz B): yeni merkezi guard db_smart/table_guard.enforce_sql_scope (check_table_whitelist boş=allow-all footgun'unu kapatır) → query_builder/preview (None idi), query_state/preview (self-referential [req.table] idi), agentic /api/agentic-query[/stream] (get_allowed_tables=tüm tablolar idi; current_user threadlendi + per-SQL enforce), schedule_runner (zamanlanmış rerun owner can_execute re-check) hepsi bağlandı; yetkisiz tablo→DENY (yetkili listeler, sızdırmaz). + Faz A/G3 (v3.39.2). v3.39.2 "Veritabanında Ara" (DB-Only) restricted kullanıcı NET yetki mesajı (Faz A/G3): yetkisiz tablo sorulunca generic "Yalnızca SELECT / farklı sorun" VEYA check_table_whitelist'in sormadığın FK-komşu adını ("Tablo erişim yetkisi yok: SİPARİŞLER") sızdırması yerine tek mesaj → "Yetkili tablolarınız: X. Sorunuz yetkili olmadığınız bir tabloya ilişkin." (_scope_restricted_message). Faz B (agentic/query_builder/query_state/schedule_runner fail-closed) pending. v3.39.1 ast_renderer kolon ÇIKTI alias'ı serbest metin (boşluk/Türkçe) KÖK fix: _render_column alias'ı bare-identifier (_validate_ident) sanıp "Invalid identifier: 'Adres Kimliği'" → preview "assembly failed" veriyordu; çıktı alias'ı referans değil sonuç başlığıdır → _quote_output_alias güvenli tırnaklama (kapatma-tırnağı ikilenir=injection guard, kontrol baytı reddi, 128 cap), expr strict kalır, 4 dialect+104 test. + wizard 8 eksik i18n toast/error/banner key (TR+EN, raw key gösteriyordu). v3.39.0 tablo-yetki KÖK fix (RealDictCursor scope çöp dönüyordu '('schema_name','table_name')' + admin-honors-grants Opsiyon A + saved-report rerun execute/stream tablo whitelist gate, yetkisiz tablo→403 Türkçe sonuç yok) + wizard footer "SQL" önizleme butonu (talep+pretty SQL+kopyala VyraModal) + Graphify manuel (graphify.bat USE_TF=0/sistem py313 embed_errors 91→0, start.ps1'den çıkarıldı, mcp_warmup.bat silindi). v3.38.8 BİTİR code-review fix: (KRİTİK regresyon) report_detail_modal mark-run snapshot bloğu `result`'ı const tanımdan ÖNCE okuyordu → TDZ ReferenceError → HER Çalıştır başarısız + snapshot yazılmıyordu; result+render önce, mark-run sonra. + _prettyPrintSql marker'ı OBJECT ({kw}) — v3.38.6 düz 'KW'/'STR' marker'ları 'KWH_total'/'STR2024' gibi tanımlayıcılarla çakışıyordu (kontrol baytı da re-korupsiyon riskliydi); STR placeholder __VYRA_STR_N__. + mark-run server-side snapshot cap (rows≤100 + ~600KB, DoS guard). + vyrazeus DB kuralı düzeltildi (RealDictCursor) + REFACTOR_BACKLOG sistemik dict(zip) listesi. v3.38.7 İki bulgu: (1) "Çalıştır kolon var veri yok" KÖK fix — report_detail_modal _renderRunResult SSE/snapshot rows POZİSYONEL dizi ([v0,v1,...]) iken row[c] ile kolon ADIYLA indeksliyordu → her hücre undefined→boş; Array.isArray ise pozisyona eriş. + mark-run artık snapshot kaydediyor (last_run_snapshot NULL kalmıyordu) + modal açılışta snapshot render. (2) Duplicate-name uyarısı native window.confirm + ham i18n key yerine modern VyraModal.confirm (onConfirm=üzerine yaz, onCancel=alan hatası, isim XSS-escape) + eksik i18n key'ler (wizard.confirm.duplicate_name[.title/.confirm/.cancel], error.duplicate_name_field, toast.report_updated) TR+EN eklendi. v3.38.6 SQL üretme W0/W garbage KÖK fix: db_smart_wizard _prettyPrintSql keyword marker'ı '\x02KW\x02' (gizli STX kontrol baytları, bayt korupsiyonu — _tblKey NUL ile aynı sınıf); slice(2) sadece ilk 2 karakteri atıp 'W\x02'+keyword bırakıyordu → ekranda W0SELECT/W0FROM/... Backend SQL TERTEMİZ; W frontend display formatter bug'ıydı (backend _repair_glued_keyword_garbage yanlış teşhis/band-aid). Fix: 4 STX baytı silindi → marker temiz 'KW' → slice(2) doğru strip eder. node ile doğrulandı: temiz formatlı SQL, W yok. v3.38.5 B4-3 silinen kayıtlı rapor anında kaybolmuyor — EKSİK fix tamam: optimistic removeItem vardı ama home.html ardından refresh() çağırıyor; refresh GET'i DELETE commit'ini görmeden race edip kaydı geri getirebiliyordu (skeleton flash + reappear). Fix: SavedReportsGrid _deletedIds Set — optimistic-silinen id'ler refresh re-fetch'inde filtrelenir (reappear engellenir), sunucu artık döndürmeyince self-heal. v3.38.4 Bulgular4 kalan 2 madde KÖK fix: (B4-4 Çalıştır 500) _load_source rec mapping — get_db_context RealDictCursor → row dict; dict(zip(keys,row)) dict ANAHTARLARINI yineliyordu → rec değerleri kolon adlarına eşitleniyordu (host='host'→canary→HER saved-report rerun "kaynak bozuk" 500; decrypt fail de semptomu). Fix: dict(row) if isinstance(row,dict). Uçtan uca kanıt: Oracle'dan 10 satır aktı. (B4-1 WHERE→409) ast/patch base_ast fallback: session context.ast stale/empty olabilir → client canonical AST'ini taban al (FE base_ast gönderir), 409 yerine patch uygulanır. v3.38.3 Merkezi Hata Gözlemi: JSONFormatter artık exc_info(traceback) yazar (eskiden düşürüyordu→traceback kayboluyordu) + logs/errors.jsonl ayrı ERROR+ akışı + log_exception() (NUL-strip + hassas alan redaksiyonu + boyut limiti) + request_id/X-Request-ID korelasyonu + GET /api/system/errors(+stats) admin endpoint + "Hata İzleme" admin UI sekmesi (error_monitor.js) + .agents/tools/show_errors.py CLI + mig 049 (system_logs.request_id + indeks) + ajan kuralı (vyrazeus "HATA AYIKLAMA: önce errors.jsonl"). v3.38.2 Tablo-yetki KAYDET FIX: data_sources_module _tblKey ayraç baytı NUL(0x00)→boşluk — join(NUL) ile split(boşluk) uyuşmuyordu → (1) şema/tablo bölünmüyor (schema='' + composite), (2) NUL'lı string PG'ye gidince "null character not permitted" → 500 (Save permissions error). + backend savunması (PUT /permissions: schema/table'dan NUL & U+FFFD strip, boş-schema composite ayraçtan böl) + bozuk data_source_table_permissions temizliği. Kaynak dosya 3 NUL baytı içeriyordu ('data' olarak sınıflanıyordu) → grep/build riski. v3.38.1 Bulgular4 round2 (5 fix): B4-1 add_filter düz {expr,op,value} kabul (WHERE 400 TypeError fix) + B4-2 garbage regex anchor (?:^|(?<=\s)) (satır-içi W0FROM onarımı) + B4-3 saved-report grid optimistic removeItem (silince anında kaybolur) + B4-4 save source_id/dialect wizard_state fallback (rerun "kaynak bozuk" fix + rapor backfill) + B4-5 #dswResults reset (Yeni Keşif fresh) & wizard.toast.select_table_first i18n. v3.38.0 Tablo bazlı yetkilendirme (DB+schema+tablo): data_source_table_permissions + scope_mode (mig 048) + user_accessible_tables gate + Discover/Smart Discovery/text-to-sql/execute whitelist tablo filtresi (yetkisiz tablo görülemez/tahmin edilemez) + Yetkilendirme modalı schema akordion + code-review fix (deep_think DB-Only & generate_report execute whitelist scope-kesişimi, boş→reddet). v3.37.9 Bulgular4 Smart Discovery 5 fix: B1 Step3 "İleri" guard (_applySuggestionSlot _updateNextGuard çağırmıyordu — LLM öneri uygulayınca buton pasif kalıyordu) + B2 AST editor redundant ORDER BY section kaldırıldı (wizard SIRALAMA chip barı kalır) + B3 ast_renderer dual-key (select↔columns köprü) — WHERE filtre /explain 400 "SELECT requires at least one column" fix + B4 LLM glued garbage keyword-prefix (W0SELECT/WDFROM) hedefli onarım (raw telemetri korunur) + version drift fix (3.37.1→3.37.9) + bundle rebuild. v3.37.1 Smart Discovery follow-up: A (rerun port resolve) + B (metric auto-LLM) + C (saved-report pretty SQL) + D (Step3 metric-aware kolon + validation toast, deterministik POSEIDON kuralları, /llm/column-filter-suggest endpoint) + E (Step3 user-note sticky) + F (Step4 Run button header) + G (format auto-run) + 047 migration (saved_reports source_id backfill) + Graphify-guard hook path-aware redesign. v3.37.0 Smart Discovery bulgular B1-B8 + LLM augmentation (metric/column/format suggest) + db_type normalize fix. v3.36.0 Smart Discovery Completion (F6-F22): F6 WHERE AST fix + F7 multi-column endpoint + F8/F8b LLM suggestion slots (table_id round-trip) + F9 generate-report LLM endpoint + Çalıştır popup + F10b saved-reports flat fallback route + post_save_report_flat + F11/F11b DbSmartChart popup + Oracle DD-MON-YY date detection + chart z-index 11050 + F13 picker FK multi-hop graph (adjacency BFS, abort controller) + F14 metric step accordion+search+multi-checkbox + F15 allowed_tables case-insensitive + F16 save modal z-index 11100 + INSERT 500 root cause + F17 AST explain/patch graceful 422 + F19-F21 retro (report detail modal route prefix, edit-mode hydration step1 chips, Çalıştır SSE, AST undo/redo + last-step Next + Maliyet badge removal) + F22 saved-report rerun dialect resolution (omit FE, BE alias normalization) + edit-mode source_id snake/camel hydration + picker initialSelection round-trip (primary+joins) + cost badge UI removal. v3.34.3 post-test fixes (picker z-index 1100→1300, wizard step1 source readonly badge, saved_reports × is-filled toggle verify) + v3.34.2 picker 6 enhancement (schema accordion, Tümünü Temizle, Sadece Seçilenler toggle, search × icon, persistence, FK warning). v3.34.0 vyraFetch helper + Frontend HTTP migrasyonu (~30 modülde Türkçe defansif hata kontratı: 502/503/504, network failure, 401/403) + MemPalace freshness gate (HEAD-hash short-circuit, MINE_TIMEOUT 600s) + v3.33.1 fix bundle (rapor şablonu prompt, display SQL, multi-tenant RLS tanılaması, picker limit 500, wizard tablo arama %% escape) + archive housekeeping (v3.30 agentic_master + v3.34 paketi). v3.33.0 Akıllı Veri Keşfi (Smart Data Discovery): saved-reports card grid (Ajan-B) + modal wizard wrapper (ESC/overlay/focus-trap/return-focus, HEBE polish) + SaaS modern dialog (glass-morphism + gradient stepper) + i18n loader bootstrap fix (auto-init + bundle entry) + backend RLS-aware /sources & duplicate/delete endpoints (Ajan-D) + admin company_id NULL data-fix. v3.32.0 Query Builder execute path + JOIN HINTS smart search + Fernet rotation + admin learning widgets. v3.29.11 Dedupe L2 pgvector guard (FK Loop poison fix) — dedupe_service.check_duplicate Layer 2 artık question_embedding kolonu `vector` değilse (float8[]/array) sessizce atlanır; aksi halde `<=> ::vector` operatörü tip uyumsuzluğunda transaction'ı poison'lıyordu (psycopg2.errors.InFailedSqlTransaction) ve fk_synthetic_generator'da 58/58 attempt fail oluyordu. learned_queries_service._detect_embedding_column_type lazy import. + detect_objects response'una declared_count/inferred_count/total_relationships eklendi (UI ayrı gösterim). v3.29.10 Housekeeping closure + 2 bug fix (heatmap 500 + enrichment empty-state onclick null) — see README. v3.29.9 Multi-dialect FK Inference Layer — RC1: fk_inference_service.py (convention-based: naming patterns + type compat + sample validation, 4 dialect adapters PG/Oracle/MSSQL/MySQL via Protocol + factory) + migration 031 (ds_db_relationships → is_inferred/inference_method/evidence_json/admin_verified/verified_by/verified_at/rejected_at + system_settings FK_INFERENCE_DEPLOY_TS) + 50 test. RC2: 6 admin endpoint (POST /infer-fks, GET /inferred-relationships, POST /verify, POST /reject, POST /bulk-verify, GET /fk-inference-stats) + auto-trigger in ds_learning_service Step 2. RC3: v3.29.8 integration — multi_signal_rank.build_centrality_index (confidence-weighted: declared=1.0, inferred unverified=0.5×conf, verified=1.0, rejected=0) + analyze_signal_weights min_event_age_hours filter (fk_centrality samples filtered pre-Pearson) + signal_weight_api /current adds fk_inference_recent_deploy/age_hours + text_to_sql FK SELECT filter (rejected NULL, is_inferred=FALSE OR verified OR conf≥0.70). RC4: signal_weight_tuner deploy banner + agentic_observability "FK Inference" tab + ds_learning_module "FK Çıkarımını Yenile" button + Inferred/Declared rozetleri. 89 test green.

    # Frontend & API prefix
    api_prefix: str = "/api"
    frontend_origin: str = "http://localhost:5500"

    # CORS için kullanılan origin listesi
    # Production'da .env'den oku: CORS_ORIGINS=https://vyra.company.com
    # Birden fazla origin virgülle ayrılarak tanımlanabilir
    CORS_ORIGINS: str = ""
    
    backend_cors_origins: List[str] = [
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:8002",
        "http://127.0.0.1:8002",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
    ]

    @model_validator(mode='after')
    def _merge_cors_origins(self) -> 'Settings':
        """Production .env'den CORS_ORIGINS varsa listeye ekle. Replit domain otomatik eklenir."""
        import os
        replit_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
        if replit_domain:
            for scheme in ["https://", "http://"]:
                origin = f"{scheme}{replit_domain}"
                if origin not in self.backend_cors_origins:
                    self.backend_cors_origins.append(origin)
        replit_domains = os.environ.get("REPLIT_DOMAINS", "")
        if replit_domains:
            for domain in replit_domains.split(","):
                domain = domain.strip()
                if domain:
                    for scheme in ["https://", "http://"]:
                        origin = f"{scheme}{domain}"
                        if origin not in self.backend_cors_origins:
                            self.backend_cors_origins.append(origin)
        if self.CORS_ORIGINS:
            extra_origins = [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
            for origin in extra_origins:
                if origin not in self.backend_cors_origins:
                    self.backend_cors_origins.append(origin)
        return self

    # -------------------------------------------------
    #  JWT ayarları
    # -------------------------------------------------
    JWT_SECRET: str = ""  # ⚠️ ZORUNLU: .env dosyasından ayarlanmalı
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 saat
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    def validate_jwt_secret(self) -> None:
        """JWT_SECRET'ın güvenli bir şekilde ayarlandığını doğrular."""
        insecure_values = ["", "CHANGE_ME_IN_.ENV", "your-secret-key", "secret", "changeme"]
        if self.JWT_SECRET in insecure_values or len(self.JWT_SECRET) < 32:
            raise RuntimeError(
                "\n" + "=" * 60 + "\n"
                "🔒 GÜVENLİK HATASI: JWT_SECRET ayarlanmamış!\n"
                "=" * 60 + "\n"
                "JWT_SECRET değeri .env dosyasında tanımlanmalıdır.\n"
                "En az 32 karakter uzunluğunda güvenli bir değer kullanın.\n\n"
                "Örnek (.env dosyasına ekleyin):\n"
                "JWT_SECRET=your-super-secret-key-at-least-32-characters-long\n"
                "=" * 60
            )

    # -------------------------------------------------
    #  PostgreSQL Veritabanı Ayarları
    # -------------------------------------------------
    # Standalone PostgreSQL kurulumu
    PGSQL_DIR: str = str(BASE_DIR / "pgsql")
    
    # Bağlantı parametreleri
    # ⚠️ GÜVENLİK: Üretimde 'postgres' superuser yerine 
    # kısıtlı yetkili 'vyra_app' kullanıcısını kullanın.
    # Bkz: scripts/create_app_user.sql
    DB_HOST: str = "localhost"
    DB_PORT: int = 5005  # Standalone kurulum için özel port
    DB_NAME: str = "vyra"
    DB_USER: str = "postgres"      # .env: DB_USER=vyra_app (önerilen)
    DB_PASSWORD: str = "postgres"  # .env: DB_PASSWORD=guclu_sifre

    # -------------------------------------------------
    #  RAG / Dosya Yükleme ayarları
    # -------------------------------------------------
    # Desteklenen dosya formatları
    SUPPORTED_FILE_EXTENSIONS: List[str] = [
        ".pdf", ".docx", ".doc",
        ".xlsx", ".xls",
        ".pptx", ".ppt",
        ".txt", ".csv"  # v3.3.0: CSV desteği
    ]
    
    # Maksimum dosya boyutu (MB)
    MAX_FILE_SIZE_MB: int = 50
    
    # ChromaDB embedding model
    EMBEDDING_MODEL: str = "paraphrase-multilingual-MiniLM-L12-v2"
    
    # Chunk ayarları
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 100
    
    # v3.3.0 [A6]: RAG chunk konfigürasyon — .env ile override edilebilir
    RAG_PDF_CHUNK_SIZE: int = 2000       # PDF section max chunk boyutu
    RAG_PDF_CHUNK_OVERLAP: int = 100     # PDF chunk overlap
    RAG_MIN_CHUNK_LENGTH: int = 30       # Minimum chunk karakter uzunluğu
    RAG_LLM_MAX_CONTENT_CHARS: int = 6000  # Enhancement LLM'e gönderilecek max karakter
    
    # -------------------------------------------------
    #  Cache & Performans Ayarları
    # -------------------------------------------------
    EMBEDDING_CACHE_SIZE: int = 500  # Max cached embedding sayısı
    FUZZY_CACHE_SIZE: int = 500  # Max cached fuzzy match sayısı
    LLM_BYPASS_THRESHOLD: float = 0.70  # RAG skoru bu değerin üzerindeyse LLM atlanır
    PGVECTOR_INDEX: bool = True  # pgvector index kullanımı etkin mi
    REDIS_URL: str = "redis://localhost:6380/1"  # 🔧 v2.60.2: Port 6380 (6379 çakışma önleme)
    
    # 🆕 v2.57.0: Hybrid Router & Safe SQL Executor
    SQL_EXEC_TIMEOUT: int = 5       # SQL sorgu timeout (saniye)
    SQL_MAX_ROWS: int = 100         # Maksimum döndürülen satır sayısı

    # v3.15.0: Long-running DB query — kullanıcı beklemek istediği sürece sabretmek için
    # SSE wait-loop maks bekleme süresi (saniye). Bu süre dolunca kullanıcıya
    # "X dakika içinde tamamlanamadı" mesajı gösterilir; SQL hala arka planda kalmaz
    # (executor thread bırakılır). Nginx proxy_read_timeout bunun üzerinde olmalı.
    DB_QUERY_MAX_WAIT_SECONDS: int = 900  # 15 dakika
    
    # -------------------------------------------------
    #  Scheduler & System Ayarları (v2.27.2)
    # -------------------------------------------------
    SCHEDULER_INTERVAL_SECONDS: int = 300  # İnaktif dialog kapatma interval (5 dk)

    # RAG Arama Parametreleri
    RAG_DEFAULT_RESULTS: int = 5  # Varsayılan RAG sonuç sayısı
    RAG_MIN_SCORE: float = 0.30  # 🔧 v2.33.2: 0.40'tan düşürüldü - PDF dokümanları için
    
    # DB Connection Yönetimi
    DB_MAX_RETRIES: int = 15  # Veritabanı bağlantı deneme sayısı

    # -------------------------------------------------
    # Synthetic Q/SQL Generator (v3.28.0 — Faz 5 G2)
    # -------------------------------------------------
    # Synthetic generate_db_query_pairs günlük LLM bütçe sınırı (USD).
    # 0 = sınırsız (önerilmez). Aşıldığında üretim erken durur.
    MAX_LLM_DAILY_BUDGET_USD: float = 1.0

    # -------------------------------------------------
    # FK Graph Resolver (v3.29.5 — Faz 7 carry-over)
    # -------------------------------------------------
    # K-shortest path arama parametreleri. Çok-tablolu sorular için path
    # patlamasını sınırlar. Yüksek değerler latency artışı getirir.
    FK_GRAPH_DEFAULT_K: int = 5            # Maks alternatif yol sayısı
    FK_GRAPH_DEFAULT_MAX_HOPS: int = 5     # Tek yol için maks zincir uzunluğu

    # -------------------------------------------------
    # Code Value Auto Re-scan (v3.29.5 — Faz 7 carry-over)
    # -------------------------------------------------
    # ds_db_samples güncellendikten sonra ds_code_values otomatik yenileme.
    # 0 = devre dışı (manuel admin tetikleme). >0 ise scheduler interval'inin
    # bir katı olarak çalışır (SCHEDULER_INTERVAL_SECONDS × bu çarpan).
    CODE_VALUE_AUTO_RESCAN_INTERVAL_MULT: int = 0   # 0 = off; örn 12 = ~1 saat
    CODE_VALUE_AUTO_RESCAN_MIN_AGE_MINUTES: int = 60  # Son tarama bu kadar eskiyse yeniden tara

    # -------------------------------------------------
    # Signal Weight Analyzer (v3.29.8 — Layer 2)
    # -------------------------------------------------
    # multi_signal_rank ağırlıklarının offline Pearson korelasyon
    # tabanlı önerilerini üreten analyzer. Önerileri sadece
    # signal_weight_suggestions tablosuna yazar; admin onayı (Layer 3)
    # olmadan asıl ağırlıkları değiştirmez.
    # 0 = devre dışı (manuel admin tetikleme). >0 ise scheduler interval'inin
    # bir katı olarak çalışır (SCHEDULER_INTERVAL_SECONDS × bu çarpan).
    # Default 288 → 288 × 300s ≈ 24 saat (günde 1 kez).
    SIGNAL_WEIGHT_ANALYZER_INTERVAL_MULT: int = 0    # 0 = off; öneri 288 (~24h)
    SIGNAL_WEIGHT_ANALYZER_WINDOW_DAYS: int = 7       # Pencere
    SIGNAL_WEIGHT_ANALYZER_MIN_SAMPLE_SIZE: int = 50  # Sample yetersizse skip
    SIGNAL_WEIGHT_ANALYZER_LAMBDA: float = 0.3        # Yumuşak ayarlama katsayısı

    # -------------------------------------------------
    # DB Smart Wizard — Scheduled Reports (v3.30.0 FAZ 3 P17)
    # -------------------------------------------------
    # dbsmart_saved_reports.schedule_cron olan kayıtların periyodik yeniden
    # çalıştırılması. 0 = off; >0 ise scheduler interval'inin (SCHEDULER_INTERVAL_SECONDS=300s)
    # katı olarak tick. Default 12 → 12 × 300s = 60 dk (saatlik kontrol).
    # Her tick: schedule_next_run <= NOW() olan raporlar çalıştırılır,
    # last_run_snapshot JSONB'ye yazılır, croniter ile bir sonraki çalışma zamanı set'lenir.
    # E-mail/PDF delivery KAPSAM DIŞI (v3.30.0 plan kararı — in-app snapshot).
    DBSMART_SCHEDULE_INTERVAL_MULT: int = 12          # 0 = off; 12 ≈ saatlik
    DBSMART_SCHEDULE_MAX_PER_TICK: int = 20           # Tick başına max çalışan rapor
    DBSMART_SCHEDULE_QUERY_TIMEOUT_S: int = 60        # Schedule SQL timeout
    DBSMART_SCHEDULE_MAX_ROWS: int = 5_000            # Snapshot row limit

    # -------------------------------------------------
    # Langfuse Observability (v3.26.0 Faz 5 P2-b — opsiyonel)
    # -------------------------------------------------
    # Boş bırakılırsa Langfuse devre dışı kalır. pipeline_events DB-tabanlı
    # observability her hâlükârda çalışmaya devam eder.
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # -------------------------------------------------
    # OpenTelemetry + Prometheus (v3.30.0 FAZ 5 P36)
    # -------------------------------------------------
    # OTel OTLP HTTP trace endpoint (örn. http://otel-collector:4318/v1/traces).
    # Boş bırakılırsa OTel devre dışı (no-op tracer). pipeline_events DB-tabanlı
    # observability her hâlükârda çalışmaya devam eder.
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""
    # Prometheus custom metric kayıtları (wizard_completed_total vs.) için ana flag.
    # False ise tüm metric helper'ları no-op olur; /metrics endpoint 403/503 döner.
    PROMETHEUS_ENABLED: bool = False
    # /metrics endpoint IP allowlist (virgülle ayrılmış). Boş = kapalı (default).
    # Örn: "10.0.0.5,10.0.0.6". Dev için "0.0.0.0/0" → explicit open.
    METRICS_IP_ALLOWLIST: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -------------------------------------------------
    #  Computed Properties
    # -------------------------------------------------
    
    @property
    def DATABASE_URL(self) -> str:
        """SQLAlchemy için PostgreSQL connection string"""
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    @property
    def PGSQL_BIN_DIR(self) -> Path:
        """PostgreSQL binary dizini"""
        return Path(self.PGSQL_DIR) / "bin"


settings = Settings()

# 🔒 Startup güvenlik kontrolü
settings.validate_jwt_secret()
