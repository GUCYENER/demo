"""
VYRA - DS Learning Service
============================
Veri kaynağı keşif ve öğrenme pipeline servisi.
3 aşamalı: Technology → Objects → Samples

Version: 2.56.0
"""

import logging
import re
import time
import json

from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _safe_identifier(name):
    """Allow only alphanumeric, underscore, dot, space (for quoted identifiers)."""
    if not name:
        return ""
    cleaned = re.sub(r'[^\w\s.]', '', name)
    return cleaned


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

    # B1 guard v3.37.0 (ATHENA-BE defensive): _load_source upstream'inde
    # db_type normalize edilmeden gelen değerler (None / "" / literal "db_type")
    # downstream'de "Desteklenmeyen veritabanı tipi" mesajı veriyordu;
    # bu mesaj caller'ın gerçek hatasını gizliyor (kayıtlı rapor rerun yolu
    # için B1 root cause). Açıklayıcı hata mesajına çevir.
    if db_type in (None, "", "db_type"):
        raise ValueError(
            f"Geçersiz/normalleştirilmemiş db_type değeri: {db_type!r} — "
            "_load_source çağrısı kontrol edin"
        )

    # v3.37.1 Brief A (HERMES→ZEUS direct-apply 2026-05-26):
    # port int defensive — saved-report rerun yolunda literal "port" string'i
    # sızıyordu; psycopg2/oracledb ham hatası "invalid integer value 'port'
    # for connection option 'port'" kafa karıştırıcıydı. Açıklayıcı mesajla
    # erkenden raise et.
    if not isinstance(port, int):
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise ValueError(
                f"Geçersiz port değeri: {port!r} — int bekleniyor "
                f"(source_id={source.get('id')}, db_type={db_type!r})"
            )

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
        import oracledb
        from app.api.routes.data_sources_api import _init_oracle_thick_mode
        _init_oracle_thick_mode()
        dsn = oracledb.makedsn(host, port, service_name=db_name)
        conn = oracledb.connect(user=db_user, password=password, dsn=dsn)
        return conn, "oracle"

    else:
        raise ValueError(f"Desteklenmeyen veritabanı tipi: {db_type}")


def _decrypt_password(encrypted: str) -> str:
    """
    Şifreli parolayı çözer.

    Desteklenen formatlar:
    - "b64:<base64>"  → base64 decode
    - Diğer           → app.core.encryption.decrypt_password

    Hata durumunda şifreli metni asla düz metin olarak döndürmez;
    exception fırlatır (bağlantı daha açık bir hatayla başarısız olur).
    """
    if not encrypted:
        return ""
    if encrypted.startswith("b64:"):
        import base64 as _b64
        try:
            decoded = _b64.b64decode(encrypted[4:], validate=True).decode("utf-8")
            return decoded
        except Exception as e:
            from app.services.logging_service import log_error
            log_error(f"b64 parola çözme hatası: {e}", "ds_learning")
            raise ValueError(f"Parola çözme başarısız (geçersiz base64): {e}") from e
    try:
        from app.core.encryption import decrypt_password
        return decrypt_password(encrypted)
    except ImportError:
        from app.services.logging_service import log_error
        log_error("Şifreleme modülü bulunamadı (app.core.encryption)", "ds_learning")
        raise
    except Exception as e:
        from app.services.logging_service import log_error
        log_error(f"Parola çözme hatası: {e}", "ds_learning")
        raise ValueError(f"Parola çözme başarısız: {e}") from e


# =====================================================
# Adım 1: Teknoloji Keşfi
# =====================================================

def discover_technology(source: dict, vyra_conn) -> dict:
    """
    Veritabanı teknolojisini keşfeder.
    - DB sürümü, şema listesi, genel bilgi
    """
    start = time.time()
    db_conn = None

    try:
        password = _decrypt_password(source.get("db_password_encrypted", ""))
        db_conn, db_dialect = _get_db_connector(source, password)
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
            logger.info("[DSLearning] PG version: %s", result["db_version"][:80])

            # pg_catalog üzerinden schema listesi
            try:
                cur.execute("""
                    SELECT nspname FROM pg_catalog.pg_namespace
                    WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
                      AND nspname NOT LIKE 'pg_temp%%'
                      AND nspname NOT LIKE 'pg_toast_temp%%'
                    ORDER BY nspname
                """)
                result["schemas"] = [r[0] for r in cur.fetchall()]
                logger.info("[DSLearning] pg_namespace şema sayısı: %d, şemalar: %s",
                            len(result["schemas"]), result["schemas"][:10])
            except Exception as schema_err:
                logger.error("[DSLearning] Schema sorgusu hatası: %s — %s",
                             type(schema_err).__name__, str(schema_err)[:200])
                # Fallback: information_schema dene
                try:
                    cur.execute("""
                        SELECT schema_name FROM information_schema.schemata
                        WHERE schema_name NOT IN ('pg_catalog','information_schema','pg_toast')
                        ORDER BY schema_name
                    """)
                    result["schemas"] = [r[0] for r in cur.fetchall()]
                    logger.info("[DSLearning] Fallback schemata sonucu: %d", len(result["schemas"]))
                except Exception:
                    result["schemas"] = []

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
            cur.execute("""
                SELECT DISTINCT owner FROM all_tables
                WHERE owner NOT IN (
                    'SYS','SYSTEM','OUTLN','DBSNMP','XDB','CTXSYS','MDSYS',
                    'ORDDATA','ORDSYS','WMSYS','EXFSYS','OLAPSYS','DVSYS',
                    'LBACSYS','APEX_PUBLIC_USER','FLOWS_FILES','ANONYMOUS',
                    'APEX_040000','APEX_040200','APPQOSSYS','AUDSYS',
                    'GSMADMIN_INTERNAL','OJVMSYS','DVF','DBSFWUSER'
                )
                ORDER BY owner
            """)
            result["schemas"] = [r[0] for r in cur.fetchall()]
            logger.info("[DSLearning] Oracle schema sayısı: %d, schemalar: %s",
                        len(result["schemas"]), result["schemas"][:10])

        elapsed = int((time.time() - start) * 1000)
        result["elapsed_ms"] = elapsed

        db_conn.close()
        return {"success": True, "data": result}

    except Exception as e:
        try:
            db_conn.close()
        except Exception:
            pass
        logger.error("[DSLearning] Teknoloji keşfi sırasında hata oluştu: %s", str(e))
        return {"success": False, "error": "Veritabanı bağlantısı veya sorgulama sırasında güvenlik/iletişim hatası oluştu, lütfen logları inceleyin."}


# =====================================================
# Adım 2: Obje & İlişki Tespiti
# =====================================================

