"""
VYRA - DS Diff Service
========================
Schema snapshot oluşturma ve diff (fark) hesaplama servisi.
İki snapshot arasında eklenen/silinen/değişen tablo ve sütunları tespit eder.

Version: 3.0.0
"""

import hashlib
import json
import logging

logger = logging.getLogger(__name__)


# =====================================================
# Snapshot Oluşturma
# =====================================================

def create_snapshot(vyra_conn, source_id: int, objects: list, relationships: list) -> dict:
    """
    Keşfedilen obje ve ilişkilerden snapshot oluşturur.
    Önceki snapshot ile karşılaştırarak diff hesaplar.

    Args:
        vyra_conn: VYRA DB bağlantısı
        source_id: Kaynak ID
        objects: detect_objects çıktısındaki obje listesi
        relationships: detect_objects çıktısındaki ilişki listesi

    Returns:
        dict: {snapshot_id, diff, is_first_run}
    """
    try:
        cur = vyra_conn.cursor()

        # Snapshot verisi oluştur
        snapshot_data = _build_snapshot_data(objects, relationships)
        snapshot_hash = _compute_snapshot_hash(snapshot_data)

        # Önceki snapshot'ı al
        prev_snapshot = get_latest_snapshot(vyra_conn, source_id)

        # Diff hesapla
        diff = {}
        is_first_run = prev_snapshot is None

        if is_first_run:
            diff = {
                "added_tables": [_table_key(o) for o in objects],
                "removed_tables": [],
                "modified_tables": [],
                "unchanged_tables": [],
                "summary": f"İlk keşif: {len(objects)} tablo/view bulundu"
            }
            logger.info("[DSDiff] İlk snapshot oluşturuluyor: source_id=%s, %d obje",
                        source_id, len(objects))
        else:
            # Aynı hash → değişiklik yok
            if prev_snapshot.get("snapshot_hash") == snapshot_hash:
                logger.info("[DSDiff] Şema değişmedi: source_id=%s", source_id)
                return {
                    "snapshot_id": prev_snapshot.get("id"),
                    "diff": {
                        "added_tables": [],
                        "removed_tables": [],
                        "modified_tables": [],
                        "unchanged_tables": [_table_key(o) for o in objects],
                        "summary": "Değişiklik yok"
                    },
                    "is_first_run": False,
                    "has_changes": False
                }

            # Diff hesapla
            prev_data = prev_snapshot.get("snapshot_data", {})
            diff = compute_diff(prev_data, snapshot_data)
            logger.info("[DSDiff] Diff hesaplandı: +%d -%d ~%d tablo",
                        len(diff.get("added_tables", [])),
                        len(diff.get("removed_tables", [])),
                        len(diff.get("modified_tables", [])))

        # Snapshot kaydet
        total_cols = sum(len(o.get("columns", [])) for o in snapshot_data.get("tables", []))
        cur.execute("""
            INSERT INTO ds_schema_snapshots
                (source_id, snapshot_hash, snapshot_data, diff_summary,
                 table_count, column_count, relationship_count)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (
            source_id, snapshot_hash,
            json.dumps(snapshot_data, default=str),
            json.dumps(diff, default=str),
            len(objects), total_cols, len(relationships)
        ))
        row = cur.fetchone()
        snapshot_id = row["id"] if isinstance(row, dict) else row[0]
        vyra_conn.commit()

        has_changes = bool(
            diff.get("added_tables") or
            diff.get("removed_tables") or
            diff.get("modified_tables")
        )

        return {
            "snapshot_id": snapshot_id,
            "diff": diff,
            "is_first_run": is_first_run,
            "has_changes": has_changes
        }

    except Exception as e:
        logger.error("[DSDiff] Snapshot oluşturma hatası: %s — %s",
                     type(e).__name__, str(e)[:300])
        try:
            vyra_conn.rollback()
        except Exception:
            pass
        return {
            "snapshot_id": None,
            "diff": {"error": str(e)[:200]},
            "is_first_run": True,
            "has_changes": True  # Hata durumunda güvenli taraf: hepsini işle
        }


# =====================================================
# Diff Hesaplama
# =====================================================

def compute_diff(old_snapshot_data: dict, new_snapshot_data: dict) -> dict:
    """
    İki snapshot_data arasındaki farkları hesaplar.

    Returns:
        dict: {
            added_tables: ["schema.table", ...],
            removed_tables: ["schema.table", ...],
            modified_tables: [{table, added_columns, removed_columns, type_changes}...],
            unchanged_tables: ["schema.table", ...]
        }
    """
    old_tables = _index_tables(old_snapshot_data)
    new_tables = _index_tables(new_snapshot_data)

    old_keys = set(old_tables.keys())
    new_keys = set(new_tables.keys())

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    common = old_keys & new_keys

    modified = []
    unchanged = []

    for key in sorted(common):
        old_t = old_tables[key]
        new_t = new_tables[key]

        old_hash = _compute_table_hash(old_t)
        new_hash = _compute_table_hash(new_t)

        if old_hash == new_hash:
            unchanged.append(key)
        else:
            # Detaylı sütun diff'i
            changes = _compute_column_diff(old_t, new_t)
            changes["table"] = key
            changes["old_hash"] = old_hash
            changes["new_hash"] = new_hash
            modified.append(changes)

    total_changes = len(added) + len(removed) + len(modified)
    summary = f"+{len(added)} yeni, -{len(removed)} silinen, ~{len(modified)} değişen tablo"

    return {
        "added_tables": added,
        "removed_tables": removed,
        "modified_tables": modified,
        "unchanged_tables": unchanged,
        "summary": summary,
        "total_changes": total_changes
    }


# =====================================================
# Yardımcı Fonksiyonlar
# =====================================================

def get_latest_snapshot(vyra_conn, source_id: int) -> dict:
    """Kaynağın son snapshot'ını döner."""
    try:
        cur = vyra_conn.cursor()
        cur.execute("""
            SELECT id, snapshot_hash, snapshot_data, diff_summary, created_at
            FROM ds_schema_snapshots
            WHERE source_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """, (source_id,))
        row = cur.fetchone()
        if not row:
            return None

        data = row["snapshot_data"] if isinstance(row, dict) else row[2]
        if isinstance(data, str):
            data = json.loads(data)

        return {
            "id": row["id"] if isinstance(row, dict) else row[0],
            "snapshot_hash": row["snapshot_hash"] if isinstance(row, dict) else row[1],
            "snapshot_data": data,
            "created_at": row["created_at"] if isinstance(row, dict) else row[4]
        }
    except Exception as e:
        logger.error("[DSDiff] Snapshot okuma hatası: %s", type(e).__name__)
        return None


def get_snapshot_history(vyra_conn, source_id: int, limit: int = 10) -> list:
    """Kaynağın snapshot geçmişini döner."""
    cur = vyra_conn.cursor()
    cur.execute("""
        SELECT id, snapshot_hash, diff_summary, table_count, column_count,
               relationship_count, created_at
        FROM ds_schema_snapshots
        WHERE source_id = %s
        ORDER BY created_at DESC
        LIMIT %s
    """, (source_id, limit))

    history = []
    for row in cur.fetchall():
        diff = row["diff_summary"] if isinstance(row, dict) else row[2]
        if isinstance(diff, str):
            try:
                diff = json.loads(diff)
            except Exception:
                diff = {}
        history.append({
            "id": row["id"] if isinstance(row, dict) else row[0],
            "snapshot_hash": row["snapshot_hash"] if isinstance(row, dict) else row[1],
            "diff_summary": diff,
            "table_count": row["table_count"] if isinstance(row, dict) else row[3],
            "column_count": row["column_count"] if isinstance(row, dict) else row[4],
            "relationship_count": row["relationship_count"] if isinstance(row, dict) else row[5],
            "created_at": (row["created_at"] if isinstance(row, dict) else row[6]).isoformat()
        })
    return history


def _build_snapshot_data(objects: list, relationships: list) -> dict:
    """Obje ve ilişki listesinden snapshot verisi oluşturur."""
    tables = []
    for obj in objects:
        cols = obj.get("columns_json", [])
        if isinstance(cols, str):
            try:
                cols = json.loads(cols)
            except Exception:
                cols = []

        tables.append({
            "schema": obj.get("schema_name", ""),
            "name": obj.get("object_name", ""),
            "type": obj.get("object_type", "table"),
            "columns": [
                {
                    "name": c.get("name", ""),
                    "data_type": c.get("data_type", ""),
                    "is_nullable": c.get("is_nullable", True),
                    "is_pk": c.get("is_pk", False)
                }
                for c in (cols if isinstance(cols, list) else [])
            ],
            "row_estimate": obj.get("row_count_estimate", 0)
        })

    rels = []
    for rel in relationships:
        rels.append({
            "from": f"{rel.get('from_schema', '')}.{rel.get('from_table', '')}.{rel.get('from_column', '')}",
            "to": f"{rel.get('to_schema', '')}.{rel.get('to_table', '')}.{rel.get('to_column', '')}",
            "name": rel.get("constraint_name", "")
        })

    return {"tables": tables, "relationships": rels}


def _index_tables(snapshot_data: dict) -> dict:
    """Snapshot verisini tablo key'e göre indexler."""
    index = {}
    for t in snapshot_data.get("tables", []):
        key = _table_key_from_data(t)
        index[key] = t
    return index


def _table_key(obj: dict) -> str:
    """Obje dict'inden benzersiz tablo key'i üretir."""
    schema = obj.get("schema_name", "")
    name = obj.get("object_name", "")
    return f"{schema}.{name}" if schema else name


def _table_key_from_data(table_data: dict) -> str:
    """Snapshot table verisinden key üretir."""
    schema = table_data.get("schema", "")
    name = table_data.get("name", "")
    return f"{schema}.{name}" if schema else name


def _compute_snapshot_hash(snapshot_data: dict) -> str:
    """Tüm snapshot verisinin hash'ini hesaplar."""
    # Sadece tablo yapılarını hash'e dahil et (satır sayısı değişikliğini yoksay)
    hashable = []
    for t in sorted(snapshot_data.get("tables", []), key=lambda x: x.get("name", "")):
        cols = sorted(t.get("columns", []), key=lambda c: c.get("name", ""))
        hashable.append({
            "schema": t.get("schema", ""),
            "name": t.get("name", ""),
            "type": t.get("type", ""),
            "columns": cols
        })

    data_str = json.dumps(hashable, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()


def _compute_table_hash(table_data: dict) -> str:
    """Tek tablonun yapısal hash'i."""
    cols = sorted(table_data.get("columns", []), key=lambda c: c.get("name", ""))
    data_str = json.dumps({
        "name": table_data.get("name", ""),
        "type": table_data.get("type", ""),
        "columns": cols
    }, sort_keys=True)
    return hashlib.md5(data_str.encode()).hexdigest()


def _compute_column_diff(old_table: dict, new_table: dict) -> dict:
    """İki tablo versiyonu arasındaki sütun farklarını hesaplar."""
    old_cols = {c["name"]: c for c in old_table.get("columns", [])}
    new_cols = {c["name"]: c for c in new_table.get("columns", [])}

    old_names = set(old_cols.keys())
    new_names = set(new_cols.keys())

    added_columns = sorted(new_names - old_names)
    removed_columns = sorted(old_names - new_names)

    type_changes = []
    for col_name in sorted(old_names & new_names):
        old_type = old_cols[col_name].get("data_type", "")
        new_type = new_cols[col_name].get("data_type", "")
        if old_type != new_type:
            type_changes.append({
                "column": col_name,
                "old_type": old_type,
                "new_type": new_type
            })

    pk_changes = []
    for col_name in sorted(old_names & new_names):
        old_pk = old_cols[col_name].get("is_pk", False)
        new_pk = new_cols[col_name].get("is_pk", False)
        if old_pk != new_pk:
            pk_changes.append({
                "column": col_name,
                "was_pk": old_pk,
                "is_pk": new_pk
            })

    return {
        "added_columns": added_columns,
        "removed_columns": removed_columns,
        "type_changes": type_changes,
        "pk_changes": pk_changes
    }
