"""
VYRA - DS Learning Service
============================
Veri kaynağı keşif ve öğrenme pipeline servisi.
3 aşamalı: Technology → Objects → Samples

Version: 2.56.0
"""

import logging
import time
import json
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# =====================================================
# DB Bağlantı Yardımcıları
# =====================================================

def _get_db_connector(source: dict, password: str):
    """Kaynak bilgilerine göre DB bağlantı nesnesi döndürür."""
    db_type = source.get("db_type", "")
    host = source.get("host", "")
    port = source.get("port", 5432)
    db_name = source.get("db_name", "")
    db_user = source.get("db_user", "")

    if db_type == "postgresql":
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=host, port=port, dbname=db_name,
            user=db_user, password=password,
            connect_timeout=15
        )
        conn.autocommit = True
        return conn, "postgresql"

    elif db_type == "mssql":
        import pymssql
        conn = pymssql.connect(
            server=host, port=str(port), database=db_name,
            user=db_user, password=password,
            login_timeout=15, as_dict=True
        )
        return conn, "mssql"

    elif db_type == "mysql":
        import pymysql
        import pymysql.cursors
        conn = pymysql.connect(
            host=host, port=port, database=db_name,
            user=db_user, password=password,
            connect_timeout=15,
            cursorclass=pymysql.cursors.DictCursor
        )
        return conn, "mysql"

    elif db_type == "oracle":
        import cx_Oracle
        dsn = cx_Oracle.makedsn(host, port, service_name=db_name)
        conn = cx_Oracle.connect(user=db_user, password=password, dsn=dsn)
        return conn, "oracle"

    else:
        raise ValueError(f"Desteklenmeyen veritabanı tipi: {db_type}")


def _decrypt_password(encrypted: str) -> str:
    """Şifreli parolayı çözer."""
    if not encrypted:
        return ""
    if encrypted.startswith("b64:"):
        import base64
        return base64.b64decode(encrypted[4:]).decode()
    try:
        from app.core.encryption import decrypt_password
        return decrypt_password(encrypted)
    except Exception:
        return encrypted


# =====================================================
# Adım 1: Teknoloji Keşfi
# =====================================================

