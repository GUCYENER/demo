"""
VYRA - DS Enrichment Service
================================
LLM ile tablo ve sütunları anlamlandırma (zenginleştirme) servisi.
Her tablo için iş anlamı, Türkçe açıklama, kategori ve güven skoru üretir.
Skor eşiğinin altındaki tablolar Admin onay kuyruğuna düşer.

Version: 3.0.0
"""

import hashlib
import json
import logging
import re
import time

logger = logging.getLogger(__name__)

# v3.43.0: LLM JSON onarımı için toleranslı extractor (modül-seviyesi, döngü-içi import değil).
# Guarded — llm.py ds_enrichment_service'i import etmez (circular yok), yine de güvenli düş.
try:
    from app.core.llm import extract_json_obj
except Exception:  # pragma: no cover
    extract_json_obj = None

# =====================================================
# Sabitler
# =====================================================

CONFIDENCE_THRESHOLD = 0.7  # Bu skorun altındaki tablolar admin onayı bekler
BATCH_SIZE = 1  # Kaliteli analiz: 1 tablo/çağrı


# =====================================================
# Tablo Seviyesi Enrichment
# =====================================================

def enrich_table(vyra_conn, source_id: int, company_id: int,
                 table_info: dict, sample_data: list = None,
                 relationships: list = None) -> dict:
    """
    Tek bir tabloyu LLM ile analiz edip zenginleştirir.

    Args:
        vyra_conn: VYRA DB bağlantısı
        source_id: Veri kaynağı ID
        company_id: Şirket ID
        table_info: {schema_name, table_name, object_type, columns_json, row_count_estimate}
        sample_data: Örnek veri satırları
        relationships: Bu tabloya ait FK ilişkileri

    Returns:
        dict: {enrichment_id, score, business_name_tr, admin_required}
    """
    schema = table_info.get("schema_name", "")
    table = table_info.get("table_name") or table_info.get("object_name", "")
    obj_type = table_info.get("object_type", "table")

    # Sütun bilgilerini hazırla
    columns = table_info.get("columns_json", [])
    if isinstance(columns, str):
        try:
            columns = json.loads(columns)
        except Exception:
            columns = []

    # Tablo yapısal hash'i hesapla (değişiklik tespiti)
    schema_hash = _compute_table_schema_hash(table, columns)

    # Daha önce enrichment yapılmış mı kontrol et
    existing = _get_existing_enrichment(vyra_conn, source_id, schema, table)
    if existing and existing.get("schema_hash") == schema_hash and existing.get("is_active"):
        logger.info("[DSEnrich] Tablo zaten enrich edilmiş ve değişmemiş: %s.%s (skor: %.2f)",
                    schema, table, existing.get("enrichment_score", 0))
        return {
            "enrichment_id": existing["id"],
            "score": existing.get("enrichment_score", 0),
            "business_name_tr": existing.get("business_name_tr", ""),
            "admin_required": not existing.get("admin_approved", False),
            "skipped": True
        }

    # LLM ile analiz
    llm_result = _call_llm_for_table_analysis(table, columns, sample_data, relationships)

    if not llm_result:
        logger.warning("[DSEnrich] LLM analizi başarısız: %s.%s", schema, table)
        llm_result = _generate_fallback_analysis(table, columns)

    # Bileşik skor hesapla
    enrichment_score = _compute_enrichment_score(llm_result, columns, sample_data)
    # GÜNCELLEME: Tüm tablolar RAG pipeline'ına aktarılmadan önce admin onayından geçmelidir.
    admin_required = True

    # DB'ye kaydet/güncelle
    enrichment_id = _upsert_table_enrichment(
        vyra_conn, source_id, company_id, schema, table, obj_type,
        llm_result, enrichment_score, schema_hash
    )

    # Sütun enrichment
    if columns:
        _enrich_columns(
            vyra_conn, source_id, enrichment_id,
            columns, llm_result.get("columns", {})
        )

    logger.info("[DSEnrich] Tablo enrich edildi: %s.%s → '%s' (skor: %.2f, admin: %s)",
                schema, table, llm_result.get("business_name_tr", "?"),
                enrichment_score, admin_required)

    return {
        "enrichment_id": enrichment_id,
        "score": enrichment_score,
        "business_name_tr": llm_result.get("business_name_tr", ""),
        "description_tr": llm_result.get("description_tr", ""),
        "category": llm_result.get("category", ""),
        "admin_required": admin_required,
        "skipped": False
    }


