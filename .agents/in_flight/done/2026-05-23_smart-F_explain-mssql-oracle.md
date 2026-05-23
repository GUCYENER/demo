---
status: done
agent: smart-F
title: EXPLAIN dialect coverage (MSSQL + Oracle)
target_files:
  - app/services/safe_sql_executor.py
  - app/services/pipeline/wiring.py
created_at: 2026-05-23
completed_at: 2026-05-23
version: v3.32.0
---

## Report

### Discovery
- `grep -r EXPLAIN app/services/` ile mevcut EXPLAIN dispatch tek noktada bulundu:
  `app/services/pipeline/wiring.py :: make_explain_callable` — PG/MySQL dallarında
  EXPLAIN çalıştırıyor, MSSQL/Oracle dallarında doğrudan `return None`
  (yorum: "EXPLAIN devre dışı — predictor reltuples yoluna düşer").
- `SafeSQLExecutor.execute()` üzerinden EXPLAIN çağırmak mümkün değil: `validate_sql`
  fonksiyonu BLOCKED_KEYWORDS (EXEC/EXECUTE/MERGE/...) ve "must start with SELECT/WITH"
  kuralları nedeniyle `SET SHOWPLAN_XML ON` ve `EXPLAIN PLAN FOR` ifadelerini reddeder.
  Bu nedenle `SafeSQLExecutor` üzerinde validation-bypass eden yeni bir `explain_plan()`
  method'u eklendi; ham connector aynı `_get_db_connector` yolundan açılıyor.
- `result_size_predictor._explain_row_estimate` zaten `plan.get("rows")` anahtarını
  tanıyor — wiring callable'ının `{"rows": N}` döndürmesi yeterli, predict_size
  node'a dokunmaya gerek yok.

### Touched files
1. `app/services/safe_sql_executor.py`
   - `SafeSQLExecutor.explain_plan(query, dialect, source) -> Dict` (yeni public API)
   - `SafeSQLExecutor._explain_mssql(conn, query, result)` (private)
   - `SafeSQLExecutor._explain_oracle(conn, query, result)` (private)
   - PG dalı: bilinçli olarak no-op (`error="pg_handled_elsewhere"`) — PG akışı
     mevcut `make_explain_callable` PG dalında değişmedi (backward compat).

2. `app/services/pipeline/wiring.py`
   - `make_explain_callable` içindeki MSSQL+Oracle iki ayrı `return None` dalı
     tek dala birleştirildi; `executor.explain_plan(sql, dialect=d, source=source_dict)`
     çağrılıyor, sonuç `{"rows": int(estimated_rows)}` formatında dönüyor.
   - Docstring güncellendi (MSSQL: SHOWPLAN_XML, Oracle: EXPLAIN PLAN + plan_table).
   - PG/MySQL dalları **değişmedi**.

### Method imzaları
```python
def explain_plan(
    self,
    query: str,
    dialect: str,                  # "mssql" | "sqlserver" | "oracle"
                                   # ("postgresql" -> no-op, geri uyum)
    source: dict,                  # data_sources satırı (db_password_encrypted dahil)
) -> Dict[str, Any]:
    """
    Returns:
        {
            "estimated_rows": int | None,
            "dialect": str,
            "raw": <XML kısaltma | dict | None>,
            "error": str | None,   # "no_plan_xml" | "plan_table_unavailable" | ...
        }
    """
```

### MSSQL XML parse stratejisi
- `xml.etree.ElementTree` (stdlib).
- `SET SHOWPLAN_XML ON` → query execute → `SET SHOWPLAN_XML OFF` (her durumda kapatılır,
  session leak yok).
- ShowPlanXML namespace'i ortadan kaldırılır (tag adı `}` sonrası alınır).
- Öncelik sırası: `StmtSimple/@StatementEstRows` → `RelOp/@EstimateRows` (DFS;
  en üst seviyede ilk eşleşmede dur). MSSQL float verir (ör. 1234.5) → `int(round(...))`.
