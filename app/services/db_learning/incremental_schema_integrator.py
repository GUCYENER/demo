"""VYRA v3.29.6 — Incremental Schema Integrator (Faz 7).

Mevcut bir data_source içinde yeni tablo(lar) eklendiğinde, sistemi sıfırdan
"full re-discovery" yapmaya zorlamadan keşfeder; en kritik şekilde de
**yeni tablonun, daha önce keşfedilmiş tablolarla olan FK ilişkilerini**
bulup ds_db_relationships'a ekler ve downstream öğrenme pipeline'ını
(cardinality, sample, code_value, synthetic queries, learned failures)
yeniden tetikler.

Tasarım kararları
-----------------
1. **Soft introspect** — `ds_learning_service.detect_objects` agresif DELETE
   yapıyor (ds_table_enrichments / ds_column_enrichments / ds_db_samples /
   ds_db_objects / ds_db_relationships hepsini siler). Bu admin'in onayladığı
   enrichment'ları kaybettirir. Bu yüzden burada sadece **yeni tablolar için
   INSERT** + **yeni FK'lar için ON CONFLICT DO NOTHING upsert** kullanılır.
2. **Relink önceliği** — `ds_learning_service._refresh_relationships_for_tables`
   PG ve Oracle için "FROM=yeni OR TO=yeni" sorgusu yapar. Bu sayede yeni
   tablonun mevcut tablolarla olan FK'ları otomatik bulunur.
3. **Junction global** — yeni FK eklendiğinde cardinality_analyzer TÜM source
   için yeniden çalıştırılır (junction tespiti tablo başına FK sayımına
   bağlı, dolayısıyla yeni tablo eklenince eski tabloların junction durumu
   değişebilir).
4. **Failure re-eligibility** — `learned_query_failures` içinde error_class
   IN ('missing_table', 'amb_column') olan kayıtlarda yeni tablo ismi
   geçiyorsa kayda not düşülür (pattern_hint) ve recurrence_count >=3
   eşiği reset edilir (admin tekrar görmeli).

Public API
----------
    integrate_new_tables(source, vyra_conn, *, dry_run=False, auto_synthetic=True,
                         auto_codevalues=True, auto_reflag_failures=True,
                         max_new_tables=100) -> IntegrationSummary
    detect_new_tables(source, vyra_conn) -> List[(schema, table)]
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# DTO
# ─────────────────────────────────────────────────────────────

@dataclass
class IntegrationSummary:
    source_id: int
    added_tables: List[str] = field(default_factory=list)        # "schema.table"
    new_relationships: int = 0
    cardinality_analyzed: int = 0
    samples_collected: int = 0
    code_values_added: int = 0
    synthetic_generated: int = 0
    reflagged_failures: int = 0
    dry_run: bool = False
    elapsed_ms: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────
# Remote-side fetch
# ─────────────────────────────────────────────────────────────

def _fetch_remote_tables(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Remote DB'den (data source) tüm tablo+view'ları okur.

    Returns: [{"schema": str, "name": str, "type": "table"|"view"}, ...]
    """
    from app.services.ds_learning_service import (
        _get_db_connector, _decrypt_password,
    )
    password = _decrypt_password(source.get("db_password_encrypted", ""))
    db_conn = None
    out: List[Dict[str, Any]] = []
    try:
        db_conn, dialect = _get_db_connector(source, password)
        cur = db_conn.cursor()
        if dialect == "postgresql":
            cur.execute("""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
                ORDER BY table_schema, table_name
            """)
            for r in cur.fetchall():
                sch = r[0] if not hasattr(r, "get") else r["table_schema"]
                tbl = r[1] if not hasattr(r, "get") else r["table_name"]
                typ = r[2] if not hasattr(r, "get") else r["table_type"]
                out.append({
                    "schema": (sch or "").strip(),
                    "name": (tbl or "").strip(),
                    "type": "view" if (typ and "VIEW" in str(typ).upper()) else "table",
                })
        elif dialect == "mssql":
            cur.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA NOT IN ('sys','INFORMATION_SCHEMA')
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """)
            for r in cur.fetchall():
                sch = r[0] if not hasattr(r, "get") else r["TABLE_SCHEMA"]
                tbl = r[1] if not hasattr(r, "get") else r["TABLE_NAME"]
                typ = r[2] if not hasattr(r, "get") else r["TABLE_TYPE"]
                out.append({
                    "schema": (sch or "").strip(),
                    "name": (tbl or "").strip(),
                    "type": "view" if (typ and "VIEW" in str(typ).upper()) else "table",
                })
        elif dialect == "oracle":
            cur.execute("""
                SELECT owner, table_name, 'TABLE' AS object_type FROM all_tables
                WHERE owner NOT IN ('SYS','SYSTEM','OUTLN','DBSNMP','XDB','CTXSYS')
                UNION ALL
                SELECT owner, view_name, 'VIEW' FROM all_views
                WHERE owner NOT IN ('SYS','SYSTEM','OUTLN','DBSNMP','XDB','CTXSYS')
            """)
            for r in cur.fetchall():
                sch = r[0] if not hasattr(r, "get") else r["OWNER"]
                tbl = r[1] if not hasattr(r, "get") else r["TABLE_NAME"]
                typ = r[2] if not hasattr(r, "get") else r["OBJECT_TYPE"]
                out.append({
                    "schema": (sch or "").strip(),
                    "name": (tbl or "").strip(),
                    "type": "view" if (typ and "VIEW" in str(typ).upper()) else "table",
                })
        elif dialect == "mysql":
            db_name = source.get("db_name") or ""
            cur.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = %s
            """, (db_name,))
            for r in cur.fetchall():
                sch = r[0] if not hasattr(r, "get") else r["TABLE_SCHEMA"]
                tbl = r[1] if not hasattr(r, "get") else r["TABLE_NAME"]
                typ = r[2] if not hasattr(r, "get") else r["TABLE_TYPE"]
                out.append({
                    "schema": (sch or "").strip(),
                    "name": (tbl or "").strip(),
                    "type": "view" if (typ and "VIEW" in str(typ).upper()) else "table",
                })
    except Exception as exc:
        logger.exception("[incremental] remote fetch failed source_id=%s", source.get("id"))
        raise
    finally:
        if db_conn is not None:
            try:
                db_conn.close()
            except Exception:
                pass
    return out