def detect_objects(source: dict, vyra_conn) -> dict:
    """
    Veritabanındaki tabloları, view'ları, sütunları ve FK ilişkilerini keşfeder.
    """
    source_id = source["id"]
    start = time.time()
    db_conn = None

    try:
        password = _decrypt_password(source.get("db_password_encrypted", ""))
        db_conn, db_dialect = _get_db_connector(source, password)
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

            # ── Toplu kolon sorgusu (N+1 yerine 1 sorgu) ──
            all_columns = {}  # key: (schema, table) → list of column dicts
            cur.execute("""
                SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
                ORDER BY table_schema, table_name, ordinal_position
            """)
            for col in cur.fetchall():
                key = (col[0] if isinstance(col, tuple) else col["table_schema"],
                       col[1] if isinstance(col, tuple) else col["table_name"])
                if key not in all_columns:
                    all_columns[key] = []
                col_name = col[2] if isinstance(col, tuple) else col["column_name"]
                data_type = col[3] if isinstance(col, tuple) else col["data_type"]
                is_nullable = col[4] if isinstance(col, tuple) else col["is_nullable"]
                default_val = col[5] if isinstance(col, tuple) else col["column_default"]
                all_columns[key].append({
                    "name": col_name,
                    "data_type": data_type,
                    "is_nullable": is_nullable == "YES",
                    "default_val": str(default_val) if default_val else None
                })

            # ── Toplu PK sorgusu (1 sorgu ile tüm PK'lar) ──
            all_pks = {}  # key: (schema, table) → set of column names
            cur.execute("""
                SELECT tc.table_schema, tc.table_name, kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema NOT IN ('pg_catalog','information_schema','pg_toast')
            """)
            for pk_row in cur.fetchall():
                key = (pk_row[0] if isinstance(pk_row, tuple) else pk_row["table_schema"],
                       pk_row[1] if isinstance(pk_row, tuple) else pk_row["table_name"])
                if key not in all_pks:
                    all_pks[key] = set()
                all_pks[key].add(pk_row[2] if isinstance(pk_row, tuple) else pk_row["column_name"])

            # ── Toplu satır tahmini (pg_stat_user_tables) ──
            row_estimates = {}
            cur.execute("""
                SELECT schemaname, relname, n_live_tup
                FROM pg_stat_user_tables
            """)
            for est_row in cur.fetchall():
                key = (est_row[0] if isinstance(est_row, tuple) else est_row["schemaname"],
                       est_row[1] if isinstance(est_row, tuple) else est_row["relname"])
                row_estimates[key] = est_row[2] if isinstance(est_row, tuple) else est_row["n_live_tup"]

            # ── Faz 2f: Native comment okuma (POSEIDON audit) ──
            # Kolon yorumları: col_description((schema.table)::regclass, ordinal_position)
            col_comments = {}  # (schema, table, column) → comment
            try:
                cur.execute("""
                    SELECT n.nspname AS schema_name, c.relname AS table_name,
                           a.attname AS column_name,
                           pg_catalog.col_description(a.attrelid, a.attnum) AS comment
                    FROM pg_catalog.pg_attribute a
                    JOIN pg_catalog.pg_class c ON c.oid = a.attrelid
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE a.attnum > 0 AND NOT a.attisdropped
                      AND c.relkind IN ('r','v','m','f','p')
                      AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
                """)
                for r in cur.fetchall():
                    schema_n = r[0] if isinstance(r, tuple) else r["schema_name"]
                    table_n  = r[1] if isinstance(r, tuple) else r["table_name"]
                    col_n    = r[2] if isinstance(r, tuple) else r["column_name"]
                    cmt      = r[3] if isinstance(r, tuple) else r["comment"]
                    if cmt:
                        col_comments[(schema_n, table_n, col_n)] = cmt
            except Exception as cmt_err:
                logger.warning(f"[Discovery][PG] col_description okuma hata: {cmt_err}")

            # Tablo yorumları: obj_description(c.oid)
            tbl_comments = {}
            try:
                cur.execute("""
                    SELECT n.nspname AS schema_name, c.relname AS table_name,
                           pg_catalog.obj_description(c.oid) AS comment
                    FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind IN ('r','v','m','f','p')
                      AND n.nspname NOT IN ('pg_catalog','information_schema','pg_toast')
                """)
                for r in cur.fetchall():
                    schema_n = r[0] if isinstance(r, tuple) else r["schema_name"]
                    table_n  = r[1] if isinstance(r, tuple) else r["table_name"]
                    cmt      = r[2] if isinstance(r, tuple) else r["comment"]
                    if cmt:
                        tbl_comments[(schema_n, table_n)] = cmt
            except Exception as cmt_err:
                logger.warning(f"[Discovery][PG] obj_description okuma hata: {cmt_err}")

            # ── Objeleri birleştir ──
            for row in tables:
                schema_name, table_name, table_type = row[0], row[1], row[2]
                obj_type = "table" if table_type == "BASE TABLE" else "view"

                key = (schema_name, table_name)
                columns = list(all_columns.get(key, []))

                # PK işaretle
                pk_cols = all_pks.get(key, set())
                for c in columns:
                    c["is_pk"] = c["name"] in pk_cols
                    # Faz 2f: native kolon yorumu
                    cmt = col_comments.get((schema_name, table_name, c["name"]))
                    if cmt:
                        c["comment"] = cmt

                # Tahmini satır sayısı
                row_estimate = 0
                if obj_type == "table":
                    row_estimate = max(0, row_estimates.get(key, 0))

                obj_entry = {
                    "schema_name": schema_name,
                    "object_name": table_name,
                    "object_type": obj_type,
                    "column_count": len(columns),
                    "row_count_estimate": row_estimate,
                    "columns_json": columns
                }
                # Faz 2f: native tablo yorumu
                t_cmt = tbl_comments.get((schema_name, table_name))
                if t_cmt:
                    obj_entry["description"] = t_cmt
                objects.append(obj_entry)

            # FK İlişkileri — pg_catalog üzerinden
            # information_schema.constraint_column_usage sadece constraint sahibine veri döndürür
            try:
                # Önce FK constraint sayısını kontrol et
                cur.execute("SELECT COUNT(*) FROM pg_catalog.pg_constraint WHERE contype = 'f'")
                fk_total = cur.fetchone()[0]
                logger.info("[DSLearning] pg_constraint FK sayısı: %d", fk_total)

                if fk_total > 0:
                    cur.execute("""
                        SELECT
                            ns_from.nspname     AS from_schema,
                            cl_from.relname     AS from_table,
                            att_from.attname    AS from_column,
                            ns_to.nspname       AS to_schema,
                            cl_to.relname       AS to_table,
                            att_to.attname      AS to_column,
                            con.conname         AS constraint_name
                        FROM pg_catalog.pg_constraint con
                        JOIN pg_catalog.pg_class cl_from     ON con.conrelid  = cl_from.oid
                        JOIN pg_catalog.pg_namespace ns_from ON cl_from.relnamespace = ns_from.oid
                        JOIN pg_catalog.pg_class cl_to       ON con.confrelid = cl_to.oid
                        JOIN pg_catalog.pg_namespace ns_to   ON cl_to.relnamespace = ns_to.oid
                        JOIN pg_catalog.pg_attribute att_from
                            ON att_from.attrelid = con.conrelid
                            AND att_from.attnum = ANY(con.conkey)
                        JOIN pg_catalog.pg_attribute att_to
                            ON att_to.attrelid = con.confrelid
                            AND att_to.attnum = ANY(con.confkey)
                        WHERE con.contype = 'f'
                          AND array_length(con.conkey, 1) = 1
                          AND ns_from.nspname NOT IN ('pg_catalog','information_schema')
                        ORDER BY ns_from.nspname, cl_from.relname, con.conname
                    """)
                    for row in cur.fetchall():
                        relationships.append({
                            "from_schema": row[0],
                            "from_table": row[1],
                            "from_column": row[2],
                            "to_schema": row[3],
                            "to_table": row[4],
                            "to_column": row[5],
                            "constraint_name": row[6],
                            # Tek-column FK → fk_position daima 1
                            "fk_position": 1,
                        })

                    # Composite FK'lar (multi-column) — ayrı sorgu
                    # v3.32.0: fk_position = idx (generate_subscripts sırası)
                    cur.execute("""
                        SELECT
                            ns_from.nspname,
                            cl_from.relname,
                            att_from.attname,
                            ns_to.nspname,
                            cl_to.relname,
                            att_to.attname,
                            con.conname,
                            idx AS fk_position
                        FROM pg_catalog.pg_constraint con
                        JOIN pg_catalog.pg_class cl_from     ON con.conrelid  = cl_from.oid
                        JOIN pg_catalog.pg_namespace ns_from ON cl_from.relnamespace = ns_from.oid
                        JOIN pg_catalog.pg_class cl_to       ON con.confrelid = cl_to.oid
                        JOIN pg_catalog.pg_namespace ns_to   ON cl_to.relnamespace = ns_to.oid
                        CROSS JOIN generate_subscripts(con.conkey, 1) AS idx
                        JOIN pg_catalog.pg_attribute att_from
                            ON att_from.attrelid = con.conrelid
                            AND att_from.attnum = con.conkey[idx]
                        JOIN pg_catalog.pg_attribute att_to
                            ON att_to.attrelid = con.confrelid
                            AND att_to.attnum = con.confkey[idx]
                        WHERE con.contype = 'f'
                          AND array_length(con.conkey, 1) > 1
                          AND ns_from.nspname NOT IN ('pg_catalog','information_schema')
                        ORDER BY ns_from.nspname, cl_from.relname, con.conname, idx
                    """)
                    for row in cur.fetchall():
                        relationships.append({
                            "from_schema": row[0],
                            "from_table": row[1],
                            "from_column": row[2],
                            "to_schema": row[3],
                            "to_table": row[4],
                            "to_column": row[5],
                            "constraint_name": row[6],
                            "fk_position": int(row[7]) if row[7] is not None else 1,
                        })

                logger.info("[DSLearning] Bulunan FK ilişki sayısı: %d", len(relationships))
            except Exception as fk_err:
                logger.error("[DSLearning] FK ilişki sorgusu başarısız: %s — %s", type(fk_err).__name__, str(fk_err)[:300])
                # FK hatası obje tespitini engellemez, devam et

        elif db_dialect == "mssql":
            cur.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE IN ('BASE TABLE','VIEW')
                ORDER BY TABLE_SCHEMA, TABLE_NAME
            """)
            tables = cur.fetchall()

            # ── Toplu kolon sorgusu (N+1 yerine 1 sorgu) ──
            all_columns = {}  # key: (schema, table) → list of column dicts
            cur.execute("""
                SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
                       CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE
                FROM INFORMATION_SCHEMA.COLUMNS
                ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION
            """)
            for col in cur.fetchall():
                cs = col["TABLE_SCHEMA"] if isinstance(col, dict) else col[0]
                ct = col["TABLE_NAME"] if isinstance(col, dict) else col[1]
                key = (cs, ct)
                cn = col["COLUMN_NAME"] if isinstance(col, dict) else col[2]
                dt = col["DATA_TYPE"] if isinstance(col, dict) else col[3]
                nullable = col["IS_NULLABLE"] if isinstance(col, dict) else col[4]
                default = col["COLUMN_DEFAULT"] if isinstance(col, dict) else col[5]
                if key not in all_columns:
                    all_columns[key] = []
                all_columns[key].append({
                    "name": cn, "data_type": dt,
                    "is_nullable": nullable == "YES",
                    "default_val": str(default) if default else None,
                    "is_pk": False
                })

            # ── Toplu PK sorgusu (1 sorgu ile tüm PK'lar) ──
            all_pks = {}  # key: (schema, table) → set of column names
            cur.execute("""
                SELECT tc.TABLE_SCHEMA, tc.TABLE_NAME, kcu.COLUMN_NAME
                FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
                    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
                WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
            """)
            for pk_row in cur.fetchall():
                ps = pk_row["TABLE_SCHEMA"] if isinstance(pk_row, dict) else pk_row[0]
                pt = pk_row["TABLE_NAME"] if isinstance(pk_row, dict) else pk_row[1]
                pc = pk_row["COLUMN_NAME"] if isinstance(pk_row, dict) else pk_row[2]
                key = (ps, pt)
                if key not in all_pks:
                    all_pks[key] = set()
                all_pks[key].add(pc)

            # ── Faz 2f: Native comment okuma (MSSQL sys.extended_properties / MS_Description) ──
            mssql_col_comments = {}
            mssql_tbl_comments = {}
            try:
                cur.execute("""
                    SELECT SCHEMA_NAME(t.schema_id) AS schema_name,
                           t.name AS table_name,
                           c.name AS column_name,
                           CAST(ep.value AS NVARCHAR(MAX)) AS comment
                    FROM sys.tables t
                    JOIN sys.columns c ON c.object_id = t.object_id
                    LEFT JOIN sys.extended_properties ep
                           ON ep.major_id = c.object_id
                          AND ep.minor_id = c.column_id
                          AND ep.name = 'MS_Description'
                          AND ep.class = 1
                    WHERE ep.value IS NOT NULL
                """)
                for r in cur.fetchall():
                    sch = r["schema_name"] if isinstance(r, dict) else r[0]
                    tbl = r["table_name"] if isinstance(r, dict) else r[1]
                    col = r["column_name"] if isinstance(r, dict) else r[2]
                    cmt = r["comment"] if isinstance(r, dict) else r[3]
                    if cmt:
                        mssql_col_comments[(sch, tbl, col)] = cmt
            except Exception as cmt_err:
                logger.warning(f"[Discovery][MSSQL] col comment hata: {cmt_err}")

            try:
                cur.execute("""
                    SELECT SCHEMA_NAME(t.schema_id) AS schema_name,
                           t.name AS table_name,
                           CAST(ep.value AS NVARCHAR(MAX)) AS comment
                    FROM sys.tables t
                    JOIN sys.extended_properties ep
                           ON ep.major_id = t.object_id
                          AND ep.minor_id = 0
                          AND ep.name = 'MS_Description'
                          AND ep.class = 1
                    WHERE ep.value IS NOT NULL
                """)
                for r in cur.fetchall():
                    sch = r["schema_name"] if isinstance(r, dict) else r[0]
                    tbl = r["table_name"] if isinstance(r, dict) else r[1]
                    cmt = r["comment"] if isinstance(r, dict) else r[2]
                    if cmt:
                        mssql_tbl_comments[(sch, tbl)] = cmt
            except Exception as cmt_err:
                logger.warning(f"[Discovery][MSSQL] tablo comment hata: {cmt_err}")

            # ── Objeleri birleştir ──
            for row in tables:
                schema_name = row["TABLE_SCHEMA"] if isinstance(row, dict) else row[0]
                table_name = row["TABLE_NAME"] if isinstance(row, dict) else row[1]
                table_type = row["TABLE_TYPE"] if isinstance(row, dict) else row[2]
                obj_type = "table" if table_type == "BASE TABLE" else "view"

                key = (schema_name, table_name)
                columns = list(all_columns.get(key, []))

                # PK işaretle
                pk_cols = all_pks.get(key, set())
                for c in columns:
                    c["is_pk"] = c["name"] in pk_cols
                    # Faz 2f: native kolon yorumu
                    cmt = mssql_col_comments.get((schema_name, table_name, c["name"]))
                    if cmt:
                        c["comment"] = cmt

                obj_entry = {
                    "schema_name": schema_name,
                    "object_name": table_name,
                    "object_type": obj_type,
                    "column_count": len(columns),
                    "row_count_estimate": 0,
                    "columns_json": columns
                }
                # Faz 2f: native tablo yorumu
                t_cmt = mssql_tbl_comments.get((schema_name, table_name))
                if t_cmt:
                    obj_entry["description"] = t_cmt
                objects.append(obj_entry)

            # MSSQL FK İlişkileri
            # v3.32.0: fk_position = fkc.constraint_column_id (composite FK
            # column sırası — 1..N).
            cur.execute("""
                SELECT
                    SCHEMA_NAME(fk.schema_id) AS from_schema,
                    OBJECT_NAME(fk.parent_object_id) AS from_table,
                    COL_NAME(fkc.parent_object_id, fkc.parent_column_id) AS from_column,
                    SCHEMA_NAME(pk_tab.schema_id) AS to_schema,
                    OBJECT_NAME(fk.referenced_object_id) AS to_table,
                    COL_NAME(fkc.referenced_object_id, fkc.referenced_column_id) AS to_column,
                    fk.name AS constraint_name,
                    fkc.constraint_column_id AS fk_position
                FROM sys.foreign_keys fk
                JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
                JOIN sys.tables pk_tab ON fk.referenced_object_id = pk_tab.object_id
                ORDER BY from_schema, from_table, constraint_name, fkc.constraint_column_id
            """)
            for row in cur.fetchall():
                fs = row["from_schema"] if isinstance(row, dict) else row[0]
                ft = row["from_table"] if isinstance(row, dict) else row[1]
                fc = row["from_column"] if isinstance(row, dict) else row[2]
                ts = row["to_schema"] if isinstance(row, dict) else row[3]
                tt = row["to_table"] if isinstance(row, dict) else row[4]
                tc = row["to_column"] if isinstance(row, dict) else row[5]
                cn = row["constraint_name"] if isinstance(row, dict) else row[6]
                fp_raw = row["fk_position"] if isinstance(row, dict) else (row[7] if len(row) > 7 else 1)
                relationships.append({
                    "from_schema": fs, "from_table": ft, "from_column": fc,
                    "to_schema": ts, "to_table": tt, "to_column": tc,
                    "constraint_name": cn,
                    "fk_position": int(fp_raw) if fp_raw is not None else 1,
                })

        elif db_dialect == "mysql":
            db_name = source.get("db_name", "")
            # Faz 2f: TABLE_COMMENT da çekiyoruz
            cur.execute("""
                SELECT TABLE_NAME, TABLE_TYPE, TABLE_ROWS, TABLE_COMMENT
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = %s
                ORDER BY TABLE_NAME
            """, (db_name,))
            tables = cur.fetchall()

            for row in tables:
                table_name = row.get("TABLE_NAME", "") if isinstance(row, dict) else row[0]
                table_type = row.get("TABLE_TYPE", "") if isinstance(row, dict) else row[1]
                table_rows = row.get("TABLE_ROWS", 0) if isinstance(row, dict) else row[2]
                table_comment = (row.get("TABLE_COMMENT", "") if isinstance(row, dict) else (row[3] if len(row) > 3 else "")) or ""
                obj_type = "table" if table_type == "BASE TABLE" else "view"

                # Faz 2f: COLUMN_COMMENT da çekiyoruz
                cur.execute("""
                    SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, COLUMN_KEY, COLUMN_COMMENT
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
                    col_comment = (col.get("COLUMN_COMMENT", "") if isinstance(col, dict) else (col[5] if len(col) > 5 else "")) or ""
                    entry = {
                        "name": cn, "data_type": dt,
                        "is_nullable": nullable == "YES",
                        "default_val": str(default) if default else None,
                        "is_pk": key == "PRI"
                    }
                    if col_comment:
                        entry["comment"] = col_comment
                    columns.append(entry)

                obj_entry = {
                    "schema_name": db_name,
                    "object_name": table_name,
                    "object_type": obj_type,
                    "column_count": len(columns),
                    "row_count_estimate": table_rows or 0,
                    "columns_json": columns
                }
                if table_comment:
                    obj_entry["description"] = table_comment
                objects.append(obj_entry)

            # MySQL FK İlişkileri
            # v3.32.0: fk_position = kcu.ORDINAL_POSITION (composite FK sırası)
            cur.execute("""
                SELECT
                    TABLE_SCHEMA AS from_schema,
                    TABLE_NAME AS from_table,
                    COLUMN_NAME AS from_column,
                    REFERENCED_TABLE_SCHEMA AS to_schema,
                    REFERENCED_TABLE_NAME AS to_table,
                    REFERENCED_COLUMN_NAME AS to_column,
                    CONSTRAINT_NAME AS constraint_name,
                    ORDINAL_POSITION AS fk_position
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
                WHERE TABLE_SCHEMA = %s
                  AND REFERENCED_TABLE_NAME IS NOT NULL
                ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION
            """, (db_name,))
            for row in cur.fetchall():
                fs = row.get("from_schema", "") if isinstance(row, dict) else row[0]
                ft = row.get("from_table", "") if isinstance(row, dict) else row[1]
                fc = row.get("from_column", "") if isinstance(row, dict) else row[2]
                ts = row.get("to_schema", "") if isinstance(row, dict) else row[3]
                tt = row.get("to_table", "") if isinstance(row, dict) else row[4]
                tc = row.get("to_column", "") if isinstance(row, dict) else row[5]
                cn = row.get("constraint_name", "") if isinstance(row, dict) else row[6]
                fp_raw = row.get("fk_position", 1) if isinstance(row, dict) else (row[7] if len(row) > 7 else 1)
                relationships.append({
                    "from_schema": fs, "from_table": ft, "from_column": fc,
                    "to_schema": ts, "to_table": tt, "to_column": tc,
                    "constraint_name": cn,
                    "fk_position": int(fp_raw) if fp_raw is not None else 1,
                })

        elif db_dialect == "oracle":
            # Oracle: Tablo ve View keşfi
            # db_user ile bağlanan kullanıcının erişebildiği tüm schema'ları keşfet
            # Sadece db_user'ın kendi schema'sı değil, erişim izni olan diğer schema'lar da dahil
            schema_owner = source.get("db_user", "").upper()

            # Adım 1 sonucundaki schema listesi varsa kullan, yoksa bağlanan kullanıcının schema'sını al
            # Oracle'da bağlanan kullanıcı kendi schema'sındaki tablolara erişir
            # Ama başka schema'lara da grant ile erişim olabilir
            logger.info("[DSLearning] Oracle keşif: db_user=%s, schema_owner=%s", source.get("db_user"), schema_owner)

            # Bağlanan kullanıcının görebildiği tüm tabloları al (SYS/SYSTEM hariç)
            excluded_owners = (
                'SYS', 'SYSTEM', 'OUTLN', 'DBSNMP', 'XDB', 'CTXSYS', 'MDSYS',
                'ORDDATA', 'ORDSYS', 'WMSYS', 'EXFSYS', 'OLAPSYS', 'DVSYS',
                'LBACSYS', 'APEX_PUBLIC_USER', 'FLOWS_FILES', 'ANONYMOUS',
                'APEX_040000', 'APEX_040200', 'APPQOSSYS', 'AUDSYS',
                'GSMADMIN_INTERNAL', 'OJVMSYS', 'DVF', 'DBSFWUSER'
            )
            exclude_placeholders = ",".join([f"'{o}'" for o in excluded_owners])

            cur.execute(f"""
                SELECT owner, table_name, 'TABLE' AS object_type, num_rows
                FROM all_tables
                WHERE owner NOT IN ({exclude_placeholders})
                ORDER BY owner, table_name
            """)
            tables_raw = cur.fetchall()
            logger.info("[DSLearning] Oracle all_tables sonucu: %d tablo", len(tables_raw))

            cur.execute(f"""
                SELECT owner, view_name, 'VIEW' AS object_type, 0
                FROM all_views
                WHERE owner NOT IN ({exclude_placeholders})
                ORDER BY owner, view_name
            """)
            views_raw = cur.fetchall()
            logger.info("[DSLearning] Oracle all_views sonucu: %d view", len(views_raw))

            all_objects = list(tables_raw) + list(views_raw)
            logger.info("[DSLearning] Oracle toplam obje: %d (tablo+view)", len(all_objects))

            # ── Toplu kolon sorgusu (676 tablo × tek tek yerine 1 sorgu) ──
            all_columns = {}  # key: (owner, table_name) → list of column dicts
            try:
                cur.execute(f"""
                    SELECT owner, table_name, column_name, data_type, nullable,
                           data_length, data_precision, data_scale, column_id
                    FROM all_tab_columns
                    WHERE owner NOT IN ({exclude_placeholders})
                    ORDER BY owner, table_name, column_id
                """)
                for col in cur.fetchall():
                    key = (col[0], col[1])
                    data_type = col[3]
                    data_length = col[5]
                    data_precision = col[6]
                    data_scale = col[7]

                    if data_type in ("NUMBER",) and data_precision is not None:
                        full_type = f"{data_type}({data_precision},{data_scale or 0})"
                    elif data_type in ("VARCHAR2", "CHAR", "NVARCHAR2", "NCHAR", "RAW"):
                        full_type = f"{data_type}({data_length})"
                    else:
                        full_type = data_type

                    if key not in all_columns:
                        all_columns[key] = []
                    all_columns[key].append({
                        "name": col[2],
                        "data_type": full_type,
                        "is_nullable": col[4] == "Y",
                        "default_val": None,
                        "is_pk": False
                    })
                logger.info("[DSLearning] Oracle toplu kolon sorgusu: %d tablo için kolon alındı", len(all_columns))
            except Exception as col_err:
                logger.error("[DSLearning] Oracle toplu kolon sorgusu hatası: %s", str(col_err)[:300])

            # ── Toplu PK sorgusu (1 sorgu ile tüm PK'lar) ──
            all_pks = {}  # key: (owner, table_name) → set of column names
            try:
                cur.execute(f"""
                    SELECT c.owner, c.table_name, cc.column_name
                    FROM all_constraints c
                    JOIN all_cons_columns cc ON c.constraint_name = cc.constraint_name AND c.owner = cc.owner
                    WHERE c.constraint_type = 'P'
                      AND c.owner NOT IN ({exclude_placeholders})
                """)
                for row in cur.fetchall():
                    key = (row[0], row[1])
                    if key not in all_pks:
                        all_pks[key] = set()
                    all_pks[key].add(row[2])
                logger.info("[DSLearning] Oracle toplu PK sorgusu: %d tablo için PK alındı", len(all_pks))
            except Exception as pk_err:
                logger.error("[DSLearning] Oracle toplu PK sorgusu hatası: %s", str(pk_err)[:300])

            # ── Faz 2f: Native comment (Oracle all_col_comments / all_tab_comments) ──
            oracle_col_comments = {}  # (owner, table, column) → comment
            oracle_tbl_comments = {}  # (owner, table) → comment
            try:
                cur.execute(f"""
                    SELECT owner, table_name, column_name, comments
                    FROM all_col_comments
                    WHERE owner NOT IN ({exclude_placeholders})
                      AND comments IS NOT NULL
                """)
                for r in cur.fetchall():
                    if r[3]:
                        oracle_col_comments[(r[0], r[1], r[2])] = r[3]
                logger.info("[DSLearning] Oracle kolon comment: %d", len(oracle_col_comments))
            except Exception as e:
                logger.warning("[DSLearning] Oracle all_col_comments hata: %s", str(e)[:200])

            try:
                cur.execute(f"""
                    SELECT owner, table_name, comments
                    FROM all_tab_comments
                    WHERE owner NOT IN ({exclude_placeholders})
                      AND comments IS NOT NULL
                """)
                for r in cur.fetchall():
                    if r[2]:
                        oracle_tbl_comments[(r[0], r[1])] = r[2]
                logger.info("[DSLearning] Oracle tablo comment: %d", len(oracle_tbl_comments))
            except Exception as e:
                logger.warning("[DSLearning] Oracle all_tab_comments hata: %s", str(e)[:200])

            # ── Objeleri birleştir ──
            for row in all_objects:
                obj_owner = row[0]
                obj_name = row[1]
                obj_type_raw = row[2]
                row_estimate = row[3] or 0
                obj_type = "table" if obj_type_raw == "TABLE" else "view"

                key = (obj_owner, obj_name)
                columns = all_columns.get(key, [])

                # PK işaretle
                pk_cols = all_pks.get(key, set())
                for c in columns:
                    c["is_pk"] = c["name"] in pk_cols
                    # Faz 2f: native kolon yorumu
                    cmt = oracle_col_comments.get((obj_owner, obj_name, c["name"]))
                    if cmt:
                        c["comment"] = cmt

                obj_entry = {
                    "schema_name": obj_owner,
                    "object_name": obj_name,
                    "object_type": obj_type,
                    "column_count": len(columns),
                    "row_count_estimate": row_estimate,
                    "columns_json": columns
                }
                # Faz 2f: native tablo yorumu
                t_cmt = oracle_tbl_comments.get((obj_owner, obj_name))
                if t_cmt:
                    obj_entry["description"] = t_cmt
                objects.append(obj_entry)

            # Oracle FK İlişkileri
            # v3.32.0: fk_position = cc.position (composite FK sırası 1..N)
            try:
                cur.execute(f"""
                    SELECT
                        c.owner         AS from_schema,
                        c.table_name    AS from_table,
                        cc.column_name  AS from_column,
                        r.owner         AS to_schema,
                        r.table_name    AS to_table,
                        rc.column_name  AS to_column,
                        c.constraint_name,
                        cc.position     AS fk_position
                    FROM all_constraints c
                    JOIN all_cons_columns cc ON c.constraint_name = cc.constraint_name AND c.owner = cc.owner
                    JOIN all_constraints r ON c.r_constraint_name = r.constraint_name AND c.r_owner = r.owner
                    JOIN all_cons_columns rc ON r.constraint_name = rc.constraint_name AND r.owner = rc.owner
                        AND cc.position = rc.position
                    WHERE c.constraint_type = 'R'
                      AND c.owner NOT IN ({exclude_placeholders})
                    ORDER BY c.table_name, c.constraint_name, cc.position
                """)
                for row in cur.fetchall():
                    fp_raw = row[7] if len(row) > 7 else 1
                    relationships.append({
                        "from_schema": row[0],
                        "from_table": row[1],
                        "from_column": row[2],
                        "to_schema": row[3],
                        "to_table": row[4],
                        "to_column": row[5],
                        "constraint_name": row[6],
                        "fk_position": int(fp_raw) if fp_raw is not None else 1,
                    })
                logger.info("[DSLearning] Oracle FK ilişki sayısı: %d", len(relationships))
            except Exception as fk_err:
                logger.error("[DSLearning] Oracle FK sorgusu hatası: %s", str(fk_err)[:300])

            logger.info("[DSLearning] Oracle keşif tamamlandı: %d obje, %d ilişki", len(objects), len(relationships))

        elapsed = int((time.time() - start) * 1000)
        db_conn.close()

        # VYRA DB'ye kaydet
        vyra_cur = vyra_conn.cursor()

        # Eski objeleri ve enrichment kalıntılarını temizle (FK sırasına dikkat)
        vyra_cur.execute("DELETE FROM ds_column_enrichments WHERE source_id = %s", (source_id,))
        vyra_cur.execute("DELETE FROM ds_table_enrichments WHERE source_id = %s", (source_id,))
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
            # v3.32.0: fk_position 9. kolon olarak eklendi. Eski keşif
            # kaynakları (ör. drift'te dialect probe) fk_position vermezse
            # default 1 kullanılır — migration 038 ile de DB DEFAULT 1 garanti.
            vyra_cur.execute("""
                INSERT INTO ds_db_relationships
                    (source_id, from_schema, from_table, from_column, to_schema, to_table, to_column, constraint_name, fk_position)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                source_id, rel["from_schema"], rel["from_table"], rel["from_column"],
                rel["to_schema"], rel["to_table"], rel["to_column"], rel["constraint_name"],
                int(rel.get("fk_position", 1) or 1),
            ))

        vyra_conn.commit()

        # ─── v3.29.9: FK Inference auto-trigger (naming+type only) ───
        # Tüm 4 dialect için çalışır (PG / Oracle / MSSQL / MySQL).
        # Hedef DB'ye bağlanmaz — sadece VYRA DB'deki ds_db_objects'i okur.
        # Hata olması keşfi BLOKLAMAZ.
        inferred_count = 0
        try:
            from app.services.db_learning.fk_inference_service import (
                infer_fks_for_source,
            )
            _inf = infer_fks_for_source(
                vyra_cur, source_id,
                sample_validate=False,
                min_confidence=0.60,
                dialect=db_dialect,
            )
            vyra_conn.commit()
            logger.info(
                "[DSLearning.fk_inference] source=%s dialect=%s declared=%d "
                "candidates=%d persisted=%d skipped_existing=%d skipped_low=%d",
                source_id, db_dialect, len(relationships),
                _inf.get("candidates", 0),
                _inf.get("persisted", 0),
                _inf.get("skipped_existing", 0),
                _inf.get("skipped_low_confidence", 0),
            )
        except Exception as _fk_inf_err:
            try:
                vyra_conn.rollback()
            except Exception:
                pass
            logger.warning(
                "[DSLearning.fk_inference] failed source=%s: %s",
                source_id, str(_fk_inf_err)[:200],
            )

        # v3.29.11: inferred FK sayısını otoriter olarak DB'den oku (UI için)
        try:
            vyra_cur.execute(
                "SELECT COUNT(*) FROM ds_db_relationships "
                "WHERE source_id = %s AND is_inferred = TRUE",
                (source_id,),
            )
            _row = vyra_cur.fetchone()
            if _row:
                inferred_count = int(_row[0] if not hasattr(_row, "get") else _row.get("count", _row[0]))
        except Exception as _inf_count_err:
            try:
                vyra_conn.rollback()
            except Exception:
                pass
            logger.debug("[DSLearning.fk_inference] inferred_count read failed: %s", _inf_count_err)

        # Snapshot oluştur ve diff hesapla (v3.0)
        snapshot_result = {}
        try:
            from app.services import ds_diff_service
            snapshot_result = ds_diff_service.create_snapshot(vyra_conn, source_id, objects, relationships)
            if snapshot_result.get("has_changes") or snapshot_result.get("is_first_run"):
                logger.info("[DSLearning] Schema snapshot oluşturuldu: id=%s, diff=%s",
                            snapshot_result.get("snapshot_id"),
                            snapshot_result.get("diff", {}).get("summary", ""))

                # v3.10.0: Schema değişikliği → otomatik schema_record invalidation
                if snapshot_result.get("has_changes") and not snapshot_result.get("is_first_run"):
                    _auto_invalidate_schema_records(vyra_conn, source_id, snapshot_result.get("diff", {}))

                    # v3.27.0 G6: Schema drift → learned_db_queries + few_shot_examples + col_embeddings
                    try:
                        from app.services.db_learning.schema_drift_detector import apply_drift
                        drift_cur = vyra_conn.cursor()
                        try:
                            drift_summary = apply_drift(
                                drift_cur,
                                source_id=source_id,
                                company_id=source.get("company_id"),
                                diff=snapshot_result.get("diff", {}),
                            )
                            vyra_conn.commit()
                            logger.info(
                                "[DSLearning.drift] invalidated_learned=%d penalized_fs=%d dropped_embs=%d",
                                drift_summary.invalidated_learned,
                                drift_summary.penalized_few_shot,
                                drift_summary.dropped_column_embeddings,
                            )
                        finally:
                            drift_cur.close()
                    except Exception as drift_err:
                        logger.warning("[DSLearning.drift] hata: %s", drift_err)
            else:
                logger.info("[DSLearning] Şemada değişiklik yok, snapshot atlandı")
        except Exception as snap_err:
            logger.error("[DSLearning] Snapshot oluşturma hatası: %s — %s",
                         type(snap_err).__name__, str(snap_err)[:200])

        return {
            "success": True,
            "data": {
                "table_count": sum(1 for o in objects if o["object_type"] == "table"),
                "view_count": sum(1 for o in objects if o["object_type"] == "view"),
                "relationship_count": len(relationships),
                # v3.29.11: declared (DB FK constraint) ve inferred (naming/type) ayrı gösterilsin
                "declared_count": len(relationships),
                "inferred_count": inferred_count,
                "total_relationships": len(relationships) + inferred_count,
                "total_columns": sum(o["column_count"] for o in objects),
                "elapsed_ms": elapsed,
                "snapshot": {
                    "id": snapshot_result.get("snapshot_id"),
                    "is_first_run": snapshot_result.get("is_first_run", True),
                    "has_changes": snapshot_result.get("has_changes", True),
                    "diff_summary": snapshot_result.get("diff", {}).get("summary", "")
                }
            }
        }

    except Exception as e:
        try:
            db_conn.close()
        except Exception:
            pass
        logger.error("[DSLearning] Obje tespiti sırasında hata oluştu: %s", str(e))
        return {"success": False, "error": "Veritabanı analiz edilirken sistemsel bir hata oluştu, işlem detayları loglandı."}


# =====================================================
# Adım 3: Örnek Veri Toplama
# =====================================================

def collect_samples(source: dict, vyra_conn, max_rows: int = 10, schema_filter: list = None) -> dict:
    """
    Keşfedilen tablolardan örnek SELECT sorguları hazırlayıp çalıştırır.
    schema_filter: Belirli schema adlarına göre filtreler (None = tüm şemalar).
    """
    source_id = source["id"]
    start = time.time()
    db_conn = None

    try:
        password = _decrypt_password(source.get("db_password_encrypted", ""))
        db_conn, db_dialect = _get_db_connector(source, password)

        # VYRA DB'den keşfedilmiş objeleri al (opsiyonel schema filtresi ile)
        vyra_cur = vyra_conn.cursor()
        if schema_filter:
            format_strings = ','.join(['%s'] * len(schema_filter))
            vyra_cur.execute(f"""
                SELECT id, schema_name, object_name, object_type, columns_json
                FROM ds_db_objects
                WHERE source_id = %s AND object_type = 'table'
                  AND schema_name IN ({format_strings})
                ORDER BY schema_name, object_name
            """, [source_id] + list(schema_filter))
            logger.info("[DSLearning] Veri toplama: schema filtresi uygulandı (%d şema: %s)",
                        len(schema_filter), schema_filter[:5])
        else:
            vyra_cur.execute("""
                SELECT id, schema_name, object_name, object_type, columns_json
                FROM ds_db_objects
                WHERE source_id = %s AND object_type = 'table'
                ORDER BY schema_name, object_name
            """, (source_id,))
        db_objects = vyra_cur.fetchall()

        if not db_objects:
            return {"success": False, "error": "Önce obje tespiti yapılmalı (detect-objects)"}

        target_cur = db_conn.cursor()
        total_sampled = 0
        failed_tables = []
        total_tables = len(db_objects)

        # Eski sample'ları temizle
        vyra_cur.execute("DELETE FROM ds_db_samples WHERE source_id = %s", (source_id,))

        for idx, obj_row in enumerate(db_objects):
            if (idx + 1) % 50 == 0 or idx == 0:
                logger.info("[DSLearning] Veri toplama ilerleme: %d/%d tablo", idx + 1, total_tables)
            obj_id = obj_row["id"] if isinstance(obj_row, dict) else obj_row[0]
            schema_name = obj_row["schema_name"] if isinstance(obj_row, dict) else obj_row[1]
            object_name = obj_row["object_name"] if isinstance(obj_row, dict) else obj_row[2]
            columns_data = obj_row["columns_json"] if isinstance(obj_row, dict) else obj_row[4]

            if isinstance(columns_data, str):
                columns_data = json.loads(columns_data)

            # Sadece güvenli (binary/LOB olmayan) kolonları seç
            unsafe_types = ["blob", "bytea", "varbinary", "binary", "image", "raw", "bfile",
                            "clob", "nclob", "long", "long raw", "xmltype", "blobtype"]
            safe_cols = []
            for col in (columns_data or []):
                ctype = col.get("data_type", "").lower()
                if not any(u in ctype for u in unsafe_types):
                    safe_cols.append(_safe_identifier(col.get("name", "")))

            if not safe_cols:
                safe_cols = ["*"]

            # Maksimum 50 kolon (çok geniş tablolarda performans)
            if safe_cols[0] != "*" and len(safe_cols) > 50:
                safe_cols = safe_cols[:50]

            # Güvenli tablo adı — sadece alfanümerik, underscore, nokta, boşluk
            safe_name = _safe_identifier(object_name)
            safe_schema = _safe_identifier(schema_name or "")

            if db_dialect == "postgresql":
                cols_str = ", ".join([f'"{c}"' for c in safe_cols]) if safe_cols[0] != "*" else "*"
                fqn = f'"{safe_schema}"."{safe_name}"' if safe_schema else f'"{safe_name}"'
                query = f"SELECT {cols_str} FROM {fqn} LIMIT {max_rows}"
            elif db_dialect == "mssql":
                cols_str = ", ".join([f'[{c}]' for c in safe_cols]) if safe_cols[0] != "*" else "*"
                fqn = f"[{safe_schema}].[{safe_name}]" if safe_schema else f"[{safe_name}]"
                query = f"SELECT TOP {max_rows} {cols_str} FROM {fqn}"
            elif db_dialect == "mysql":
                cols_str = ", ".join([f'`{c}`' for c in safe_cols]) if safe_cols[0] != "*" else "*"
                query = f"SELECT {cols_str} FROM `{safe_name}` LIMIT {max_rows}"
            elif db_dialect == "oracle":
                cols_str = ", ".join([f'"{c}"' for c in safe_cols]) if safe_cols[0] != "*" else "*"
                fqn = f'"{safe_schema}"."{safe_name}"' if safe_schema else f'"{safe_name}"'
                query = f"SELECT {cols_str} FROM {fqn} WHERE ROWNUM <= {max_rows}"
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
                logger.error("[DSLearning] Tablo veri alma hatası (%s): %s", object_name, str(table_err))
                failed_tables.append({"table": object_name, "error": "Veri okuma başarısız"})
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
        logger.error("[DSLearning] Örnek veri toplama sırasında hata oluştu: %s", str(e))
        return {"success": False, "error": "Örnek veri toplama işlemi sırasında sistem hatası oluştu, işlem detayları loglandı."}


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


def _refresh_relationships_for_tables(vyra_conn, source: dict, source_id: int, table_names: set):
    """
    v3.14.0: Belirli tablolar için FK ilişkilerini kaynak DB'den yeniden keşfeder.
    Partial enrichment sırasında yeni eklenen tabloların FK'ları güncel kalır.

    Mevcut ilişkileri silmez — sadece yeni bulunan ilişkileri ekler (UPSERT).
    """
    db_type = (source.get("db_type") or "").lower()
    remote_conn = None

    try:
        password = _decrypt_password(source.get("db_password_encrypted", ""))
        remote_conn, _ = _get_db_connector(source, password)
        if not remote_conn:
            return

        remote_cur = remote_conn.cursor()
        new_rels = []

        if db_type == "oracle":
            for tname in table_names:
                try:
                    remote_cur.execute("""
                        SELECT a.owner, a.table_name, a.column_name,
                               c_pk.owner AS r_owner, c_pk.table_name AS r_table_name,
                               b.column_name AS r_column_name,
                               a.constraint_name
                        FROM all_cons_columns a
                        JOIN all_constraints c ON a.constraint_name = c.constraint_name AND a.owner = c.owner
                        JOIN all_constraints c_pk ON c.r_constraint_name = c_pk.constraint_name AND c.r_owner = c_pk.owner
                        JOIN all_cons_columns b ON c_pk.constraint_name = b.constraint_name AND c_pk.owner = b.owner
                        WHERE c.constraint_type = 'R'
                          AND (UPPER(a.table_name) = UPPER(:1) OR UPPER(c_pk.table_name) = UPPER(:2))
                    """, [tname, tname])
                    for row in remote_cur.fetchall():
                        new_rels.append({
                            "from_schema": row[0], "from_table": row[1], "from_column": row[2],
                            "to_schema": row[3], "to_table": row[4], "to_column": row[5],
                            "constraint_name": row[6],
                        })
                except Exception:
                    pass

        elif db_type == "postgresql":
            for tname in table_names:
                try:
                    remote_cur.execute("""
                        SELECT kcu.table_schema, kcu.table_name, kcu.column_name,
                               ccu.table_schema, ccu.table_name, ccu.column_name,
                               kcu.constraint_name
                        FROM information_schema.key_column_usage kcu
                        JOIN information_schema.referential_constraints rc
                            ON kcu.constraint_name = rc.constraint_name
                        JOIN information_schema.constraint_column_usage ccu
                            ON rc.unique_constraint_name = ccu.constraint_name
                        WHERE LOWER(kcu.table_name) = LOWER(%s)
                           OR LOWER(ccu.table_name) = LOWER(%s)
                    """, [tname, tname])
                    for row in remote_cur.fetchall():
                        new_rels.append({
                            "from_schema": row[0], "from_table": row[1], "from_column": row[2],
                            "to_schema": row[3], "to_table": row[4], "to_column": row[5],
                            "constraint_name": row[6],
                        })
                except Exception:
                    pass

        # Mevcut ilişkilerle UPSERT (duplicate'ları atla)
        if new_rels:
            vyra_cur = vyra_conn.cursor()
            for rel in new_rels:
                try:
                    # COALESCE ile NULL schema'ları boş string'e çevir (unique index uyumu)
                    from_sch = rel.get("from_schema") or ""
                    to_sch = rel.get("to_schema") or ""
                    vyra_cur.execute("""
                        INSERT INTO ds_db_relationships
                            (source_id, from_schema, from_table, from_column,
                             to_schema, to_table, to_column, constraint_name)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_id, from_schema, from_table, from_column,
                                     to_schema, to_table, to_column) DO NOTHING
                    """, (
                        source_id,
                        from_sch, rel["from_table"], rel["from_column"],
                        to_sch, rel["to_table"], rel["to_column"],
                        rel.get("constraint_name", ""),
                    ))
                except Exception:
                    pass
            vyra_conn.commit()
            logger.info("[DSLearning] %d yeni FK ilişkisi eklendi", len(new_rels))

    except Exception as e:
        logger.warning("[DSLearning] FK refresh hatası: %s", str(e)[:200])
    finally:
        if remote_conn:
            try:
                remote_conn.close()
            except Exception:
                pass


def check_running_job(vyra_conn, source_id: int) -> dict:
    """
    Bu kaynak için çalışan (running) bir iş var mı kontrol eder.
    30 dakikadan eski stuck job'ları otomatik 'failed' olarak işaretler.
    
    Returns:
        dict: {"has_running": bool, "job": {...} or None}
    """
    cur = vyra_conn.cursor()

    # 1) Stuck job temizliği: 30 dakikadan eski running job'ları failed yap
    cur.execute("""
        UPDATE ds_discovery_jobs
        SET status = 'failed',
            error_message = 'Zaman aşımı: İş 30 dakikadan uzun sürdüğü için otomatik iptal edildi.',
            completed_at = NOW()
        WHERE source_id = %s
          AND status = 'running'
          AND started_at < NOW() - INTERVAL '30 minutes'
    """, (source_id,))
    cleaned = cur.rowcount
    if cleaned > 0:
        vyra_conn.commit()
        logger.warning("[DSLearning] %d stuck job temizlendi (source_id=%s)", cleaned, source_id)

    # 2) Hâlâ running olan iş var mı?
    cur.execute("""
        SELECT id, job_type, started_at
        FROM ds_discovery_jobs
        WHERE source_id = %s AND status = 'running'
        ORDER BY started_at DESC
        LIMIT 1
    """, (source_id,))
    row = cur.fetchone()

    if row:
        job_type = row["job_type"] if isinstance(row, dict) else row[1]
        started = row["started_at"] if isinstance(row, dict) else row[2]
        job_id = row["id"] if isinstance(row, dict) else row[0]
        return {
            "has_running": True,
            "job": {
                "id": job_id,
                "job_type": job_type,
                "started_at": started.isoformat() if started else None
            }
        }

    return {"has_running": False, "job": None}


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

    # İlişkiler (v3.29.0 Faz 6 G1 — cardinality + junction metadata)
    cur.execute("""
        SELECT id, from_schema, from_table, from_column,
               to_schema, to_table, to_column, constraint_name,
               cardinality_from, cardinality_to, is_junction,
               path_weight, inverse_relationship_id,
               confidence_score, last_analyzed_at
        FROM ds_db_relationships WHERE source_id = %s
    """, (source_id,))
    rels = []
    for row in cur.fetchall():
        last_analyzed = row["last_analyzed_at"] if "last_analyzed_at" in row.keys() else None
        rels.append({
            "id": row["id"],
            "from_schema": row["from_schema"], "from_table": row["from_table"], "from_column": row["from_column"],
            "to_schema": row["to_schema"], "to_table": row["to_table"], "to_column": row["to_column"],
            "constraint_name": row["constraint_name"],
            "cardinality_from": row["cardinality_from"],
            "cardinality_to": row["cardinality_to"],
            "is_junction": bool(row["is_junction"]) if row["is_junction"] is not None else False,
            "path_weight": row["path_weight"],
            "inverse_relationship_id": row["inverse_relationship_id"],
            "confidence_score": float(row["confidence_score"]) if row["confidence_score"] is not None else None,
            "last_analyzed_at": last_analyzed.isoformat() if last_analyzed else None,
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


def get_learning_results(vyra_conn, source_id: int, content_type: str = None,
                         job_id: int = None, limit: int = 50,
                         offset: int = 0, search: str = None) -> dict:
    """
    ML pipeline'ın ürettiği öğrenme sonuçlarını (QA çiftleri) döner.
    v3.7.0: Pagination (offset/limit) ve arama (search) desteği eklendi.
    """
    cur = vyra_conn.cursor()

    # Dinamik WHERE builder
    conditions = ["source_id = %s", "is_valid = TRUE"]
    params = [source_id]

    if content_type:
        conditions.append("content_type = %s")
        params.append(content_type)

    if job_id:
        conditions.append("job_id = %s")
        params.append(job_id)

    if search:
        conditions.append("(metadata::text ILIKE %s OR content_text ILIKE %s)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    where_clause = " AND ".join(conditions)

    # Toplam kayıt sayısı (pagination için)
    cur.execute(f"""
        SELECT COUNT(*) AS cnt
        FROM ds_learning_results
        WHERE {where_clause}
    """, tuple(params))
    total_filtered = cur.fetchone()["cnt"]

    # Sayfalanmış sonuçları al
    query_params = list(params) + [limit, offset]
    cur.execute(f"""
        SELECT id, content_type, content_text, metadata, created_at, job_id
        FROM ds_learning_results
        WHERE {where_clause}
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, tuple(query_params))

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
            "job_id": row["job_id"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None
        })

    # Tip bazlı sayılar (filtre uygulanmadan — genel istatistik)
    count_conditions = ["source_id = %s", "is_valid = TRUE"]
    count_params = [source_id]
    if job_id:
        count_conditions.append("job_id = %s")
        count_params.append(job_id)

    cur.execute(f"""
        SELECT content_type, COUNT(*) as cnt
        FROM ds_learning_results
        WHERE {' AND '.join(count_conditions)}
        GROUP BY content_type
        ORDER BY cnt DESC
    """, tuple(count_params))
    type_counts = {}
    for row in cur.fetchall():
        type_counts[row["content_type"]] = row["cnt"]

    total_all = sum(type_counts.values())
    total_pages = (total_filtered + limit - 1) // limit if limit > 0 else 1
    current_page = (offset // limit) + 1 if limit > 0 else 1

    return {
        "results": results,
        "type_counts": type_counts,
        "total": total_all,
        "total_filtered": total_filtered,
        "page": current_page,
        "page_size": limit,
        "total_pages": total_pages
    }


def get_job_result_stats(vyra_conn, source_id: int) -> list:
    """Her job_id bazlı sonuç istatistiklerini döner (iş geçmişi dropdown için)."""
    cur = vyra_conn.cursor()
    cur.execute("""
        SELECT
            r.job_id,
            j.job_type,
            j.started_at,
            j.status,
            j.duration_ms,
            COUNT(*) as result_count,
            COUNT(DISTINCT r.content_type) as type_count
        FROM ds_learning_results r
        LEFT JOIN ds_discovery_jobs j ON j.id = r.job_id
        WHERE r.source_id = %s AND r.job_id IS NOT NULL
        GROUP BY r.job_id, j.job_type, j.started_at, j.status, j.duration_ms
        ORDER BY j.started_at DESC
    """, (source_id,))

    stats = []
    for row in cur.fetchall():
        stats.append({
            "job_id": row["job_id"],
            "job_type": row["job_type"],
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "status": row["status"],
            "duration_ms": row["duration_ms"],
            "result_count": row["result_count"],
            "type_count": row["type_count"]
        })
    return stats


# =====================================================
# Faz 2: DB Knowledge Arama (RAG Entegrasyonu)
# =====================================================



def search_db_knowledge(query: str, company_id: int = None, min_score: float = 0.35, max_results: int = 3, source_id: int = None) -> list:
    """
    Önceden öğrenilmiş DB bilgilerinde cosine similarity araması yapar.

    Args:
        query: Kullanıcı sorusu
        company_id: Firma filtresi (opsiyonel)
        min_score: Minimum benzerlik skoru
        max_results: Maksimum sonuç sayısı
        source_id: v3.20.0 Faz 1c — verilirse arama o kaynağa RLS-scope edilir.
                   Verilmezse cross-source legacy davranış (bypass=True) sürer.

    Returns:
        List[dict]: [{content, score, source_name, content_type, metadata}]
    """
    try:
        from app.services.rag.embedding import EmbeddingManager
        from app.services.rag import scoring
        # v3.20.0 Faz 1c: ds_learning_results RLS koruma altında. source_id verilmezse
        # cross-source taranır (admin/RAG path) → bypass; verilmişse o kaynağa scope.
        from app.core.db import get_db_context_scoped

        emb_mgr = EmbeddingManager()
        query_embedding = emb_mgr.get_embedding(query)

        scoped_kwargs = {"source_id": source_id} if source_id is not None else {"bypass": True}
        with get_db_context_scoped(**scoped_kwargs) as conn:
            cur = conn.cursor()

            # source_id verilmişse en spesifik filtre; yoksa company / hepsi
            if source_id is not None:
                cur.execute("""
                    SELECT lr.id, lr.content_text, lr.embedding, lr.content_type, lr.metadata, lr.score AS base_score,
                           ds.name AS source_name
                    FROM ds_learning_results lr
                    JOIN data_sources ds ON lr.source_id = ds.id
                    WHERE lr.source_id = %s
                      AND lr.embedding IS NOT NULL
                      AND lr.is_valid = TRUE
                      AND lr.content_type = 'schema_record'
                """, (source_id,))
            elif company_id:
                cur.execute("""
                    SELECT lr.id, lr.content_text, lr.embedding, lr.content_type, lr.metadata, lr.score AS base_score,
                           ds.name AS source_name
                    FROM ds_learning_results lr
                    JOIN data_sources ds ON lr.source_id = ds.id
                    WHERE ds.company_id = %s
                      AND lr.embedding IS NOT NULL
                      AND lr.is_valid = TRUE
                      AND lr.content_type = 'schema_record'
                """, (company_id,))
            else:
                cur.execute("""
                    SELECT lr.id, lr.content_text, lr.embedding, lr.content_type, lr.metadata, lr.score AS base_score,
                           ds.name AS source_name
                    FROM ds_learning_results lr
                    JOIN data_sources ds ON lr.source_id = ds.id
                    WHERE lr.embedding IS NOT NULL
                      AND lr.is_valid = TRUE
                      AND lr.content_type = 'schema_record'
                """)

            rows = cur.fetchall()

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

    except Exception as _sdb_err:
        import traceback as _tb
        logger.error(
            "[DSLearning] DB knowledge search hatasi: %s | %s",
            type(_sdb_err).__name__, str(_sdb_err)[:200]
        )
        logger.debug("[DSLearning] Traceback: %s", _tb.format_exc())
        return []


# =====================================================
# Faz 2: Kısmi ve Tam Pipeline Çalıştırma
# =====================================================

def run_partial_enrichment(source: dict, object_ids: list, vyra_conn, user_id: int = None) -> dict:
    source_id = source["id"]
    company_id = source.get("company_id", 1)
    
    job_id = create_job(vyra_conn, source_id, company_id, "partial_enrichment", user_id)
    if not job_id:
        return {"success": False, "error": "Job oluşturulamadı."}

    results = {"steps": []}
    try:
        from app.services import ds_enrichment_service
        cur = vyra_conn.cursor()
        format_strings = ','.join(['%s'] * len(object_ids))
        cur.execute(f"""
            SELECT id, schema_name, object_name, object_type,
                   column_count, row_count_estimate, columns_json
            FROM ds_db_objects 
            WHERE source_id = %s AND id IN ({format_strings})
        """, [source_id] + object_ids)
        objects = [dict(row) if hasattr(row, 'keys') else dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]
        
        cur.execute(f"""
            SELECT object_id, sample_data
            FROM ds_db_samples
            WHERE source_id = %s AND object_id IN ({format_strings})
        """, [source_id] + object_ids)
        samples_map = {}
        for row in cur.fetchall():
            obj_id = row["object_id"] if hasattr(row, 'keys') else row[0]
            s_data = row["sample_data"] if hasattr(row, 'keys') else row[1]
            if isinstance(s_data, str):
                try:
                    s_data = json.loads(s_data)
                except Exception:
                    s_data = []
            samples_map[obj_id] = s_data if isinstance(s_data, list) else []
            
        # v3.14.0: Partial enrichment'ta FK ilişkilerini yeniden keşfet
        # Yeni eklenen tablolar mevcut tablolarla FK ilişkisi olabilir
        try:
            new_table_names = {o.get("object_name", "") for o in objects}
            _refresh_relationships_for_tables(vyra_conn, source, source_id, new_table_names)
            logger.info("[DSLearning] FK ilişkileri yenilendi: %s tablo", len(new_table_names))
        except Exception as fk_err:
            logger.warning("[DSLearning] FK yenileme hatası (devam ediliyor): %s", str(fk_err)[:200])

        cur.execute("""
            SELECT from_schema, from_table, from_column,
                   to_schema, to_table, to_column, constraint_name
            FROM ds_db_relationships WHERE source_id = %s
        """, (source_id,))
        relationships = [dict(row) if hasattr(row, 'keys') else dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]

        enrichment_result = ds_enrichment_service.enrich_tables_batch(
            vyra_conn, source_id, company_id,
            objects, samples_map, relationships
        )
        
        results["steps"].append({
            "step": "partial_enrichment",
            "success": True,
            "data": {
                "total": enrichment_result.get("total", 0),
                "enriched": enrichment_result.get("enriched", 0),
                "skipped": enrichment_result.get("skipped", 0),
                "admin_required": enrichment_result.get("admin_required", 0),
                "errors": enrichment_result.get("errors", 0),
                "elapsed_ms": enrichment_result.get("elapsed_ms", 0)
            }
        })
        
        total_ms = enrichment_result.get("elapsed_ms", 0)
        results["total_elapsed_ms"] = total_ms
        results["success"] = True
        
        complete_job(vyra_conn, job_id, {
            "success": True, "data": {"elapsed_ms": total_ms, **results}
        })
        return {"success": True}
    except Exception as e:
        logger.error("[DSLearning] Partial enrichment hatası: %s", str(e))
        complete_job(vyra_conn, job_id, {"success": False, "error": str(e)})
        return {"success": False, "error": str(e)}

def run_full_learning(source: dict, vyra_conn, user_id: int = None) -> dict:
    """
    5 adımlı tam öğrenme pipeline'ı (v3.0):
    1. Teknoloji Keşfi
    2. Obje Tespiti (+ schema snapshot)
    3. Örnek Veri Toplama
    4. LLM Enrichment (tablo/sütun anlamlandırma)
    5. Sentetik QA Üretimi
    """
    source_id = source["id"]
    company_id = source.get("company_id", 1)
    results = {"steps": []}

    # Job oluştur
    job_id = create_job(vyra_conn, source_id, company_id, "full_learning", user_id)

    try:
        # Adım 1: Teknoloji Keşfi
        logger.info("[DSLearning] Full pipeline step 1/5: Technology for source %s", source_id)
        r1 = discover_technology(source, vyra_conn)
        results["steps"].append({"step": "technology", "success": r1.get("success"), "data": r1.get("data")})
        if not r1.get("success"):
            raise Exception(f"Technology discovery failed: {r1.get('error')}")

        # Adım 2: Obje Tespiti (+ snapshot diff)
        logger.info("[DSLearning] Full pipeline step 2/5: Objects for source %s", source_id)
        r2 = detect_objects(source, vyra_conn)
        results["steps"].append({"step": "objects", "success": r2.get("success"), "data": r2.get("data")})
        if not r2.get("success"):
            raise Exception(f"Object detection failed: {r2.get('error')}")

        # Adım 3: Örnek Veri Toplama
        logger.info("[DSLearning] Full pipeline step 3/5: Samples for source %s", source_id)
        r3 = collect_samples(source, vyra_conn)
        results["steps"].append({"step": "samples", "success": r3.get("success"), "data": r3.get("data")})
        if not r3.get("success"):
            raise Exception(f"Sample collection failed: {r3.get('error')}")

        # Adım 4: LLM Enrichment (v5.0 — sadece onaylı tablolar)
        logger.info("[DSLearning] Full pipeline step 4/5: LLM Enrichment (approved only) for source %s", source_id)
        try:
            from app.services import ds_enrichment_service

            # Sadece onaylı tabloların objelerini al
            cur = vyra_conn.cursor()
            cur.execute("""
                SELECT o.id, o.schema_name, o.object_name, o.object_type,
                       o.column_count, o.row_count_estimate, o.columns_json
                FROM ds_db_objects o
                JOIN ds_table_enrichments te
                    ON te.source_id = o.source_id
                    AND te.table_name = o.object_name
                    AND COALESCE(te.schema_name, '') = COALESCE(o.schema_name, '')
                    AND te.is_active = TRUE
                    AND te.admin_approved = TRUE
                WHERE o.source_id = %s AND o.object_type = 'table'
            """, (source_id,))
            objects = [dict(row) if hasattr(row, 'keys') else row for row in cur.fetchall()]

            if not objects:
                logger.info("[DSLearning] Onaylı tablo yok, enrichment atlanıyor")
                results["steps"].append({
                    "step": "enrichment",
                    "success": True,
                    "data": {"total": 0, "enriched": 0, "skipped": 0, "message": "Onaylı tablo yok"}
                })
            else:
                # Sample'ları indexle (object_id bazlı)
                cur.execute("""
                    SELECT object_id, sample_data
                    FROM ds_db_samples WHERE source_id = %s
                """, (source_id,))
                samples_map = {}
                for row in cur.fetchall():
                    obj_id = row["object_id"] if isinstance(row, dict) else row[0]
                    s_data = row["sample_data"] if isinstance(row, dict) else row[1]
                    if isinstance(s_data, str):
                        try:
                            s_data = json.loads(s_data)
                        except Exception:
                            s_data = []
                    samples_map[obj_id] = s_data if isinstance(s_data, list) else []

                # İlişkileri al
                cur.execute("""
                    SELECT from_schema, from_table, from_column,
                           to_schema, to_table, to_column, constraint_name
                    FROM ds_db_relationships WHERE source_id = %s
                """, (source_id,))
                relationships = [dict(row) if hasattr(row, 'keys') else row for row in cur.fetchall()]

                # Enrichment çalıştır (sadece onaylı tablolar)
                logger.info("[DSLearning] Enrichment: %d onaylı tablo işlenecek", len(objects))
                enrichment_result = ds_enrichment_service.enrich_tables_batch(
                    vyra_conn, source_id, company_id,
                    objects, samples_map, relationships
                )
                results["steps"].append({
                    "step": "enrichment",
                    "success": True,
                    "data": {
                        "total": enrichment_result.get("total", 0),
                        "enriched": enrichment_result.get("enriched", 0),
                        "skipped": enrichment_result.get("skipped", 0),
                        "admin_required": enrichment_result.get("admin_required", 0),
                        "errors": enrichment_result.get("errors", 0),
                        "elapsed_ms": enrichment_result.get("elapsed_ms", 0)
                    }
                })

        except Exception as enrich_err:
            logger.error("[DSLearning] Enrichment hatası: %s — %s",
                         type(enrich_err).__name__, str(enrich_err)[:200])
            results["steps"].append({
                "step": "enrichment",
                "success": False,
                "data": {"error": str(enrich_err)[:200]}
            })
            # Enrichment başarısız olsa bile QA üretimine devam et

        # Adım 5: Şema Öğrenimi (v5.0 — sadece onaylı tablolar için schema_record)
        logger.info("[DSLearning] Full pipeline step 5/5: Schema Learning for source %s", source_id)
        try:
            from app.services import ds_qa_generator
            r4 = ds_qa_generator.generate_enriched_qa(source_id, vyra_conn)
        except Exception as qa_err:
            logger.warning("[DSLearning] Schema learning hatası: %s", str(qa_err)[:200])
            r4 = {"success": False, "data": {"error": str(qa_err)[:200]}}
        results["steps"].append({"step": "schema_learning", "success": r4.get("success"), "data": r4.get("data")})

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

    except Exception:
        logger.error("[DSLearning] Full pipeline sırasında hata oluştu")
        results["success"] = False
        results["error"] = "Pipeline çalıştırma sırasında hata oluştu"
        complete_job(vyra_conn, job_id, {"success": False, "error": "Pipeline hatası"})
        return results



def run_approved_qa_learning(source: dict, vyra_conn, user_id: int = None) -> dict:
    """Sadece onaylı tablolar için şema öğrenimi sürecini çalıştırır (v5.0)."""
    source_id = source["id"]
    company_id = source.get("company_id", 1)
    results = {"steps": []}

    # Job type backward compat için qa_generation kalıyor
    job_id = create_job(vyra_conn, source_id, company_id, "qa_generation", user_id)

    try:
        logger.info("[DSLearning] Schema learning for approved tables: source %s", source_id)
        from app.services import ds_qa_generator
        r1 = ds_qa_generator.generate_enriched_qa(source_id, vyra_conn)
        results["steps"].append({"step": "qa_generation", "success": r1.get("success"), "data": r1.get("data")})
        
        total_ms = sum(s.get("data", {}).get("elapsed_ms", 0) for s in results["steps"] if s.get("data"))
        results["total_elapsed_ms"] = total_ms
        results["success"] = r1.get("success", False)
        if not results["success"]:
            results["error"] = r1.get("error", "Şema öğrenimi başarısız")

        complete_job(vyra_conn, job_id, {"success": results["success"], "error": results.get("error"), "data": {"elapsed_ms": total_ms, **results}})
        return results
    except Exception as e:
        logger.error("[DSLearning] QA_learning sırasında hata oluştu: %s", str(e))
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
    try:
        cur = vyra_conn.cursor()

        # company_id'yi data_sources'tan al
        cur.execute("SELECT company_id FROM data_sources WHERE id = %s", (source_id,))
        source = cur.fetchone()
        if not source:
            logger.error("[DSLearning] Schedule kaydedilirken kaynak bulunamadı: source_id=%s", source_id)
            return {"success": False, "message": "Kaynak bulunamadı"}
        company_id = source["company_id"]

        # next_run_at hesapla
        next_run = None
        if is_active and schedule_type != "manual_only":
            from datetime import timedelta
            hours = interval_hours or (24 if schedule_type == "daily" else 12)
            next_run = datetime.now(timezone.utc) + timedelta(hours=hours)

        # ON CONFLICT upsert (unique constraint: source_id)
        cur.execute("""
            INSERT INTO ds_learning_schedules
                (source_id, company_id, schedule_type, interval_value, is_active, next_run_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO UPDATE SET
                schedule_type = EXCLUDED.schedule_type,
                interval_value = EXCLUDED.interval_value,
                is_active = EXCLUDED.is_active,
                next_run_at = EXCLUDED.next_run_at,
                updated_at = NOW()
        """, (source_id, company_id, schedule_type, interval_hours, is_active, next_run))

        vyra_conn.commit()
        logger.info("[DSLearning] Schedule kaydedildi: source_id=%s, type=%s, active=%s", source_id, schedule_type, is_active)
        return {"success": True, "message": "Zamanlama kaydedildi", "schedule_type": schedule_type, "is_active": is_active}

    except Exception:
        logger.error("[DSLearning] Schedule kaydetme sırasında hata oluştu")
        try:
            vyra_conn.rollback()
        except Exception:
            pass
        return {"success": False, "message": "Zamanlama kaydedilemedi"}


# =====================================================
# v3.10.0: Schema Change → Auto Re-Learn
# =====================================================

def _auto_invalidate_schema_records(vyra_conn, source_id: int, diff: dict):
    """
    Schema değişikliği tespit edildiğinde:
    1. Değişen tabloların schema_record embedding'lerini invalidate et
    2. SQL query cache'ini temizle
    3. Değişiklik logla

    Bu fonksiyon detect_objects snapshot diff sonucunda çağrılır.
    Admin'in tekrar "Öğrenme Başlat" çalıştırmasına gerek kalmaz,
    sonraki approve veya learning job schema_record'ları yeniden oluşturur.
    """
    try:
        cur = vyra_conn.cursor()

        # Değişen tablo isimleri
        affected_tables = set()
        for t in diff.get("added_tables", []):
            affected_tables.add(t)
        for t in diff.get("removed_tables", []):
            affected_tables.add(t)
        for mod in diff.get("modified_tables", []):
            if isinstance(mod, dict):
                affected_tables.add(mod.get("table", ""))
            elif isinstance(mod, str):
                affected_tables.add(mod)

        if not affected_tables:
            return

        # 1. Değişen tablolara ait schema_record'ların embedding'ini temizle
        invalidated_count = 0
        for full_table in affected_tables:
            if not full_table:
                continue
            cur.execute("""
                UPDATE ds_learning_results
                SET embedding = NULL, updated_at = NOW()
                WHERE source_id = %s
                  AND content_type = 'schema_record'
                  AND metadata->>'full_table' = %s
            """, (source_id, full_table))
            invalidated_count += cur.rowcount

        # 2. Silinen tabloların schema_record'larını tamamen kaldır
        for full_table in diff.get("removed_tables", []):
            if not full_table:
                continue
            cur.execute("""
                DELETE FROM ds_learning_results
                WHERE source_id = %s
                  AND content_type = 'schema_record'
                  AND metadata->>'full_table' = %s
            """, (source_id, full_table))

        vyra_conn.commit()

        # 3. SQL query cache'ini temizle
        try:
            from app.services.deep_think_service import invalidate_sql_cache
            invalidate_sql_cache(source_id=source_id)
        except Exception:
            pass

        logger.info(
            "[DSLearning] Schema change → auto-invalidate: %d schema_record, "
            "%d tablo etkilendi (source_id=%s)",
            invalidated_count, len(affected_tables), source_id
        )

    except Exception as e:
        logger.warning("[DSLearning] Auto-invalidate hatası: %s — %s",
                       type(e).__name__, str(e)[:200])
        try:
            vyra_conn.rollback()
        except Exception:
            pass