def enrich_tables_batch(vyra_conn, source_id: int, company_id: int,
                        tables: list, samples_map: dict = None,
                        relationships: list = None,
                        max_workers: int = 4, progress_cb=None) -> dict:
    """
    Birden fazla tabloyu enrich eder.

    v3.43.0 (P1-C): max_workers > 1 ise tablolar SINIRLI EŞZAMANLILIKLA işlenir
    (LLM I/O-bound; ~max_workers kat hızlanma). Her worker KENDİ DB connection'ını
    get_db_conn()'dan alır (psycopg2 connection thread-safe değil). max_workers=1 →
    eski sıralı davranış (geçirilen vyra_conn kullanılır). enrich_table kendi içinde
    commit ettiği için tablolar arası transaction izolasyonu korunur.

    Args:
        tables: detect_objects çıktısı (obje listesi)
        samples_map: {object_id: [sample_rows...]}
        relationships: FK ilişkileri
        max_workers: eşzamanlı LLM worker sayısı (pool maxconn'u tüketmeyecek şekilde sınırlı)
        progress_cb: opsiyonel callable(done:int, total:int) — ana thread'den çağrılır

    Returns:
        dict: {total, enriched, skipped, admin_required, errors, results}
    """
    start = time.time()
    results = []
    counters = {"enriched": 0, "skipped": 0, "admin": 0, "errors": 0}
    total = len(tables)
    samples_map = samples_map or {}
    relationships = relationships or []

    def _rels_for(table_name):
        return [r for r in relationships
                if r.get("from_table") == table_name or r.get("to_table") == table_name]

    def _accumulate(res, done):
        """Sonucu say + ilerlemeyi bildir. SADECE ana thread'den çağrılır (race yok)."""
        results.append(res)
        if res.get("error"):
            counters["errors"] += 1
        elif res.get("skipped"):
            counters["skipped"] += 1
        else:
            counters["enriched"] += 1
            if res.get("admin_required"):
                counters["admin"] += 1
        if progress_cb:
            try:
                progress_cb(done, total)
            except Exception:
                pass

    def _run_one(tbl, conn):
        table_name = tbl.get("object_name", tbl.get("table_name", ""))
        sample_data = samples_map.get(tbl.get("id"), [])
        return enrich_table(conn, source_id, company_id, tbl, sample_data, _rels_for(table_name))

    def _err_result(tbl, exc):
        table_name = tbl.get("object_name", tbl.get("table_name", ""))
        logger.error("[DSEnrich] Tablo enrich hatası (%s): %s — %s",
                     table_name, type(exc).__name__, str(exc)[:200])
        return {"enrichment_id": None, "table_name": table_name,
                "error": str(exc)[:200], "skipped": False}

    workers = max(1, min(int(max_workers or 1), total)) if total else 1

    if workers <= 1:
        # Sıralı yol (eski davranış) — geçirilen connection kullanılır
        for idx, tbl in enumerate(tables):
            try:
                res = _run_one(tbl, vyra_conn)
            except Exception as e:
                res = _err_result(tbl, e)
            _accumulate(res, idx + 1)
    else:
        # Sınırlı eşzamanlılık — her worker kendi connection'ını alır/iade eder
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from app.core.db import get_db_conn

        def _worker(tbl):
            wconn = None
            try:
                wconn = get_db_conn()
                return _run_one(tbl, wconn)
            except Exception as e:
                return _err_result(tbl, e)
            finally:
                if wconn is not None:
                    try:
                        wconn.close()  # PooledConnection → pool'a iade
                    except Exception:
                        pass

        done = 0
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="dsenrich") as ex:
            futures = [ex.submit(_worker, t) for t in tables]
            for fut in as_completed(futures):
                done += 1
                _accumulate(fut.result(), done)

    elapsed = int((time.time() - start) * 1000)
    summary = {
        "total": total,
        "enriched": counters["enriched"],
        "skipped": counters["skipped"],
        "admin_required": counters["admin"],
        "errors": counters["errors"],
        "elapsed_ms": elapsed,
        "results": results
    }

    logger.info("[DSEnrich] Batch tamamlandı (workers=%d): %d toplam, %d yeni, %d atlandı, "
                "%d admin bekliyor, %d hata (%dms)",
                workers, total, counters["enriched"], counters["skipped"],
                counters["admin"], counters["errors"], elapsed)

    return summary


# =====================================================
# LLM Analiz
# =====================================================

# v3.60.0: eski sabit 30 kapağı → 30+ kolonlu tablolarda 31+ kolon LLM'e HİÇ gitmiyordu
# (İŞ ADI/AÇIKLAMA boş "—", semantic 'other'). Modern LLM 100 kolonu tek prompt'ta rahat işler.
# Modern LLM 100 kolonu tek prompt'ta rahat işler. v3.71.0: 100'de KORUNDU (v3.70.0 geçici 60'a
# düşürmüştü ama bu 61-100 kolonlu tabloları geriletiyordu — o kolonlar örnek-bağlamsız chunk'a
# düşüyordu). Asıl sorun (LLM timeout) artık ENRICH_LLM_TIMEOUT ile çözülüyor (aşağıda).
MAX_ENRICH_COLUMNS = 100
# v3.66.0: cap'i AŞAN kolonlar CHUNK'lı enrich edilir (kalan kolonlar parça parça LLM'e, merge).
_COL_CHUNK_SIZE = 80
_MAX_TOTAL_ENRICH_COLUMNS = 500
# v3.71.0: enrichment LLM çağrılarına özel UZUN timeout (config'in kısa 60sn'si geniş tablo
# prompt'unda timeout→retry-loop→"—" yaratıyordu). 100/80 kolonluk prompt tek seferde bitsin.
ENRICH_LLM_TIMEOUT = 150


def _llm_enrich_columns_only(table_name: str, cols_chunk: list) -> dict:
    """v3.66.0: YALNIZ sütun enrichment (tablo-seviye analiz yok) — 100+ kolonlu tabloda taşan
    kolonlar için. Döner: {col_name: {business_name_tr, description_tr, semantic_type, synonyms_tr,
    is_searchable}}. Hata/boşta {} (non-blocking)."""
    try:
        from app.core.llm import call_llm_api
    except ImportError:
        return {}
    col_lines = []
    for c in cols_chunk:
        cl = f"  - {c.get('name', '?')} ({c.get('data_type', '?')})"
        if c.get("is_pk"):
            cl += " [PK]"
        col_lines.append(cl)
    prompt = (
        f"Tablo: {table_name}\n"
        "Aşağıdaki sütunların HER BİRİ için Türkçe iş adı, kısa açıklama ve semantic tip üret.\n"
        "Sütunlar:\n" + "\n".join(col_lines) + "\n\n"
        "YANIT SADECE JSON (gönderilen HER sütunu ekle):\n"
        '{"columns": {"sütun_adı": {"business_name_tr":"...","description_tr":"...",'
        '"semantic_type":"id/name/date/amount/status/code/description/flag/quantity/other",'
        '"synonyms_tr":["..."],"is_searchable":true}}}\n'
        "JSON KESİNLİKLE GEÇERLİ olmalı (string'leri tek satır, çift tırnağı \\\" ile kaçır). Sadece JSON döndür."
    )
    messages = [
        {"role": "system", "content": "Sen bir veritabanı analiz uzmanısın. Sadece istenen JSON'u döndür."},
        {"role": "user", "content": prompt},
    ]
    try:
        resp = call_llm_api(messages, timeout_override=ENRICH_LLM_TIMEOUT)
        if not resp:
            return {}
        parsed = _parse_llm_analysis(resp)
        cols = (parsed or {}).get("columns")
        return cols if isinstance(cols, dict) else {}
    except Exception as e:
        logger.warning("[DSEnrich] kolon-chunk enrich hatası (%s): %s", table_name, str(e)[:150])
        return {}


