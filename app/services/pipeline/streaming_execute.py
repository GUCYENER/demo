"""
streaming_execute — Faz 6b
==========================
Server-side cursor üzerinden batch'lik satır yield eden generator.

Mevcut execute_node bir kerede tüm satırları belleğe alıp döner —
büyük sonuçlar için problemli. Bu modül:
    1) named cursor (PG server-side) veya fetchmany loop ile satırları
       sabit boyutlu batch'ler hâlinde yield eder
    2) SSE event'lere kolay map edilebilir dict yapıları döner

Kullanım (sync):
    for evt in stream_execute(execute_callable, sql, batch_size=200):
        # evt: {"type": "columns"|"rows"|"end"|"error", ...}
        ...

Kullanım (async iterator istenirse caller'da):
    async def agen():
        for evt in stream_execute(...):
            yield evt; await asyncio.sleep(0)

Beklenen `execute_callable` imzaları (tek bir tanesini destekler):
    A) "stream-aware":
       callable(sql, batch_size=200, mode='stream') -> Iterator[dict]
       Iterator dict şekli:
         - {"columns": [...]}
         - {"rows": [[...], ...]}
         - {"row_count": N, "elapsed_ms": M, "truncated": bool}
    B) "buffered":
       callable(sql) -> {"rows": [...], "columns": [...], "row_count": N, ...}
       → bu durumda bellekteki sonuç batch'lere bölünür (fallback)

Public API:
    stream_execute(execute_callable, sql, *, batch_size=200, max_rows=None)
        -> Iterator[Dict[str, Any]]

    StreamEvent type'ları:
        "start"   {"sql_preview": "..."}
        "columns" {"columns": [...]}
        "rows"    {"rows": [...], "batch_index": k}
        "end"     {"row_count": N, "elapsed_ms": M, "truncated": bool}
        "error"   {"message": "..."}
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, Iterator, List, Optional


DEFAULT_BATCH_SIZE = 200
DEFAULT_MAX_ROWS = 100_000  # güvenlik tavanı


def _slice_into_batches(rows: List[Any], batch_size: int) -> Iterator[List[Any]]:
    for i in range(0, len(rows), batch_size):
        yield rows[i : i + batch_size]


def stream_execute(
    execute_callable: Callable[..., Any],
    sql: str,
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_rows: Optional[int] = DEFAULT_MAX_ROWS,
) -> Iterator[Dict[str, Any]]:
    """
    SQL'i yürütüp batch event'leri yield eden generator.

    Stream-aware callable varsa onu kullanır; yoksa buffered çağrı yapıp
    sonucu batch'lere böler.
    """
    sql = (sql or "").strip()
    if not sql:
        yield {"type": "error", "message": "empty_sql"}
        return

    yield {"type": "start", "sql_preview": sql[:160]}
    started = time.perf_counter()

    # A) stream-aware deneme
    streamed = False
    try:
        gen = execute_callable(sql, batch_size=batch_size, mode="stream")
    except TypeError:
        gen = None  # buffered fallback
    except Exception as e:
        yield {"type": "error", "message": f"execute_error: {e}"}
        return

    if gen is not None and hasattr(gen, "__iter__"):
        batch_idx = 0
        row_count = 0
        columns_sent = False
        truncated = False
        try:
            for chunk in gen:
                if not isinstance(chunk, dict):
                    continue
                if "columns" in chunk and not columns_sent:
                    yield {"type": "columns", "columns": list(chunk["columns"])}
                    columns_sent = True
                if "rows" in chunk and chunk["rows"]:
                    rows = chunk["rows"]
                    remaining = (max_rows - row_count) if max_rows is not None else None
                    if remaining is not None and len(rows) > remaining:
                        rows = rows[:remaining]
                        truncated = True
                    if rows:
                        yield {"type": "rows", "rows": rows, "batch_index": batch_idx}
                        batch_idx += 1
                        row_count += len(rows)
                    if truncated:
                        break
                # final metadata chunk
                if "row_count" in chunk or "elapsed_ms" in chunk:
                    pass  # son end event'inde dolduracağız
            streamed = True
        except Exception as e:
            yield {"type": "error", "message": f"stream_error: {e}"}
            return

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        yield {
            "type": "end",
            "row_count": row_count,
            "elapsed_ms": elapsed_ms,
            "truncated": truncated,
        }
        return

    # B) buffered fallback
    if not streamed:
        try:
            result = execute_callable(sql)
        except Exception as e:
            yield {"type": "error", "message": f"execute_error: {e}"}
            return

        if not isinstance(result, dict):
            yield {"type": "error", "message": "invalid_execute_result"}
            return

        columns = result.get("columns") or []
        rows = result.get("rows") or []
        truncated = bool(result.get("truncated", False))

        if max_rows is not None and len(rows) > max_rows:
            rows = rows[:max_rows]
            truncated = True

        if columns:
            yield {"type": "columns", "columns": list(columns)}

        for idx, batch in enumerate(_slice_into_batches(rows, batch_size)):
            yield {"type": "rows", "rows": batch, "batch_index": idx}

        elapsed_ms = int(result.get("elapsed_ms") or (time.perf_counter() - started) * 1000)
        yield {
            "type": "end",
            "row_count": int(result.get("row_count", len(rows))),
            "elapsed_ms": int(elapsed_ms),
            "truncated": truncated,
        }


def stream_to_sse(event: Dict[str, Any]) -> str:
    """Stream event → SSE wire format. event['type'] → SSE 'event:' alanı."""
    import json
    etype = event.get("type", "message")
    data = {k: v for k, v in event.items() if k != "type"}
    return f"event: {etype}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
