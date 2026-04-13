"""
VYRA - DS Schema Learner (v5.0.0)
===================================
Onaylı tablolar için zengin tablo + kolon şema öğrenimi.

Hedef: LLM doğru SQL üretebilsin diye:
  - Tablo adı (schema.table) + iş adı + açıklama
  - Kolon listesi (ad, tip, PK, nullable, İŞ ADI, EŞ ANLAMLILAR)
  - FK ilişkileri
  - Değer örnekleri (enum/status kolonları)
  - Aranabilir alan işaretleri

Her onaylı tablo için 1 adet "schema_record" üretilir, embedding'e çevrilir
ve ds_learning_results'a yazılır.

Version: 5.0.0
"""

import json
import time
import logging

logger = logging.getLogger(__name__)


# =====================================================
# Yardımcı Fonksiyonlar
# =====================================================

def _extract_value_hints(sample_data: list, col_names: list) -> dict:
    """
    Örnek verilerden enum-benzeri kolonların olası değerlerini çıkarır.
    Eğer bir kolonda 2-10 arası unique değer varsa, listeyi döner.
    """
    if not sample_data or not isinstance(sample_data, list):
        return {}

    value_hints = {}
    for col_name in col_names:
        values = set()
        for row in sample_data:
            if isinstance(row, dict) and col_name in row:
                val = row.get(col_name)
                if val is not None and str(val).strip():
                    values.add(str(val).strip()[:50])

        # 2-10 arası unique değer → enum benzeri kolon
        if 2 <= len(values) <= 10:
            value_hints[col_name] = sorted(list(values))

    return value_hints


def _is_searchable_column(col: dict, enrichment: dict) -> bool:
    """Kolonun metin aramasında kullanılabilir olup olmadığını belirler."""
    enr = enrichment or {}

    # Enrichment'tan gelen is_searchable bilgisi
    if enr.get("is_searchable"):
        return True

    # Veri tipine göre otomatik tespit
    data_type = (col.get("data_type") or "").lower()
    searchable_types = ("char", "text", "string", "varchar", "nvarchar", "ntext", "clob")
    if any(t in data_type for t in searchable_types):
        return True

    # Semantic type'a göre
    sem_type = enr.get("semantic_type", "")
    searchable_semantics = ("name", "description", "email", "address", "phone", "title")
    if sem_type in searchable_semantics:
        return True

    return False


# =====================================================
# Schema Text Builder (v5.0 — Zengin)
# =====================================================

def _build_schema_text(table_name: str, schema: str, cols: list,
                       bname: str, desc: str, row_est: int,
                       rels_from: list, rels_to: list,
                       col_enrichments: dict = None,
                       value_hints: dict = None) -> str:
    """
    LLM'in SQL üretmesi için zengin şema metni üretir.

    v5.0: Kolon iş isimleri, eşanlamlılar, değer örnekleri ve aranabilirlik dahil.
    Formatı embedding + doğrudan LLM bağlamı olarak kullanmaya uygundur.
    """
    lines = []
    col_enrichments = col_enrichments or {}
    value_hints = value_hints or {}
    full_table = f"{schema}.{table_name}" if schema and schema not in ("", "public") else table_name

    lines.append(f"TABLO: {full_table}")
    if bname and bname != table_name:
        lines.append(f"İş Adı: {bname}")
    if desc:
        lines.append(f"Açıklama: {desc}")
    if row_est:
        lines.append(f"Tahmini Kayıt Sayısı: {row_est}")

    if cols:
        pk_cols = [c["name"] for c in cols if c.get("is_pk")]
        if pk_cols:
            lines.append(f"Primary Key: {', '.join(pk_cols)}")

        lines.append("Sütunlar:")
        for c in cols:
            col_name = c.get("name", "")
            data_type = c.get("data_type", "")
            nullable = "" if c.get("nullable", True) else " NOT NULL"
            pk_mark = " [PK]" if c.get("is_pk") else ""

            # Kolon enrichment bilgileri
            enr = col_enrichments.get(col_name, {})
            bname_col = enr.get("business_name_tr") or enr.get("admin_label_tr") or ""
            synonyms = enr.get("synonyms", [])
            is_searchable = _is_searchable_column(c, enr)

            # Temel satır
            line = f"  - {col_name} ({data_type}){nullable}{pk_mark}"

            # İş adı
            if bname_col:
                line += f" → İş Adı: {bname_col}"

            # Eşanlamlılar
            if synonyms:
                syn_text = ", ".join(str(s) for s in synonyms[:5])
                line += f" | Eşanlamlılar: [{syn_text}]"

            # Aranabilirlik
            if is_searchable:
                line += " [ARANABİLİR]"

            lines.append(line)

            # Değer örnekleri (varsa)
            hints = value_hints.get(col_name)
            if hints:
                hint_text = ", ".join(str(v) for v in hints[:8])
                lines.append(f"    Olası Değerler: {hint_text}")

    if rels_from:
        lines.append("İlişkiler (FK çıkan):")
        for r in rels_from:
            lines.append(f"  - {r['from_column']} → {r['to_schema']}.{r['to_table']}.{r['to_column']}")

    if rels_to:
        lines.append("İlişkiler (FK gelen):")
        for r in rels_to:
            lines.append(f"  - {r['from_schema']}.{r['from_table']}.{r['from_column']} → {r['to_column']}")

    return "\n".join(lines)