def _enrich_overflow_columns(table_name: str, columns: list, parsed: dict,
                             start: int = MAX_ENRICH_COLUMNS) -> None:
    """v3.66.0: start'tan sonraki kolonları CHUNK'lı enrich edip parsed['columns']'a ekler (in-place).
    Main yol: start=MAX_ENRICH_COLUMNS (ilk MAX_ENRICH_COLUMNS kolon ana çağrıda → kalanı chunk).
    Fallback yol: start=0 (mini-prompt columns boş döner → TÜM kolonlar chunk'lanır). Çok kolonlu
    tabloda (ör. 313) hepsi etiketlenir."""
    if not parsed or len(columns) <= start:
        return
    total_cap = min(len(columns), _MAX_TOTAL_ENRICH_COLUMNS)
    remaining = columns[start:total_cap]
    merged = parsed.get("columns")
    if not isinstance(merged, dict):
        merged = {}
    got = 0
    for i in range(0, len(remaining), _COL_CHUNK_SIZE):
        chunk = remaining[i:i + _COL_CHUNK_SIZE]
        chunk_cols = _llm_enrich_columns_only(table_name, chunk)
        if chunk_cols:
            merged.update(chunk_cols)
            got += len(chunk_cols)
    parsed["columns"] = merged
    logger.info("[DSEnrich] %s: %d/%d taşan kolon chunk'lı enrich edildi",
                table_name, got, len(remaining))
    if len(columns) > _MAX_TOTAL_ENRICH_COLUMNS:
        try:
            from app.services.logging_service import log_system_event
            log_system_event(
                level="WARNING",
                message=(f"[DSEnrich] {table_name}: {len(columns)} kolon — ilk {_MAX_TOTAL_ENRICH_COLUMNS} "
                         f"enrich edildi, kalan {len(columns) - _MAX_TOTAL_ENRICH_COLUMNS} etiketsiz."),
                module="ds_enrichment",
            )
        except Exception:
            pass


def _fill_missing_columns(table_name: str, columns: list, parsed: dict) -> None:
    """v3.74.2 KÖK fix (veri kaybı): ana LLM çağrısı çok-kolonlu tabloda bazı kolonları
    DÖNDÜRMEZ (büyük structured-JSON'da model anahtar atlar/keser) → o kolonlar "—" kalıyordu
    (kullanıcı bulgusu: ilk keşifte eksik, 'Yeniden Öğren'de tam → non-determinism).

    Ana çağrı + overflow SONRASI hâlâ `parsed['columns']`'da OLMAYAN kolonları CHUNK'lı doldur.
    ≤100 kolonlu tabloyu da kapsar (overflow yalnız 100+ ile ilgilenir). Chunk yolu güvenilir
    (her chunk küçük → LLM hepsini döndürür). Metadata tamlığı = doğru cevap kaynağı.
    """
    if not parsed:
        return
    cols_map = parsed.get("columns")
    if not isinstance(cols_map, dict):
        cols_map = {}
        parsed["columns"] = cols_map
    cap = min(len(columns), _MAX_TOTAL_ENRICH_COLUMNS)
    candidates = [c for c in columns[:cap] if c.get("name")]
    filled = 0
    # v3.74.2 code-review: CASE-INSENSITIVE üyelik. LLM kolon adını farklı kasada döndürebilir
    # (ADGroupId → adgroupid) — _enrich_columns zaten case-insensitive yazar; burada exact-match
    # olsaydı etiketli kolon "missing" sanılıp GEREKSİZ yeniden gönderilirdi (token israfı + kirli key).
    # 2-pass bounded retry: chunk çağrısı da kolon düşürebilir → still-missing'i bir kez daha dene.
    for _pass in range(2):
        present_ci = {str(k).strip().lower() for k in cols_map if isinstance(k, str)}
        missing = [c for c in candidates if str(c["name"]).strip().lower() not in present_ci]
        if not missing:
            break
        for i in range(0, len(missing), _COL_CHUNK_SIZE):
            chunk = missing[i:i + _COL_CHUNK_SIZE]
            chunk_cols = _llm_enrich_columns_only(table_name, chunk)
            if chunk_cols:
                cols_map.update(chunk_cols)
                filled += len(chunk_cols)
    if filled:
        logger.info(
            "[DSEnrich] %s: ana çağrıda DÜŞEN %d kolon chunk'lı dolduruldu (veri-kaybı önlendi)",
            table_name, filled,
        )