def discover_technology(source: dict, vyra_conn) -> dict:
    """
    Veritabanı teknolojisini keşfeder.
    - DB sürümü, şema listesi, genel bilgi
    """
    password = _decrypt_password(source.get("db_password_encrypted", ""))
    db_conn, db_dialect = _get_db_connector(source, password)
    start = time.time()

    try:
        cur = db_conn.cursor()

        result = {
            "db_dialect": db_dialect,
            "db_version": "",
            "schemas": [],
            "character_set": "",
        }

        if db_dialect == "postgresql":
            cur.execute("SELECT version()")
            result["db_version"] = cur.fetchone()[0]

            cur.execute("""
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
                ORDER BY schema_name
            """)
            result["schemas"] = [r[0] for r in cur.fetchall()]

            cur.execute("SHOW server_encoding")
            result["character_set"] = cur.fetchone()[0]

        elif db_dialect == "mssql":
            cur.execute("SELECT @@VERSION")
            row = cur.fetchone()
            result["db_version"] = row[""] if isinstance(row, dict) else str(row)

            cur.execute("SELECT name FROM sys.schemas WHERE name NOT IN ('sys','INFORMATION_SCHEMA','guest') ORDER BY name")
            result["schemas"] = [r["name"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

        elif db_dialect == "mysql":
            cur.execute("SELECT VERSION()")
            row = cur.fetchone()
            result["db_version"] = row.get("VERSION()", "") if isinstance(row, dict) else str(row)

            cur.execute("SHOW DATABASES")
            result["schemas"] = [list(r.values())[0] if isinstance(r, dict) else r[0] for r in cur.fetchall()]

        elif db_dialect == "oracle":
            result["db_version"] = db_conn.version
            cur.execute("SELECT DISTINCT owner FROM all_tables WHERE owner NOT IN ('SYS','SYSTEM','OUTLN','DBSNMP') ORDER BY owner")
            result["schemas"] = [r[0] for r in cur.fetchall()]

        elapsed = int((time.time() - start) * 1000)
        result["elapsed_ms"] = elapsed

        db_conn.close()
        return {"success": True, "data": result}

    except Exception as e:
        try:
            db_conn.close()
        except Exception:
            pass
        logger.error(f"[DSLearning] Technology discovery error: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# Adım 2: Obje & İlişki Tespiti
# =====================================================

def detect_objects(source: dict, vyra_conn) -> dict:
    """
    Veritabanındaki tabloları, view'ları, sütunları ve FK ilişkilerini keşfeder.
    """
    password = _decrypt_password(source.get("db_password_encrypted", ""))
    db_conn, db_dialect = _get_db_connector(source, password)
    source_id = source["id"]
    start = time.time()

    try:
        cur = db_conn.cursor()
        objects = []
        relationships = []

        if db_dialect == "postgresql":
            # Tablolar & View'lar
            cur.execute("""
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
                ORDER BY table_schema, table_name
            """)
            tables = cur.fetchall()

            for row in tables:
                schema_name, table_name, table_type = row[0], row[1], row[2]
                obj_type = "table" if table_type == "BASE TABLE" else "view"

                # Sütunlar
                cur.execute("""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                """, (schema_name, table_name))
                columns = []
                for col in cur.fetchall():
                    columns.append({
                        "name": col[0],
                        "data_type": col[1],
                        "is_nullable": col[2] == "YES",
                        "default_val": str(col[3]) if col[3] else None
                    })

                # PK tespiti
                cur.execute("""
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                        AND tc.table_schema = %s AND tc.table_name = %s
                """, (schema_name, table_name))
                pk_cols = {r[0] for r in cur.fetchall()}
                for c in columns:
                    c["is_pk"] = c["name"] in pk_cols

                # Tahmini satır sayısı
                row_estimate = 0
                if obj_type == "table":
                    try:
                        cur.execute(f"""
                            SELECT reltuples::bigint FROM pg_class
                            WHERE oid = '{schema_name}.{table_name}'::regclass
                        """)
                        est = cur.fetchone()
                        row_estimate = max(0, est[0]) if est else 0
                    except Exception:
                        pass

                objects.append({
                    "schema_name": schema_name,
                    "object_name": table_name,
                    "object_type": obj_type,
                    "column_count": len(columns),
                    "row_count_estimate": row_estimate,
                    "columns_json": columns
                })

            # FK İlişkileri
            cur.execute("""
                SELECT
                    tc.table_schema AS from_schema,
                    tc.table_name AS from_table,
                    kcu.column_name AS from_column,
                    ccu.table_schema AS to_schema,
                    ccu.table_name AS to_table,
                    ccu.column_name AS to_column,
                    tc.constraint_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                    ON ccu.constraint_name = tc.constraint_name
                    AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_schema NOT IN ('pg_catalog','information_schema')
            """)
            for row in cur.fetchall():
                relationships.append({
                    "from_schema": row[0],
                    "from_table": row[1],
                    "from_column": row[2],
                    "to_schema": row[3],
                    "to_table": row[4],
                    "to_column": row[5],
                    "constraint_name": row[6]
                })

        elif db_dialect == "mssql":
            cur.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE IN ('BASE TABLE','VIEW')
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """)
            tables = cur.fetchall()

            for row in tables:
                schema_name = row["TABLE_SCHEMA"] if isinstance(row, dict) else row[0]
                table_name = row["TABLE_NAME"] if isinstance(row, dict) else row[1]
                table_type = row["TABLE_TYPE"] if isinstance(row, dict) else row[2]
                obj_type = "table" if table_type == "BASE TABLE" else "view"

                cur.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                """, (schema_name, table_name))
                columns = []
                for col in cur.fetchall():
                    cn = col["COLUMN_NAME"] if isinstance(col, dict) else col[0]
                    dt = col["DATA_TYPE"] if isinstance(col, dict) else col[1]
                    nullable = col["IS_NULLABLE"] if isinstance(col, dict) else col[2]
                    default = col["COLUMN_DEFAULT"] if isinstance(col, dict) else col[3]
                    columns.append({
                        "name": cn, "data_type": dt,
                        "is_nullable": nullable == "YES",
                        "default_val": str(default) if default else None,
                        "is_pk": False
                    })

                objects.append({
                    "schema_name": schema_name,
                    "object_name": table_name,
                    "object_type": obj_type,
                    "column_count": len(columns),
                    "row_count_estimate": 0,
                    "columns_json": columns
                })

        elif db_dialect == "mysql":
            db_name = source.get("db_name", "")
            cur.execute("""
                SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME
            """, (db_name,))
            tables = cur.fetchall()

            for row in tables:
                table_name = row.get("TABLE_NAME", "") if isinstance(row, dict) else row[0]
                table_type = row.get("TABLE_TYPE", "") if isinstance(row, dict) else row[1]
                table_rows = row.get("TABLE_ROWS", 0) if isinstance(row, dict) else row[2]
                obj_type = "table" if table_type == "BASE TABLE" else "view"

                cur.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                """, (db_name, table_name))
                columns = []
                for col in cur.fetchall():
                    cn = col.get("COLUMN_NAME", "") if isinstance(col, dict) else col[0]
                    dt = col.get("DATA_TYPE", "") if isinstance(col, dict) else col[1]
                    nullable = col.get("IS_NULLABLE", "") if isinstance(col, dict) else col[2]
                    default = col.get("COLUMN_DEFAULT", None) if isinstance(col, dict) else col[3]
                    key = col.get("COLUMN_KEY", "") if isinstance(col, dict) else col[4]
                    columns.append({
                        "name": cn, "data_type": dt,
                        "is_nullable": nullable == "YES",
                        "default_val": str(default) if default else None,
                        "is_pk": key == "PRI"
                    })

                objects.append({
                    "schema_name": db_name,
                    "object_name": table_name,
                    "object_type": obj_type,
                    "column_count": len(columns),
                    "row_count_estimate": table_rows or 0,
                    "columns_json": columns
                })

        elapsed = int((time.time() - start) * 1000)
        db_conn.close()

        # VYRA DB'ye kaydet
        vyra_cur = vyra_conn.cursor()

        # Eski objeleri temizle
        vyra_cur.execute("DELETE FROM ds_db_samples WHERE source_id = %s", (source_id,))
        vyra_cur.execute("DELETE FROM ds_db_objects WHERE source_id = %s", (source_id,))
        vyra_cur.execute("DELETE FROM ds_db_relationships WHERE source_id = %s", (source_id,))

        for obj in objects:
            vyra_cur.execute("""
                INSERT INTO ds_db_objects
                    (source_id, schema_name, object_name, object_type, column_count, row_count_estimate, columns_json)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                source_id, obj["schema_name"], obj["object_name"],
                obj["object_type"], obj["column_count"],
                obj["row_count_estimate"], json.dumps(obj["columns_json"])
            ))

        for rel in relationships:
            vyra_cur.execute("""
                INSERT INTO ds_db_relationships
                    (source_id, from_schema, from_table, from_column, to_schema, to_table, to_column, constraint_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                source_id, rel["from_schema"], rel["from_table"], rel["from_column"],
                rel["to_schema"], rel["to_table"], rel["to_column"], rel["constraint_name"]
            ))

        vyra_conn.commit()

        return {
            "success": True,
            "data": {
                "table_count": sum(1 for o in objects if o["object_type"] == "table"),
                "view_count": sum(1 for o in objects if o["object_type"] == "view"),
                "relationship_count": len(relationships),
                "total_columns": sum(o["column_count"] for o in objects),
                "elapsed_ms": elapsed
            }
        }

    except Exception as e:
        try:
            db_conn.close()
        except Exception:
            pass
        logger.error(f"[DSLearning] Object detection error: {e}")
        return {"success": False, "error": str(e)}


# =====================================================
# Adım 3: Örnek Veri Toplama
# =====================================================

def collect_samples(source: dict, vyra_conn, max_rows: int = 10) -> dict:
    """
    Keşfedilen tablolardan örnek SELECT sorguları hazırlayıp çalıştırır.
    """
    password = _decrypt_password(source.get("db_password_encrypted", ""))
    db_conn, db_dialect = _get_db_connector(source, password)
    source_id = source["id"]
    start = time.time()

    try:
        # VYRA DB'den keşfedilmiş objeleri al
        vyra_cur = vyra_conn.cursor()
        vyra_cur.execute("""
            SELECT id, schema_name, object_name, object_type
            FROM ds_db_objects
            WHERE source_id = %s AND object_type = 'table'
            ORDER BY object_name
        """, (source_id,))
        db_objects = vyra_cur.fetchall()

        if not db_objects:
            return {"success": False, "error": "Önce obje tespiti yapılmalı (detect-objects)"}

        target_cur = db_conn.cursor()
        total_sampled = 0
        failed_tables = []

        # Eski sample'ları temizle
        vyra_cur.execute("DELETE FROM ds_db_samples WHERE source_id = %s", (source_id,))

        for obj_row in db_objects:
            obj_id = obj_row["id"] if isinstance(obj_row, dict) else obj_row[0]
            schema_name = obj_row["schema_name"] if isinstance(obj_row, dict) else obj_row[1]
            object_name = obj_row["object_name"] if isinstance(obj_row, dict) else obj_row[2]

            # Güvenli tablo adı — sadece alfanümerik ve underscore
            safe_name = object_name.replace("'", "").replace(";", "")
            safe_schema = (schema_name or "").replace("'", "").replace(";", "")

            if db_dialect == "postgresql":
                fqn = f'"{safe_schema}"."{safe_name}"' if safe_schema else f'"{safe_name}"'
                query = f"SELECT * FROM {fqn} LIMIT {max_rows}"
            elif db_dialect == "mssql":
                fqn = f"[{safe_schema}].[{safe_name}]" if safe_schema else f"[{safe_name}]"
                query = f"SELECT TOP {max_rows} * FROM {fqn}"
            elif db_dialect == "mysql":
                query = f"SELECT * FROM `{safe_name}` LIMIT {max_rows}"
            elif db_dialect == "oracle":
                fqn = f'"{safe_schema}"."{safe_name}"' if safe_schema else f'"{safe_name}"'
                query = f"SELECT * FROM {fqn} WHERE ROWNUM <= {max_rows}"
            else:
                continue

            try:
                target_cur.execute(query)

                # Sütun isimlerini al
                col_names = [desc[0] for desc in target_cur.description] if target_cur.description else []
                rows = target_cur.fetchall()

                sample_data = []
                for r in rows:
                    if isinstance(r, dict):
                        # dict cursor
                        row_dict = {}
                        for k, v in r.items():
                            row_dict[k] = _serialize_value(v)
                        sample_data.append(row_dict)
                    else:
                        # tuple cursor
                        row_dict = {}
                        for i, val in enumerate(r):
                            col_name = col_names[i] if i < len(col_names) else f"col_{i}"
                            row_dict[col_name] = _serialize_value(val)
                        sample_data.append(row_dict)

                # VYRA DB'ye kaydet
                vyra_cur.execute("""
                    INSERT INTO ds_db_samples (object_id, source_id, sample_query, sample_data, row_count)
                    VALUES (%s, %s, %s, %s, %s)
                """, (obj_id, source_id, query, json.dumps(sample_data, default=str), len(sample_data)))
                total_sampled += 1

            except Exception as table_err:
                failed_tables.append({"table": object_name, "error": str(table_err)[:200]})
                continue

        vyra_conn.commit()
        elapsed = int((time.time() - start) * 1000)
        db_conn.close()

        return {
            "success": True,
            "data": {
                "tables_sampled": total_sampled,
                "tables_failed": len(failed_tables),
                "failed_details": failed_tables[:10],
                "elapsed_ms": elapsed
            }
        }

    except Exception as e:
        try:
            db_conn.close()
        except Exception:
            pass
        logger.error(f"[DSLearning] Sample collection error: {e}")
        return {"success": False, "error": str(e)}


def _serialize_value(val):
    """DB değerini JSON-safe formata çevirir."""
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    if isinstance(val, (datetime,)):
        return val.isoformat()
    if isinstance(val, bytes):
        return f"<binary {len(val)} bytes>"
    if isinstance(val, (list, dict)):
        return val
    return str(val)


# =====================================================
# Job Yönetimi
# =====================================================

def create_job(vyra_conn, source_id: int, company_id: int, job_type: str, user_id: int = None) -> int:
    """Yeni keşif job kaydı oluşturur, ID döner."""
    cur = vyra_conn.cursor()
    cur.execute("""
        INSERT INTO ds_discovery_jobs (source_id, company_id, job_type, status, started_at, created_by)
        VALUES (%s, %s, %s, 'running', NOW(), %s)
        RETURNING id
    """, (source_id, company_id, job_type, user_id))
    row = cur.fetchone()
    job_id = row["id"] if isinstance(row, dict) else row[0]
    vyra_conn.commit()
    return job_id


def complete_job(vyra_conn, job_id: int, result: dict):
    """Job'ı tamamlandı olarak işaretler."""
    cur = vyra_conn.cursor()
    status = "completed" if result.get("success") else "failed"
    elapsed = result.get("data", {}).get("elapsed_ms", 0) if result.get("success") else 0
    error_msg = result.get("error", "") if not result.get("success") else None
    summary = json.dumps(result.get("data", {}), default=str) if result.get("success") else None

    cur.execute("""
        UPDATE ds_discovery_jobs
        SET status = %s, completed_at = NOW(), duration_ms = %s,
            result_summary = %s, error_message = %s
        WHERE id = %s
    """, (status, elapsed, summary, error_msg, job_id))
    vyra_conn.commit()


def get_discovery_status(vyra_conn, source_id: int) -> dict:
    """Kaynağın tüm keşif adımlarının güncel durumunu döner."""
    cur = vyra_conn.cursor()

    # Her job_type için son kaydı al
    result = {}
    for jtype in ["technology", "objects", "samples"]:
        cur.execute("""
            SELECT id, status, result_summary, error_message, duration_ms, completed_at
            FROM ds_discovery_jobs
            WHERE source_id = %s AND job_type = %s
            ORDER BY created_at DESC LIMIT 1
        """, (source_id, jtype))
        row = cur.fetchone()
        if row:
            result[jtype] = {
                "job_id": row["id"],
                "status": row["status"],
                "result_summary": row["result_summary"],
                "error_message": row["error_message"],
                "duration_ms": row["duration_ms"],
                "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None
            }
        else:
            result[jtype] = {"status": "not_started"}

    # Obje sayıları
    cur.execute("SELECT COUNT(*) AS cnt FROM ds_db_objects WHERE source_id = %s", (source_id,))
    result["total_objects"] = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) AS cnt FROM ds_db_relationships WHERE source_id = %s", (source_id,))
    result["total_relationships"] = cur.fetchone()["cnt"]

    cur.execute("SELECT COUNT(*) AS cnt FROM ds_db_samples WHERE source_id = %s", (source_id,))
    result["total_samples"] = cur.fetchone()["cnt"]

    return result


