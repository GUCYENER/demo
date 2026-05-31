"""Deterministik, scope-filtreli FK join yolu planlayıcı (v3.42.0 — Faz 2).

Amaç: "bu siparişin müşteri detayı" gibi takip/ilave taleplerde JOIN'i LLM'e TAHMİN
ETTİRMEK yerine, `ds_db_relationships` (FK grafiği) üzerinden iki/çok tablo arasındaki
EN KISA join yolunu DETERMİNİSTİK hesaplamak. Yol üzerindeki TÜM tablolar kullanıcının
kapsamında (scope) olmalı; aksi halde eksik köprü tablo(lar) raporlanır → çağıran net
DIAGNOSTIC verir (LLM `FATURALAR.MUSTERI_ID` gibi olmayan kolon uydurmaz).

Saf fonksiyon (`find_join_path`) DB'siz unit-test edilir; `load_fk_edges` ince DB sarmalayıcı.
"""
from __future__ import annotations

from collections import deque
from typing import Callable, Dict, List, Optional, Set, Tuple

# NOT: `get_db_context` lazy import edilir (load_fk_edges içinde) — saf fonksiyonlar
# (find_join_path/render_join_hint) ağır DB/LLM stack'i yüklemeden import edilip test edilsin.

# Bir join kenarı: (sol_tablo, sol_kolon, sağ_tablo, sağ_kolon) — hepsi "schema.table" lowercase
Edge = Tuple[str, str, str, str]


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _qual(schema: Optional[str], table: Optional[str]) -> str:
    s, t = _norm(schema), _norm(table)
    return f"{s}.{t}" if s else t


def load_fk_edges(source_id: int) -> List[Edge]:
    """`ds_db_relationships`'ten FK kenarlarını yükler (schema.table lowercase)."""
    from app.core.db import get_db_context  # lazy — saf fonksiyonları hafif tut
    edges: List[Edge] = []
    with get_db_context() as conn:
        cur = conn.cursor()
        # code-review fix: admin'in REDDETTİĞİ (rejected_at) ve düşük-güvenli doğrulanmamış
        # inferred FK'ları DIŞLA — aksi halde "deterministik" join, yanlış-pozitif bir FK üzerinden
        # kurulur (tam da bu özelliğin önlemeye çalıştığı halüsinasyon sınıfı). text_to_sql FK
        # SELECT filtresiyle (v3.29.9) tutarlı: rejected NULL + (declared VEYA verified VEYA conf≥0.70).
        cur.execute(
            """
            SELECT from_schema, from_table, from_column, to_schema, to_table, to_column
            FROM ds_db_relationships
            WHERE source_id = %s
              AND rejected_at IS NULL
              AND (
                  COALESCE(is_inferred, FALSE) = FALSE
                  OR admin_verified = TRUE
                  OR COALESCE(confidence_score, 0) >= 0.70
              )
            """,
            (source_id,),
        )
        for r in cur.fetchall() or []:
            d = r if isinstance(r, dict) else {
                "from_schema": r[0], "from_table": r[1], "from_column": r[2],
                "to_schema": r[3], "to_table": r[4], "to_column": r[5],
            }
            ft = _qual(d.get("from_schema"), d.get("from_table"))
            tt = _qual(d.get("to_schema"), d.get("to_table"))
            fc, tc = _norm(d.get("from_column")), _norm(d.get("to_column"))
            if ft and tt and fc and tc:
                edges.append((ft, fc, tt, tc))
    return edges


def _adjacency(edges: List[Edge]) -> Dict[str, List[Tuple[str, str, str]]]:
    """Yönsüz komşuluk: tablo -> [(komşu_tablo, bu_tablonun_kolonu, komşunun_kolonu)].

    Join iki yönlü çalışır; bu yüzden her FK kenarını çift yönlü ekleriz.
    """
    adj: Dict[str, List[Tuple[str, str, str]]] = {}
    for ft, fc, tt, tc in edges:
        adj.setdefault(ft, []).append((tt, fc, tc))
        adj.setdefault(tt, []).append((ft, tc, fc))
    return adj