def _call_llm_for_table_analysis(table_name: str, columns: list,
                                  sample_data: list = None,
                                  relationships: list = None) -> dict:
    """
    LLM'e tablo bilgilerini gönderip analiz ettirir.

    Returns:
        dict: {
            business_name_tr, business_name_en, description_tr,
            category, sample_questions, llm_confidence,
            columns: {col_name: {business_name_tr, description_tr, is_key, semantic_type}}
        }
    """
    try:
        from app.core.llm import call_llm_api
    except ImportError:
        logger.error("[DSEnrich] call_llm_api import edilemedi")
        return None

    # Prompt oluştur
    col_descriptions = []
    for c in columns[:MAX_ENRICH_COLUMNS]:
        col_str = f"  - {c.get('name', '?')} ({c.get('data_type', '?')})"
        if c.get("is_pk"):
            col_str += " [PRIMARY KEY]"
        if not c.get("is_nullable", True):
            col_str += " [NOT NULL]"
        col_descriptions.append(col_str)

    columns_block = "\n".join(col_descriptions) if col_descriptions else "  (sütun bilgisi yok)"

    # v3.66.0: cap'i aşan kolonlar artık _enrich_overflow_columns ile CHUNK'lı enrich edilir
    # (eski "etiketlenmeyebilir" WARNING'i kaldırıldı — her >100 tabloda gereksiz flood yaratıyordu).

    # Sample data ekle
    sample_block = ""
    if sample_data and len(sample_data) > 0:
        try:
            sample_rows = sample_data[:3]  # Max 3 satır
            sample_block = f"\n\nÖrnek Veriler (ilk 3 satır):\n{json.dumps(sample_rows, ensure_ascii=False, indent=2, default=str)[:1000]}"
        except Exception:
            sample_block = ""

    # Relationship ekle
    rel_block = ""
    if relationships:
        rel_lines = []
        for r in relationships[:10]:
            rel_lines.append(f"  {r.get('from_table', '?')}.{r.get('from_column', '?')} → {r.get('to_table', '?')}.{r.get('to_column', '?')}")
        rel_block = "\n\nForeign Key İlişkileri:\n" + "\n".join(rel_lines)

    prompt = f"""Aşağıdaki veritabanı tablosunu analiz et ve iş anlamını çıkar.

Tablo Adı: {table_name}
Sütunlar:
{columns_block}{sample_block}{rel_block}

GÖREV: Bu tablonun ne işe yaradığını, Türkçe iş ismini ve kategorisini belirle.

YANIT FORMATI (KESİNLİKLE bu JSON formatında cevap ver):
{{
  "business_name_tr": "Tablonun Türkçe iş adı (örn: Fatura, Müşteri, Sipariş)",
  "business_name_en": "Business name in English",
  "description_tr": "Tablonun ne işe yaradığının kısa Türkçe açıklaması (1-2 cümle)",
  "category": "Kategori (finance, hr, crm, inventory, system, log, config, auth, other)",
  "confidence": 0.85,
  "sample_questions": ["Bu tabloyla sorulabilecek 2-3 Türkçe soru"],
  "columns": {{
    "sütun_adı": {{
      "business_name_tr": "Sütunun Türkçe iş adı (örn: EMAIL → Elektronik Posta Adresi)",
      "description_tr": "Bu sütunun ne tuttuğunun kısa açıklaması",
      "is_key": true/false,
      "semantic_type": "id/name/date/amount/status/code/description/flag/quantity/other",
      "synonyms_tr": ["Bu sütun için alternatif Türkçe isimler, örn: e-posta, mail, elektronik posta"],
      "is_searchable": true/false
    }}
  }}
}}

KURALLAR:
- Tablo adından, sütunlardan ve örnek veriden anlam çıkar
- confidence: 0-1 arası. Tablo adından anlamı çıkarabiliyorsan 0.8+, çıkaramıyorsan 0.3-0.5
- Türkçe business name kısa ve anlamlı olsun (1-3 kelime)
- sample_questions: Bir kullanıcı bu tabloyu sorgularken sorabileceği doğal Türkçe sorular
- synonyms_tr: Kullanıcıların bu sütuna atıfta bulunurken kullanabileceği ALTERNATİF Türkçe isimler listesi (en az 2-3 eşanlamlı). Örn: EMAIL → ["e-posta", "mail", "elektronik posta", "mail adresi"]
- is_searchable: Bu sütun metin aramasında kullanılabilir mi? (isim, adres, açıklama gibi alanlar true; ID, FK, tarih gibi alanlar false)
- Sadece JSON döndür, açıklama/yorum YAZMA
- JSON KESİNLİKLE GEÇERLİ olmalı: her alandan sonra (son alan hariç) VİRGÜL koy; string
  değerlerin içindeki çift tırnağı \\" ile kaçır; string'leri TEK SATIRDA yaz (satır sonu koyma);
  açıklamaları kısa tut. Geçersiz JSON kabul edilmez."""

    messages = [
        {"role": "system", "content": "Sen bir veritabanı analiz uzmanısın. Tabloları analiz edip iş anlamlarını çıkarırsın. Sadece istenen JSON formatında yanıt ver."},
        {"role": "user", "content": prompt}
    ]

    try:
        response = call_llm_api(messages, timeout_override=ENRICH_LLM_TIMEOUT)
        if response:
            parsed = _parse_llm_analysis(response)
            if parsed:
                # v3.66.0: cap'i aşan kolonları (101+) chunk'lı enrich et → "—" kalmasın.
                _enrich_overflow_columns(table_name, columns, parsed)
                # v3.74.2: ana çağrının DÜŞÜRDÜĞÜ kolonları (≤100 dahil) chunk'lı doldur → veri kaybı yok.
                _fill_missing_columns(table_name, columns, parsed)
                return parsed
    except Exception as e:
        logger.warning("[DSEnrich] İlk LLM denemesi başarısız, daraltılmış prompt ile tekrar deneniyor. Hata: %s", type(e).__name__)

    # Fallback / Retry (Eğer yukarıdaki başarılı olmazsa)
    logger.info("[DSEnrich] %s için küçültülmüş bağlam ile ikinci deneme yapılıyor", table_name)
    import time
    time.sleep(1) # Azure Rate Limit veya geçici hatalara karşı kısa bir bekleme
    
    # Küçültülmüş prompt: Sadece tablo adı ve sütun adları, sample/relation YOK.
    col_names = []
    for c in columns[:MAX_ENRICH_COLUMNS]:
        col_names.append(f"  - {c.get('name', '?')}")
    mini_columns_block = "\n".join(col_names) if col_names else "  (sütun bilgisi yok)"
    
    mini_prompt = f"""Aşağıdaki veritabanı tablosunu analiz et ve iş anlamını çıkar.
Tablo Adı: {table_name}
Sütunlar:
{mini_columns_block}

GÖREV: Bu tablonun ne işe yaradığını, Türkçe iş ismini ve kategorisini belirle.

YANIT FORMATI (KESİNLİKLE bu JSON formatında cevap ver):
{{
  "business_name_tr": "Tablonun Türkçe iş adı",
  "business_name_en": "Business name in English",
  "description_tr": "Tablonun ne işe yaradığının Türkçe açıklaması (1 cümle)",
  "category": "Kategori (finance, hr, crm, inventory, system, log, config, auth, other)",
  "confidence": 0.5,
  "sample_questions": ["Örnek soru"],
  "columns": {{}} 
}}
Sadece JSON döndür."""

    messages[1]["content"] = mini_prompt
    
    try:
        response2 = call_llm_api(messages, timeout_override=ENRICH_LLM_TIMEOUT)
        if response2:
            parsed2 = _parse_llm_analysis(response2)
            if parsed2:
                # v3.66.0 code-review: fallback mini-prompt columns={} döner → TÜM kolonları (start=0)
                # chunk'lı enrich et (yoksa fallback'e düşen tablonun kolonları "—" kalırdı).
                _enrich_overflow_columns(table_name, columns, parsed2, start=0)
                # v3.74.2: emniyet — hâlâ düşen kolon kaldıysa doldur (no-op if none).
                _fill_missing_columns(table_name, columns, parsed2)
            return parsed2
    except Exception as e:
        logger.error("[DSEnrich] LLM analiz hatası (2. Deneme): %s — %s",
                     type(e).__name__, str(e)[:200])
        return None
    return None


