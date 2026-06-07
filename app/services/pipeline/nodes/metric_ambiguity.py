"""
metric_ambiguity — TEMA-2 Dilim-2 (v3.79.0)
============================================
Agentic serbest-metin yolunda METRİK/YORUM belirsizliğini tespit eder.
"top 10 müşteri" → ciroya mı, adede mi, son tarihe mi göre? LLM sessizce seçmesin;
≥2 distinkt aday metrik varsa kullanıcıya sor (metric_clarification interrupt).

Tasarım (plan-eng-review, kullanıcı onaylı):
  - HEURİSTİK (LLM yok): ranking-keyword + extract_intent_heuristic.agg_func==None
    + seçili tablolardan (selected_tables aday-objeleri) aday-metrik enumerasyonu.
  - ambiguity_gate.top1_dominant deseni: ≥2 distinkt aday → clarify; aksi → auto.
  - GÜVENLİ: çalışan table-clarify'a dokunmaz; graph routing yalnız table AUTO-çözüldüğünde
    devreye sokar (iki ardışık interrupt'tan kaçın → user_choice bayatlamaz).

Girdi: `selected_tables` aday listesi (her biri {table_name, business_name_tr,
columns:[{column_name, data_type, business_name_tr, is_pk, is_fk}]}) — sql_generate'in
gördüğü şekil (retrieve.py column_index). Saf fonksiyon, DB'siz unit-test edilir.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.services.db_smart.custom_metric_parser import extract_intent_heuristic

# Ranking/superlatif niyet (TR + EN). agg_func=None İLE birleşince belirsizlik sinyali.
# adversarial-fix: diakritiksiz ASCII formlar da (TR kullanıcı sık böyle yazar: "en cok").
_RANKING_RE = re.compile(
    r"(\btop\s*\d+\b|\bilk\s*\d+\b"
    r"|\ben\s+(çok|cok|fazla|yüksek|yuksek|büyük|buyuk|i̇yi|iyi|az|düşük|dusuk|küçük|kucuk)\b"
    r"|\b(sırala|siralama|ranking|rank|best|worst|highest|lowest|most|least)\b)",
    re.IGNORECASE,
)
# adversarial-fix: salt-yenilik niyeti ("en son/yeni/güncel") metrik DEĞİL → MAX(tarih) ima eder,
# soru sorma (downstream çözer). Belirsizlik kontrolünden ÖNCE elenir.
_RECENCY_RE = re.compile(
    r"\ben\s+(son|yeni|güncel|guncel)\b|\bson\s+\d+\b|\b(en\s+)?(latest|newest|recent)\b",
    re.IGNORECASE,
)

# SUM adayı: ölçü-benzeri numeric kolon (ad veya iş-adı bu anahtarları içerirse).
_MEASURE_HINTS = (
    "tutar", "fiyat", "miktar", "toplam", "ücret", "ucret", "bedel", "maliyet",
    "ciro", "gelir", "borç", "borc", "bakiye", "amount", "total", "price",
    "qty", "quantity", "value", "revenue", "cost", "balance",
)
_NUMERIC_TYPE_HINTS = (
    "int", "numeric", "decimal", "float", "double", "money", "number",
    "real", "bigint", "smallint", "serial",
)
_DATE_TYPE_HINTS = ("date", "time", "timestamp")


def enumerate_candidate_metrics(
    selected_tables: List[Dict[str, Any]], max_candidates: int = 4
) -> List[Dict[str, Any]]:
    """Seçili tablo aday-objelerinin kolonlarından aday ranking-metriklerini çıkar (heuristik).

    Aday tipleri:
      - COUNT(*)  → "<tablo> adedine göre" (tablo başına)
      - SUM(col)  → ölçü-benzeri numeric kolon ("toplam <iş-adı>'e göre")
      - MAX(date) → tarih kolonu ("en son <iş-adı>'e göre")
    Dedup (agg_func, table, column); max_candidates ile sınırlı. Limitation: yalnız
    SEÇİLİ tablolardan; ölçü seçilmemiş bir join-tablosundaysa kaçırılır (minimal dilim).
    """
    candidates: List[Dict[str, Any]] = []
    seen: set = set()

    def _add(agg: str, table: str, column: Optional[str], expr: str, label: str):
        key = (agg, (table or "").lower(), (column or "").lower())
        if key in seen:
            return
        seen.add(key)
        candidates.append({
            "agg_func": agg, "table": table, "column": column,
            "expr": expr, "label_tr": label,
        })

    for t in (selected_tables or []):
        # Şekil-esnek: agentic candidate (table_name/column_name) VE deep_think/text_to_sql
        # schema_ctx (name) ikisini de destekle → detektör iki path'te de reuse edilir.
        tname = t.get("table_name") or t.get("name") or ""
        if not tname:
            continue
        tlabel = t.get("business_name_tr") or t.get("admin_label_tr") or tname
        _add("COUNT", tname, None, "COUNT(*)", f"{tlabel} adedine göre")
        for c in (t.get("columns") or []):
            cn = c.get("column_name") or c.get("name") or ""
            if not cn or c.get("is_pk") or c.get("is_fk"):
                continue  # PK/FK ölçü değildir
            dt = (c.get("data_type") or "").lower()
            bn = c.get("business_name_tr") or c.get("admin_label_tr") or cn
            hay = (cn + " " + bn).lower()
            if any(h in dt for h in _NUMERIC_TYPE_HINTS) and any(m in hay for m in _MEASURE_HINTS):
                _add("SUM", tname, cn, f"SUM({cn})", f"toplam {bn}'e göre")
            elif any(h in dt for h in _DATE_TYPE_HINTS):
                _add("MAX", tname, cn, f"MAX({cn})", f"en son {bn}'e göre")

    return candidates[:max_candidates]


def detect_metric_ambiguity(
    question: str,
    selected_tables: List[Dict[str, Any]],
    *,
    min_candidates: int = 2,
) -> Dict[str, Any]:
    """Metrik/yorum belirsizliği tespiti (heuristik, fail-soft).

    BELİRSİZ koşulu (HEPSİ): (a) ranking/superlatif niyet, (b) explicit agg yok
    (extract_intent_heuristic.agg_func is None), (c) ≥min_candidates distinkt aday.

    Returns:
        {
          "needs_clarification": bool,
          "reason": "metric_ambiguous" | "explicit_metric" | "no_ranking_intent" | "single_candidate",
          "candidates": [ {agg_func, table, column, expr, label_tr} ],
        }
    """
    q = question or ""
    # adversarial-fix #5: salt-yenilik ("en son") → MAX(tarih) ima, soru sorma
    if _RECENCY_RE.search(q):
        return {"needs_clarification": False, "reason": "recency_intent", "candidates": []}
    if not _RANKING_RE.search(q):
        return {"needs_clarification": False, "reason": "no_ranking_intent", "candidates": []}

    intent = extract_intent_heuristic(q)
    if intent.get("agg_func"):
        # Kullanıcı metriği AÇIKÇA belirtmiş (toplam/adet/ortalama...) → belirsiz değil
        return {"needs_clarification": False, "reason": "explicit_metric", "candidates": []}

    candidates = enumerate_candidate_metrics(selected_tables or [])
    if len(candidates) < min_candidates:
        return {"needs_clarification": False, "reason": "single_candidate", "candidates": candidates}
    # adversarial-fix #6: hepsi COUNT(*) ise bu bir TABLO/grain sorusu (ambiguity_gate'in işi),
    # metrik belirsizliği DEĞİL → ≥1 gerçek ölçü (SUM/MAX) aday şart.
    if not any(c.get("agg_func") != "COUNT" for c in candidates):
        return {"needs_clarification": False, "reason": "count_only", "candidates": candidates}

    return {"needs_clarification": True, "reason": "metric_ambiguous", "candidates": candidates}
