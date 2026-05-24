"""LLM-driven column ordering suggestion for the DB Smart wizard Filtre step.

v3.34.x — B10 (Plan: 2026-05-25_0030_metric_filter_dnd_llm_v1)
Council: POSEIDON (data flow) + APOLLO (prompt + schema validation) + ARES (fail-closed).

The wizard Filtre step builds a drag-drop list of "columns the user wants in
the final report". The "✨ LLM ile öner" button posts the candidate column
list (plus the primary + join table ids and the source id, for FK context)
and gets back a reordered list with a short Turkish rationale.

Design rules:
    1. NEVER invent column names — the response `ordered` array must be a
       subset of the request `available_columns` names. If validation fails
       the heuristic fallback is used.
    2. NEVER raise on LLM transport failures — return heuristic ordering with
       `fallback=True` so the UI degrades gracefully.
    3. Tenant isolation is enforced by the API layer BEFORE calling this
       service; the service still uses RLS context defensively.
    4. Token budget is bounded — `available_columns` is capped at 30.
    5. Temperature pinned at 0.2 for ordering determinism.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.core.db import get_db_context
from app.core.llm import (
    LLMConfigError,
    LLMConnectionError,
    LLMResponseError,
    call_llm_api,
)
from app.services.db_smart import fk_graph
from app.services.db_smart.rls_context import apply_vyra_user_context

logger = logging.getLogger(__name__)

# Token budget guard (Plan Risk R-2).
MAX_COLUMNS_FOR_PROMPT = 30

# Heuristic ordering priority by semantic_type bucket.
# Lower number = leftmost. "other" sits between amount and fk.
_HEURISTIC_BUCKETS: Dict[str, int] = {
    "id": 0,
    "identifier": 0,
    "code": 1,
    "name": 2,
    "title": 2,
    "label": 2,
    "category": 3,
    "status": 3,
    "date": 4,
    "datetime": 4,
    "time": 4,
    "timestamp": 4,
    "amount": 5,
    "number": 5,
    "numeric": 5,
    "currency": 5,
    "quantity": 5,
    "percent": 5,
    "other": 6,
    "text": 6,
    "boolean": 6,
    "fk": 7,
    "foreign_key": 7,
    "reference": 7,
}


# ─────────────────────────────────────────────────────────────
# Helpers — table metadata + FK context
# ─────────────────────────────────────────────────────────────

def _fetch_table_names(
    cur, source_id: int, table_ids: List[int]
) -> Dict[int, str]:
    """Return {table_id: 'schema.object_name'} for the given ids on a source.

    Tolerant: ids missing from the result simply don't appear in the map.
    """
    if not table_ids:
        return {}
    # psycopg2 supports tuple expansion for IN; keep ids unique.
    uniq = list({int(t) for t in table_ids})
    try:
        cur.execute(
            """
            SELECT id, schema_name, object_name
            FROM ds_db_objects
            WHERE source_id = %s AND id = ANY(%s)
            """,
            (int(source_id), uniq),
        )
        out: Dict[int, str] = {}
        for row in cur.fetchall() or []:
            if isinstance(row, dict):
                tid = row.get("id")
                schema = row.get("schema_name") or ""
                obj = row.get("object_name") or ""
            else:
                tid, schema, obj = row[0], row[1] or "", row[2] or ""
            if tid is None:
                continue
            name = f"{schema}.{obj}" if schema else str(obj)
            out[int(tid)] = name
        return out
    except Exception as e:
        logger.warning(
            "[llm_column_order] _fetch_table_names failed source=%s ids=%s: %s",
            source_id, uniq, e,
        )
        return {}


def _fetch_fk_context(
    cur, source_id: int, table_ids: List[int]
) -> List[str]:
    """Best-effort short FK summary lines for the prompt.

    Returns a small list of strings like "musteriler ↔ siparisler (1 ilişki)".
    Empty list on failure — non-fatal.
    """
    if not table_ids:
        return []
    try:
        neighbors = fk_graph.expand_with_fk(
            cur,
            source_id=int(source_id),
            table_ids=[int(t) for t in table_ids],
            depth=1,
        ) or []
    except Exception as e:
        logger.info(
            "[llm_column_order] FK expand skipped source=%s tables=%s: %s",
            source_id, table_ids, e,
        )
        return []

    lines: List[str] = []
    # Cap at 10 to keep prompt small.
    for n in neighbors[:10]:
        try:
            schema = n.get("schema") or ""
            tbl = n.get("table") or ""
            rels = int(n.get("via_relationship_count") or 0)
            full = f"{schema}.{tbl}" if schema else tbl
            lines.append(f"- {full} ({rels} ilişki)")
        except Exception:
            continue
    return lines


# ─────────────────────────────────────────────────────────────
# Heuristic ordering — fallback when LLM is unavailable/invalid
# ─────────────────────────────────────────────────────────────

def _heuristic_order(columns: List[Dict[str, Any]]) -> List[str]:
    """Stable heuristic sort by semantic_type bucket; name-only secondary sort.

    NOTE (F8b): Returns name-only list for backwards compat. Use
    `_heuristic_order_pairs()` for the (name, table_id) form.
    """
    def keyfn(c: Dict[str, Any]):
        stype = (c.get("semantic_type") or "other").strip().lower()
        bucket = _HEURISTIC_BUCKETS.get(stype, _HEURISTIC_BUCKETS["other"])
        # Within bucket: column-name alpha for determinism.
        return (bucket, (c.get("name") or "").lower())

    return [c.get("name") or "" for c in sorted(columns, key=keyfn) if c.get("name")]


def _heuristic_order_pairs(columns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """F8b: heuristic sort returning [{name, table_id}] pairs.

    table_id is carried through when present in input; None otherwise.
    """
    def keyfn(c: Dict[str, Any]):
        stype = (c.get("semantic_type") or "other").strip().lower()
        bucket = _HEURISTIC_BUCKETS.get(stype, _HEURISTIC_BUCKETS["other"])
        return (bucket, (c.get("name") or "").lower())

    out: List[Dict[str, Any]] = []
    for c in sorted(columns, key=keyfn):
        nm = c.get("name") or ""
        if not nm:
            continue
        out.append({"name": nm, "table_id": c.get("table_id")})
    return out


# ─────────────────────────────────────────────────────────────
# LLM JSON parsing — defensive
# ─────────────────────────────────────────────────────────────

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    """Pull the first {...} JSON object from an LLM response string.

    Handles ```json fences, leading prose, etc. Returns None if no valid JSON.
    """
    if not text:
        return None
    s = text.strip()
    # Strip leading code fences.
    if s.startswith("```"):
        # remove starting ``` or ```json line
        s = re.sub(r"^```(?:json)?\s*", "", s, count=1)
        s = re.sub(r"\s*```\s*$", "", s, count=1)
    # First try whole string.
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Fallback: greedy first {...}.
    m = _JSON_BLOCK_RE.search(s)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────