def _resolve_node(nodes: Set[str], name: str) -> str:
    """Sorgu tablo adını grafiğin kanonik düğümüne çöz: qualified ("schema.table") VEYA
    bare ("table") eşleşmesi. 'siparisler' → 'vyra_test.siparisler' (tek aday varsa).
    Belirsiz (birden fazla şemada aynı bare ad) veya bulunamazsa `name` aynen döner.
    Wizard tablo adları bare gelebilir; FK grafiği qualified → bu köprüyü kurar.
    """
    n = _norm(name)
    if n in nodes:
        return n
    bare = n.rsplit(".", 1)[-1]
    cands = [x for x in nodes if x.rsplit(".", 1)[-1] == bare]
    return cands[0] if len(cands) == 1 else n


def _shortest_path(adj, start: str, target: str) -> Optional[List[Tuple[str, str, str, str]]]:
    """start → target en kısa join zinciri (BFS). Her adım (sol, sol_kol, sağ, sağ_kol).

    Aynı tablo ise [] (join gerekmez). Yol yoksa None.
    """
    if start == target:
        return []
    seen: Set[str] = {start}
    # kuyruk: (mevcut_tablo, o ana kadarki join-adımları)
    q: deque = deque([(start, [])])
    while q:
        node, path = q.popleft()
        for nbr, left_col, right_col in adj.get(node, []):
            if nbr in seen:
                continue
            step = (node, left_col, nbr, right_col)
            new_path = path + [step]
            if nbr == target:
                return new_path
            seen.add(nbr)
            q.append((nbr, new_path))
    return None


def find_join_path(
    edges: List[Edge],
    start_table: str,
    target_tables: List[str],
    in_scope: Callable[[str], bool],
) -> dict:
    """`start_table`'tan `target_tables`'a (her birine) scope-içi en kısa join yolunu bul.

    Args:
        edges: FK kenarları (load_fk_edges çıktısı veya test verisi).
        start_table: çıpa tablo (ör. "vyra_test.siparisler").
        target_tables: erişilmesi gereken tablolar (ör. ["vyra_test.musteriler"]).
        in_scope: tablo -> bool (kullanıcının kapsamında mı). `AccessScope.allows_table_name`
                  veya benzeri ile köprülenir; all_tables ise her zaman True.

    Returns:
        {
          "ok": bool,                # TÜM hedeflere scope-içi yol bulundu mu
          "joins": [ {left, left_col, right, right_col} ],  # birleşik, dedup join adımları
          "tables": [ ... ],         # yol üzerindeki tüm tablolar (start dahil)
          "missing_scope": [ ... ],  # yolda gereken ama scope-DIŞI tablolar
          "unreachable": [ ... ],    # FK grafiğinde hiç yol bulunamayan hedefler
        }
    """
    adj = _adjacency(edges)
    _nodes = set(adj.keys())
    start = _resolve_node(_nodes, start_table)
    joins: List[dict] = []
    tables: Set[str] = {start}
    missing_scope: Set[str] = set()
    unreachable: List[str] = []
    seen_join_keys: Set[Tuple[str, str, str, str]] = set()

    for tgt in target_tables:
        t = _resolve_node(_nodes, tgt)
        if not t or t == start:
            continue
        path = _shortest_path(adj, start, t)
        if path is None:
            unreachable.append(t)
            continue
        for left, left_col, right, right_col in path:
            tables.add(left)
            tables.add(right)
            key = (left, left_col, right, right_col)
            if key not in seen_join_keys:
                seen_join_keys.add(key)
                joins.append({
                    "left": left, "left_col": left_col,
                    "right": right, "right_col": right_col,
                })

    # Scope kontrolü: yol üzerindeki her tablo scope'ta olmalı
    for tbl in tables:
        if not in_scope(tbl):
            missing_scope.add(tbl)

    ok = (not unreachable) and (not missing_scope)
    return {
        "ok": ok,
        "joins": joins,
        "tables": sorted(tables),
        "missing_scope": sorted(missing_scope),
        "unreachable": sorted(unreachable),
    }


def render_join_hint(plan: dict, dialect: str = "") -> str:
    """LLM prompt'una eklenecek NET join talimatı (deterministik join koşulları).

    Sadece `plan["ok"]` iken anlamlı; çağıran ok=False'da DIAGNOSTIC üretir.
    """
    if not plan.get("joins"):
        return ""
    lines = []
    for j in plan["joins"]:
        lines.append(
            f"  {j['left']} JOIN {j['right']} ON {j['left']}.{j['left_col']} = {j['right']}.{j['right_col']}"
        )
    return (
        "DETERMİNİSTİK JOIN YOLU (FK grafiğinden — bu koşulları AYNEN kullan, "
        "başka join uydurma):\n" + "\n".join(lines)
    )