def get_discovery_details(vyra_conn, source_id: int) -> dict:
    """Keşfedilmiş objelerin detaylı listesini döner."""
    cur = vyra_conn.cursor()

    # Objeler
    cur.execute("""
        SELECT id, schema_name, object_name, object_type, column_count, row_count_estimate, columns_json
        FROM ds_db_objects WHERE source_id = %s
        ORDER BY schema_name, object_name
    """, (source_id,))
    objects = []
    for row in cur.fetchall():
        objects.append({
            "id": row["id"], "schema_name": row["schema_name"], "object_name": row["object_name"],
            "object_type": row["object_type"], "column_count": row["column_count"],
            "row_count_estimate": row["row_count_estimate"], "columns": row["columns_json"]
        })

    # İlişkiler
    cur.execute("""
        SELECT from_schema, from_table, from_column, to_schema, to_table, to_column, constraint_name
        FROM ds_db_relationships WHERE source_id = %s
    """, (source_id,))
    rels = []
    for row in cur.fetchall():
        rels.append({
            "from_schema": row["from_schema"], "from_table": row["from_table"], "from_column": row["from_column"],
            "to_schema": row["to_schema"], "to_table": row["to_table"], "to_column": row["to_column"],
            "constraint_name": row["constraint_name"]
        })

    return {"objects": objects, "relationships": rels}


