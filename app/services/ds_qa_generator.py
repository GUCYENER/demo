"""
VYRA - DS QA Generator (v3.0.0)
==================================
Enrichment verilerini kullanarak sentetik QA çiftleri üretir.
ds_learning_service.generate_synthetic_qa fonksiyonunun modüler karşılığı.

Enrichment'tan gelen Türkçe iş adları ve açıklamalar QA kalitesini artırır.

Version: 3.0.0
"""

import json
import hashlib
import logging
import time

logger = logging.getLogger(__name__)


def generate_enriched_qa(source_id: int, vyra_conn) -> dict:
    """
    Enrichment verileri ile zenginleştirilmiş sentetik QA çiftleri üretir.

    Enrichment'tan gelen business_name_tr, description_tr, category
    bilgilerini soru/cevap metinlerine dahil eder.

    Returns:
        dict: {success, data: {qa_pairs_generated, ...}}
    """
    start = time.time()
    cur = vyra_conn.cursor()
    logger.info("[DSQAGen] Enriched QA üretimi başlatıldı: source_id=%s", source_id)

    # company_id
    cur.execute("SELECT company_id FROM data_sources WHERE id = %s", (source_id,))
    source_row = cur.fetchone()
    company_id = source_row["company_id"] if source_row else 1

    # Embedding manager
    try:
        from app.services.rag.embedding import EmbeddingManager
        emb_mgr = EmbeddingManager()
    except Exception:
        logger.error("[DSQAGen] EmbeddingManager yüklenemedi")
        return {"success": False, "error": "Embedding modeli yüklenemedi"}

    # Enrichment verileri (Sadece admin onaylı olanları çek !!!)
    cur.execute("""
        SELECT te.id, te.schema_name, te.table_name, te.object_type,
               te.business_name_tr, te.description_tr, te.category,
               te.sample_questions, te.enrichment_score, te.admin_label_tr
        FROM ds_table_enrichments te
        WHERE te.source_id = %s AND te.is_active = TRUE AND te.admin_approved = TRUE
        ORDER BY te.table_name
    """, (source_id,))
    enrichments = cur.fetchall()

    # Objeleri al (sütun bilgileri için)
    cur.execute("""
        SELECT id, schema_name, object_name, object_type, column_count,
               row_count_estimate, columns_json
        FROM ds_db_objects WHERE source_id = %s
        ORDER BY object_name
    """, (source_id,))
    objects = {(row["schema_name"] or "", row["object_name"]): row for row in cur.fetchall()}

    # İlişkileri al
    cur.execute("""
        SELECT from_schema, from_table, from_column, to_schema, to_table, to_column
        FROM ds_db_relationships WHERE source_id = %s
    """, (source_id,))
    all_rels = cur.fetchall()

    # Sample verileri
    cur.execute("""
        SELECT s.object_id, s.sample_data, s.row_count, o.object_name
        FROM ds_db_samples s
        JOIN ds_db_objects o ON s.object_id = o.id
        WHERE s.source_id = %s
    """, (source_id,))
    all_samples = {row["object_name"]: row for row in cur.fetchall()}

    # Dedup hash'leri
    cur.execute("""
        SELECT md5(metadata->>'question') as q_hash
        FROM ds_learning_results
        WHERE source_id = %s AND is_valid = TRUE
    """, (source_id,))
    existing_hashes = {row["q_hash"] for row in cur.fetchall()}

    # Job ID
    cur.execute("""
        SELECT id FROM ds_discovery_jobs
        WHERE source_id = %s AND status = 'running'
        ORDER BY started_at DESC LIMIT 1
    """, (source_id,))
    job_row = cur.fetchone()
    current_job_id = job_row["id"] if job_row else None

    qa_count = 0
    skipped_count = 0
    total_pairs = []

    # Enrichment bazlı QA üretimi
    for enr in enrichments:
        table_name = enr["table_name"]
        schema = enr["schema_name"] or "public"
        bname = enr["admin_label_tr"] or enr["business_name_tr"] or table_name
        desc = enr["description_tr"] or ""
        category = enr["category"] or "other"
        sample_qs = enr["sample_questions"]

        if isinstance(sample_qs, str):
            try:
                sample_qs = json.loads(sample_qs)
            except Exception:
                sample_qs = []

        obj = objects.get((schema if schema != "public" else "", table_name)) or \
              objects.get(("", table_name)) or \
              objects.get(("public", table_name))

        # Sütun bilgileri
        cols = []
        col_count = 0
        row_est = 0
        if obj:
            col_count = obj["column_count"] or 0
            row_est = obj["row_count_estimate"] or 0
            cols_raw = obj["columns_json"]
            if isinstance(cols_raw, str):
                try:
                    cols = json.loads(cols_raw)
                except Exception:
                    cols = []
            else:
                cols = cols_raw or []

        pk_cols = [c["name"] for c in cols if c.get("is_pk")]
        col_text = ", ".join([f"{c['name']} ({c['data_type']})" for c in cols[:20]])

        # ─── QA 1: İş anlamı (enrichment bilgisi ile) ───
        q1 = f"{bname} tablosu ne içerir? {table_name} tablosu ne işe yarar?"
        a1 = f"{bname} ({schema}.{table_name}): {desc}" if desc else f"{bname} ({schema}.{table_name})"
        if col_count:
            a1 += f" {col_count} sütun, yaklaşık {row_est} kayıt."
        if col_text:
            a1 += f" Sütunlar: {col_text}."
        if pk_cols:
            a1 += f" Primary Key: {', '.join(pk_cols)}."

        total_pairs.append({
            "content_type": "schema_description",
            "content_text": a1,
            "question_text": q1,
            "object_name": table_name
        })

        # ─── QA 2: Kategori bilgisi ───
        cat_labels = {
            "finance": "finans ve muhasebe", "hr": "insan kaynakları",
            "crm": "müşteri ilişkileri", "inventory": "stok ve envanter",
            "auth": "kimlik doğrulama ve yetkilendirme", "system": "sistem",
            "log": "log ve denetim", "config": "ayar ve konfigürasyon"
        }
        cat_label = cat_labels.get(category, category)

        q2 = f"{bname} hangi kategoride? {table_name} ne tür veri tutar?"
        a2 = f"{bname} ({table_name}) tablosu '{cat_label}' kategorisinde yer alır."
        if desc:
            a2 += f" {desc}"

        total_pairs.append({
            "content_type": "schema_description",
            "content_text": a2,
            "question_text": q2,
            "object_name": table_name
        })

        # ─── QA 3: LLM sample_questions ───
        if sample_qs:
            for sq in sample_qs[:3]:
                if isinstance(sq, str) and len(sq) >= 5:
                    total_pairs.append({
                        "content_type": "schema_description",
                        "content_text": f"{bname} ({schema}.{table_name}): {desc or 'Detaylı bilgi için tablonun sütunlarını inceleyin.'}",
                        "question_text": sq,
                        "object_name": table_name
                    })

        # ─── QA 4: Sütun sayısı ───
        if col_count:
            q4 = f"{bname} tablosunda kaç sütun var? {table_name} kaç alana sahip?"
            a4 = f"{bname} ({table_name}) tablosunda {col_count} sütun vardır: {col_text}."
            total_pairs.append({
                "content_type": "schema_description",
                "content_text": a4,
                "question_text": q4,
                "object_name": table_name
            })

    # ─── İlişki QA'ları ───
    if all_rels:
        rel_descriptions = []
        for rel in all_rels[:30]:
            rel_descriptions.append(
                f"{rel['from_table']}.{rel['from_column']} → {rel['to_table']}.{rel['to_column']}"
            )

        q_rel = "Tablolar arası ilişkiler nelerdir? Hangi tablolar birbiriyle bağlantılı?"
        a_rel = f"Veritabanında {len(all_rels)} Foreign Key ilişkisi bulunmaktadır: " + "; ".join(rel_descriptions) + "."
        total_pairs.append({
            "content_type": "relationship_map",
            "content_text": a_rel,
            "question_text": q_rel,
            "object_name": "_relationships"
        })

    # ─── Sample Insight QA'ları ───
    for table_name, sample in all_samples.items():
        if not sample["sample_data"]:
            continue

        sample_data = sample["sample_data"]
        if isinstance(sample_data, str):
            try:
                sample_data = json.loads(sample_data)
            except Exception:
                continue

        if not sample_data:
            continue

        # Enrichment'tan iş adını al
        enr_match = next(
            (e for e in enrichments if e["table_name"] == table_name), None
        )
        bname_s = (enr_match["admin_label_tr"] or enr_match["business_name_tr"]
                   if enr_match else table_name)

        sample_rows = sample_data[:3]
        parts = []
        for i, row in enumerate(sample_rows):
            vals = ", ".join([f"{k}={v}" for k, v in list(row.items())[:8]])
            parts.append(f"  Satır {i+1}: {vals}")

        q_s = f"{bname_s} tablosunda ne tür veriler var? {table_name} örnek veriler."
        a_s = f"{bname_s} ({table_name}) tablosundan örnekler ({sample['row_count']} satır):\n" + "\n".join(parts)
        total_pairs.append({
            "content_type": "sample_insight",
            "content_text": a_s,
            "question_text": q_s,
            "object_name": table_name
        })

    # ─── Embedding üret ve DB'ye yaz ───
    if total_pairs:
        all_texts = [f"{p['question_text']} {p['content_text']}" for p in total_pairs]
        batch_size = 50

        all_embeddings = []
        for i in range(0, len(all_texts), batch_size):
            batch = all_texts[i:i + batch_size]
            batch_embs = emb_mgr.get_embeddings_batch(batch)
            all_embeddings.extend(batch_embs)

        # Eski ilgili sonuçları geçersiz kıl (incremental güncellik)
        cur.execute("""
            UPDATE ds_learning_results
            SET is_valid = FALSE, invalidated_at = NOW()
            WHERE source_id = %s AND is_valid = TRUE
        """, (source_id,))
        invalidated = cur.rowcount
        if invalidated:
            logger.info("[DSQAGen] %d eski QA sonucu invalidated", invalidated)
            # Invalidated kayıtların hash'lerini sıfırla (yeniden üretilmeli)
            existing_hashes.clear()

        for pair, embedding in zip(total_pairs, all_embeddings):
            q_hash = hashlib.md5(pair["question_text"].encode()).hexdigest()
            if q_hash in existing_hashes:
                skipped_count += 1
                continue

            cur.execute("""
                INSERT INTO ds_learning_results
                    (source_id, company_id, job_id, content_type, content_text,
                     embedding, metadata, score, is_valid, version)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, TRUE, 1)
            """, (
                source_id, company_id, current_job_id,
                pair["content_type"], pair["content_text"],
                embedding,
                json.dumps({
                    "question": pair["question_text"],
                    "table_name": pair["object_name"]
                }),
                1.0
            ))
            existing_hashes.add(q_hash)
            qa_count += 1

        vyra_conn.commit()

    elapsed = int((time.time() - start) * 1000)
    logger.info("[DSQAGen] Enriched QA üretimi: %d yeni, %d atlandı (dedup), %dms",
                qa_count, skipped_count, elapsed)

    return {
        "success": True,
        "data": {
            "qa_pairs_generated": qa_count,
            "skipped_dedup": skipped_count,
            "total_pairs_generated": len(total_pairs),
            "elapsed_ms": elapsed
        }
    }
