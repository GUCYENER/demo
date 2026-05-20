"""DB Smart — Template Marketplace (v3.30.0 FAZ 3 P18 / G3.3).

`dbsmart_metric_library` üzerinden official + community template'lerin
listelenmesi/filtrelenmesi/aranması. UI'ın "Şablon Pazarı" sekmesi bu modülü
çağırır. Endpoint katmanı:
    GET /api/db-smart/templates
        ?category=helpdesk
        &q=oldest
        &is_official=true|false|null
        &owner=mine|all|community
        &order=popular|recent|name
        &limit=50

Filtre kuralları:
- `category` boşsa hepsi
- `q` LIKE search (name_tr / description_tr) — token bütçesi: 80 char trim
- `is_official` None/True/False
- `owner=mine` → owner_user_id = current_user (custom kütüphane)
- `owner=community` → is_official=FALSE AND owner_user_id != current_user
- order: popular = usage_count DESC, recent = created_at DESC, name = name_tr ASC
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_ALLOWED_ORDER = {"popular", "recent", "name"}
_ALLOWED_OWNER = {"mine", "all", "community", "official"}
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200


def _safe_q(q: Optional[str]) -> Optional[str]:
    """LIKE injection guard — yalnızca whitespace/Türkçe harfler kalsın. Boşsa None."""
    if not q:
        return None
    s = q.strip()[:80]
    if not s:
        return None
    # SQL LIKE özel karakterlerini escape et (% _ \)
    return s.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


def browse(
    cur: Any,
    current_user: Dict[str, Any],
    *,
    category: Optional[str] = None,
    q: Optional[str] = None,
    is_official: Optional[bool] = None,
    owner: str = "all",
    order: str = "popular",
    limit: int = _DEFAULT_LIMIT,
) -> List[Dict[str, Any]]:
    """Filtreli template listesi döndürür (PII-safe)."""
    if owner not in _ALLOWED_OWNER:
        owner = "all"
    if order not in _ALLOWED_ORDER:
        order = "popular"
    if limit <= 0 or limit > _MAX_LIMIT:
        limit = _DEFAULT_LIMIT
    uid = int(current_user.get("id") or 0)

    where: List[str] = ["(is_active IS TRUE OR is_active IS NULL)"]
    params: List[Any] = []

    if category:
        where.append("category = %s")
        params.append(str(category)[:60])

    safe_like = _safe_q(q)
    if safe_like:
        where.append("(name_tr ILIKE %s ESCAPE %s OR description_tr ILIKE %s ESCAPE %s)")
        pattern = f"%{safe_like}%"
        params.extend([pattern, "\\", pattern, "\\"])

    if is_official is True:
        where.append("is_official IS TRUE")
    elif is_official is False:
        where.append("is_official IS FALSE")

    if owner == "mine":
        where.append("owner_user_id = %s")
        params.append(uid)
    elif owner == "community":
        # A-8 fix: 'community' artık "official + own custom" anlamına gelir
        # (önceki davranış: tüm diğer kullanıcıların custom template'lerini
        # leak ediyordu — cross-tenant PII riski).
        where.append("(is_official IS TRUE OR owner_user_id = %s OR owner_user_id IS NULL)")
        params.append(uid)
    elif owner == "official":
        where.append("is_official IS TRUE")
    else:
        # A-8 fix: default 'all' artık own-or-official ile sınırlı.
        # Önceki davranış: hiç filtre yoktu → tüm kullanıcıların custom
        # template'leri sızıyordu (sql_templates, description_tr dahil).
        where.append("(is_official IS TRUE OR owner_user_id = %s OR owner_user_id IS NULL)")
        params.append(uid)

    order_sql = {
        "popular": "usage_count DESC NULLS LAST, success_rate DESC NULLS LAST",
        "recent":  "created_at DESC NULLS LAST",
        "name":    "name_tr ASC NULLS LAST",
    }[order]

    sql = f"""
        SELECT id, metric_key, name_tr, name_en, category, sub_category,
               description_tr, default_viz, applicable_when, sql_templates,
               is_official, owner_user_id,
               usage_count, success_rate, created_at
          FROM dbsmart_metric_library
         WHERE {' AND '.join(where)}
      ORDER BY {order_sql}
         LIMIT %s
    """
    params.append(int(limit))
    cur.execute(sql, tuple(params))
    cols = ["id", "metric_key", "name_tr", "name_en", "category", "sub_category",
            "description_tr", "default_viz", "applicable_when", "sql_templates",
            "is_official", "owner_user_id", "usage_count", "success_rate", "created_at"]
    out: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        rec = dict(zip(cols, row))
        # PII-safe: owner_user_id'yi "self/other" bayrağıyla değiştir
        own = rec.pop("owner_user_id", None)
        rec["is_mine"] = bool(own is not None and int(own) == uid)
        # created_at ISO string
        if rec.get("created_at") is not None:
            try:
                rec["created_at"] = rec["created_at"].isoformat()
            except Exception:
                rec["created_at"] = None
        out.append(rec)
    return out


def get_categories(cur: Any) -> List[Dict[str, Any]]:
    """Marketplace UI için kategori sayım listesi."""
    cur.execute(
        """
        SELECT category, COUNT(*)::int AS n
          FROM dbsmart_metric_library
         WHERE (is_active IS TRUE OR is_active IS NULL)
         GROUP BY category
         ORDER BY n DESC, category ASC
        """
    )
    return [{"category": r[0], "count": int(r[1] or 0)} for r in cur.fetchall()]


def get_by_key(cur: Any, metric_key: str, current_user: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tek bir template detayı (apply için).

    A-7 fix (ARES KRITIK): owner filter eklendi — sadece official, NULL-owner
    (legacy seed) veya çağıran kullanıcının kendi custom template'i döner.
    Önceki davranış: herhangi bir authenticated user başkasının custom
    template'inin detayını (sql_templates dahil) çekebiliyordu.
    """
    uid = int(current_user.get("id") or 0)
    cur.execute(
        """
        SELECT id, metric_key, name_tr, name_en, category, sub_category,
               description_tr, rationale_template_tr, default_viz,
               applicable_when, sql_templates, required_features, optional_features,
               is_official, owner_user_id, usage_count, success_rate, created_at
          FROM dbsmart_metric_library
         WHERE metric_key = %s
           AND (is_active IS TRUE OR is_active IS NULL)
           AND (is_official IS TRUE OR owner_user_id = %s OR owner_user_id IS NULL)
         LIMIT 1
        """,
        (str(metric_key)[:120], uid),
    )
    row = cur.fetchone()
    if not row:
        return None
    cols = ["id", "metric_key", "name_tr", "name_en", "category", "sub_category",
            "description_tr", "rationale_template_tr", "default_viz",
            "applicable_when", "sql_templates", "required_features", "optional_features",
            "is_official", "owner_user_id", "usage_count", "success_rate", "created_at"]
    rec = dict(zip(cols, row))
    own = rec.pop("owner_user_id", None)
    rec["is_mine"] = bool(own is not None and int(own) == uid)
    if rec.get("created_at") is not None:
        try:
            rec["created_at"] = rec["created_at"].isoformat()
        except Exception:
            rec["created_at"] = None
    return rec