def get_learning_history(vyra_conn, source_id: int, limit: int = 20) -> list:
    """Keşif iş geçmişini döner."""
    cur = vyra_conn.cursor()
    cur.execute("""
        SELECT id, job_type, status, result_summary, error_message,
               duration_ms, started_at, completed_at
        FROM ds_discovery_jobs
        WHERE source_id = %s
        ORDER BY created_at DESC
        LIMIT %s
    """, (source_id, limit))

    history = []
    for row in cur.fetchall():
        history.append({
            "id": row["id"], "job_type": row["job_type"], "status": row["status"],
            "result_summary": row["result_summary"], "error_message": row["error_message"],
            "duration_ms": row["duration_ms"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None
        })
    return history


def get_learning_results(vyra_conn, source_id: int, content_type: str = None, limit: int = 50) -> dict:
    """ML pipeline'ın ürettiği öğrenme sonuçlarını (QA çiftleri) döner."""
    cur = vyra_conn.cursor()

    if content_type:
        cur.execute("""
            SELECT id, content_type, content_text, metadata, created_at
            FROM ds_learning_results
            WHERE source_id = %s AND content_type = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (source_id, content_type, limit))
    else:
        cur.execute("""
            SELECT id, content_type, content_text, metadata, created_at
            FROM ds_learning_results
            WHERE source_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """, (source_id, limit))

    results = []
    for row in cur.fetchall():
        meta = row["metadata"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        results.append({
            "id": row["id"],
            "content_type": row["content_type"],
            "content_text": row["content_text"],
            "question": meta.get("question", "") if meta else "",
            "table_name": meta.get("table_name", "") if meta else "",
            "metadata": meta,
            "created_at": row["created_at"].isoformat() if row["created_at"] else None
        })

    # Tip bazlı sayılar
    cur.execute("""
        SELECT content_type, COUNT(*) as cnt
        FROM ds_learning_results
        WHERE source_id = %s
        GROUP BY content_type
        ORDER BY cnt DESC
    """, (source_id,))
    type_counts = {}
    for row in cur.fetchall():
        type_counts[row["content_type"]] = row["cnt"]

    return {"results": results, "type_counts": type_counts, "total": sum(type_counts.values())}

# =====================================================
# Faz 2: Sentetik QA Üretimi (Template-Based)
# =====================================================

def generate_synthetic_qa(source_id: int, vyra_conn) -> dict:
    """
    Keşfedilen DB verilerinden template-based sentetik QA çiftleri üretir.
    Her QA çifti embedding'lenir ve ds_learning_results tablosuna yazılır.

    Üretilen içerik tipleri:
    - schema_description: Tablo yapısı açıklaması
    - relationship_map: Tablo ilişkileri
    - sample_insight: Örnek veri bilgisi
    - aggregate_query: SQL sorgu önerileri
    """
    start = time.time()
    cur = vyra_conn.cursor()

    # Embedding manager'ı al
    try:
        from app.services.rag.embedding import EmbeddingManager
        emb_mgr = EmbeddingManager()
    except Exception as e:
        logger.error(f"[DSLearning] EmbeddingManager yüklenemedi: {e}")
        return {"success": False, "error": f"Embedding modeli yüklenemedi: {e}"}

    # Keşfedilmiş objeleri al
    cur.execute("""
        SELECT id, schema_name, object_name, object_type, column_count,
               row_count_estimate, columns_json
        FROM ds_db_objects WHERE source_id = %s
        ORDER BY object_name
    """, (source_id,))
    objects = cur.fetchall()

    if not objects:
        return {"success": False, "error": "Önce obje tespiti yapılmalı"}

    # İlişkileri al
    cur.execute("""
        SELECT from_schema, from_table, from_column, to_schema, to_table, to_column
        FROM ds_db_relationships WHERE source_id = %s
    """, (source_id,))
    all_rels = cur.fetchall()

    # Sample verileri al
    cur.execute("""
        SELECT s.object_id, s.sample_data, s.row_count, o.object_name
        FROM ds_db_samples s
        JOIN ds_db_objects o ON s.object_id = o.id
        WHERE s.source_id = %s
    """, (source_id,))
    all_samples = {row["object_id"]: row for row in cur.fetchall()}

    # Eski QA sonuçlarını temizle
    cur.execute("DELETE FROM ds_learning_results WHERE source_id = %s", (source_id,))

    qa_count = 0
    total_pairs = []

    # 1) Schema Description QA'ları
    for obj in objects:
        obj_name = obj["object_name"]
        obj_type = obj["object_type"]
        schema = obj["schema_name"] or "public"
        col_count = obj["column_count"]
        row_est = obj["row_count_estimate"] or 0

        # Sütunları parse et
        cols_raw = obj["columns_json"]
        if isinstance(cols_raw, str):
            try:
                cols = json.loads(cols_raw)
            except Exception:
                cols = []
        else:
            cols = cols_raw or []

        # Sütun açıklamalarını oluştur
        col_descriptions = []
        pk_cols = []
        for c in cols[:20]:  # Max 20 sütun
            desc = f"{c['name']} ({c['data_type']})"
            if c.get("is_pk"):
                desc += " [PK]"
                pk_cols.append(c["name"])
            col_descriptions.append(desc)

        col_text = ", ".join(col_descriptions)

        # QA Pair 1: Tablo yapısı
        question = f"{obj_name} tablosu ne içerir? {obj_name} tablosunun yapısı nedir?"
        answer = (
            f"{schema}.{obj_name} ({obj_type}): "
            f"{col_count} sütun, yaklaşık {row_est} kayıt. "
            f"Sütunlar: {col_text}."
        )
        if pk_cols:
            answer += f" Primary Key: {', '.join(pk_cols)}."

        total_pairs.append({
            "content_type": "schema_description",
            "content_text": answer,
            "question_text": question,
            "object_name": obj_name
        })

        # QA Pair 2: Sütun sayısı
        question2 = f"{obj_name} tablosunda kaç sütun var? {obj_name} kaç alana sahip?"
        answer2 = f"{obj_name} tablosunda {col_count} sütun bulunmaktadır: {col_text}."
        total_pairs.append({
            "content_type": "schema_description",
            "content_text": answer2,
            "question_text": question2,
            "object_name": obj_name
        })

        # QA Pair 3: Kayıt sayısı
        if row_est > 0:
            question3 = f"{obj_name} tablosunda kaç kayıt var? {obj_name} ne kadar veri içeriyor?"
            answer3 = f"{obj_name} tablosunda yaklaşık {row_est} kayıt bulunmaktadır."
            total_pairs.append({
                "content_type": "schema_description",
                "content_text": answer3,
                "question_text": question3,
                "object_name": obj_name
            })

    # 2) İlişki QA'ları
    if all_rels:
        # Genel ilişki sorusu
        rel_descriptions = []
        for rel in all_rels[:30]:  # Max 30 ilişki
            rel_descriptions.append(
                f"{rel['from_table']}.{rel['from_column']} → {rel['to_table']}.{rel['to_column']}"
            )

        question_rel = "Tablolar arası ilişkiler nelerdir? Hangi tablolar birbiriyle bağlantılı?"
        answer_rel = f"Veritabanında {len(all_rels)} Foreign Key ilişkisi bulunmaktadır: " + "; ".join(rel_descriptions) + "."
        total_pairs.append({
            "content_type": "relationship_map",
            "content_text": answer_rel,
            "question_text": question_rel,
            "object_name": "_relationships"
        })

        # Tablo bazlı ilişki soruları
        rel_by_table = {}
        for rel in all_rels:
            rel_by_table.setdefault(rel["from_table"], []).append(rel)
            rel_by_table.setdefault(rel["to_table"], []).append(rel)

        for table_name, rels in rel_by_table.items():
            if len(rels) > 0:
                rel_text = "; ".join([
                    f"{r['from_table']}.{r['from_column']} → {r['to_table']}.{r['to_column']}"
                    for r in rels[:10]
                ])
                q = f"{table_name} tablosu hangi tablolarla ilişkili? {table_name} FK ilişkileri nelerdir?"
                a = f"{table_name} tablosu şu tablolarla ilişkilidir: {rel_text}."
                total_pairs.append({
                    "content_type": "relationship_map",
                    "content_text": a,
                    "question_text": q,
                    "object_name": table_name
                })

    # 3) Sample Insight QA'ları
    for obj in objects:
        obj_id = obj["id"]
        obj_name = obj["object_name"]
        sample = all_samples.get(obj_id)
        if not sample or not sample["sample_data"]:
            continue

        sample_data = sample["sample_data"]
        if isinstance(sample_data, str):
            try:
                sample_data = json.loads(sample_data)
            except Exception:
                continue

        if not sample_data or len(sample_data) == 0:
            continue

        # İlk 3 satırı göster
        sample_rows = sample_data[:3]
        sample_text_parts = []
        for i, row in enumerate(sample_rows):
            row_vals = ", ".join([f"{k}={v}" for k, v in list(row.items())[:8]])
            sample_text_parts.append(f"  Satır {i+1}: {row_vals}")

        sample_text = "\n".join(sample_text_parts)

        question_s = f"{obj_name} tablosunda ne tür veriler var? {obj_name} örnek veriler nelerdir?"
        answer_s = (
            f"{obj_name} tablosundan örnek veriler ({sample['row_count']} satır örneklendi):\n"
            f"{sample_text}"
        )
        total_pairs.append({
            "content_type": "sample_insight",
            "content_text": answer_s,
            "question_text": question_s,
            "object_name": obj_name
        })

    # 4) Aggregate Query önerileri
    for obj in objects:
        if obj["object_type"] != "table":
            continue
        obj_name = obj["object_name"]
        row_est = obj["row_count_estimate"] or 0
        schema = obj["schema_name"] or "public"

        question_agg = f"{obj_name} tablosunda kaç kayıt var? {obj_name} toplam satır sayısı nedir?"
        answer_agg = (
            f"{obj_name} tablosundaki kayıt sayısını bulmak için: "
            f"SELECT COUNT(*) FROM {schema}.{obj_name}; "
            f"Tahmini mevcut kayıt sayısı: {row_est}."
        )
        total_pairs.append({
            "content_type": "aggregate_query",
            "content_text": answer_agg,
            "question_text": question_agg,
            "object_name": obj_name
        })

    # Embedding üret ve DB'ye yaz
    if total_pairs:
        # Batch embedding
        all_texts = [f"{p['question_text']} {p['content_text']}" for p in total_pairs]
        batch_size = 50

        all_embeddings = []
        for i in range(0, len(all_texts), batch_size):
            batch = all_texts[i:i + batch_size]
            batch_embs = emb_mgr.get_embeddings_batch(batch)
            all_embeddings.extend(batch_embs)

        # DB'ye yaz
        for pair, embedding in zip(total_pairs, all_embeddings):
            cur.execute("""
                INSERT INTO ds_learning_results
                    (source_id, content_type, content_text, embedding, metadata, score)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                source_id,
                pair["content_type"],
                pair["content_text"],
                embedding,
                json.dumps({
                    "question": pair["question_text"],
                    "object_name": pair["object_name"]
                }),
                1.0  # Pre-computed, yüksek güvenilirlik
            ))
            qa_count += 1

        vyra_conn.commit()

    elapsed = int((time.time() - start) * 1000)
    logger.info(f"[DSLearning] Sentetik QA üretimi: {qa_count} çift, {elapsed}ms")

    return {
        "success": True,
        "data": {
            "qa_pairs_generated": qa_count,
            "schema_descriptions": sum(1 for p in total_pairs if p["content_type"] == "schema_description"),
            "relationship_maps": sum(1 for p in total_pairs if p["content_type"] == "relationship_map"),
            "sample_insights": sum(1 for p in total_pairs if p["content_type"] == "sample_insight"),
            "aggregate_queries": sum(1 for p in total_pairs if p["content_type"] == "aggregate_query"),
            "elapsed_ms": elapsed
        }
    }