def _strip_trailing_commas(s: str) -> str:
    """JSON metnindeki YAPISAL trailing virgülleri kaldırır (,} ,] → } ]) — QUOTE-AWARE.

    String içeriğine DOKUNMAZ: in-string durumunu (escape'lere saygılı) izleyerek yalnız
    string DIŞINDA, '}' veya ']' önündeki virgülü siler. v3.43.0 code-review: çıplak regex
    `,\\s*([}\\]])` string içi `"a,]"` desenini bozuyordu → quote-aware walker ile değişti."""
    out = []
    in_str = False
    esc = False
    n = len(s)
    i = 0
    while i < n:
        ch = s[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j < n and s[j] in "}]":
                i += 1  # yapısal trailing virgül — atla (string dışı)
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def _coerce_llm_json(text: str) -> dict:
    """LLM çıktısından JSON sözlüğü elde eder; yaygın LLM kusurlarını toleranslı işler (v3.43.0).

    Sıra:
      1) Düz json.loads
      2) app.core.llm.extract_json_obj — kod bloğu/çevre metin toleranslı balanced-brace raw_decode
      3) GÜVENLİ onarım: ilk{..son} aralığı + quote-aware trailing virgül temizliği + string içi
         literal control-char (newline/tab) → boşluk, sonra tekrar dene.

    Riskli onarımlar (eksik virgül/kaçışsız tırnak enjeksiyonu) BİLİNÇLİ yapılmaz — string
    içeriğini bozabilirler. Hepsi başarısızsa None (çağıran fallback heuristic'e düşer)."""
    if not text:
        return None

    def _try(s):
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    # 1) Düz
    obj = _try(text)
    if obj is not None:
        return obj

    # 2) Mevcut toleranslı extractor (modül-seviyesi import, döngü-içi değil)
    if extract_json_obj is not None:
        try:
            obj = extract_json_obj(text)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    # 3) Güvenli onarım
    s = text
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        s = s[i:j + 1]
    s_no_trailing = _strip_trailing_commas(s)                 # quote-aware ,} ,] → } ]
    s_no_ctrl = re.sub(r"[\r\n\t]+", " ", s_no_trailing)      # string içi literal newline/tab → boşluk
    for cand in (s_no_trailing, s_no_ctrl):
        obj = _try(cand)
        if obj is not None:
            return obj
    return None


def _parse_llm_analysis(response: str) -> dict:
    """LLM yanıtından JSON parse eder."""
    if not response:
        return None

    # Markdown code block temizle
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # İlk ve son satırı at
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()

    try:
        data = _coerce_llm_json(text)
        if data is None:
            raise ValueError("JSON elde edilemedi (tüm stratejiler başarısız)")

        raw_columns = data.get("columns", {})
        if not isinstance(raw_columns, dict):
            raw_columns = {}

        # Zorunlu alanları kontrol et
        result = {
            "business_name_tr": data.get("business_name_tr", ""),
            "business_name_en": data.get("business_name_en", ""),
            "description_tr": data.get("description_tr", ""),
            "category": data.get("category", "other"),
            "llm_confidence": float(data.get("confidence", 0.5) if str(data.get("confidence", "")).replace(".","").isdigit() else 0.5),
            "sample_questions": data.get("sample_questions", []),
            "columns": raw_columns
        }

        # Geçerli kategori kontrolü
        valid_categories = {"finance", "hr", "crm", "inventory", "system",
                            "log", "config", "auth", "other"}
        if result["category"] not in valid_categories:
            result["category"] = "other"

        return result

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("[DSEnrich] LLM JSON parse hatası: %s — yanıt: %s",
                       str(e)[:100], text[:200])
        return None


def _generate_fallback_analysis(table_name: str, columns: list) -> dict:
    """LLM başarısız olduğunda heuristic analiz üretir."""
    name_lower = table_name.lower()

    # Basit heuristic: tablo adından kategori ve isim tahmini
    category = "other"
    business_name = table_name

    patterns = {
        "finance": ["invoice", "payment", "fatura", "tahsilat", "accounting", "balance", "odeme"],
        "hr": ["employee", "personel", "staff", "calisan", "izin", "leave", "salary"],
        "crm": ["customer", "musteri", "client", "contact", "lead", "campaign"],
        "inventory": ["product", "urun", "stock", "stok", "warehouse", "depo"],
        "auth": ["user", "role", "permission", "yetki", "login", "session"],
        "log": ["log", "audit", "history", "tarihce"],
        "config": ["config", "setting", "param", "ayar", "preference"],
        "system": ["sys", "system", "job", "queue", "task", "migration"]
    }

    for cat, keywords in patterns.items():
        if any(kw in name_lower for kw in keywords):
            category = cat
            break

    return {
        "business_name_tr": business_name,
        "business_name_en": business_name,
        "description_tr": f"{table_name} tablosu — otomatik analiz (LLM kullanılamadı)",
        "category": category,
        "llm_confidence": 0.3,
        "sample_questions": [],
        "columns": {}
    }


# =====================================================
# Skor Hesaplama
# =====================================================

def _compute_enrichment_score(llm_result: dict, columns: list, sample_data: list) -> float:
    """
    Bileşik enrichment skoru hesaplar.

    Bileşenler:
      - LLM confidence (ağırlık: 0.5)
      - İsim kalitesi (ağırlık: 0.2)
      - Sütun coverage (ağırlık: 0.2)
      - Örnek veri varlığı (ağırlık: 0.1)
    """
    score = 0.0

    # 1. LLM confidence (0.5)
    llm_conf = llm_result.get("llm_confidence", 0.5)
    score += llm_conf * 0.5

    # 2. İsim kalitesi (0.2) — business_name_tr dolu ve makul uzunlukta mı
    bname = llm_result.get("business_name_tr", "")
    if bname and len(bname) >= 2 and bname != llm_result.get("business_name_en", "?"):
        score += 0.2
    elif bname:
        score += 0.1

    # 3. Sütun coverage (0.2) — kaç sütun enrich edilmiş
    enriched_cols = llm_result.get("columns", {})
    if columns and len(columns) > 0:
        coverage = len(enriched_cols) / len(columns)
        score += min(coverage, 1.0) * 0.2

    # 4. Örnek veri (0.1) — sample varsa analiz daha güvenilir
    if sample_data and len(sample_data) > 0:
        score += 0.1

    return round(min(score, 1.0), 2)


# =====================================================
# DB Operations
# =====================================================

def _get_existing_enrichment(vyra_conn, source_id: int, schema: str, table: str) -> dict:
    """Mevcut enrichment kaydını döner."""
    try:
        cur = vyra_conn.cursor()
        cur.execute("""
            SELECT id, schema_hash, enrichment_score, business_name_tr,
                   admin_approved, is_active, version
            FROM ds_table_enrichments
            WHERE source_id = %s AND schema_name = %s AND table_name = %s
        """, (source_id, schema or "", table))
        row = cur.fetchone()
        if row:
            return dict(row) if hasattr(row, 'keys') else {
                "id": row[0], "schema_hash": row[1], "enrichment_score": row[2],
                "business_name_tr": row[3], "admin_approved": row[4],
                "is_active": row[5], "version": row[6]
            }
        return None
    except Exception as e:
        logger.error("[DSEnrich] Existing enrichment sorgu hatası: %s", type(e).__name__)
        return None


def _upsert_table_enrichment(vyra_conn, source_id: int, company_id: int,
                              schema: str, table: str, obj_type: str,
                              llm_result: dict, score: float,
                              schema_hash: str) -> int:
    """Tablo enrichment kaydı oluştur veya güncelle."""
    cur = vyra_conn.cursor()

    try:
        cur.execute("""
            INSERT INTO ds_table_enrichments
                (source_id, company_id, schema_name, table_name, object_type,
                 business_name_tr, business_name_en, description_tr,
                 category, sample_questions, llm_confidence,
                 enrichment_score, schema_hash, last_enriched_at, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), TRUE)
            ON CONFLICT (source_id, schema_name, table_name)
            DO UPDATE SET
                business_name_tr = EXCLUDED.business_name_tr,
                business_name_en = EXCLUDED.business_name_en,
                description_tr = EXCLUDED.description_tr,
                category = EXCLUDED.category,
                sample_questions = EXCLUDED.sample_questions,
                llm_confidence = EXCLUDED.llm_confidence,
                enrichment_score = EXCLUDED.enrichment_score,
                schema_hash = EXCLUDED.schema_hash,
                last_enriched_at = NOW(),
                version = ds_table_enrichments.version + 1,
                updated_at = NOW()
            RETURNING id
        """, (
            source_id, company_id, schema or "", table, obj_type,
            llm_result.get("business_name_tr", ""),
            llm_result.get("business_name_en", ""),
            llm_result.get("description_tr", ""),
            llm_result.get("category", "other"),
            json.dumps(llm_result.get("sample_questions", []), ensure_ascii=False),
            llm_result.get("llm_confidence", 0.5),
            score, schema_hash
        ))

        row = cur.fetchone()
        enrichment_id = row["id"] if isinstance(row, dict) else row[0]
        vyra_conn.commit()
        return enrichment_id

    except Exception as e:
        vyra_conn.rollback()
        logger.error("[DSEnrich] Upsert hatası: %s — %s", type(e).__name__, str(e)[:200])
        raise


_COLUMN_SCHEMA_MIGRATED = False

def _enrich_columns(vyra_conn, source_id: int, table_enrichment_id: int,
                    columns: list, llm_columns: dict):
    """Sütun enrichment kayıtlarını oluştur/güncelle. v5.0: synonyms + is_searchable desteği."""
    global _COLUMN_SCHEMA_MIGRATED
    cur = vyra_conn.cursor()

    # İdempotent schema migration — yeni kolonları ekle (process başına bir kez)
    if not _COLUMN_SCHEMA_MIGRATED:
        try:
            cur.execute("ALTER TABLE ds_column_enrichments ADD COLUMN IF NOT EXISTS synonyms_json TEXT DEFAULT NULL")
            cur.execute("ALTER TABLE ds_column_enrichments ADD COLUMN IF NOT EXISTS is_searchable BOOLEAN DEFAULT FALSE")
            vyra_conn.commit()
            _COLUMN_SCHEMA_MIGRATED = True
        except Exception:
            try:
                vyra_conn.rollback()
            except Exception:
                pass

    # v3.60.0: LLM kolon adını farklı kasada döndürebilir (ADGroupId → adgroupid) → exact key
    # eşleşmezse etiket KAYBOLURDU. Önce exact, sonra case-insensitive (lower) indeks ile eşleştir.
    raw_llm_columns = llm_columns if isinstance(llm_columns, dict) else {}
    _llm_cols_ci = {
        k.strip().lower(): v for k, v in raw_llm_columns.items() if isinstance(k, str)
    }

    for col in columns:
        col_name = col.get("name", "")
        if not col_name:
            continue

        col_info = raw_llm_columns.get(col_name)
        if not isinstance(col_info, dict) or not col_info:
            col_info = _llm_cols_ci.get(col_name.strip().lower(), {})
        if not isinstance(col_info, dict):
            col_info = {}

        col_hash = hashlib.md5(
            json.dumps({"name": col_name, "type": col.get("data_type", "")}, sort_keys=True).encode()
        ).hexdigest()[:16]

        # Synonyms: LLM'den gelen eşanlamlılar
        synonyms_raw = col_info.get("synonyms_tr", [])
        if isinstance(synonyms_raw, list):
            synonyms_json = json.dumps(synonyms_raw, ensure_ascii=False)
        else:
            synonyms_json = None

        # Searchable: LLM'den gelen veya veri tipine göre otomatik tespit
        is_searchable = col_info.get("is_searchable", False)
        if not is_searchable:
            data_type = (col.get("data_type") or "").lower()
            if any(t in data_type for t in ("char", "text", "string", "varchar", "nvarchar")):
                sem_type = col_info.get("semantic_type", "")
                if sem_type in ("name", "description", "email", "address", "phone", "title"):
                    is_searchable = True

        try:
            cur.execute("""
                INSERT INTO ds_column_enrichments
                    (source_id, table_enrichment_id, column_name, data_type,
                     business_name_tr, description_tr, is_key_column,
                     semantic_type, column_hash, synonyms_json, is_searchable)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (table_enrichment_id, column_name)
                DO UPDATE SET
                    business_name_tr = EXCLUDED.business_name_tr,
                    description_tr = EXCLUDED.description_tr,
                    is_key_column = EXCLUDED.is_key_column,
                    semantic_type = EXCLUDED.semantic_type,
                    column_hash = EXCLUDED.column_hash,
                    synonyms_json = EXCLUDED.synonyms_json,
                    is_searchable = EXCLUDED.is_searchable,
                    version = ds_column_enrichments.version + 1,
                    updated_at = NOW()
            """, (
                source_id, table_enrichment_id, col_name,
                col.get("data_type", ""),
                col_info.get("business_name_tr", ""),
                col_info.get("description_tr", ""),
                col_info.get("is_key", col.get("is_pk", False)),
                col_info.get("semantic_type", "other"),
                col_hash,
                synonyms_json,
                is_searchable
            ))
        except Exception as e:
            logger.warning("[DSEnrich] Sütun enrich hatası (%s): %s", col_name, str(e)[:100])
            continue

    try:
        vyra_conn.commit()
    except Exception:
        vyra_conn.rollback()


# =====================================================
# Admin Onay API Yardımcıları
# =====================================================

def get_all_tables_status(vyra_conn, source_id: int) -> list:
    """
    Örneklenen schema'lardaki tabloların keşif/zenginleştirme (enrichment) durumlarını döner.

    v3.14.0: Sadece ds_db_samples kaydı olan (örneklenmiş) schema'lardaki tabloları gösterir.
    Böylece kullanıcı Adım 3'te sadece belirli schema'ları seçtiyse, panelde sadece onlar görünür.
    Eğer hiç sample yoksa (Adım 3 henüz yapılmamışsa), tüm tabloları gösterir (fallback).
    """
    cur = vyra_conn.cursor()

    # v3.14.0: Örneklenmiş schema'ları bul
    cur.execute("""
        SELECT DISTINCT o.schema_name
        FROM ds_db_samples s
        JOIN ds_db_objects o ON s.object_id = o.id
        WHERE o.source_id = %s AND o.schema_name IS NOT NULL
    """, (source_id,))
    sampled_schemas = [row[0] if not isinstance(row, dict) else row["schema_name"] for row in cur.fetchall()]

    if sampled_schemas:
        # Sadece örneklenmiş schema'lardaki tabloları getir
        format_strings = ','.join(['%s'] * len(sampled_schemas))
        cur.execute(f"""
            SELECT
                o.id as object_id,
                o.schema_name,
                o.object_name as table_name,
                o.object_type,
                te.id as enrichment_id,
                te.business_name_tr,
                te.description_tr,
                te.category,
                te.enrichment_score,
                te.llm_confidence,
                te.admin_approved,
                te.admin_label_tr,
                te.admin_notes,
                te.last_enriched_at,
                te.version,
                EXISTS(SELECT 1 FROM ds_db_samples s WHERE s.object_id = o.id) AS has_sample
            FROM ds_db_objects o
            LEFT JOIN ds_table_enrichments te
              ON o.source_id = te.source_id
             AND COALESCE(o.schema_name, '') = COALESCE(te.schema_name, '')
             AND o.object_name = te.table_name
            WHERE o.source_id = %s AND o.object_type IN ('table', 'view')
              AND o.schema_name IN ({format_strings})
            ORDER BY
                CASE WHEN te.id IS NULL THEN 0 ELSE 1 END,
                te.enrichment_score ASC,
                o.object_name
        """, [source_id] + sampled_schemas)
    else:
        # Fallback: Henüz sampling yapılmamışsa tüm tabloları göster
        cur.execute("""
            SELECT
                o.id as object_id,
                o.schema_name,
                o.object_name as table_name,
                o.object_type,
                te.id as enrichment_id,
                te.business_name_tr,
                te.description_tr,
                te.category,
                te.enrichment_score,
                te.llm_confidence,
                te.admin_approved,
                te.admin_label_tr,
                te.admin_notes,
                te.last_enriched_at,
                te.version,
                EXISTS(SELECT 1 FROM ds_db_samples s WHERE s.object_id = o.id) AS has_sample
            FROM ds_db_objects o
            LEFT JOIN ds_table_enrichments te
              ON o.source_id = te.source_id
             AND COALESCE(o.schema_name, '') = COALESCE(te.schema_name, '')
             AND o.object_name = te.table_name
            WHERE o.source_id = %s AND o.object_type IN ('table', 'view')
            ORDER BY
                CASE WHEN te.id IS NULL THEN 0 ELSE 1 END,
                te.enrichment_score ASC,
                o.object_name
        """, (source_id,))
    
    rows = cur.fetchall()
    results = []
    for row in rows:
        d = dict(row) if hasattr(row, 'keys') else dict(zip([c[0] for c in cur.description], row))
        if d.get("last_enriched_at"):
            d["last_enriched_at"] = d["last_enriched_at"].isoformat()
        d["is_approved"] = bool(d.get("admin_approved"))
        d["has_sample"] = bool(d.get("has_sample"))  # v3.69.0 Katman-2: örnek var mı (UI rozeti)
        results.append(d)
    return results

def get_pending_approvals(vyra_conn, source_id: int = None,
                          company_id: int = None,
                          score_threshold: float = CONFIDENCE_THRESHOLD) -> list:
    """Admin onayı bekleyen tabloları döner."""
    cur = vyra_conn.cursor()

    query = """
        SELECT te.id, te.source_id, te.schema_name, te.table_name,
               te.business_name_tr, te.description_tr, te.category,
               te.enrichment_score, te.llm_confidence,
               te.admin_approved, te.admin_label_tr, te.admin_notes,
               te.last_enriched_at, te.version,
               ds.name AS source_name
        FROM ds_table_enrichments te
        LEFT JOIN data_sources ds ON ds.id = te.source_id
        WHERE te.admin_approved = FALSE
          AND te.is_active = TRUE
    """
    params = []

    if source_id:
        query += " AND te.source_id = %s"
        params.append(source_id)
    if company_id:
        query += " AND te.company_id = %s"
        params.append(company_id)

    query += " ORDER BY te.enrichment_score ASC, te.table_name ASC"

    cur.execute(query, params)
    # v3.43.0: RealDictCursor (pool default) dict satır döner; çıplak dict(zip(cols,row))
    # RealDictRow'u key'leriyle zip'leyip {kolon: kolon} çöpü üretiyordu (admin onay paneli
    # değer yerine kolon adı gösteriyordu). Dual-mode ile dict satır doğru aktarılır.
    rows = cur.fetchall()
    if rows and hasattr(rows[0], 'keys'):
        return [dict(row) for row in rows]
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in rows]


