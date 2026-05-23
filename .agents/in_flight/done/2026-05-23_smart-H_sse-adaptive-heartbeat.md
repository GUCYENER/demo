---
status: done
agent: smart-H
task: SSE Adaptive Heartbeat
target_files:
  - app/api/routes/dialog.py
started_at: 2026-05-23
completed_at: 2026-05-23
version: v3.32.0
---

# Smart-H — SSE Adaptive Heartbeat

## Brief

`/dialogs/{id}/messages/stream` SSE endpoint heartbeat'i sabit
`HEARTBEAT_INTERVAL = 15` saniyeydi. Uzun `execute_node` (örn. 30s büyük
query) sırasında proxy idle timeout riski yoktu ama heartbeat çok seyrekti;
kısa query'lerde de aynı sabit periyot. Hedef: pipeline aktif token üretirken
1s, idle iken kademeli olarak 5s'ye çıkan adaptive heartbeat.

## Report

### Değişiklik Kapsamı (TEK DOSYA)

- `app/api/routes/dialog.py`
  - **Eklenen modül-level config blok** (router tanımından sonra,
    yaklaşık L39–L69): `HEARTBEAT_MIN_INTERVAL`, `HEARTBEAT_MAX_INTERVAL`,
    `HEARTBEAT_BACKOFF_FACTOR` constants + `_sse_float_env()` helper.
  - **Yeniden yazılan generator** (yaklaşık L421–L495): eski sabit-interval
    döngüsü → exponential-backoff state machine.

### State Machine Logic

```python
idle_count = 0  # her gerçek event'te 0'a reset
while True:
    next_interval = min(
        HEARTBEAT_MIN_INTERVAL * (HEARTBEAT_BACKOFF_FACTOR ** idle_count),
        HEARTBEAT_MAX_INTERVAL,
    )
    try:
        event = q.get(timeout=next_interval)
    except _queue.Empty:
        yield ": heartbeat\n\n"
        idle_count += 1
        continue
    if event is SENTINEL:
        break
    idle_count = 0          # gerçek event → reset
    # ... yield f"data: {payload}\n\n"
```

**Default progression (MIN=1.0, MAX=5.0, FACTOR=1.5):**
`1.0s → 1.5s → 2.25s → 3.375s → 5.0s (cap) → 5.0s → ...`

**Gerçek event tanımı:** Producer queue'ya koyulan her şey (heartbeat hariç).
Mevcut pipeline event tipleri: `token`, `cache_hit`, `sample_data_preview`,
`size_prediction`, `clarification_v2`, `error`, `run_summary`, `status`,
`rag_complete`, `cached`, `done` — hepsi `idle_count = 0` reset'i tetikler.

### Env Override Convention

Module-level config env değişkenleri:

| Env var               | Default | Açıklama                          |
|-----------------------|---------|-----------------------------------|
| `VYRA_SSE_HB_MIN`     | `1.0`   | Minimum (başlangıç) interval — sn |
| `VYRA_SSE_HB_MAX`     | `5.0`   | Maximum (cap) interval — sn       |
| `VYRA_SSE_HB_FACTOR`  | `1.5`   | Exponential backoff çarpanı       |

Sanity guard'lar: `MIN <= 0` → 1.0; `MAX < MIN` → MIN; `FACTOR < 1.0` → 1.5.
Yanlış env değerleri sessizce default'a düşer (parsing exception yutulur).

### Heartbeat Payload

`: heartbeat\n\n` — SSE comment frame (RFC: `:` ile başlayan satır).
EventSource consume eder ama JS dispatch'i yoktur. Eski payload
`: keepalive\n\n` idi; semantik olarak ekvivalent — sadece etiket değişti.

### Backward Compatibility

- Davranış: idle pipeline hâlâ proxy timeout korumalı (max 5s interval, eski
  15s'den daha sıkı; Nginx default `proxy_read_timeout=60s` ile uyumlu).
- API kontratı (event format, headers) **değişmedi**.
- Mevcut test suite `tests/ -k "stream or sse or heartbeat"`:
  **97 passed, 1 skipped, 0 failed** (48.49s).

### Doğrulama

```
python -m py_compile app/api/routes/dialog.py        → OK
python -m pytest tests/ -k "stream or sse or heartbeat" -q
  → 97 passed, 1 skipped, 2238 deselected in 48.49s
```

### Dokunulmayan Dosyalar

Brief'in disjoint scope kuralı gereği yalnızca `app/api/routes/dialog.py`
düzenlendi. SSE helper (`app/services/sse/`) klasörü mevcut değil;
implementasyon doğrudan route generator'ında yapıldı (mevcut pattern).