# =====================================================
# Faz 2: DB Knowledge Arama (RAG Entegrasyonu)
# =====================================================

def search_db_knowledge(query: str, company_id: int = None, min_score: float = 0.35, max_results: int = 3) -> list:
    """
    Önceden öğrenilmiş DB bilgilerinde cosine similarity araması yapar.
    
    Args:
        query: Kullanıcı sorusu
        company_id: Firma filtresi (opsiyonel)
        min_score: Minimum benzerlik skoru
        max_results: Maksimum sonuç sayısı
    
    Returns:
        List[dict]: [{content, score, source_name, content_type, metadata}]
    """
    try:
        from app.services.rag.embedding import EmbeddingManager
        from app.services.rag import scoring
        from app.core.db import get_db_conn

        emb_mgr = EmbeddingManager()
        query_embedding = emb_mgr.get_embedding(query)

        conn = get_db_conn()
        try:
            cur = conn.cursor()

            # source_id'leri company filtresine göre bul
            if company_id:
                cur.execute("""
                    SELECT lr.id, lr.content_text, lr.embedding, lr.content_type, lr.metadata, lr.score AS base_score,
                           ds.name AS source_name
                    FROM ds_learning_results lr
                    JOIN data_sources ds ON lr.source_id = ds.id
                    WHERE ds.company_id = %s AND lr.embedding IS NOT NULL
                """, (company_id,))
            else:
                cur.execute("""
                    SELECT lr.id, lr.content_text, lr.embedding, lr.content_type, lr.metadata, lr.score AS base_score,
                           ds.name AS source_name
                    FROM ds_learning_results lr
                    JOIN data_sources ds ON lr.source_id = ds.id
                    WHERE lr.embedding IS NOT NULL
                """)

            rows = cur.fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        # Batch cosine similarity
        all_embeddings = []
        valid_rows = []
        for row in rows:
            emb = row["embedding"]
            if emb:
                all_embeddings.append(emb)
                valid_rows.append(row)

        if not all_embeddings:
            return []

        similarities = scoring.cosine_similarity_batch(query_embedding, all_embeddings)

        # Sonuçları skora göre sırala
        results = []
        for idx, row in enumerate(valid_rows):
            sim_score = similarities[idx]
            if sim_score >= min_score:
                meta = row["metadata"]
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}

                results.append({
                    "content": row["content_text"],
                    "score": round(float(sim_score), 4),
                    "source_name": f"DB: {row['source_name']}",
                    "content_type": row["content_type"],
                    "metadata": meta
                })

        # Skora göre sırala
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:max_results]

    except Exception as e:
        logger.error(f"[DSLearning] DB knowledge search error: {e}")
        return []


