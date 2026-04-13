"""
VYRA - DS Enrichment Service
================================
LLM ile tablo ve sütunları anlamlandırma (zenginleştirme) servisi.
Her tablo için iş anlamı, Türkçe açıklama, kategori ve güven skoru üretir.
Skor eşiğinin altındaki tablolar Admin onay kuyruğuna düşer.

Version: 3.0.0
"""

import json
import hashlib
import logging
import time

logger = logging.getLogger(__name__)

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
                        relationships: list = None) -> dict:
    """
    Birden fazla tabloyu sırayla enrich eder.

    Args:
        tables: detect_objects çıktısı (obje listesi)
        samples_map: {object_id: [sample_rows...]}
        relationships: FK ilişkileri

    Returns:
        dict: {total, enriched, skipped, admin_required, errors, results}
    """
    start = time.time()
    results = []
    enriched = 0
    skipped = 0
    admin_count = 0
    errors = 0

    for idx, tbl in enumerate(tables):
        obj_id = tbl.get("id")
        table_name = tbl.get("object_name", tbl.get("table_name", ""))

        try:
            # İlgili sample'ları bul
            sample_data = (samples_map or {}).get(obj_id, [])

            # İlgili ilişkileri bul
            table_rels = [
                r for r in (relationships or [])
                if r.get("from_table") == table_name or r.get("to_table") == table_name
            ]

            result = enrich_table(
                vyra_conn, source_id, company_id,
                tbl, sample_data, table_rels
            )
            results.append(result)

            if result.get("skipped"):
                skipped += 1
            else:
                enriched += 1
                if result.get("admin_required"):
                    admin_count += 1

            # Progress log (her 10 tabloda bir)
            if (idx + 1) % 10 == 0:
                logger.info("[DSEnrich] İlerleme: %d/%d tablo işlendi", idx + 1, len(tables))

        except Exception as e:
            errors += 1
            logger.error("[DSEnrich] Tablo enrich hatası (%s): %s — %s",
                         table_name, type(e).__name__, str(e)[:200])
            results.append({
                "enrichment_id": None,
                "table_name": table_name,
                "error": str(e)[:200],
                "skipped": False
            })

    elapsed = int((time.time() - start) * 1000)

    summary = {
        "total": len(tables),
        "enriched": enriched,
        "skipped": skipped,
        "admin_required": admin_count,
        "errors": errors,
        "elapsed_ms": elapsed,
        "results": results
    }

    logger.info("[DSEnrich] Batch tamamlandı: %d toplam, %d yeni, %d atlandı, "
                "%d admin bekliyor, %d hata (%dms)",
                len(tables), enriched, skipped, admin_count, errors, elapsed)

    return summary


# =====================================================
# LLM Analiz
# =====================================================

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
    for c in columns[:30]:  # Max 30 sütun gönder
        col_str = f"  - {c.get('name', '?')} ({c.get('data_type', '?')})"
        if c.get("is_pk"):
            col_str += " [PRIMARY KEY]"
        if not c.get("is_nullable", True):
            col_str += " [NOT NULL]"
        col_descriptions.append(col_str)

    columns_block = "\n".join(col_descriptions) if col_descriptions else "  (sütun bilgisi yok)"

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
- Sadece JSON döndür, açıklama/yorum YAZMA"""

    messages = [
        {"role": "system", "content": "Sen bir veritabanı analiz uzmanısın. Tabloları analiz edip iş anlamlarını çıkarırsın. Sadece istenen JSON formatında yanıt ver."},
        {"role": "user", "content": prompt}
    ]

    try:
        response = call_llm_api(messages)
        if response:
            parsed = _parse_llm_analysis(response)
            if parsed:
                return parsed
    except Exception as e:
        logger.warning("[DSEnrich] İlk LLM denemesi başarısız, daraltılmış prompt ile tekrar deneniyor. Hata: %s", type(e).__name__)

    # Fallback / Retry (Eğer yukarıdaki başarılı olmazsa)
    logger.info("[DSEnrich] %s için küçültülmüş bağlam ile ikinci deneme yapılıyor", table_name)
    import time
    time.sleep(1) # Azure Rate Limit veya geçici hatalara karşı kısa bir bekleme
    
    # Küçültülmüş prompt: Sadece tablo adı ve sütun adları, sample/relation YOK.
    col_names = []
    for c in columns[:30]:
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
        response2 = call_llm_api(messages)
        if response2:
            return _parse_llm_analysis(response2)
    except Exception as e:
        logger.error("[DSEnrich] LLM analiz hatası (2. Deneme): %s — %s",
                     type(e).__name__, str(e)[:200])
        return None
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
        data = json.loads(text)

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


def _enrich_columns(vyra_conn, source_id: int, table_enrichment_id: int,
                    columns: list, llm_columns: dict):
    """Sütun enrichment kayıtlarını oluştur/güncelle. v5.0: synonyms + is_searchable desteği."""
    cur = vyra_conn.cursor()

    # İdempotent schema migration — yeni kolonları ekle (yoksa)
    try:
        cur.execute("ALTER TABLE ds_column_enrichments ADD COLUMN IF NOT EXISTS synonyms_json TEXT DEFAULT NULL")
        cur.execute("ALTER TABLE ds_column_enrichments ADD COLUMN IF NOT EXISTS is_searchable BOOLEAN DEFAULT FALSE")
        vyra_conn.commit()
    except Exception:
        try:
            vyra_conn.rollback()
        except Exception:
            pass

    for col in columns:
        col_name = col.get("name", "")
        if not col_name:
            continue

        raw_llm_columns = llm_columns if isinstance(llm_columns, dict) else {}
        col_info = raw_llm_columns.get(col_name, {})
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
    """Tüm tabloların keşif/zenginleştirme (enrichment) durumlarını beraber döner."""
    cur = vyra_conn.cursor()
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
            te.version
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
    rows = cur.fetchall()
    return [dict(r) if hasattr(r, 'keys') else r for r in rows]


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
    rows = cur.fetchall()
    return [dict(r) if hasattr(r, 'keys') else r for r in rows]


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
    """Kaynak için enrichment istatistikleri döner."""
    cur = vyra_conn.cursor()
    try:
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

    return [dict(r) if hasattr(r, 'keys') else r for r in cur.fetchall()]


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