def _fetch_remote_columns_for_tables(
    source: Dict[str, Any],
    new_tables: Set[Tuple[str, str]],
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    """Yeni tablolar için kolon listesi + PK işareti çek (PG/MSSQL/Oracle)."""
    from app.services.ds_learning_service import (
        _get_db_connector, _decrypt_password,
    )
    if not new_tables:
        return {}
    password = _decrypt_password(source.get("db_password_encrypted", ""))
    out: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    db_conn = None
    try:
        db_conn, dialect = _get_db_connector(source, password)
        cur = db_conn.cursor()
        # Toplu çekip Python tarafında filtrele (basit + dialect-portable)
        if dialect == "postgresql":
            cur.execute("""
                SELECT table_schema, table_name, column_name, data_type,
                       is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
                ORDER BY table_schema, table_name, ordinal_position
            """)
            for r in cur.fetchall():
                sch = (r[0] or "").strip()
                tbl = (r[1] or "").strip()
                key = (sch, tbl)
                if key not in new_tables:
                    continue
                out.setdefault(key, []).append({
                    "name": r[2],
                    "data_type": r[3],
                    "is_nullable": (r[4] == "YES"),
                    "default_val": str(r[5]) if r[5] else None,
                    "is_pk": False,
                })
            # PK işareti
            cur.execute("""
                SELECT tc.table_schema, tc.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                   AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
            """)
            for r in cur.fetchall():
                key = ((r[0] or "").strip(), (r[1] or "").strip())
                if key not in new_tables or key not in out:
                    continue
                for c in out[key]:
                    if c["name"] == r[2]:
                        c["is_pk"] = True
        else:
            # MSSQL/Oracle/MySQL — basit fallback: column list yine info_schema'dan
            # PK ayrımı dialect-specific olduğundan burada is_pk=False kalır.
            try:
                cur.execute("""
                    SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE,
                           IS_NULLABLE, COLUMN_DEFAULT
                    FROM INFORMATION_SCHEMA.COLUMNS
                """)
                for r in cur.fetchall():
                    sch = (r[0] or "").strip()
                    tbl = (r[1] or "").strip()
                    key = (sch, tbl)
                    if key not in new_tables:
                        continue
                    out.setdefault(key, []).append({
                        "name": r[2],
                        "data_type": r[3],
                        "is_nullable": (str(r[4]).upper() == "YES"),
                        "default_val": str(r[5]) if r[5] else None,
                        "is_pk": False,
                    })
            except Exception as exc:
                logger.debug("[incremental] non-PG column fetch failed: %s", exc)
    except Exception:
        logger.exception("[incremental] remote columns fetch failed")
        raise
    finally:
        if db_conn is not None:
            try:
                db_conn.close()
            except Exception:
                pass
    return out


# ─────────────────────────────────────────────────────────────
# Vyra-side diff + insert
# ─────────────────────────────────────────────────────────────

def _fetch_existing_table_keys(vyra_conn, source_id: int) -> Set[Tuple[str, str]]:
    """ds_db_objects'tan mevcut (schema, name) anahtarlarını topla."""
    cur = vyra_conn.cursor()
    try:
        cur.execute(
            """
            SELECT COALESCE(schema_name, ''), object_name
            FROM ds_db_objects
            WHERE source_id = %s
            """,
            (source_id,),
        )
        return {((r[0] or "").strip(), (r[1] or "").strip()) for r in cur.fetchall() or []}
    finally:
        cur.close()


def detect_new_tables(source: Dict[str, Any], vyra_conn) -> List[Tuple[str, str, str]]:
    """Remote DB'de olup ds_db_objects'ta olmayan tabloları döndür.

    Returns: [(schema, table, type), ...]
    """
    remote = _fetch_remote_tables(source)
    existing = _fetch_existing_table_keys(vyra_conn, source["id"])
    out: List[Tuple[str, str, str]] = []
    for t in remote:
        key = (t["schema"], t["name"])
        if not t["name"]:
            continue
        if key in existing:
            continue
        out.append((t["schema"], t["name"], t["type"]))
    return out


def _insert_new_objects(
    vyra_conn,
    source_id: int,
    new_tables: List[Tuple[str, str, str]],
    columns_by_key: Dict[Tuple[str, str], List[Dict[str, Any]]],
) -> int:
    """Yeni tabloları ds_db_objects'a INSERT et (idempotent ON CONFLICT DO NOTHING)."""
    if not new_tables:
        return 0
    cur = vyra_conn.cursor()
    inserted = 0
    try:
        for schema, name, obj_type in new_tables:
            cols = columns_by_key.get((schema, name)) or []
            try:
                cur.execute(
                    """
                    INSERT INTO ds_db_objects
                        (source_id, schema_name, object_name, object_type,
                         column_count, row_count_estimate, columns_json)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        source_id, schema or None, name, obj_type,
                        len(cols), 0, json.dumps(cols),
                    ),
                )
                if (cur.rowcount or 0) > 0:
                    inserted += 1
            except Exception as exc:
                logger.warning(
                    "[incremental] insert object skipped %s.%s: %s", schema, name, exc,
                )
    finally:
        cur.close()
    return inserted


# ─────────────────────────────────────────────────────────────
# Re-flag missing_table / amb_column failures (re-eligibility)
# ─────────────────────────────────────────────────────────────

def _reflag_missing_table_failures(
    vyra_conn,
    source_id: int,
    new_table_names: Set[str],
) -> int:
    """Yeni tablo eklendiğinde, 'missing_table' veya 'amb_column' kategorisindeki
    eski failure kayıtlarını incelemeye geri al.

    Yöntem: error_message veya failed_sql içinde yeni tablo ismi geçen kayıtların
    recurrence_count'unu 1'e indir (admin'in tekrar incelemesi gerekecek).
    pattern_hint'e "[Yeni tablo: <name>] LLM tekrar denesin" notu eklenir.
    """
    if not new_table_names:
        return 0
    cur = vyra_conn.cursor()
    updated = 0
    try:
        for t in new_table_names:
            try:
                cur.execute(
                    """
                    UPDATE learned_query_failures
                    SET recurrence_count = 1,
                        pattern_hint = COALESCE(pattern_hint || ' | ', '')
                                       || %s
                    WHERE source_id = %s
                      AND admin_approved = FALSE
                      AND error_class IN ('missing_table','amb_column','unknown')
                      AND (
                            error_message ILIKE %s
                         OR failed_sql ILIKE %s
                         OR question ILIKE %s
                      )
                    """,
                    (
                        f"[Yeni tablo: {t}] LLM tekrar denesin",
                        source_id,
                        f"%{t}%", f"%{t}%", f"%{t}%",
                    ),
                )
                updated += (cur.rowcount or 0)
            except Exception as exc:
                logger.debug("[incremental] reflag failed for %s: %s", t, exc)
    finally:
        cur.close()
    return updated


# ─────────────────────────────────────────────────────────────
# Observability — pipeline_events
# ─────────────────────────────────────────────────────────────

def _log_integration_event(
    vyra_conn,
    source_id: int,
    company_id: Optional[int],
    summary: IntegrationSummary,
) -> None:
    cur = vyra_conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO pipeline_events
                (event_type, source_id, company_id, metadata, created_at)
            VALUES ('schema_incremental_integration', %s, %s, %s::jsonb, NOW())
            """,
            (source_id, company_id, json.dumps(summary.to_dict(), default=str)),
        )
    except Exception as exc:
        logger.debug("[incremental] pipeline_events insert skipped: %s", exc)
    finally:
        cur.close()


# ─────────────────────────────────────────────────────────────
# Public orchestrator
# ─────────────────────────────────────────────────────────────

def integrate_new_tables(
    source: Dict[str, Any],
    vyra_conn,
    *,
    dry_run: bool = False,
    auto_synthetic: bool = True,
    auto_codevalues: bool = True,
    auto_reflag_failures: bool = True,
    max_new_tables: int = 100,
) -> Dict[str, Any]:
    """Schema'da yeni eklenen tabloları keşfedip downstream pipeline'a entegre et.

    Akış:
        1. Remote DB'den fresh tablo listesi
        2. Diff (ds_db_objects vs fresh)
        3. (dry_run değilse) yeni tabloları ds_db_objects'a INSERT (enrichment kaybı YOK)
        4. _refresh_relationships_for_tables — yeni tablonun MEVCUT tablolarla
           olan FK'ları otomatik bulunur (en kritik adım)
        5. cardinality_analyzer.analyze_relationships — junction global etkilenir
        6. (opsiyonel) fk_synthetic_generator.generate_for_source skip_existing=True
        7. (opsiyonel) code_value_extractor.extract_from_samples
        8. (opsiyonel) learned_query_failures re-flag
        9. pipeline_events INSERT
    """
    t0 = time.time()
    source_id = int(source["id"])
    company_id = source.get("company_id")
    summary = IntegrationSummary(source_id=source_id, dry_run=dry_run)

    # 1+2: Diff
    try:
        new_tables = detect_new_tables(source, vyra_conn)
    except Exception as exc:
        summary.errors.append(f"detect_new_tables: {type(exc).__name__}: {str(exc)[:200]}")
        summary.elapsed_ms = int((time.time() - t0) * 1000)
        return summary.to_dict()

    if not new_tables:
        summary.elapsed_ms = int((time.time() - t0) * 1000)
        logger.info("[incremental] source_id=%s yeni tablo yok", source_id)
        return summary.to_dict()

    # max_new_tables cap (latency koruma)
    new_tables = new_tables[:max_new_tables]
    summary.added_tables = [
        f"{s}.{t}".strip(".") for (s, t, _typ) in new_tables
    ]

    if dry_run:
        summary.elapsed_ms = int((time.time() - t0) * 1000)
        return summary.to_dict()

    # 3: Yeni tablolar için kolon fetch + INSERT
    new_keys: Set[Tuple[str, str]] = {(s, t) for (s, t, _typ) in new_tables}
    try:
        columns_by_key = _fetch_remote_columns_for_tables(source, new_keys)
    except Exception as exc:
        summary.errors.append(f"fetch_columns: {type(exc).__name__}: {str(exc)[:200]}")
        columns_by_key = {}

    try:
        ins = _insert_new_objects(vyra_conn, source_id, new_tables, columns_by_key)
        vyra_conn.commit()
        logger.info("[incremental] source_id=%s %d yeni obje insert", source_id, ins)
    except Exception as exc:
        try:
            vyra_conn.rollback()
        except Exception:
            pass
        summary.errors.append(f"insert_objects: {type(exc).__name__}: {str(exc)[:200]}")

    # 4: FK relink — mevcut tablolarla olan ilişkileri yakala
    try:
        from app.services.ds_learning_service import _refresh_relationships_for_tables
        before_count = _count_relationships(vyra_conn, source_id)
        _refresh_relationships_for_tables(
            vyra_conn, source, source_id,
            {t for (_s, t, _typ) in new_tables},
        )
        after_count = _count_relationships(vyra_conn, source_id)
        summary.new_relationships = max(0, after_count - before_count)
    except Exception as exc:
        summary.errors.append(f"relink_fk: {type(exc).__name__}: {str(exc)[:200]}")

    # 5: Cardinality re-analyze (TÜM source — junction global)
    try:
        from app.services.db_learning.cardinality_analyzer import analyze_relationships
        cur = vyra_conn.cursor()
        try:
            card_result = analyze_relationships(cur, source_id)
            vyra_conn.commit()
            summary.cardinality_analyzed = int(card_result.get("analyzed", 0))
        finally:
            cur.close()
    except Exception as exc:
        try:
            vyra_conn.rollback()
        except Exception:
            pass
        summary.errors.append(f"cardinality: {type(exc).__name__}: {str(exc)[:200]}")

    # 6: Synthetic queries (yeni FK'lar için)
    if auto_synthetic and summary.new_relationships > 0:
        try:
            from app.services.db_learning.fk_synthetic_generator import (
                generate_for_source,
            )
            cur = vyra_conn.cursor()
            try:
                synth = generate_for_source(
                    cur,
                    source_id,
                    dialect=(source.get("db_type") or "postgresql").lower(),
                    company_id=company_id,
                    skip_existing=True,
                )
                vyra_conn.commit()
                # GenerationSummary dataclass — .success = öğretilen sentetik sayısı
                summary.synthetic_generated = int(getattr(synth, "success", 0) or 0)
            finally:
                cur.close()
        except Exception as exc:
            try:
                vyra_conn.rollback()
            except Exception:
                pass
            summary.errors.append(f"synthetic: {type(exc).__name__}: {str(exc)[:200]}")

    # 7: Code values (yeni tablo sample'lar için — sample'lar varsa)
    if auto_codevalues:
        try:
            from app.services.db_learning.code_value_extractor import extract_from_samples
            cur = vyra_conn.cursor()
            try:
                cv = extract_from_samples(cur, source_id, company_id)
                vyra_conn.commit()
                summary.code_values_added = int(cv.get("values_upserted", 0))
            finally:
                cur.close()
        except Exception as exc:
            try:
                vyra_conn.rollback()
            except Exception:
                pass
            summary.errors.append(f"code_values: {type(exc).__name__}: {str(exc)[:200]}")

    # 8: Re-flag missing_table failures
    if auto_reflag_failures:
        try:
            reflagged = _reflag_missing_table_failures(
                vyra_conn, source_id,
                {t for (_s, t, _typ) in new_tables},
            )
            vyra_conn.commit()
            summary.reflagged_failures = reflagged
        except Exception as exc:
            try:
                vyra_conn.rollback()
            except Exception:
                pass
            summary.errors.append(f"reflag_failures: {type(exc).__name__}: {str(exc)[:200]}")

    # 9: Observability
    try:
        _log_integration_event(vyra_conn, source_id, company_id, summary)
        vyra_conn.commit()
    except Exception:
        pass

    summary.elapsed_ms = int((time.time() - t0) * 1000)
    logger.info(
        "[incremental] source_id=%s tamamlandı: %d tablo, %d FK, %d synth, %d cv, %d reflag (%dms)",
        source_id, len(summary.added_tables), summary.new_relationships,
        summary.synthetic_generated, summary.code_values_added,
        summary.reflagged_failures, summary.elapsed_ms,
    )
    return summary.to_dict()


def _count_relationships(vyra_conn, source_id: int) -> int:
    cur = vyra_conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM ds_db_relationships WHERE source_id = %s", (source_id,))
        row = cur.fetchone()
        return int(row[0] if row else 0)
    except Exception:
        return 0
    finally:
        cur.close()


__all__ = [
    "IntegrationSummary",
    "detect_new_tables",
    "integrate_new_tables",
]