# =====================================================
# Faz 2: Tam Pipeline Çalıştırma
# =====================================================

def run_full_learning(source: dict, vyra_conn, user_id: int = None) -> dict:
    """
    4 adımlı tam öğrenme pipeline'ı:
    1. Teknoloji Keşfi
    2. Obje Tespiti
    3. Örnek Veri Toplama
    4. Sentetik QA Üretimi
    """
    source_id = source["id"]
    company_id = source.get("company_id", 1)
    results = {"steps": []}

    # Job oluştur
    job_id = create_job(vyra_conn, source_id, company_id, "full_learning", user_id)

    try:
        # Adım 1
        logger.info(f"[DSLearning] Full pipeline step 1/4: Technology for source {source_id}")
        r1 = discover_technology(source, vyra_conn)
        results["steps"].append({"step": "technology", "success": r1.get("success"), "data": r1.get("data")})
        if not r1.get("success"):
            raise Exception(f"Technology discovery failed: {r1.get('error')}")

        # Adım 2
        logger.info(f"[DSLearning] Full pipeline step 2/4: Objects for source {source_id}")
        r2 = detect_objects(source, vyra_conn)
        results["steps"].append({"step": "objects", "success": r2.get("success"), "data": r2.get("data")})
        if not r2.get("success"):
            raise Exception(f"Object detection failed: {r2.get('error')}")

        # Adım 3
        logger.info(f"[DSLearning] Full pipeline step 3/4: Samples for source {source_id}")
        r3 = collect_samples(source, vyra_conn)
        results["steps"].append({"step": "samples", "success": r3.get("success"), "data": r3.get("data")})
        if not r3.get("success"):
            raise Exception(f"Sample collection failed: {r3.get('error')}")

        # Adım 4
        logger.info(f"[DSLearning] Full pipeline step 4/4: Synthetic QA for source {source_id}")
        r4 = generate_synthetic_qa(source_id, vyra_conn)
        results["steps"].append({"step": "qa_generation", "success": r4.get("success"), "data": r4.get("data")})

        total_ms = sum(
            s.get("data", {}).get("elapsed_ms", 0)
            for s in results["steps"] if s.get("data")
        )
        results["total_elapsed_ms"] = total_ms
        results["success"] = True

        complete_job(vyra_conn, job_id, {
            "success": True, "data": {"elapsed_ms": total_ms, **results}
        })

        return results

    except Exception as e:
        logger.error(f"[DSLearning] Full pipeline error: {e}")
        results["success"] = False
        results["error"] = str(e)
        complete_job(vyra_conn, job_id, {"success": False, "error": str(e)})
        return results


