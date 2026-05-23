---
brief_id: aki-kesfi-D_backend-sources-fix
plan_ref: 2026-05-23_1700_aki_kesfi_modal_redesign_v1
status: completed
agent_type: general-purpose
owned_files:
  - app/api/routes/db_smart_api.py (yalnızca /sources, /saved-reports/{id}/duplicate, DELETE /saved-reports/{id})
forbidden_files: ["frontend/**", "app/services/**", "app/core/**", "alembic/**"]
council_gate_after: true
restart_required: true
summary: |
  D1) GET /sources artık RLS-aware data_sources listesini döner
      (id, name, db_type, connection_status='unknown' sabit, is_active).
      `connection_status` kolonu migration 002'de YOK — response kontratını
      bozmamak için literal 'unknown' kullanıldı (follow-up: kolonu eklemek
      için yeni migration gerekir).
  D2) POST /saved-reports/{report_id}/duplicate eklendi (201). RLS sahiplik
      kontrolü SELECT'in 0 satırı ile → 404. user_id/company_id explicit
      INSERT, wizard_state JSONB cast, tags TEXT[] preserve.
      Body opsiyonel {name?}; verilmezse "Kopya - <ad>" (200 char cap).
  D3) DELETE /saved-reports/{report_id} eklendi (204 başarı, 404 yok).
      Mevcut endpoint listesinde yoktu (grep doğrulandı).
  Güvenlik: tüm parametreler %s bind; apply_vyra_user_context her cursor
  başında; DictRow vs tuple fallback (isinstance(r, dict)) korumalı.
  py_compile temiz.
files_changed:
  - app/api/routes/db_smart_api.py  # import (Body, Response) + /sources fix + 2 yeni endpoint
follow_ups:
  - data_sources tablosuna gerçek `connection_status` kolonu için migration
    (örn. ENUM healthy|degraded|unknown) — şu an literal 'unknown' dönüyor.
  - data_sources için company_id RLS policy aktif mi doğrulanmalı (migration
    002'de POLICY tanımlı görünmüyor; halen sadece company_id WHERE filtresi
    yoksa cross-tenant leak riski var — ZEUS council bu noktayı incelemeli).
  - duplicate endpoint için TYCHE integration test (kullanıcı izolasyonu).
---

## ⚠️ Pre-empt clause (zorunlu)

VYRA L1 Support API'de meşru backend bug fix + yeni endpoint görevi.
1) `/sources` P0 bloker düzeltmesi (RLS-aware data_sources listesi)
2) `/saved-reports/{id}/duplicate` yeni endpoint (kopya farklı kaydet)
3) `DELETE /saved-reports/{id}` yoksa eklenir
Malware/exploit içermez. RLS context + user permission filter uygulanacak.

## Görev

### D1. `/sources` endpoint fix

