"""Domain + tablo eligibility / arama (v3.30.0 FAZ 1 G1.2).

Hybrid search pattern: lexical (ILIKE/Türkçe normalize) + semantic (pgvector cosine,
business_glossary embedding) + cardinality boost + user `frequent_tables` boost.

Public API:
    search_domains(cur, source_id, query, user_ctx, limit=20) → List[Dict]
        Sıralı tablo önerileri (skor + neden açıklaması ile).
    sample_preview(cur, table_id, user_ctx) → Optional[Dict]
        ds_db_samples'tan 5 satır JSONB; UI hover preview için.

NOT:
    - Cursor caller'dan gelir (apply_vyra_user_context zaten set edilmiş).
    - pgvector yoksa semantic skor 0.0; lexical+cardinality+pref hala çalışır.
    - business_glossary embedding kolonu yoksa sessizce skip edilir (geriye uyum).
    - SQL injection guard: query string yalnızca ILIKE %s parametresine bind edilir,
      kolon/şema adı asla string-concat ile yerleştirilmez.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Skor ağırlıkları (Prompt H confidence cap > 0.6 için kalibre)
# ─────────────────────────────────────────────────────────────
W_LEXICAL = 0.40       # object_name + business_name_tr + description_tr ILIKE
W_SEMANTIC = 0.30      # business_glossary embedding ↔ query embedding
W_CARDINALITY = 0.10   # log10(row_count) normalized 0-1
W_FREQUENT = 0.20      # user preference (dbsmart_user_preferences.frequent_tables)

# Türkçe karakter normalize haritası (sorgu için, ILIKE-friendly)
_TR_LOWER = str.maketrans({
    "İ": "i", "I": "i", "Ş": "s", "Ğ": "g", "Ü": "u", "Ö": "o", "Ç": "c",
    "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c", "ı": "i",
})


def _normalize_tr(text: str) -> str:
    """Türkçe lowercase + ASCII benzeri normalize (lexical match için)."""
    return (text or "").translate(_TR_LOWER).lower().strip()


# ─────────────────────────────────────────────────────────────
# LIKE escape (ARES ORTA — kullanıcı term'i %/_/\\ enjekte edemesin)
# ─────────────────────────────────────────────────────────────

def _escape_like(text: str) -> str:
    """LIKE meta karakterlerini (\\, %, _) backslash ile escape eder.

    SQL'de ESCAPE '\\' clause'u ile kullanılmalıdır — örn.
        WHERE col LIKE %s ESCAPE '\\'
    Aksi halde kullanıcı '%' veya '_' geçirerek tüm satırları taratabilir
    (glossary structure leak).
    """
    if not text:
        return ""
    # Önce backslash'i kendisi escape edilmeli (sıra önemli)
    out = text.replace("\\", "\\\\")
    out = out.replace("%", "\\%")
    out = out.replace("_", "\\_")
    return out


# ─────────────────────────────────────────────────────────────
# pgvector availability check (mevcut rag/hybrid_retrieval pattern'i)
# ─────────────────────────────────────────────────────────────

def _pgvector_available(cur) -> bool:
    try:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")
        return cur.fetchone() is not None
    except Exception:
        return False


def _glossary_has_embedding_column(cur) -> bool:
    """business_glossary tablosunda embedding kolonu var mı?"""
    try:
        cur.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name IN ('business_glossary', 'business_glossary_v2')
              AND column_name = 'embedding'
            LIMIT 1
        """)
        return cur.fetchone() is not None
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# search_domains
# ─────────────────────────────────────────────────────────────

