"""Metric library engine — applicable_when match + skor sıralama (v3.30.0 FAZ 1 P3 G1.4).

Akış:
    1. load_table_signature(cur, source_id, table_id) → tablo metadata snapshot
       (object_name, row_count_estimate, columns: [{name, data_type, semantic_type}])
    2. list_eligible(cur, table_signature, user_ctx, min_score=0.6):
         dbsmart_metric_library'i tarayıp applicable_when'i eşleştir → skor hesapla → sırala
    3. get_template(metric_key, dialect) → SQL template + parametre listesi
    4. record_usage(metric_key, success, user_ctx) → usage_count++ + success_rate moving average

applicable_when JSONB şeması (033 migration'da seed edildi):
    {
      "requires_columns": ["measure_numeric", "dimension_categorical", "created_at", ...],
      "min_rows": int,
      "cardinality_max": int,
      "table_hints": ["ticket", "order", ...]
    }

ds_column_enrichments.semantic_type sözlüğü (ds_enrichment_service.py:270):
    id / name / date / amount / status / code / description / flag / quantity / other
"""
from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _col(row: Any, key: str, idx: int) -> Any:
    """RealDictCursor + tuple cursor uyumu — kolon adıyla eriş."""
    if row is None:
        return None
    return row[key] if isinstance(row, dict) else row[idx]


# Skor ağırlıkları — plan G1.4 (pattern × 0.5 + usage_norm × 0.3 + user_pref × 0.2)
W_PATTERN = 0.5
W_USAGE = 0.3
W_USER_PREF = 0.2

# Usage normalization referansı (log skala) — 100 kullanım ≈ 1.0
USAGE_NORM_REF = 100.0


# ─────────────────────────────────────────────────────────────
# Semantic tag matchers
# ─────────────────────────────────────────────────────────────
# Her tag bir kolon sözlüğünü kabul edip True/False döner.
# Kolon: {"name": str, "data_type": str, "semantic_type": str}
# Eşleme iki yollu: (1) saf semantic_type, (2) isim regex'i (TR + EN).

def _col_name_lower(c: Dict[str, Any]) -> str:
    return (c.get("name") or "").lower()


def _sem(c: Dict[str, Any]) -> str:
    return (c.get("semantic_type") or "").lower()


SEMANTIC_TAG_MATCHERS: Dict[str, Callable[[Dict[str, Any]], bool]] = {
    # Pure semantic
    "any":                   lambda c: True,
    "date_column":           lambda c: _sem(c) == "date",
    "date":                  lambda c: _sem(c) == "date",
    "measure_numeric":       lambda c: _sem(c) in ("amount", "quantity"),
    "dimension_categorical": lambda c: _sem(c) in ("code", "status", "flag"),
    "dimension_any":         lambda c: _sem(c) in ("code", "status", "flag", "name", "id"),

    # Hybrid (semantic + name regex)
    "created_at":   lambda c: _sem(c) == "date" and bool(re.search(r"creat|olus|tarih_olus|create_dat|olusturma", _col_name_lower(c))),
    "closed_at":    lambda c: _sem(c) == "date" and bool(re.search(r"clos|kapan|resol|cozum|kapatma", _col_name_lower(c))),
    "first_response_at": lambda c: _sem(c) == "date" and bool(re.search(r"first_resp|ilk_yanit|first_reply|ilk_cevap", _col_name_lower(c))),
    "sla_deadline": lambda c: bool(re.search(r"sla|deadline|son_tarih|due", _col_name_lower(c))),

    "amount":       lambda c: _sem(c) == "amount" or bool(re.search(r"amount|tutar|fiyat|price|revenue|ucret", _col_name_lower(c))),

    "status":       lambda c: _sem(c) == "status" or bool(re.search(r"status|durum|state", _col_name_lower(c))),
    "priority":     lambda c: bool(re.search(r"priorit|oncelik|onem", _col_name_lower(c))),
    "status_history": lambda c: bool(re.search(r"reopen|tekrar|status_hist|durum_gec", _col_name_lower(c))),

    "customer_id":  lambda c: bool(re.search(r"customer|musteri|client", _col_name_lower(c))),
    "product_id":   lambda c: bool(re.search(r"product|urun|sku", _col_name_lower(c))),

    "team_or_assignee": lambda c: bool(re.search(r"team|assignee|owner|atanan|sorumlu|takim", _col_name_lower(c))),
    "city_or_region":   lambda c: bool(re.search(r"city|region|sehir|bolge|state|ilce|il_", _col_name_lower(c))),
}