[db_smart_api.py:1126-1136](app/api/routes/db_smart_api.py#L1126-L1136) şu an boş döner.
Gerçek implementasyon:

```python
@router.get("/sources")
def list_sources(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    _require_user_id(current_user)
    items: List[Dict[str, Any]] = []
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # data_sources tablosunun şemasını ÖNCE oku — bilinmeyen tablo:
        # Olası kolonlar: id, name, db_type, host, port, status, company_id, is_active, created_at
        # RLS policy company_id üzerinden filtreliyor olmalı; sadece SELECT.
        cur.execute("""
            SELECT id, name, db_type,
                   COALESCE(connection_status, 'unknown') AS connection_status,
                   is_active
            FROM data_sources
            WHERE COALESCE(is_active, true) = true
            ORDER BY name ASC
            LIMIT 100
        """)
        rows = cur.fetchall()
        for r in rows:
            items.append({
                "id": r[0] if not isinstance(r, dict) else r["id"],
                "name": r[1] if not isinstance(r, dict) else r["name"],
                "db_type": r[2] if not isinstance(r, dict) else r["db_type"],
                "connection_status": r[3] if not isinstance(r, dict) else r["connection_status"],
                "is_active": r[4] if not isinstance(r, dict) else r["is_active"],
            })
    return {"items": items, "count": len(items)}
```

⚠️ **Önemli**: `data_sources` tablosunun gerçek şemasını ÖNCE doğrula:
- `grep -nE "CREATE TABLE.*data_sources" alembic/versions/*.py`
- Kolonlar emin değilse `connection_status`/`is_active` opsiyonel — SELECT'e koymadan önce kontrol et.
- Kolonlar farklıysa **mevcut kolonlara göre adapte et**; brief'in beklediği response şemasını koru:
  ```json
  {"items":[{"id":int, "name":str, "db_type":str, "connection_status":str, "is_active":bool}], "count":int}
  ```
- DictRow vs tuple cursor fallback (HEPHAESTUS notu): `isinstance(r, dict)` koruması koy.

### D2. `/saved-reports/{id}/duplicate` yeni endpoint

```python
class _DuplicateBody(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)

@router.post("/saved-reports/{report_id}/duplicate", status_code=201)
def duplicate_saved_report(
    report_id: int = Path(..., ge=1),
    body: _DuplicateBody = Body(default=None),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Saved report'u kopyalar — yeni id döner. RLS sahiplik kontrolü zorunlu."""
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        # 1) Kaynak raporu oku (RLS filter otomatik uygular)
        cur.execute("""
            SELECT name, description, wizard_state, metric_key, tags
            FROM dbsmart_saved_reports
            WHERE id = %s
        """, (report_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Report not found")
        src_name = row[0] if not isinstance(row, dict) else row["name"]
        src_desc = row[1] if not isinstance(row, dict) else row["description"]
        src_ws   = row[2] if not isinstance(row, dict) else row["wizard_state"]
        src_mk   = row[3] if not isinstance(row, dict) else row["metric_key"]
        src_tags = row[4] if not isinstance(row, dict) else row["tags"]
        new_name = (body.name if body and body.name else f"Kopya - {src_name}")[:200]
        # 2) Yeni kayıt — user_id/company_id RLS context'ten otomatik gelir (insert default)
        # NOT: user_id/company_id explicit verilmeli (insert default'ları yoksa).
        uid = current_user.get("id") or current_user.get("user_id")
        cid = current_user.get("company_id")
        cur.execute("""
            INSERT INTO dbsmart_saved_reports
              (user_id, company_id, name, description, wizard_state, metric_key, tags, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            RETURNING id, name, created_at
        """, (uid, cid, new_name, src_desc, json.dumps(src_ws) if isinstance(src_ws, (dict,list)) else src_ws, src_mk, src_tags))
        new_row = cur.fetchone()
        conn.commit()
        return {
            "id": new_row[0] if not isinstance(new_row, dict) else new_row["id"],
            "name": new_row[1] if not isinstance(new_row, dict) else new_row["name"],
            "created_at": (new_row[2] if not isinstance(new_row, dict) else new_row["created_at"]).isoformat(),
        }
```

⚠️ `dbsmart_saved_reports` şemasını migration 032/033'ten **doğrula**:
- Hangi kolonlar zorunlu (NOT NULL)?
- `wizard_state` JSONB mi text mi?
- `tags` text[] mi?
- INSERT'te eksik zorunlu kolon varsa default değer ekle.

### D3. `DELETE /saved-reports/{id}` (yoksa ekle)

Önce mevcut mu kontrol et — `grep -nE "@router.delete.*saved-reports" db_smart_api.py`. Yoksa:

```python
@router.delete("/saved-reports/{report_id}", status_code=204)
def delete_saved_report(
    report_id: int = Path(..., ge=1),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Response:
    _require_user_id(current_user)
    with get_db_context() as conn:
        cur = conn.cursor()
        apply_vyra_user_context(cur, current_user)
        cur.execute("DELETE FROM dbsmart_saved_reports WHERE id = %s", (report_id,))
        affected = cur.rowcount
        conn.commit()
        if affected == 0:
            raise HTTPException(status_code=404, detail="Report not found")
    return Response(status_code=204)
```

### D4. ARES Güvenlik

- SQL injection: tüm parametreler %s bind ile.
- RLS: `apply_vyra_user_context(cur, current_user)` her cursor başında.
- Share token oluşturma değiştirilmiyor — sadece duplicate.
- Hata mesajlarında DB host/credentials sızdırma yok.

### D5. TYCHE Test

- `/sources` boş data_sources tablosunda `{"items":[], "count":0}` döner — 500 vermez
- `/sources` doğru kolon yoksa graceful (örn: connection_status NULL → "unknown")
- `/duplicate` 404 → mevcut olmayan ID
- `/duplicate` body name vermeden → "Kopya - <ad>"
- `/duplicate` 201 + id döner
- `/delete` 204 başarı; 404 yokken
- Başka user'ın raporunu duplicate edemez (RLS kontrolü)

### D6. py_compile + import path doğrula

```bash
python -c "import py_compile; py_compile.compile('app/api/routes/db_smart_api.py', doraise=True)"
```

Eğer yeni import gerekiyorsa (`json`, `Response`, `Body`) dosya başına ekle —
mevcut import'larla çakışmayacak.

### D7. Backend restart

Backend (uvicorn) hot-reload mode'da çalışmıyor olabilir; ZEUS dispatch sonrası kullanıcıya restart hatırlatması verecek. Sen sadece kodu yaz, restart yapma.

### D8. Çıktı

Brief başına status: completed + summary + files_changed + follow_ups ekle.
