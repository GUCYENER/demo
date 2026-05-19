"""VYRA v3.29.0 — Cardinality & Junction Analyzer (Faz 6 G1).

ds_db_relationships satırları için cardinality (1/N) ve junction (N:M köprü)
metadatasını çıkarır. Çıkarım, ``ds_db_objects.columns_json`` içindeki
``is_pk`` bayrağı ve tablo başına FK çıkış/giriş sayımına dayanır.

Kullanım:
    from app.services.db_learning import cardinality_analyzer
    summary = cardinality_analyzer.analyze_relationships(cur, source_id)

Çıktı:
    {
        "analyzed": int,
        "junctions": int,
        "one_to_one": int,
        "one_to_many": int,
        "many_to_many": int,
        "inverse_pairs_linked": int,
        "skipped": int,
    }

Algoritma:
    1. Tüm FK satırlarını ve referans verilen tabloların columns_json'unu çek.
    2. Her FK için:
        - from_column tablo PK'sının (tek kolonlu) tamamı ise cardinality_from='1'
          (1:1 — örn. extension tablo). Aksi halde 'N'.
        - to_column PK olmak zorundadır (FK target) → cardinality_to='1'.
    3. Junction tespiti — bir from_table:
        - en az 2 FK çıkışı var
        - tablo PK'sı tam olarak bu FK kolonlarından oluşuyor (composite PK)
        - başka veri kolonu az (≤2 yardımcı), yani neredeyse saf köprü
       Bu durumda ilgili FK'ler is_junction=TRUE işaretlenir.
    4. Inverse FK eşleşmesi: (A.x→B.y) ve (B.y→A.x) çiftleri için
       her iki satırın ``inverse_relationship_id`` alanı diğerini gösterir.
    5. ``path_weight`` — düşük=tercih:
        - 1:1                              → 50
        - 1:N (parent yön, normal)         → 100
        - N:M (junction üzerinden geçiş)   → 200
       Self loop +20 ceza.
    6. ``confidence_score``:
        - PK kanıtı net (columns_json'da is_pk var) → +0.5
        - Junction sinyali tam (composite PK eşleşti) → +0.3
        - Inverse partner bulundu → +0.2
        Tavan 1.0, taban 0.0.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Yardımcılar
# ─────────────────────────────────────────────────────────────

def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _table_key(schema: Optional[str], table: str) -> Tuple[str, str]:
    return (_norm(schema), _norm(table))


def _load_columns_index(cur, source_id: int) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """{(schema,table): [columns_json]} indeksi döndürür."""
    cur.execute(
        """
        SELECT schema_name, object_name, columns_json
        FROM ds_db_objects
        WHERE source_id = %s
        """,
        (source_id,),
    )
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for row in cur.fetchall():
        if isinstance(row, dict):
            sch, name, cols = row.get("schema_name"), row.get("object_name"), row.get("columns_json")
        else:
            sch, name, cols = row[0], row[1], row[2]
        if isinstance(cols, str):
            try:
                cols = json.loads(cols)
            except Exception:
                cols = []
        if not isinstance(cols, list):
            cols = []
        out[_table_key(sch, name)] = cols
    return out


def _pk_columns(cols: List[Dict[str, Any]]) -> List[str]:
    return [_norm(c.get("name")) for c in cols if c.get("is_pk")]


def _is_junction_table(
    table_cols: List[Dict[str, Any]],
    outgoing_fk_columns: List[str],
) -> bool:
    """Tablo neredeyse saf köprü mü?

    Kural:
        - PK kompozit (≥2 kolon)
        - PK kolonları tamamen outgoing FK kolonlarından oluşuyor
        - Toplam kolon sayısı PK_count + max 2 yardımcı (örn. created_at, id) içinde
    """
    pk_cols = _pk_columns(table_cols)
    if len(pk_cols) < 2:
        return False
    pk_set = set(pk_cols)
    fk_set = {_norm(c) for c in outgoing_fk_columns}
    if not pk_set.issubset(fk_set):
        return False
    # Yardımcı kolon toleransı
    return len(table_cols) <= len(pk_set) + 2


# ─────────────────────────────────────────────────────────────
# Ana analiz
# ─────────────────────────────────────────────────────────────

def analyze_relationships(cur, source_id: int) -> Dict[str, int]:
    """Verilen source_id için FK satırlarını analiz eder, sonuçları yazar."""
    cols_idx = _load_columns_index(cur, source_id)

    cur.execute(
        """
        SELECT id, from_schema, from_table, from_column,
               to_schema, to_table, to_column
        FROM ds_db_relationships
        WHERE source_id = %s
        ORDER BY id
        """,
        (source_id,),
    )
    rels_raw = cur.fetchall()
    rels: List[Dict[str, Any]] = []
    for row in rels_raw:
        if isinstance(row, dict):
            rels.append(dict(row))
        else:
            rels.append({
                "id": row[0],
                "from_schema": row[1], "from_table": row[2], "from_column": row[3],
                "to_schema": row[4], "to_table": row[5], "to_column": row[6],
            })

    # Tablo başına outgoing FK kolonları
    outgoing: Dict[Tuple[str, str], List[str]] = {}
    for r in rels:
        k = _table_key(r["from_schema"], r["from_table"])
        outgoing.setdefault(k, []).append(_norm(r["from_column"]))

    # Inverse map: (from_table_key, to_table_key) → [rel_id...]
    # İki tablo arasında ters yönde başka bir FK varsa "inverse" sayılır.
    # Graph traversal için yön çiftini eşler.
    pair_map: Dict[Tuple[Tuple[str, str], Tuple[str, str]], List[int]] = {}
    for r in rels:
        key = (
            _table_key(r["from_schema"], r["from_table"]),
            _table_key(r["to_schema"], r["to_table"]),
        )
        pair_map.setdefault(key, []).append(r["id"])

    stats = {
        "analyzed": 0,
        "junctions": 0,
        "one_to_one": 0,
        "one_to_many": 0,
        "many_to_many": 0,
        "inverse_pairs_linked": 0,
        "skipped": 0,
    }

    # 1. Geçiş — cardinality + junction + confidence
    updates: List[Tuple[str, str, bool, int, float, int]] = []
    # (cardinality_from, cardinality_to, is_junction, path_weight, confidence, rel_id)

    for r in rels:
        from_key = _table_key(r["from_schema"], r["from_table"])
        to_key = _table_key(r["to_schema"], r["to_table"])
        from_col = _norm(r["from_column"])
        to_col = _norm(r["to_column"])

        from_cols = cols_idx.get(from_key, [])
        to_cols = cols_idx.get(to_key, [])
        if not from_cols or not to_cols:
            stats["skipped"] += 1
            updates.append(("N", "1", False, 100, 0.0, r["id"]))
            continue

        from_pk = _pk_columns(from_cols)
        to_pk = _pk_columns(to_cols)

        # cardinality_to — referans hedef neredeyse her zaman PK
        c_to = "1" if to_col in to_pk else "N"

        # cardinality_from — from_col tek başına from_table'ın PK'sıysa 1:1
        if from_pk == [from_col]:
            c_from = "1"
        else:
            c_from = "N"

        # Junction
        is_junc = _is_junction_table(from_cols, outgoing.get(from_key, []))

        # path_weight
        if is_junc:
            weight = 200
        elif c_from == "1" and c_to == "1":
            weight = 50
        else:
            weight = 100
        if from_key == to_key:
            weight += 20  # self-loop ceza

        # confidence
        conf = 0.0
        if to_pk and to_col in to_pk:
            conf += 0.5
        if from_pk:
            conf += 0.2
        if is_junc:
            conf += 0.3
        conf = max(0.0, min(1.0, conf))

        # İstatistik
        stats["analyzed"] += 1
        if is_junc:
            stats["junctions"] += 1
            stats["many_to_many"] += 1
        elif c_from == "1" and c_to == "1":
            stats["one_to_one"] += 1
        else:
            stats["one_to_many"] += 1

        updates.append((c_from, c_to, is_junc, weight, conf, r["id"]))

    # Batch update
    for c_from, c_to, is_junc, weight, conf, rel_id in updates:
        cur.execute(
            """
            UPDATE ds_db_relationships
            SET cardinality_from = %s,
                cardinality_to = %s,
                is_junction = %s,
                path_weight = %s,
                confidence_score = %s,
                last_analyzed_at = NOW()
            WHERE id = %s
            """,
            (c_from, c_to, is_junc, weight, conf, rel_id),
        )

    # 2. Geçiş — inverse_relationship_id eşleştirmesi
    # (from_table, to_table) çiftinde ters yönde başka FK varsa ilkini referans göster.
    for r in rels:
        from_key = _table_key(r["from_schema"], r["from_table"])
        to_key = _table_key(r["to_schema"], r["to_table"])
        if from_key == to_key:
            continue  # self FK
        inverse_candidates = [rid for rid in pair_map.get((to_key, from_key), []) if rid != r["id"]]
        if inverse_candidates:
            cur.execute(
                "UPDATE ds_db_relationships SET inverse_relationship_id = %s WHERE id = %s",
                (inverse_candidates[0], r["id"]),
            )
            stats["inverse_pairs_linked"] += 1

    logger.info("[CardinalityAnalyzer] source_id=%s stats=%s", source_id, stats)
    return stats


def override_relationship(
    cur,
    relationship_id: int,
    *,
    cardinality_from: Optional[str] = None,
    cardinality_to: Optional[str] = None,
    is_junction: Optional[bool] = None,
    path_weight: Optional[int] = None,
    confidence_score: Optional[float] = None,
) -> bool:
    """Admin manuel override — verilen alanları günceller."""
    sets: List[str] = []
    args: List[Any] = []
    if cardinality_from is not None:
        if cardinality_from not in ("1", "N"):
            raise ValueError("cardinality_from must be '1' or 'N'")
        sets.append("cardinality_from = %s")
        args.append(cardinality_from)
    if cardinality_to is not None:
        if cardinality_to not in ("1", "N"):
            raise ValueError("cardinality_to must be '1' or 'N'")
        sets.append("cardinality_to = %s")
        args.append(cardinality_to)
    if is_junction is not None:
        sets.append("is_junction = %s")
        args.append(bool(is_junction))
    if path_weight is not None:
        sets.append("path_weight = %s")
        args.append(int(path_weight))
    if confidence_score is not None:
        cs = max(0.0, min(1.0, float(confidence_score)))
        sets.append("confidence_score = %s")
        args.append(cs)
    if not sets:
        return False
    sets.append("last_analyzed_at = NOW()")
    args.append(relationship_id)
    cur.execute(
        f"UPDATE ds_db_relationships SET {', '.join(sets)} WHERE id = %s",
        tuple(args),
    )
    return (cur.rowcount or 0) > 0