- Plan XML 4000 char kısaltıp `raw` alanına debug için yazılır.
- `cur.nextset()` driver desteği varsa first non-empty result set'i tarayarak plan
  satırını bulur (bazı pyodbc sürümleri SHOWPLAN_XML'i ek result set'lere taşır).

### Oracle plan_table stratejisi
- `EXPLAIN PLAN SET STATEMENT_ID = 'vyra_<uuid24>' FOR <query>` — uuid4 hex 24 char,
  collision riski sıfıra yakın.
- `SELECT cardinality FROM plan_table WHERE statement_id = :sid AND id = 0` — top-level
  (root) operation satırının cardinality'si en doğru toplam tahmin.
- Bind parameter (`:sid`) kullanılıyor — string concat yok, injection risksiz.
- **Cleanup:** finally bloğunda `DELETE FROM plan_table WHERE statement_id = :sid` +
  `conn.commit()` (best-effort; exception swallow). Yalnızca `plan_inserted=True`
  ise çalışır → EXPLAIN PLAN fail etmişse boşa DELETE atılmaz.

### Güvenlik / edge case'ler
- **Query injection:** `query` zaten `state["sql"]` — pipeline validate node'undan
  geçmiş. Ayrıca çoklu statement koruması: `rstrip(';')` sonrası gövdede string-literal
  dışında `;` varsa `error="multi_statement_in_query"` ile reddedilir (MSSQL'de
  SHOWPLAN_XML ON modunda ikinci statement query'yi çalıştırırdı — bu kapı kapatıldı).
- **Boş query:** `error="empty_query"`.
- **Bilinmeyen dialect:** `error="unsupported_dialect:<d>"`.
- **PG çağrılırsa:** `error="pg_handled_elsewhere"` ile no-op döner; PG akışı
  `make_explain_callable` mevcut PG dalında bozulmadan çalışır.
- **plan_table yoksa (Oracle):** `error="plan_table_unavailable:<exc>"` → caller
  `None` görür → predictor reltuples/heuristic dalına düşer.
- **SHOWPLAN_XML driver fail:** `error="showplan_on_failed:<exc>"` → None →
  predictor heuristic.
- **XML parse fail:** `error="xml_parse_error:..."` → None → heuristic.
- **Connection cleanup:** Her dalda `finally: conn.close()`. MSSQL'de SHOWPLAN_XML
  her durumda OFF — connection pool'a kirli session dönmez.
- **Timeout:** Mevcut connection timeout (MSSQL login/CommandTimeout, Oracle
  call_timeout) uygulanır; ek timeout eklenmedi (brief gereği).
- **Dependency:** Sadece stdlib `xml.etree.ElementTree` + `uuid` + `re`. Yeni
  package yok.

### Backward compat
- PG EXPLAIN davranışı **değişmedi** — `make_explain_callable` PG/MySQL dalları
  birebir aynı kalıyor.
- MSSQL/Oracle eski davranışı `None` döndürmekti → predictor reltuples'a düşüyordu.
  Yeni davranışta plan alınabilirse `{"rows": N}` döner, alınamazsa **yine `None`**
  döner → predictor reltuples/heuristic dalları korunuyor.

### Verification
```bash
python -m py_compile app/services/safe_sql_executor.py app/services/pipeline/wiring.py
# OK
python -m pytest tests/ -k "explain or predict_size or safe_executor or safe_sql" -q
# 44 passed, 1 skipped, 2291 deselected in 17.37s
```

### Not-touched (disjoint scope)
- `app/services/pipeline/nodes/predict_size.py` — yok (predict_size logic
  `result_size_predictor.predict_size_node` içinde, dokunulmadı; mevcut
  `_explain_row_estimate` zaten `{"rows": N}` anahtarını tanıyor).
- `result_size_predictor.py` — dokunulmadı.
- Test dosyaları — brief gereği yazılmadı.