def get_approved_enrichments(vyra_conn, source_id: int = None, company_id: int = None) -> list:
    """Admin onayı verilmiş (RAG için aktif) tabloları döner."""
    cur = vyra_conn.cursor()

    query = """
        SELECT te.id, te.source_id, te.schema_name, te.table_name,
               te.business_name_tr, te.description_tr, te.category,
               te.admin_label_tr, te.admin_approved,
               ds.name AS source_name
        FROM ds_table_enrichments te
        LEFT JOIN data_sources ds ON ds.id = te.source_id
        WHERE te.admin_approved = TRUE
          AND te.is_active = TRUE
    """
    params = []

    if source_id:
        query += " AND te.source_id = %s"
        params.append(source_id)
    if company_id:
        query += " AND te.company_id = %s"
        params.append(company_id)

    query += " ORDER BY te.table_name ASC"

    cur.execute(query, params)
    # v3.43.0: RealDictCursor dict satır uyumu (bkz. get_pending_approvals notu)
    rows = cur.fetchall()
    if rows and hasattr(rows[0], 'keys'):
        return [dict(row) for row in rows]
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in rows]


def approve_enrichment(vyra_conn, enrichment_id: int, user_id: int,
                       admin_label_tr: str = None,
                       admin_notes: str = None) -> bool:
    """Bir tablo enrichment'ını admin olarak onaylar."""
    cur = vyra_conn.cursor()
    try:
        updates = ["admin_approved = TRUE", "approved_by = %s", "approved_at = NOW()"]
        params = [user_id]

        if admin_label_tr:
            updates.append("admin_label_tr = %s")
            params.append(admin_label_tr)
        if admin_notes:
            updates.append("admin_notes = %s")
            params.append(admin_notes)

        params.append(enrichment_id)

        cur.execute(f"""
            UPDATE ds_table_enrichments
            SET {', '.join(updates)}, updated_at = NOW()
            WHERE id = %s
        """, params)

        vyra_conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        vyra_conn.rollback()
        logger.error("[DSEnrich] Onay hatası: %s", type(e).__name__)
        return False


