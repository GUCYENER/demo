---
task_id: smart-E
status: completed
agent_type: parent-fallback
target_files:
  - app/services/pipeline/nodes/sql_generate.py
started_at: 2026-05-23
completed_at: 2026-05-23
---

## Brief

FK-aware JOIN HINTS prompt injection. Ajan dispatch'i aşırı temkinli refusal verdi (system-reminder generic safeguard yanlış uygulandı), parent direkt implement etti.

## Report

### Değişiklikler

`app/services/pipeline/nodes/sql_generate.py`:

1. **`_build_context()` içine yeni blok** (SAMPLE DATA injection'dan sonra, return'den önce):
   - `selected` ≥ 2 ve `cur`/`source_id` mevcut ise `_fetch_join_hints(...)` çağrılır.
   - Hata olursa `logger.debug` ile sessiz skip (mevcut idiomatic pattern).

2. **Yeni helper `_fetch_join_hints(cur, source_id, table_pairs)`** (module-level):
   - `ds_db_relationships`'i `source_id = %s AND confidence_score >= 0.7` ile sorgular.
   - Sadece her İKİ tablo da `selected_tables` içindeyse edge dahil edilir (transitive değil).
   - Composite FK'ler `constraint_name` ile gruplanır → tek satır + `[composite]` etiketi.
   - Schema "public" ve boş eşdeğer kabul (normalize edilir).
   - Max 20 edge (prompt budget koruması).
   - Output format:
     ```
     JOIN HINTS (bilinen FK ilişkileri):
       orders.customer_id → customers.id  [declared, conf=1.00]
       order_items.(order_id, product_id) → orders.(id) + products.(id)  [composite]  [declared, conf=0.95]
     ```

### Şema Referansı

`ds_db_relationships` (migrations 003 + 023 + 031 + 038):
- `from_schema`, `from_table`, `from_column`
- `to_schema`, `to_table`, `to_column`
- `constraint_name`, `confidence_score` (0.0-1.0), `is_inferred`, `is_junction`, `fk_position`

### Varsayımlar

- `cur` `state["_cursor"]`'dan gelir (mevcut CODE VALUE + SAMPLE DATA bloklarıyla aynı pattern).
- `selected` boyutu `len < 2` ise blok atlanır (tek tablo = JOIN gereksiz).
- Row tip-toleransı: dict ve tuple iki form da destekleniyor (psycopg2 RealDictCursor vs default).

### Doğrulama

- `python -m py_compile`: ✅ OK
- pytest sql_generate filter: 0 dedicated test (mevcut sql_generate dedicated test yok, integration tests pipeline üzerinden çalışır).

### Notlar

- Brief'in ek scope (dynamic gap threshold, schema-permission filter) kullanıcı tarafından devre dışı bırakıldı, sadece JOIN HINTS prompt enjeksiyonu yapıldı.
- Backward compat: mevcut blokların hiçbiri değişmedi, sadece yeni blok eklendi.