def _match_required_tag(tag: str, columns: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Tag'i sağlayan ilk kolon (varsa) — yoksa None.

    Bilinmeyen tag'ler için son çare: kolon adında alt-string araması.
    """
    matcher = SEMANTIC_TAG_MATCHERS.get(tag)
    if matcher is not None:
        for c in columns:
            try:
                if matcher(c):
                    return c
            except Exception as e:
                logger.debug("[metric_engine] matcher %s failed: %s", tag, e)
        return None
    # Bilinmeyen tag → kolon adı substring fallback (örn. "amount" gibi ek tag'ler)
    needle = tag.lower()
    for c in columns:
        if needle in _col_name_lower(c):
            return c
    return None


# ─────────────────────────────────────────────────────────────
# Table signature loader
# ─────────────────────────────────────────────────────────────

def load_table_signature(
    cur: Any,
    source_id: int,
    table_id: int,
) -> Optional[Dict[str, Any]]:
    """ds_db_objects + ds_column_enrichments birleşik snapshot.

    Returns None → tablo bulunamadı (yetkisiz veya yanlış id).
    """
    cur.execute(
        """
        SELECT id, schema_name, object_name, row_count_estimate, columns_json
          FROM ds_db_objects
         WHERE id = %s AND source_id = %s
        """,
        (table_id, source_id),
    )
    row = cur.fetchone()
    if not row:
        return None
    tid = _col(row, 'id', 0)
    schema_name = _col(row, 'schema_name', 1)
    object_name = _col(row, 'object_name', 2)
    row_count = _col(row, 'row_count_estimate', 3)
    columns_json = _col(row, 'columns_json', 4)
    cols_raw: List[Dict[str, Any]] = []
    if isinstance(columns_json, list):
        cols_raw = columns_json
    elif isinstance(columns_json, str):
        try:
            parsed = json.loads(columns_json)
            if isinstance(parsed, list):
                cols_raw = parsed
        except Exception:
            cols_raw = []

    # ds_column_enrichments'ten semantic_type'ları çek (enrichment JOIN)
    enrich_map: Dict[str, Dict[str, Any]] = {}
    try:
        cur.execute(
            """
            SELECT ce.column_name, ce.semantic_type, ce.business_name_tr
              FROM ds_column_enrichments ce
              JOIN ds_table_enrichments te ON te.id = ce.table_enrichment_id
             WHERE te.source_id = %s
               AND LOWER(COALESCE(te.schema_name, '')) = LOWER(COALESCE(%s, ''))
               AND LOWER(te.table_name) = LOWER(%s)
            """,
            (source_id, schema_name, object_name),
        )
        for er in cur.fetchall() or []:
            cn = _col(er, 'column_name', 0)
            st = _col(er, 'semantic_type', 1)
            bn = _col(er, 'business_name_tr', 2)
            enrich_map[(cn or "").lower()] = {
                "semantic_type": (st or "other").lower(),
                "business_name_tr": bn,
            }
    except Exception as e:
        # ds_table_enrichments yoksa veya RLS engelliyorsa — sessiz devam
        logger.debug("[metric_engine] enrichment join skipped: %s", e)

    columns: List[Dict[str, Any]] = []
    for c in cols_raw:
        name = (c.get("name") or c.get("column_name") or "")
        if not name:
            continue
        enr = enrich_map.get(name.lower(), {})
        columns.append({
            "name": name,
            "data_type": c.get("type") or c.get("data_type"),
            "semantic_type": enr.get("semantic_type") or _infer_semantic_from_type(c.get("type") or c.get("data_type")),
            "business_name_tr": enr.get("business_name_tr"),
        })

    return {
        "table_id": tid,
        "schema_name": schema_name,
        "object_name": object_name,
        "row_count": int(row_count or 0),
        "columns": columns,
    }


def _infer_semantic_from_type(data_type: Optional[str]) -> str:
    """Enrichment yokken DB tipinden kaba semantic_type tahmini."""
    if not data_type:
        return "other"
    t = data_type.lower()
    if any(k in t for k in ("date", "time", "timestamp")):
        return "date"
    if any(k in t for k in ("int", "numeric", "decimal", "float", "double", "real", "money")):
        return "amount"
    if "bool" in t:
        return "flag"
    return "other"


# ─────────────────────────────────────────────────────────────
# Skor ve eligibility
# ─────────────────────────────────────────────────────────────

def _check_applicable(
    applicable_when: Dict[str, Any],
    signature: Dict[str, Any],
) -> Tuple[bool, float, Dict[str, str]]:
    """applicable_when'i tablo imzasıyla eşleştir.

    Returns:
        (matches, pattern_strength_0_1, bindings_dict)
        bindings_dict: tag → seçilen kolon adı (ilk eşleşen) — UI'de placeholder hint.
    """
    if not applicable_when:
        return True, 0.5, {}

    bindings: Dict[str, str] = {}
    required = applicable_when.get("requires_columns") or []
    columns = signature.get("columns") or []
    row_count = signature.get("row_count") or 0

    # 1) requires_columns — her tag için en az 1 eşleşen kolon
    matched = 0
    if isinstance(required, list):
        for tag in required:
            if not isinstance(tag, str):
                continue
            c = _match_required_tag(tag, columns)
            if c is not None:
                matched += 1
                bindings[tag] = c["name"]
        if required and matched < len(required):
            return False, 0.0, {}

    # 2) min_rows
    min_rows = applicable_when.get("min_rows")
    if isinstance(min_rows, (int, float)) and row_count < min_rows:
        return False, 0.0, {}

    # 3) cardinality_max — semantic_type categorical olan en az 1 kolonun cardinality'si <= max
    # Cardinality stored kolonda yoksa heuristic: status/code/flag → düşük cardinality varsayımı
    card_max = applicable_when.get("cardinality_max")
    if isinstance(card_max, (int, float)):
        has_low_card_col = False
        for c in columns:
            card = c.get("cardinality")
            if isinstance(card, (int, float)):
                if card <= card_max:
                    has_low_card_col = True
                    break
            elif _sem(c) in ("status", "flag", "code"):
                # Heuristic: bu semantic'ler tipik olarak düşük cardinality
                has_low_card_col = True
                break
        if not has_low_card_col:
            return False, 0.0, {}

    # 4) table_hints — tablo adında alt-string
    hints = applicable_when.get("table_hints")
    hint_bonus = 0.0
    if isinstance(hints, list) and hints:
        tname = (signature.get("object_name") or "").lower()
        if any(isinstance(h, str) and h.lower() in tname for h in hints):
            hint_bonus = 0.2
        else:
            # table_hints var ama uymuyor → uygulanabilir değil
            return False, 0.0, {}

    # Pattern strength: required column match oranı + hint bonus (0..1 clip)
    base = 0.6  # tüm requires geçti
    if isinstance(required, list) and required:
        base = min(1.0, 0.6 + 0.1 * (matched - len(required)))  # tam eşleşmede 0.6
    strength = min(1.0, base + hint_bonus)
    return True, strength, bindings


def _usage_norm(usage_count: Optional[int]) -> float:
    """log skala: 0 kullanım → 0, USAGE_NORM_REF (100) → 1.0."""
    if not usage_count or usage_count <= 0:
        return 0.0
    return min(1.0, math.log(1 + usage_count) / math.log(1 + USAGE_NORM_REF))


def list_eligible(
    cur: Any,
    table_signature: Dict[str, Any],
    user_ctx: Dict[str, Any],
    min_score: float = 0.6,
    limit: int = 60,
) -> List[Dict[str, Any]]:
    """Tablo imzasına uyan ve skor >= min_score olan metric'leri sıralı döndür.

    Skor = pattern_strength * 0.5 + usage_norm * 0.3 + user_pref_match * 0.2
    """
    cur.execute(
        """
        SELECT metric_key, name_tr, category, sub_category, description_tr,
               default_viz, applicable_when, sql_templates,
               COALESCE(usage_count, 0) AS usage_count, success_rate
          FROM dbsmart_metric_library
         WHERE is_active IS TRUE OR is_active IS NULL
         ORDER BY category, metric_key
         LIMIT %s
        """,
        (max(int(limit), 1),),
    )
    rows = cur.fetchall() or []

    # user_preferences.frequent_metrics — boost listesi (opsiyonel)
    user_pref_set = _load_user_pref_metrics(cur, user_ctx)

    out: List[Dict[str, Any]] = []
    for r in rows:
        metric_key = _col(r, 'metric_key', 0)
        name_tr = _col(r, 'name_tr', 1)
        category = _col(r, 'category', 2)
        sub_cat = _col(r, 'sub_category', 3)
        desc = _col(r, 'description_tr', 4)
        default_viz = _col(r, 'default_viz', 5)
        applicable_when = _col(r, 'applicable_when', 6)
        sql_templates = _col(r, 'sql_templates', 7)
        usage = _col(r, 'usage_count', 8)
        # _success = _col(r, 'success_rate', 9)  # currently unused
        aw = applicable_when if isinstance(applicable_when, dict) else _safe_json(applicable_when)
        matches, strength, bindings = _check_applicable(aw or {}, table_signature)
        if not matches:
            continue
        user_pref = 1.0 if metric_key in user_pref_set else 0.0
        score = W_PATTERN * strength + W_USAGE * _usage_norm(usage) + W_USER_PREF * user_pref
        if score < min_score:
            continue
        out.append({
            "metric_key": metric_key,
            "name_tr": name_tr,
            "category": category,
            "sub_category": sub_cat,
            "description_tr": desc,
            "default_viz": default_viz,
            "applicable_when": aw or {},
            "sql_templates": sql_templates if isinstance(sql_templates, dict) else _safe_json(sql_templates) or {},
            "score": round(score, 4),
            "pattern_strength": round(strength, 4),
            "bindings": bindings,
        })

    out.sort(key=lambda m: m["score"], reverse=True)
    return out


def list_all_active(
    cur: Any,
    limit: int = 60,
) -> List[Dict[str, Any]]:
    """Tüm aktif metric library girdilerini döndür (fallback path).

    list_eligible() boş döndüğünde (örn. tablo enrichment yok, default skor < min_score)
    çağıran tarafın "tüm library'yi göster" davranışına geçebilmesi için kullanılır.

    Her item'a `fallback=True` flag eklenir. Skor / bindings hesaplanmaz; shape
    list_eligible'ın döndürdüğü item'larla aynı anahtarlara sahiptir.
    """
    cur.execute(
        """
        SELECT metric_key, name_tr, category, sub_category, description_tr,
               default_viz, applicable_when, sql_templates
          FROM dbsmart_metric_library
         WHERE is_active IS TRUE OR is_active IS NULL
         ORDER BY category, metric_key
         LIMIT %s
        """,
        (max(int(limit), 1),),
    )
    rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []
    for r in rows:
        metric_key = _col(r, 'metric_key', 0)
        name_tr = _col(r, 'name_tr', 1)
        category = _col(r, 'category', 2)
        sub_cat = _col(r, 'sub_category', 3)
        desc = _col(r, 'description_tr', 4)
        default_viz = _col(r, 'default_viz', 5)
        applicable_when = _col(r, 'applicable_when', 6)
        sql_templates = _col(r, 'sql_templates', 7)
        aw = applicable_when if isinstance(applicable_when, dict) else _safe_json(applicable_when)
        tpl = sql_templates if isinstance(sql_templates, dict) else _safe_json(sql_templates)
        out.append({
            "metric_key": metric_key,
            "name_tr": name_tr,
            "category": category,
            "sub_category": sub_cat,
            "description_tr": desc,
            "default_viz": default_viz,
            "applicable_when": aw or {},
            "sql_templates": tpl or {},
            "score": 0.0,
            "pattern_strength": 0.0,
            "bindings": {},
            "fallback": True,
        })
    return out


def _safe_json(v: Any) -> Optional[Dict[str, Any]]:
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        try:
            j = json.loads(v)
            return j if isinstance(j, dict) else None
        except Exception:
            return None
    return None


def _load_user_pref_metrics(cur: Any, user_ctx: Dict[str, Any]) -> set:
    """dbsmart_user_preferences.frequent_metrics içinden set döner. Hata → boş set.

    FIX15 (B13): SAVEPOINT pattern — `dbsmart_user_preferences` tablosu yok/RLS
    deny/şema uyumsuzluğu hallerinde SELECT başarısız olduğunda
    `InFailedSqlTransaction` ile sonraki sorguların patlamasını engeller. Hatayı
    yalnızca SAVEPOINT'e kadar geri alır; çağıranın transaction'ı sağlam kalır.

    Not: autocommit=False (get_db_context default'u) gerektirir — autocommit=True
    altında SAVEPOINT komutu kendi başına başarısız olur. Bu yüzden iç try/except
    ROLLBACK TO SAVEPOINT'i de güvenlikle sarar.
    """
    uid = user_ctx.get("id")
    if not uid:
        return set()
    sp = "sp_user_pref"
    try:
        cur.execute(f"SAVEPOINT {sp}")
        cur.execute(
            """
            SELECT frequent_metrics
              FROM dbsmart_user_preferences
             WHERE user_id = %s
             LIMIT 1
            """,
            (uid,),
        )
        row = cur.fetchone()
        cur.execute(f"RELEASE SAVEPOINT {sp}")
        if not row:
            return set()
        fm = _col(row, 'frequent_metrics', 0)
        if isinstance(fm, list):
            return {m for m in fm if isinstance(m, str)}
        parsed = _safe_json(fm)
        if isinstance(parsed, list):
            return {m for m in parsed if isinstance(m, str)}
    except Exception as e:
        logger.warning(
            "[metric_engine] user_pref load failed (savepoint rollback): %s", e
        )
        try:
            cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
        except Exception:
            # SAVEPOINT hiç oluşmadıysa (örn. autocommit=True altında ilk
            # cur.execute SAVEPOINT zaten patladıysa) — sessizce geç. Bu
            # durumda transaction zaten aborted, caller'ın conn.rollback()
            # etmesi gerekir, ama biz tek SAVEPOINT'i temizleyebilirsek temizleriz.
            pass
    return set()


# ─────────────────────────────────────────────────────────────
# Template & usage
# ─────────────────────────────────────────────────────────────

def get_template(cur: Any, metric_key: str, dialect: str) -> Optional[Dict[str, Any]]:
    """metric_library.sql_templates[dialect] + meta döndür."""
    cur.execute(
        """
        SELECT metric_key, default_viz, applicable_when, sql_templates
          FROM dbsmart_metric_library
         WHERE metric_key = %s
           AND (is_active IS TRUE OR is_active IS NULL)
         LIMIT 1
        """,
        (metric_key,),
    )
    r = cur.fetchone()
    if not r:
        return None
    default_viz = _col(r, 'default_viz', 1)
    applicable_when = _col(r, 'applicable_when', 2)
    sql_templates = _col(r, 'sql_templates', 3)
    tpl = sql_templates if isinstance(sql_templates, dict) else _safe_json(sql_templates) or {}
    sql = tpl.get(dialect)
    if not sql:
        return None
    return {
        "metric_key": metric_key,
        "dialect": dialect,
        "sql_template": sql,
        "default_viz": default_viz,
        "applicable_when": applicable_when if isinstance(applicable_when, dict) else _safe_json(applicable_when) or {},
    }


def record_usage(cur: Any, metric_key: str, success: bool, user_ctx: Dict[str, Any]) -> None:
    """usage_count++ + success_rate moving average (alpha=0.2).

    Hata → log + sessiz dön (telemetri kritik path'i bloklamasın).
    """
    try:
        cur.execute(
            """
            UPDATE dbsmart_metric_library
               SET usage_count = COALESCE(usage_count, 0) + 1,
                   success_rate = CASE
                       WHEN success_rate IS NULL THEN %s
                       ELSE 0.8 * success_rate + 0.2 * %s
                   END
             WHERE metric_key = %s
            """,
            (1.0 if success else 0.0, 1.0 if success else 0.0, metric_key),
        )
    except Exception as e:
        logger.warning("[metric_engine] record_usage failed key=%s: %s", metric_key, e)