def get_enrichment_stats(vyra_conn, source_id: int) -> dict:
    """
    Kaynak için enrichment istatistikleri döner.

    v3.14.0: Sadece örneklenmiş schema'lardaki tabloları sayar.
    """
    cur = vyra_conn.cursor()
    try:
        # v3.14.0: Örneklenmiş schema'ları bul
        cur.execute("""
            SELECT DISTINCT o.schema_name
            FROM ds_db_samples s
            JOIN ds_db_objects o ON s.object_id = o.id
            WHERE o.source_id = %s AND o.schema_name IS NOT NULL
        """, (source_id,))
        sampled_schemas = [row[0] if not isinstance(row, dict) else row["schema_name"] for row in cur.fetchall()]

        if sampled_schemas:
            format_strings = ','.join(['%s'] * len(sampled_schemas))
            cur.execute(f"""
                WITH ObjectStats AS (
                    SELECT COUNT(*) as total_db_tables
                    FROM ds_db_objects
                    WHERE source_id = %s AND object_type IN ('table', 'view')
                      AND schema_name IN ({format_strings})
                ),
                EnrichmentStats AS (
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE admin_approved = TRUE) AS approved,
                        COUNT(*) FILTER (WHERE admin_approved = FALSE) AS pending_review,
                        0 AS auto_approved,
                        COALESCE(AVG(enrichment_score), 0) AS avg_score,
                        MAX(last_enriched_at) AS last_enriched
                    FROM ds_table_enrichments
                    WHERE source_id = %s AND is_active = TRUE
                      AND schema_name IN ({format_strings})
                )
                SELECT e.total, e.approved, e.pending_review, e.auto_approved, e.avg_score, e.last_enriched, o.total_db_tables
                FROM EnrichmentStats e CROSS JOIN ObjectStats o
            """, [source_id] + sampled_schemas + [source_id] + sampled_schemas)
        else:
            cur.execute("""
                WITH ObjectStats AS (
                    SELECT COUNT(*) as total_db_tables
                    FROM ds_db_objects
                    WHERE source_id = %s AND object_type IN ('table', 'view')
                ),
                EnrichmentStats AS (
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE admin_approved = TRUE) AS approved,
                        COUNT(*) FILTER (WHERE admin_approved = FALSE) AS pending_review,
                        0 AS auto_approved,
                        COALESCE(AVG(enrichment_score), 0) AS avg_score,
                        MAX(last_enriched_at) AS last_enriched
                    FROM ds_table_enrichments
                    WHERE source_id = %s AND is_active = TRUE
                )
                SELECT e.total, e.approved, e.pending_review, e.auto_approved, e.avg_score, e.last_enriched, o.total_db_tables
                FROM EnrichmentStats e CROSS JOIN ObjectStats o
            """, (source_id, source_id))

        row = cur.fetchone()
        if not row:
            return {"total": 0, "unprocessed": 0}

        total_enrich = row[0] if not isinstance(row, dict) else row["total"]
        total_db = row[6] if not isinstance(row, dict) else row["total_db_tables"]
        unprocessed = max(0, total_db - total_enrich)

        return {
            "total": total_enrich,
            "approved": row[1] if not isinstance(row, dict) else row["approved"],
            "pending_review": row[2] if not isinstance(row, dict) else row["pending_review"],
            "auto_approved": row[3] if not isinstance(row, dict) else row["auto_approved"],
            "avg_score": round(float(row[4] if not isinstance(row, dict) else row["avg_score"]), 2),
            "last_enriched": (row[5] if not isinstance(row, dict) else row["last_enriched"]).isoformat() if (row[5] if not isinstance(row, dict) else row.get("last_enriched")) else None,
            "unprocessed": unprocessed
        }
    except Exception as e:
        logger.error("[DSEnrich] Stats hatası: %s", type(e).__name__)
        return {"total": 0, "unprocessed": 0, "error": str(e)[:100]}


def get_column_enrichments(vyra_conn, table_enrichment_id: int) -> list:
    """Bir tablo enrichment'ına ait sütun zenginleştirmelerini döner."""
    cur = vyra_conn.cursor()
    cur.execute("""
        SELECT id, column_name, data_type, business_name_tr,
               description_tr, is_key_column, semantic_type,
               admin_label_tr, admin_approved, version
        FROM ds_column_enrichments
        WHERE table_enrichment_id = %s
        ORDER BY is_key_column DESC, column_name ASC
    """, (table_enrichment_id,))

    rows = cur.fetchall()
    if not rows:
        return []
    # RealDictCursor ile dict(row); plain cursor ile zip
    if hasattr(rows[0], 'keys'):
        return [dict(row) for row in rows]
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in rows]


# =====================================================
# Yardımcılar
# =====================================================

def _compute_table_schema_hash(table_name: str, columns: list) -> str:
    """Tablo yapısının hash'ini hesaplar."""
    cols = sorted(
        [{"name": c.get("name", ""), "type": c.get("data_type", "")} for c in columns],
        key=lambda x: x["name"]
    )
    data_str = json.dumps({"table": table_name, "columns": cols}, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()
