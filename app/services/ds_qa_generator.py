"""
VYRA - DS Schema Learner (v4.0.0)
===================================
Onaylı tablolar için SADECE şema bilgisi öğrenir.
Sıntetik QA üretimi YOK — tablo mimarisi ve kolon yapısı öğrenilir.

Hedef: LLM doğru SQL üretebilsin diye:
  - Tablo adı (schema.table)
  - Kolon listesi (ad, tip, PK mi, nullable mi)
  - Foreign key ilişkileri
  - Satır tahmini

Her tablo için 1 adet "schema_record" üretilir, embedding'e çevrilir
ve ds_learning_results'a yazılır.

Version: 4.0.0
"""

import json
import time
import logging

logger = logging.getLogger(__name__)


def _build_schema_text(table_name: str, schema: str, cols: list,
                       bname: str, desc: str, row_est: int,
                       rels_from: list, rels_to: list) -> str:
    """
    LLM'in SQL üretmesi için yeterli, sade şema metni üretir.
    Formatı embedding + doğrudan LLM bağlamı olarak kullanmaya uygundur.
    """
    lines = []
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
            nullable = "" if c.get("nullable", True) else " NOT NULL"
            pk_mark = " [PK]" if c.get("is_pk") else ""
            lines.append(f"  - {c['name']} ({c['data_type']}){nullable}{pk_mark}")

    if rels_from:
        lines.append("İlişkiler (FK çıkan):")
        for r in rels_from:
            lines.append(f"  - {r['from_column']} → {r['to_schema']}.{r['to_table']}.{r['to_column']}")

    if rels_to:
        lines.append("İlişkiler (FK gelen):")
        for r in rels_to:
            lines.append(f"  - {r['from_schema']}.{r['from_table']}.{r['from_column']} → {r['to_column']}")

    return "\n".join(lines)


def generate_enriched_qa(source_id: int, vyra_conn) -> dict:
    """
    Onaylı tablolar için şema bilgisi öğrenir.

    Her onaylı tablo için:
      - Tablo adı, şema, kolon listesi, PK, FK ilişkileri → tek bir 'schema_record'
      - Bu metin embedding'e çevrilip ds_learning_results'a yazılır
      - content_type = 'schema_record'

    Sıntetik QA, örnek veri veya doğal dil soru-cevap üretilmez.

    Returns:
        dict: {success, data: {learned_tables, elapsed_ms, ...}}
    """
    start = time.time()
    cur = vyra_conn.cursor()
    logger.info("[DSSchemaLearner] Şema öğrenimi başlatıldı: source_id=%s", source_id)

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

    # Onaylı enrichment'lar (tablo adı, şema, iş adı, açıklama)
    cur.execute("""
        SELECT te.schema_name, te.table_name,
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

    # Tüm FK ilişkileri
    cur.execute("""
        SELECT from_schema, from_table, from_column,
               to_schema, to_table, to_column
        FROM ds_db_relationships
        WHERE source_id = %s
    """, (source_id,))
    all_rels = cur.fetchall()

    # tablo → [rels_from, rels_to] indeksi
    rels_from_map: dict = {}
    rels_to_map: dict = {}
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

    # Eski schema_record'ları geçersiz kıl
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

    # Her onaylı tablo için şema metni üret + embedding yaz
    records = []
    for enr in enrichments:
        table_name = enr["table_name"]
        schema = enr["schema_name"] or ""
        bname = enr["admin_label_tr"] or enr["business_name_tr"] or table_name
        desc = enr["description_tr"] or ""

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

        schema_text = _build_schema_text(
            table_name=table_name,
            schema=schema,
            cols=cols,
            bname=bname,
            desc=desc,
            row_est=row_est,
            rels_from=rels_from_map.get(table_name, []),
            rels_to=rels_to_map.get(table_name, []),
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
        logger.error("[DSSchemaLearner] Batch embedding hatasi: %s", emb_err)
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
        logger.info("[DSSchemaLearner] Ogrendi: %s (%d kolon)", full_table, len(
            [l for l in record["text"].split("\n") if l.startswith("  - ")]
        ))

    vyra_conn.commit()

    elapsed = int((time.time() - start) * 1000)
    logger.info("[DSSchemaLearner] Tamamlandi: %d tablo, %dms", learned, elapsed)

    return {
        "success": True,
        "data": {
            "learned_tables": learned,
            "elapsed_ms": elapsed,
            "tables": [r["table_name"] for r in records],
        }
    }