# =====================================================
# Faz 2: Schedule Yönetimi
# =====================================================

def get_schedule(vyra_conn, source_id: int) -> dict:
    """Kaynağın öğrenme zamanlamasını döner."""
    cur = vyra_conn.cursor()
    cur.execute("""
        SELECT id, source_id, schedule_type, interval_value, is_active,
               last_run_at, next_run_at, created_at
        FROM ds_learning_schedules
        WHERE source_id = %s
        LIMIT 1
    """, (source_id,))
    row = cur.fetchone()
    if not row:
        return {"exists": False}

    last_run = row["last_run_at"]
    next_run = row["next_run_at"]

    # last_run_at boşsa, gerçek iş geçmişinden son çalışmayı al
    if not last_run:
        cur.execute("""
            SELECT MAX(completed_at) as last_completed
            FROM ds_discovery_jobs
            WHERE source_id = %s AND status = 'completed'
        """, (source_id,))
        fallback = cur.fetchone()
        if fallback and fallback["last_completed"]:
            last_run = fallback["last_completed"]
            # Schedule tablosunda da güncelle (bir kerelik sync)
            cur.execute(
                "UPDATE ds_learning_schedules SET last_run_at = %s WHERE source_id = %s",
                (last_run, source_id)
            )
            vyra_conn.commit()

    # next_run_at boşsa ve aktifse hesapla
    if not next_run and row["is_active"] and row["schedule_type"] != "manual_only" and last_run:
        from datetime import timedelta
        hours = row["interval_value"] or 24
        next_run = last_run + timedelta(hours=hours)
        cur.execute(
            "UPDATE ds_learning_schedules SET next_run_at = %s WHERE source_id = %s",
            (next_run, source_id)
        )
        vyra_conn.commit()

    return {
        "exists": True,
        "id": row["id"],
        "schedule_type": row["schedule_type"],
        "interval_hours": row["interval_value"],
        "is_active": row["is_active"],
        "last_run_at": last_run.isoformat() if last_run else None,
        "next_run_at": next_run.isoformat() if next_run else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None
    }


def upsert_schedule(vyra_conn, source_id: int, schedule_type: str,
                    interval_hours: int = None, is_active: bool = True) -> dict:
    """Schedule oluşturur veya günceller."""
    cur = vyra_conn.cursor()

    # Mevcut schedule var mı?
    cur.execute("SELECT id FROM ds_learning_schedules WHERE source_id = %s", (source_id,))
    existing = cur.fetchone()

    # next_run_at hesapla
    next_run = None
    if is_active and schedule_type != "manual_only":
        from datetime import timedelta
        hours = interval_hours or (24 if schedule_type == "daily" else 12)
        next_run = datetime.now(timezone.utc) + timedelta(hours=hours)

    if existing:
        cur.execute("""
            UPDATE ds_learning_schedules
            SET schedule_type = %s, interval_value = %s, is_active = %s, next_run_at = %s
            WHERE source_id = %s
        """, (schedule_type, interval_hours, is_active, next_run, source_id))
    else:
        cur.execute("""
            INSERT INTO ds_learning_schedules (source_id, schedule_type, interval_value, is_active, next_run_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (source_id, schedule_type, interval_hours, is_active, next_run))

    vyra_conn.commit()
    return {"success": True, "schedule_type": schedule_type, "is_active": is_active}