# =====================================================
# Ana Fonksiyon: Zengin Şema Öğrenimi (v5.0)
# =====================================================

def generate_enriched_qa(source_id: int, vyra_conn) -> dict:
    """
    v5.0: Onaylı tablolar için zengin şema bilgisi öğrenir.

    Her onaylı tablo için:
      - Tablo adı, şema, kolon listesi, PK, FK ilişkileri
      - Kolon iş isimleri (business_name_tr) ve eşanlamlıları (synonyms)
      - Değer örnekleri (enum/status kolonlar)
      - Aranabilir alan işaretleri
      → tek bir 'schema_record' olarak embedding'e çevrilip ds_learning_results'a yazılır

    Returns:
        dict: {success, data: {learned_tables, elapsed_ms, tables}}
    """
    start = time.time()
    cur = vyra_conn.cursor()
    logger.info("[DSSchemaLearner] Zengin şema öğrenimi başlatıldı: source_id=%s", source_id)

    # company_id
    cur.execute("SELECT company_id FROM data_sources WHERE id = %s", (source_id,))
    src_row = cur.fetchone()
    company_id = src_row["company_id"] if src_row else 1

    # Embedding manager
    try:
        from app.services.rag.embedding import EmbeddingManager
        emb_mgr = EmbeddingManager()
    except Exception as emb_err:
        logger.error("[DSSchemaLearner] EmbeddingManager yüklenemedi: %s", emb_err)
        return {"success": False, "error": "Embedding modeli yüklenemedi"}

    # Onaylı enrichment'lar
    cur.execute("""
        SELECT te.id as enrichment_id, te.schema_name, te.table_name,
               te.business_name_tr, te.admin_label_tr, te.description_tr
        FROM ds_table_enrichments te
        WHERE te.source_id = %s
          AND te.is_active = TRUE
          AND te.admin_approved = TRUE
        ORDER BY te.table_name
    """, (source_id,))
    enrichments = cur.fetchall()

    if not enrichments:
        logger.info("[DSSchemaLearner] Onaylı tablo yok, işlem atlandı.")
        return {"success": True, "data": {"learned_tables": 0, "elapsed_ms": 0}}

    approved_names = {e["table_name"] for e in enrichments}

    # Obje verileri (kolon + satır tahmini)
    cur.execute("""
        SELECT schema_name, object_name, row_count_estimate, columns_json
        FROM ds_db_objects
        WHERE source_id = %s AND object_type = 'table'
    """, (source_id,))
    objects = {
        (row["schema_name"] or "", row["object_name"]): row
        for row in cur.fetchall()
    }

    # Kolon enrichment'ları (tablo bazlı grupla)
    # synonyms_json ve is_searchable kolonları yoksa hata almamak için güvenli sorgu
    col_enrichments_by_te_id = {}
    try:
        cur.execute("""
            SELECT ce.table_enrichment_id, ce.column_name,
                   ce.business_name_tr, ce.admin_label_tr,
                   ce.description_tr, ce.semantic_type,
                   ce.is_key_column,
                   ce.synonyms_json,
                   ce.is_searchable
            FROM ds_column_enrichments ce
            JOIN ds_table_enrichments te ON te.id = ce.table_enrichment_id
            WHERE te.source_id = %s AND te.admin_approved = TRUE AND te.is_active = TRUE
        """, (source_id,))

        for row in cur.fetchall():
            te_id = row["table_enrichment_id"]
            col_name = row["column_name"]

            # Synonyms parse
            synonyms = []
            raw_syn = row.get("synonyms_json")
            if raw_syn:
                try:
                    synonyms = json.loads(raw_syn) if isinstance(raw_syn, str) else (raw_syn or [])
                except Exception:
                    synonyms = []

            col_enrichments_by_te_id.setdefault(te_id, {})[col_name] = {
                "business_name_tr": row.get("business_name_tr") or "",
                "admin_label_tr": row.get("admin_label_tr") or "",
                "description_tr": row.get("description_tr") or "",
                "semantic_type": row.get("semantic_type") or "other",
                "is_key_column": row.get("is_key_column", False),
                "is_searchable": row.get("is_searchable", False),
                "synonyms": synonyms,
            }
    except Exception as col_err:
        # synonyms_json / is_searchable kolonu henüz yoksa fallback sorgu
        logger.warning("[DSSchemaLearner] Kolon enrichment sorgusu hata: %s — fallback kullanılıyor", col_err)
        try:
            vyra_conn.rollback()
        except Exception:
            pass
        cur.execute("""
            SELECT ce.table_enrichment_id, ce.column_name,
                   ce.business_name_tr, ce.admin_label_tr,
                   ce.description_tr, ce.semantic_type, ce.is_key_column
            FROM ds_column_enrichments ce
            JOIN ds_table_enrichments te ON te.id = ce.table_enrichment_id
            WHERE te.source_id = %s AND te.admin_approved = TRUE AND te.is_active = TRUE
        """, (source_id,))
        for row in cur.fetchall():
            te_id = row["table_enrichment_id"]
            col_name = row["column_name"]
            col_enrichments_by_te_id.setdefault(te_id, {})[col_name] = {
                "business_name_tr": row.get("business_name_tr") or "",
                "admin_label_tr": row.get("admin_label_tr") or "",
                "description_tr": row.get("description_tr") or "",
                "semantic_type": row.get("semantic_type") or "other",
                "is_key_column": row.get("is_key_column", False),
                "is_searchable": False,
                "synonyms": [],
            }

    # Örnek veriler (value hints için)
    samples_by_table = {}
    try:
        approved_list = list(approved_names)
        if approved_list:
            placeholders = ",".join(["%s"] * len(approved_list))
            cur.execute(f"""
                SELECT s.object_id, s.sample_data, o.object_name
                FROM ds_db_samples s
                JOIN ds_db_objects o ON s.object_id = o.id
                WHERE s.source_id = %s AND o.object_name IN ({placeholders})
            """, [source_id] + approved_list)

            for row in cur.fetchall():
                s_data = row["sample_data"]
                if isinstance(s_data, str):
                    try:
                        s_data = json.loads(s_data)
                    except Exception:
                        s_data = []
                samples_by_table[row["object_name"]] = s_data if isinstance(s_data, list) else []
    except Exception as sample_err:
        logger.warning("[DSSchemaLearner] Örnek veri sorgusu hata: %s", sample_err)

    # Tüm FK ilişkileri
    cur.execute("""
        SELECT from_schema, from_table, from_column,
               to_schema, to_table, to_column
        FROM ds_db_relationships
        WHERE source_id = %s
    """, (source_id,))
    all_rels = cur.fetchall()

    rels_from_map = {}
    rels_to_map = {}
    for r in all_rels:
        ft = r["from_table"]
        tt = r["to_table"]
        if ft in approved_names:
            rels_from_map.setdefault(ft, []).append(r)
        if tt in approved_names:
            rels_to_map.setdefault(tt, []).append(r)

    # Job ID (çalışan iş varsa bağla)
    cur.execute("""
        SELECT id FROM ds_discovery_jobs
        WHERE source_id = %s AND status = 'running'
        ORDER BY started_at DESC LIMIT 1
    """, (source_id,))
    job_row = cur.fetchone()
    current_job_id = job_row["id"] if job_row else None

    # Eski schema_record'ları invalidate et
    cur.execute("""
        UPDATE ds_learning_results
        SET is_valid = FALSE, invalidated_at = NOW()
        WHERE source_id = %s
          AND content_type = 'schema_record'
          AND is_valid = TRUE
    """, (source_id,))
    invalidated = cur.rowcount
    if invalidated:
        logger.info("[DSSchemaLearner] %d eski schema_record invalidated", invalidated)

    # Her onaylı tablo için zengin şema metni üret
    records = []
    for enr in enrichments:
        table_name = enr["table_name"]
        schema = enr["schema_name"] or ""
        bname = enr["admin_label_tr"] or enr["business_name_tr"] or table_name
        desc = enr["description_tr"] or ""
        te_id = enr["enrichment_id"]

        # Kolon bilgisi
        obj = (
            objects.get((schema, table_name))
            or objects.get(("", table_name))
            or objects.get(("public", table_name))
        )

        cols = []
        row_est = 0
        if obj:
            row_est = obj["row_count_estimate"] or 0
            cols_raw = obj["columns_json"]
            if isinstance(cols_raw, str):
                try:
                    cols = json.loads(cols_raw)
                except Exception:
                    cols = []
            elif isinstance(cols_raw, list):
                cols = cols_raw

        # Kolon enrichment'ları
        col_enr = col_enrichments_by_te_id.get(te_id, {})

        # Value hints (örnek verilerden)
        sample_data = samples_by_table.get(table_name, [])
        col_names = [c.get("name", "") for c in cols if c.get("name")]
        value_hints = _extract_value_hints(sample_data, col_names)

        schema_text = _build_schema_text(
            table_name=table_name,
            schema=schema,
            cols=cols,
            bname=bname,
            desc=desc,
            row_est=row_est,
            rels_from=rels_from_map.get(table_name, []),
            rels_to=rels_to_map.get(table_name, []),
            col_enrichments=col_enr,
            value_hints=value_hints,
        )

        records.append({
            "table_name": table_name,
            "schema": schema,
            "bname": bname,
            "text": schema_text,
        })

    if not records:
        vyra_conn.commit()
        return {"success": True, "data": {"learned_tables": 0, "elapsed_ms": 0}}

    # Batch embedding
    texts = [r["text"] for r in records]
    try:
        batch_embeddings = emb_mgr.get_embeddings_batch(texts)
    except Exception as emb_err:
        logger.error("[DSSchemaLearner] Batch embedding hatası: %s", emb_err)
        return {"success": False, "error": f"Embedding hatası: {emb_err}"}

    # DB'ye yaz
    learned = 0
    for record, embedding in zip(records, batch_embeddings):
        full_table = (
            f"{record['schema']}.{record['table_name']}"
            if record["schema"] and record["schema"] not in ("", "public")
            else record["table_name"]
        )
        metadata = json.dumps({
            "table_name": record["table_name"],
            "schema": record["schema"],
            "full_table": full_table,
            "business_name": record["bname"],
        })

        cur.execute("""
            INSERT INTO ds_learning_results
                (source_id, company_id, job_id, content_type, content_text,
                 embedding, metadata, score, is_valid, version)
            VALUES (%s, %s, %s, 'schema_record', %s, %s, %s, 1.0, TRUE, 1)
        """, (
            source_id, company_id, current_job_id,
            record["text"], embedding, metadata
        ))
        learned += 1
        logger.info("[DSSchemaLearner] Öğrendi: %s (%s)", full_table, record["bname"])

    vyra_conn.commit()

    elapsed = int((time.time() - start) * 1000)
    logger.info("[DSSchemaLearner] Tamamlandı: %d tablo, %dms", learned, elapsed)

    return {
        "success": True,
        "data": {
            "learned_tables": learned,
            "elapsed_ms": elapsed,
            "tables": [r["table_name"] for r in records],
        }
    }