# Prompt builder
# ─────────────────────────────────────────────────────────────

def _build_prompt(
    primary_table_name: Optional[str],
    join_table_names: List[str],
    fk_context_lines: List[str],
    columns: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Return chat-messages list for `call_llm_api`."""
    # F8b: aynı isimli kolonların farklı tablolardan geldiğini LLM'in görmesi
    # için her satıra table_id de eklenir. Çıktı formatı `ordered` artık
    # {name, table_id} nesne listesi olarak istenir; eski string formatı da
    # parser tarafından kabul edilir.
    cols_lines: List[str] = []
    any_has_tid = any((c.get("table_id") is not None) for c in columns)
    for c in columns:
        name = c.get("name") or ""
        stype = c.get("semantic_type") or "?"
        table = c.get("table") or "?"
        tid = c.get("table_id")
        if tid is not None:
            cols_lines.append(
                f"- {name}  (tip: {stype}, tablo: {table}, table_id: {tid})"
            )
        else:
            cols_lines.append(f"- {name}  (tip: {stype}, tablo: {table})")

    table_block_parts: List[str] = []
    if primary_table_name:
        table_block_parts.append(f"Ana tablo: {primary_table_name}")
    if join_table_names:
        table_block_parts.append("İlişkili tablolar: " + ", ".join(join_table_names))
    if fk_context_lines:
        table_block_parts.append("FK komşuları:\n" + "\n".join(fk_context_lines))
    table_block = "\n".join(table_block_parts) if table_block_parts else "Tablo bağlamı yok."

    # F8b: çıktı sözleşmesi — table_id varsa nesne formatı zorunlu (LLM aynı
    # isimli kolonları ayırt etsin). Yoksa eski string formatı yeterli.
    if any_has_tid:
        output_contract = (
            "Çıktı SADECE JSON: "
            "{\"ordered\": [{\"name\": \"col_name\", \"table_id\": 123}, ...], "
            "\"rationale\": \"kısa Türkçe açıklama\"}\n"
            "ÖNEMLİ: Aynı isimli kolonlar farklı tablolarda olabilir "
            "(örn. iki tabloda `id`). Her item'da hem `name` hem `table_id` "
            "alanlarını dahil et; `table_id` yukarıda her kolon için verildi."
        )
    else:
        output_contract = (
            "Çıktı SADECE JSON: "
            "{\"ordered\": [\"col_name1\", ...], "
            "\"rationale\": \"kısa Türkçe açıklama\"}"
        )

    user_prompt = (
        "Sen bir BI uzmanısın. Aşağıda bir raporun kaynak tablosu ve "
        "ilişkili tablolarının kolonları var.\n"
        "Bir BI kullanıcısının raporda göreceği en doğal kolon sırasını öner.\n"
        "Kural:\n"
        "- Identifier (id) sola\n"
        "- İsimler (name/title) sonra\n"
        "- Tarih kolonları orta\n"
        "- Tutar/sayısal kolonlar sağa\n"
        "- Foreign key id'ler grubun sonunda\n\n"
        f"{table_block}\n\n"
        "Mevcut kolonlar:\n"
        f"{chr(10).join(cols_lines)}\n\n"
        f"{output_contract}"
    )

    return [
        {
            "role": "system",
            "content": (
                "Sen bir kıdemli BI raporlama uzmanısın. Yalnızca geçerli JSON "
                "üret. Yorum veya açıklama ekleme. Asla yeni kolon adı uydurma; "
                "sadece sana verilen kolon adlarını kullan."
            ),
        },
        {"role": "user", "content": user_prompt},
    ]


# ─────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────

def suggest_order(
    source_id: int,
    primary_table_id: int,
    join_table_ids: List[int],
    available_columns: List[Dict[str, Any]],
    current_user: Dict[str, Any],
) -> Dict[str, Any]:
    """Suggest an ordered column list for a BI report.

    Args:
        source_id:           data_sources.id. Tenant scope is the CALLER's
                             responsibility (the route enforces company_id);
                             this service additionally applies RLS GUC.
        primary_table_id:    ds_db_objects.id of the report's primary table.
        join_table_ids:      ds_db_objects.id list of joined tables (may be []).
        available_columns:   List of {name, semantic_type?, table?}.
                             Capped at MAX_COLUMNS_FOR_PROMPT (30).
        current_user:        FastAPI auth dict ({id, company_id, is_admin, ...}).

    Returns:
        {
            "ordered":   [col_name, ...],   # always subset of input names
            "rationale": "kısa Türkçe açıklama",
            "fallback":  bool,              # True if heuristic was used
        }
    """
    # ── 1. Normalize + cap inputs ────────────────────────────
    # F8b: dedupe artık (name, table_id) çiftinde — aynı isimli kolonlar farklı
    # tablolardan gelirse her ikisini de tut. table_id verilmediyse first-wins
    # davranışına geri düş (legacy).
    cols_clean: List[Dict[str, Any]] = []
    seen_pairs: set = set()  # (name, table_id) çiftleri
    seen_legacy_names: set = set()  # table_id yok ise eski davranış
    for c in available_columns or []:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        tid_raw = c.get("table_id")
        try:
            tid = int(tid_raw) if tid_raw is not None else None
        except (TypeError, ValueError):
            tid = None
        if tid is not None:
            pair = (name, tid)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
        else:
            if name in seen_legacy_names:
                continue
            seen_legacy_names.add(name)
        cols_clean.append(
            {
                "name": name,
                "semantic_type": (c.get("semantic_type") or "").strip() or None,
                "table": (c.get("table") or "").strip() or None,
                "table_id": tid,
            }
        )
        if len(cols_clean) >= MAX_COLUMNS_FOR_PROMPT:
            break

    if not cols_clean:
        # Nothing to order — return empty deterministically.
        return {
            "ordered": [],
            "ordered_pairs": [],
            "rationale": "Sıralanacak kolon bulunamadı.",
            "fallback": True,
        }

    # F8b: valid_names eski davranış için tutulur (legacy fallback).
    # valid_pairs yeni davranış için (name, table_id) çiftleri.
    valid_names: set = {c["name"] for c in cols_clean}
    valid_pairs: set = {(c["name"], c["table_id"]) for c in cols_clean}
    any_has_tid: bool = any(c["table_id"] is not None for c in cols_clean)

    # ── 2. Pull table names + FK context (best-effort) ──────
    primary_name: Optional[str] = None
    join_names: List[str] = []
    fk_lines: List[str] = []
    try:
        with get_db_context() as conn:
            cur = conn.cursor()
            try:
                apply_vyra_user_context(cur, current_user)
            except Exception as e:
                # RLS apply failure is non-fatal here — we don't run any
                # tenant-sensitive query; we already trust source_id was
                # validated by the API layer. Still log.
                logger.info(
                    "[llm_column_order] RLS apply soft-fail (continuing): %s", e
                )
            all_ids = [int(primary_table_id)] + [int(t) for t in (join_table_ids or [])]
            name_map = _fetch_table_names(cur, int(source_id), all_ids)
            primary_name = name_map.get(int(primary_table_id))
            join_names = [
                name_map[int(t)] for t in (join_table_ids or [])
                if int(t) in name_map
            ]
            fk_lines = _fetch_fk_context(
                cur, int(source_id),
                [int(primary_table_id)] + [int(t) for t in (join_table_ids or [])],
            )
    except Exception as e:
        # DB unavailable → still attempt LLM with raw column list only.
        logger.warning("[llm_column_order] metadata lookup failed: %s", e)

    # ── 3. LLM call (defensive) ─────────────────────────────
    messages = _build_prompt(primary_name, join_names, fk_lines, cols_clean)
    try:
        raw = call_llm_api(messages, temperature=0.2)
    except (LLMConnectionError, LLMConfigError) as e:
        logger.info("[llm_column_order] LLM unavailable, heuristic fallback: %s", e)
        return {
            "ordered": _heuristic_order(cols_clean),
            "ordered_pairs": _heuristic_order_pairs(cols_clean),
            "rationale": "LLM servisine ulaşılamadı; heuristik sıra uygulandı.",
            "fallback": True,
        }
    except LLMResponseError as e:
        logger.info("[llm_column_order] LLM bad response, heuristic fallback: %s", e)
        return {
            "ordered": _heuristic_order(cols_clean),
            "ordered_pairs": _heuristic_order_pairs(cols_clean),
            "rationale": "LLM yanıt formatı geçersiz; heuristik sıra uygulandı.",
            "fallback": True,
        }
    except Exception as e:
        # Defense in depth — never propagate.
        logger.warning("[llm_column_order] LLM unexpected error: %s", e)
        return {
            "ordered": _heuristic_order(cols_clean),
            "ordered_pairs": _heuristic_order_pairs(cols_clean),
            "rationale": "LLM beklenmedik hata; heuristik sıra uygulandı.",
            "fallback": True,
        }

    # ── 4. Parse + validate LLM JSON ────────────────────────
    parsed = _extract_json_obj(raw)
    if not parsed or "ordered" not in parsed:
        logger.info(
            "[llm_column_order] LLM JSON unparseable, heuristic fallback. raw_head=%r",
            (raw or "")[:200],
        )
        return {
            "ordered": _heuristic_order(cols_clean),
            "ordered_pairs": _heuristic_order_pairs(cols_clean),
            "rationale": "LLM yanıtı doğrulanamadı; heuristik sıra uygulandı.",
            "fallback": True,
        }

    ordered_raw = parsed.get("ordered") or []
    if not isinstance(ordered_raw, list):
        return {
            "ordered": _heuristic_order(cols_clean),
            "ordered_pairs": _heuristic_order_pairs(cols_clean),
            "rationale": "LLM yanıtı doğrulanamadı; heuristik sıra uygulandı.",
            "fallback": True,
        }

    # F8b: name→[pair, ...] index for legacy string fallback (first-match
    # when LLM returns string without table_id disambiguator).
    name_to_pairs: Dict[str, List[Dict[str, Any]]] = {}
    for c in cols_clean:
        name_to_pairs.setdefault(c["name"], []).append(c)

    ordered_pairs: List[Dict[str, Any]] = []
    seen_pair_keys: set = set()  # (name, table_id) tuples already consumed
    legacy_first_match_used = False

    for item in ordered_raw:
        name: Optional[str] = None
        tid: Optional[int] = None
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            n = item.get("name")
            if isinstance(n, str):
                name = n.strip()
            tid_raw = item.get("table_id")
            try:
                tid = int(tid_raw) if tid_raw is not None else None
            except (TypeError, ValueError):
                tid = None
        else:
            continue
        if not name or name not in valid_names:
            continue

        if tid is not None and (name, tid) in valid_pairs:
            key = (name, tid)
            if key in seen_pair_keys:
                continue
            seen_pair_keys.add(key)
            ordered_pairs.append({"name": name, "table_id": tid})
        else:
            # Legacy / no table_id from LLM. Pick the first not-yet-used pair
            # for this name. Log a warning if we expected disambiguation
            # (any_has_tid=True and there are multiple candidates).
            candidates = name_to_pairs.get(name, [])
            unused = [c for c in candidates if (c["name"], c["table_id"]) not in seen_pair_keys]
            if not unused:
                continue
            pick = unused[0]
            key = (pick["name"], pick["table_id"])
            seen_pair_keys.add(key)
            ordered_pairs.append({"name": pick["name"], "table_id": pick["table_id"]})
            if any_has_tid and len(candidates) > 1:
                legacy_first_match_used = True

    if legacy_first_match_used:
        logger.warning(
            "[llm_column_order] LLM returned items without table_id while input "
            "had multi-table duplicates; first-match heuristic applied — slot "
            "may reference wrong table for ambiguous columns."
        )

    # If LLM dropped some pairs, append the rest in heuristic order.
    missing_pairs = [
        c for c in cols_clean
        if (c["name"], c["table_id"]) not in seen_pair_keys
    ]
    if missing_pairs:
        missing_sorted = _heuristic_order_pairs(missing_pairs)
        for p in missing_sorted:
            key = (p["name"], p["table_id"])
            if key in seen_pair_keys:
                continue
            seen_pair_keys.add(key)
            ordered_pairs.append(p)

    # Final sanity: ordered_pairs must be exactly the same multiset as valid_pairs.
    if {(p["name"], p["table_id"]) for p in ordered_pairs} != valid_pairs:
        logger.info(
            "[llm_column_order] post-merge pair-mismatch, heuristic fallback. "
            "ordered_pairs=%d valid_pairs=%d",
            len(ordered_pairs), len(valid_pairs),
        )
        return {
            "ordered": _heuristic_order(cols_clean),
            "ordered_pairs": _heuristic_order_pairs(cols_clean),
            "rationale": "LLM yanıtı doğrulanamadı; heuristik sıra uygulandı.",
            "fallback": True,
        }

    rationale = parsed.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        rationale = "LLM önerisi uygulandı."

    # Legacy `ordered` (List[str]) — multi-table'da aynı isim iki kez tekrar
    # edebilir; eski client'lar muhtemelen ilkini gösterir. Yeni client
    # `ordered_pairs`'i kullanmalıdır.
    ordered_names: List[str] = [p["name"] for p in ordered_pairs]

    return {
        "ordered": ordered_names,
        "ordered_pairs": ordered_pairs,
        "rationale": rationale.strip()[:500],
        "fallback": False,
    }