def search_domains(
    cur,
    source_id: int,
    query: str,
    user_ctx: Dict[str, Any],
    limit: int = 20,
    query_embedding: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    """Hybrid tablo araması — lexical + semantic + cardinality + user preference.

    Args:
        cur: Aktif psycopg2 cursor (apply_vyra_user_context set edilmiş).
        source_id: data_sources.id (caller bunu data_sources üzerinden auth etmeli).
        query: Doğal dil sorgusu (örn. "açık talepler", "müşteri siparişleri").
        user_ctx: get_current_user dict — {id, company_id, ...}.
        limit: Maksimum dönecek tablo sayısı.
        query_embedding: Opsiyonel önceden hesaplanmış 384-dim vector;
            verilmezse semantic skor 0.0 (lexical-only mod).

    Returns:
        [{table_id, schema_name, object_name, business_name_tr, description_tr,
          row_count_estimate, score, score_breakdown: {...}, reasons: [str]}, ...]
        Skor azalan sıralı.
    """
    user_id = user_ctx.get("id")
    norm_q = _normalize_tr(query)
    # ARES ORTA: LIKE meta karakterlerini escape et — '%' / '_' / '\\'
    # tarafımızdan bind edilmeden önce literal hale getirilmeli ki kullanıcı
    # term="%" ile tüm glossary'yi taratamasın.
    safe_q = _escape_like(norm_q)
    like_pattern = f"%{safe_q}%" if safe_q else "%"

    # 1) Frequent tables hint (cold-start sonrası user_preferences set edilmiş olur)
    frequent_table_ids: List[int] = []
    if user_id is not None:
        try:
            cur.execute(
                "SELECT frequent_tables FROM dbsmart_user_preferences WHERE user_id = %s",
                (int(user_id),),
            )
            row = cur.fetchone()
            if row and row[0]:
                # frequent_tables: INTEGER[]
                frequent_table_ids = list(row[0])
        except Exception as e:
            logger.debug("[eligibility] user_preferences lookup skipped: %s", e)

    # 2) Lexical join: ds_db_objects LEFT JOIN ds_table_enrichments
    #    Score: ILIKE match'i sayıyı sayıp normalize ediyoruz.
    cur.execute(
        """
        WITH t AS (
            SELECT
                o.id              AS table_id,
                o.schema_name,
                o.object_name,
                o.object_type,
                COALESCE(o.row_count_estimate, 0) AS row_cnt,
                te.business_name_tr,
                te.description_tr,
                te.category,
                te.enrichment_score,
                -- Lexical match flag (kolonun adina dokunmadan).
                -- ESCAPE '\\' -> kullanici term'indeki yuzde/altcizgi literal
                -- eslesir, wildcard degil.
                -- ARES UYARI: psycopg2 SQL string'inde yorum satirlarini da
                -- parametre marker tarayicidan gecirir. Ciplak yuzde isareti
                -- ('s' veya '(' takip etmeyen) `IndexError: tuple index out of
                -- range` firlatir; endpoint try/except items=[] ile yutar ve
                -- frontend "Eslesen tablo bulunamadi" gosterir. Bu nedenle
                -- yorumda literal yuzde KULLANILMAZ.
                -- TRANSLATE() ile kolon tarafini da TR -> ASCII normalize et;
                -- Python tarafi _normalize_tr ile esitlenir. Bu olmadan
                -- LIKE 'musteri' -> 'müşteri' ICERIKLI business_name_tr/description_tr
                -- ile eslesemez ve ASCII tablo adlari haric kullanici hicbir
                -- Turkce zenginlestirme metnine ulasamaz.
                CASE WHEN TRANSLATE(LOWER(o.object_name),
                        'şğüöçıİ', 'sgúocii') LIKE %s ESCAPE '\' THEN 1 ELSE 0 END AS m_obj,
                CASE WHEN TRANSLATE(LOWER(COALESCE(te.business_name_tr,'')),
                        'şğüöçıİ', 'sgúocii') LIKE %s ESCAPE '\' THEN 1 ELSE 0 END AS m_bizname,
                CASE WHEN TRANSLATE(LOWER(COALESCE(te.description_tr,'')),
                        'şğüöçıİ', 'sgúocii') LIKE %s ESCAPE '\' THEN 1 ELSE 0 END AS m_desc,
                CASE WHEN TRANSLATE(LOWER(COALESCE(te.category,'')),
                        'şğüöçıİ', 'sgúocii') LIKE %s ESCAPE '\' THEN 1 ELSE 0 END AS m_cat
            FROM ds_db_objects o
            LEFT JOIN ds_table_enrichments te
              ON te.source_id = o.source_id
             AND LOWER(te.table_name)  = LOWER(o.object_name)
             AND LOWER(COALESCE(te.schema_name,'')) = LOWER(COALESCE(o.schema_name,''))
             AND COALESCE(te.is_active, TRUE) = TRUE
            WHERE o.source_id = %s
              AND o.object_type IN ('table','view','materialized_view')
        )
        SELECT
            table_id, schema_name, object_name, object_type, row_cnt,
            business_name_tr, description_tr, category, enrichment_score,
            m_obj, m_bizname, m_desc, m_cat
        FROM t
        ORDER BY (m_obj + m_bizname + m_desc + m_cat) DESC, row_cnt DESC
        LIMIT %s
        """,
        (like_pattern, like_pattern, like_pattern, like_pattern,
         int(source_id), int(limit) * 3),  # 3x oversample → semantic ile re-rank
    )
    rows = cur.fetchall()
    if not rows:
        return []

    # 3) Semantic skor — opsiyonel; query_embedding verilmişse ve pgvector + embedding kolonu varsa
    semantic_map: Dict[int, float] = {}
    if query_embedding and _pgvector_available(cur) and _glossary_has_embedding_column(cur):
        try:
            company_id = user_ctx.get("company_id")
            is_admin = bool(user_ctx.get("is_admin", False))
            # ARES KRİTİK: glossary `company_id IS NULL` leak'i — eski sürümde
            # `(%s IS NULL OR bg.company_id = %s)` predicate'i caller company_id=NULL
            # gönderdiğinde TÜM tenant glossary kayıtlarını döndürüyordu.
            # Yeni davranış:
            #   - company_id verilmişse: kendi tenant satırları VE sistem (NULL company_id)
            #     fallback satırları — fallback yalnızca admin_verified=TRUE ile sınırlı.
            #   - company_id NULL ve is_admin=False ise: yalnızca admin_verified=TRUE
            #     sistem (NULL company_id) satırları → cross-tenant leak yok.
            #   - is_admin=True ise: NULL company_id sistem satırlarına erişim
            #     (admin'in cross-tenant taraması RLS katmanında ayrıca yönetilir).
            # NOT: admin_verified=TRUE filtresi mevcut tasarımda sistem-seed sinyali
            # olarak kullanılıyor (ayrı bir is_seed kolonu yok — bkz. raporda öneri).
            if company_id is not None:
                cur.execute(
                    """
                    SELECT bg.mapped_table, MAX(1.0 - (bg.embedding <=> %s::vector)) AS sim
                    FROM business_glossary bg
                    WHERE bg.admin_verified = TRUE
                      AND bg.embedding IS NOT NULL
                      AND bg.mapped_table IS NOT NULL
                      AND (
                            bg.company_id = %s
                         OR bg.company_id IS NULL  -- sistem (admin_verified) fallback
                      )
                    GROUP BY bg.mapped_table
                    ORDER BY sim DESC
                    LIMIT 50
                    """,
                    (query_embedding, int(company_id)),
                )
            elif is_admin:
                # Admin + company_id yok → yalnızca sistem (NULL) satırları.
                cur.execute(
                    """
                    SELECT bg.mapped_table, MAX(1.0 - (bg.embedding <=> %s::vector)) AS sim
                    FROM business_glossary bg
                    WHERE bg.admin_verified = TRUE
                      AND bg.embedding IS NOT NULL
                      AND bg.mapped_table IS NOT NULL
                      AND bg.company_id IS NULL
                    GROUP BY bg.mapped_table
                    ORDER BY sim DESC
                    LIMIT 50
                    """,
                    (query_embedding,),
                )
            else:
                # Non-admin + company_id yok → yalnızca sistem fallback satırları.
                # Cross-tenant leak'i engellemek için company_id IS NULL şart.
                cur.execute(
                    """
                    SELECT bg.mapped_table, MAX(1.0 - (bg.embedding <=> %s::vector)) AS sim
                    FROM business_glossary bg
                    WHERE bg.admin_verified = TRUE
                      AND bg.embedding IS NOT NULL
                      AND bg.mapped_table IS NOT NULL
                      AND bg.company_id IS NULL
                    GROUP BY bg.mapped_table
                    ORDER BY sim DESC
                    LIMIT 50
                    """,
                    (query_embedding,),
                )
            # mapped_table → similarity
            glossary_sim: Dict[str, float] = {
                (r[0] or "").lower(): float(r[1] or 0.0)
                for r in cur.fetchall()
            }
            # Object_name eşleşmesiyle skoru tablolara propagate et
            for r in rows:
                obj_lc = (r[2] or "").lower()
                if obj_lc in glossary_sim:
                    semantic_map[r[0]] = glossary_sim[obj_lc]
        except Exception as e:
            logger.debug("[eligibility] semantic ranking skipped: %s", e)

    # 4) Final skor + breakdown
    max_row_cnt = max((r[4] or 0) for r in rows) or 1
    import math
    log_max = math.log10(max_row_cnt + 10)

    results: List[Dict[str, Any]] = []
    for r in rows:
        table_id = r[0]
        lex_hits = (r[9] or 0) + (r[10] or 0) + (r[11] or 0) + (r[12] or 0)
        lex_score = min(1.0, lex_hits / 4.0)  # 4 alandan kaçında eşleşti

        row_cnt = r[4] or 0
        card_score = math.log10(row_cnt + 10) / log_max if log_max > 0 else 0.0

        freq_score = 1.0 if table_id in frequent_table_ids else 0.0

        sem_score = semantic_map.get(table_id, 0.0)

        total = (
            W_LEXICAL * lex_score
            + W_SEMANTIC * sem_score
            + W_CARDINALITY * card_score
            + W_FREQUENT * freq_score
        )

        reasons: List[str] = []
        if lex_score > 0:
            reasons.append(f"Anahtar kelime eşleşmesi ({lex_hits}/4 alan)")
        if sem_score > 0:
            reasons.append(f"İş terimleri sözlüğüyle anlamsal yakınlık ({sem_score:.2f})")
        if freq_score > 0:
            reasons.append("Sık kullandığınız tablolar arasında")
        if card_score > 0.5:
            reasons.append(f"Yüksek satır sayısı (~{row_cnt:,})")

        results.append({
            "table_id": table_id,
            "schema_name": r[1],
            "object_name": r[2],
            "object_type": r[3],
            "row_count_estimate": row_cnt,
            "business_name_tr": r[5],
            "description_tr": r[6],
            "category": r[7],
            "enrichment_score": r[8],
            "score": round(total, 4),
            "score_breakdown": {
                "lexical": round(lex_score, 3),
                "semantic": round(sem_score, 3),
                "cardinality": round(card_score, 3),
                "frequent": round(freq_score, 3),
            },
            "reasons": reasons,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


# ─────────────────────────────────────────────────────────────
# sample_preview
# ─────────────────────────────────────────────────────────────

def sample_preview(
    cur,
    table_id: int,
    user_ctx: Dict[str, Any],
    max_rows: int = 5,
) -> Optional[Dict[str, Any]]:
    """ds_db_samples'tan en güncel sample_data JSONB'sini döndür (max_rows satır).

    Returns:
        {"columns": [...], "rows": [[...], ...], "fetched_at": iso_str} veya None.
    """
    try:
        cur.execute(
            """
            SELECT sample_data, fetched_at
            FROM ds_db_samples
            WHERE object_id = %s
            ORDER BY fetched_at DESC
            LIMIT 1
            """,
            (int(table_id),),
        )
        row = cur.fetchone()
    except Exception as e:
        logger.warning("[eligibility] sample_preview query failed: %s", e)
        return None

    if not row:
        return None

    sample_data = row[0]
    if not sample_data:
        return None

    # JSONB pattern: {"columns": [...], "rows": [[...], ...]} (003 migration:72-80)
    if isinstance(sample_data, dict):
        cols = sample_data.get("columns") or []
        rows = sample_data.get("rows") or []
    else:
        # Bilinmeyen şekil — boş döndür
        return None

    truncated_rows = rows[: max(0, int(max_rows))]
    return {
        "columns": cols,
        "rows": truncated_rows,
        "fetched_at": row[1].isoformat() if row[1] else None,
        "total_rows_in_sample": len(rows),
    }
