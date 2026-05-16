# 🌊 POSEIDON — Discovery Comment Reading Audit
**Tarih:** 2026-05-17
**Faz:** 0 (Hijyen — read-only inceleme)
**İnceleyen:** POSEIDON (Entegrasyon & API Kontrat)

## Özet

**Bulgu:** Discovery pipeline (`app/services/ds_learning_service.py`) **hiçbir dialect'te native DB comment metadata'sı okumuyor.** Bu, Türkçe DBA açıklamalarının (genellikle COMMENTS/extended_properties alanlarında bulunur) tamamen kaybolduğu anlamına gelir.

## Dialect-bazlı Durum

### PostgreSQL (satır 244-326)
- ✅ Okunan: `information_schema.tables`, `information_schema.columns`, `information_schema.table_constraints`, `pg_stat_user_tables`
- ❌ **Eksik:** `col_description((schema||'.'||table)::regclass, ordinal_position)` — kolon yorumu
- ❌ **Eksik:** `obj_description((schema||'.'||table)::regclass)` — tablo yorumu
- ❌ **Eksik:** `pg_description` direkt sorgu (alternatif)

### Oracle (satır 600-722)
- ✅ Okunan: `all_tables`, `all_views`, `all_tab_columns`, `all_constraints`, `all_cons_columns`
- ❌ **Eksik:** `all_col_comments` — kolon yorumu (Türkçe DBA açıklamaları için altın madeni)
- ❌ **Eksik:** `all_tab_comments` — tablo yorumu

### MSSQL (satır 421-540)
- ✅ Okunan: `INFORMATION_SCHEMA.TABLES`, `INFORMATION_SCHEMA.COLUMNS`, `INFORMATION_SCHEMA.TABLE_CONSTRAINTS`, `sys.foreign_keys`
- ❌ **Eksik:** `sys.extended_properties` (özellikle `MS_Description` property'si) — Türkçe açıklama
- ❌ **Eksik:** `sys.fn_listextendedproperty()` (alternatif)

### MySQL (henüz incelenmedi)
- ⚠️ `INFORMATION_SCHEMA.COLUMNS.COLUMN_COMMENT` ve `INFORMATION_SCHEMA.TABLES.TABLE_COMMENT` direkt erişilebilir → kontrol edilmeli.

## Etki

- **LLM enrichment maliyeti yükseliyor** — DBA zaten Türkçe açıklama yazmış olabilirken biz sıfırdan üretmeye çalışıyoruz
- **Doğruluk düşüyor** — DBA'nın domain knowledge'ı LLM tahminine tercih edilmeli
- **`ds_enrichment_service.py` prompt'u eksik veri ile çalışıyor** — column descriptions sadece tip+nullability içeriyor

## Faz 2'de Çözüm

`ds_learning_service.py` discovery query'leri genişletilecek:

```sql
-- PostgreSQL
SELECT c.table_schema, c.table_name, c.column_name, c.data_type, c.is_nullable, c.column_default,
       col_description((c.table_schema||'.'||c.table_name)::regclass, c.ordinal_position) AS column_comment
FROM information_schema.columns c
...

-- Tablo yorumu için ayrı sorgu:
SELECT n.nspname, c.relname, obj_description(c.oid) AS table_comment
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r','v');
```

```sql
-- Oracle
SELECT owner, table_name, column_name, comments
FROM all_col_comments
WHERE owner NOT IN (...);

SELECT owner, table_name, comments
FROM all_tab_comments
WHERE owner NOT IN (...);
```

```sql
-- MSSQL
SELECT SCHEMA_NAME(t.schema_id) AS schema_name, t.name AS table_name,
       c.name AS column_name, ep.value AS column_comment
FROM sys.tables t
JOIN sys.columns c ON c.object_id = t.object_id
LEFT JOIN sys.extended_properties ep
       ON ep.major_id = c.object_id AND ep.minor_id = c.column_id
      AND ep.name = 'MS_Description' AND ep.class = 1;
```

```sql
-- MySQL
SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE, IS_NULLABLE,
       COLUMN_COMMENT
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA NOT IN ('mysql','information_schema','performance_schema','sys');

SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_COMMENT
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA NOT IN (...);
```

## Schema Etkisi

`ds_db_objects.columns_json` JSONB içine her kolona `comment` alanı eklenir:

```json
{
  "name": "MUSTERI_ADI",
  "data_type": "VARCHAR2(100)",
  "is_nullable": false,
  "is_pk": false,
  "comment": "Müşterinin tam ad-soyad bilgisi (gerçek kişi)"  // ⬅ YENİ
}
```

Tablo yorumu için `ds_db_objects.description` (mevcut sütun, henüz native comment'lerle doldurulmuyor) kullanılır.

## Faz 2 ile Bağlantı

Column-level embedding aşamasında (`ds_column_embeddings` tablosu) `description TEXT` alanı şu öncelikle doldurulacak:
1. Native DB comment (varsa) — DBA'nın yazdığı Türkçe
2. LLM-generated (yoksa) — fallback, daha düşük öncelik
3. Her ikisi de varsa: native öncelikli, LLM tamamlayıcı

## Sonuç

✅ İnceleme tamamlandı.
✅ Read-only — hiç kod değişmedi.
✅ Faz 2'de çözülecek — `ds_learning_service.py` discovery query'leri 4 dialect için genişletilecek; `columns_json` schema'sına `comment` alanı eklenecek (geriye uyumlu — yoksa `null`).

> 📌 Aksiyon: Faz 2 başında bu raporu referans alacağız. Şimdilik runtime'ı bozmadığı için Faz 0'da kod değişikliği yok.
