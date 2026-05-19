"""VYRA v3.27.0 — FK Synthetic Query Generator (G1).

ds_db_relationships içindeki her FK için 2 örnek SQL üret-execute-öğret:

  1) FK satırlarını oku (per source_id)
  2) Her FK için LOOKUP_JOIN + AGGREGATE_COUNT render et
     (kullanıcı kuralı: '2 örnek yeter')
  3) UNIQUE(source_id, relationship_id, template_kind) → idempotent
     (önceden başarıyla execute edilmişse atla)
  4) SafeSQLExecutor ile hedef DB'de execute et
  5) Başarılı + row_count > 0 → learned_db_queries'e yaz
     (source='synthetic', dedupe ile)
  6) ds_synthetic_query_runs'a audit (success/fail + elapsed)

Hatalar:
  * Single FK error pipeline'ı durdurmaz — devam edilir
  * Tüm batch için final özet döner: {total, success, skipped, failed}
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from app.services.db_learning.dedupe_service import sql_hash
from app.services.db_learning.learned_queries_service import (
    record_successful_query,
)
from app.services.db_learning.synthetic_templates import (
    COMPLEXITY_BY_KIND,
    Relationship,
    RenderedQuery,
    TEMPLATE_KINDS,
    render,
)

# v3.29.2 G3: tek-Relationship temelli ("per-FK") render edilebilen kinds.
# Chain-only kinds (CHAIN_JOIN_*, CTE_LATEST_N_PER_GROUP, LATERAL_TOP_K,
# JUNCTION_N2M) ayrı bir orchestrator gerektirir (fk_graph_resolver tabanlı).
SINGLE_REL_KINDS: tuple = (
    "LOOKUP_JOIN",
    "AGGREGATE_COUNT",
    "STRING_AGG_DETAILS",
    "TIME_SERIES_GENERATE",
    "WINDOW_RUNNING_TOTAL",
)
# v3.29.2 G3: yeni v2 template'ler — template_version=2 işaretlenir.
V2_KINDS: frozenset = frozenset({
    "CHAIN_JOIN_3HOP", "CHAIN_JOIN_NHOP", "CTE_LATEST_N_PER_GROUP",
    "LATERAL_TOP_K", "STRING_AGG_DETAILS", "JUNCTION_N2M",
    "TIME_SERIES_GENERATE", "WINDOW_RUNNING_TOTAL",
})

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# DTO
# ─────────────────────────────────────────────────────────────

@dataclass
class GenerationSummary:
    source_id: int
    dialect: str
    total_fks: int = 0
    total_attempts: int = 0       # FK × template_kinds (idempotent skip dahil)
    success: int = 0
    skipped_existing: int = 0     # zaten başarılı bir UNIQUE satır vardı
    failed_execute: int = 0
    failed_learn: int = 0
    elapsed_ms: int = 0
    errors: List[str] = None      # type: ignore

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _fetch_relationships(cur, source_id: int) -> List[Relationship]:
    """ds_db_relationships'tan FK satırlarını çek."""
    cur.execute(
        """
        SELECT id, from_schema, from_table, from_column,
               to_schema, to_table, to_column
        FROM ds_db_relationships
        WHERE source_id = %s
          AND from_table IS NOT NULL AND from_table <> ''
          AND to_table IS NOT NULL AND to_table <> ''
          AND from_column IS NOT NULL AND from_column <> ''
          AND to_column IS NOT NULL AND to_column <> ''
        ORDER BY id
        """,
        (source_id,),
    )
    rows = cur.fetchall() or []
    out: List[Relationship] = []
    for r in rows:
        def g(k, idx):
            if hasattr(r, "get"):
                return r.get(k)
            return r[idx]
        out.append(Relationship(
            id=int(g("id", 0)),
            from_schema=g("from_schema", 1),
            from_table=g("from_table", 2),
            from_column=g("from_column", 3),
            to_schema=g("to_schema", 4),
            to_table=g("to_table", 5),
            to_column=g("to_column", 6),
        ))
    return out


def _already_succeeded(cur, source_id: int, relationship_id: int, template_kind: str) -> bool:
    """Bu (FK, template) için daha önce başarılı çalıştırma var mı?"""
    try:
        cur.execute(
            """
            SELECT 1 FROM ds_synthetic_query_runs
            WHERE source_id = %s
              AND relationship_id = %s
              AND template_kind = %s
              AND success = TRUE
            LIMIT 1
            """,
            (source_id, relationship_id, template_kind),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def _audit_run(
    cur,
    source_id: int,
    company_id: Optional[int],
    rel: Relationship,
    rq: RenderedQuery,
    success: bool,
    row_count: Optional[int],
    elapsed_ms: int,
    error_message: Optional[str],
    learned_query_id: Optional[int],
) -> None:
    """ds_synthetic_query_runs'a audit kaydı (UNIQUE varsa upsert)."""
    # v3.29.2 G3: template versioning meta
    _tv = 2 if rq.template_kind in V2_KINDS else 1
    _cs = getattr(rq, "complexity_score", None) or COMPLEXITY_BY_KIND.get(rq.template_kind, 1)
    _jp = list(getattr(rq, "join_path", None) or rq.tables or [])
    try:
        cur.execute(
            """
            INSERT INTO ds_synthetic_query_runs
                (source_id, company_id, relationship_id,
                 from_schema, from_table, from_column,
                 to_schema, to_table, to_column,
                 template_kind, dialect, rendered_sql, sql_hash,
                 success, row_count, elapsed_ms, error_message, learned_query_id,
                 template_version, complexity_score, join_path)
            VALUES (%s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s)
            ON CONFLICT (source_id, relationship_id, template_kind)
              DO UPDATE SET
                rendered_sql = EXCLUDED.rendered_sql,
                sql_hash = EXCLUDED.sql_hash,
                dialect = EXCLUDED.dialect,
                executed_at = NOW(),
                success = EXCLUDED.success,
                row_count = EXCLUDED.row_count,
                elapsed_ms = EXCLUDED.elapsed_ms,
                error_message = EXCLUDED.error_message,
                learned_query_id = COALESCE(EXCLUDED.learned_query_id, ds_synthetic_query_runs.learned_query_id),
                template_version = EXCLUDED.template_version,
                complexity_score = EXCLUDED.complexity_score,
                join_path = EXCLUDED.join_path
            """,
            (
                source_id, company_id, rel.id,
                rel.from_schema, rel.from_table, rel.from_column,
                rel.to_schema, rel.to_table, rel.to_column,
                rq.template_kind, rq.dialect, rq.sql, sql_hash(rq.sql),
                success, row_count, elapsed_ms, error_message, learned_query_id,
                _tv, _cs, _jp,
            ),
        )
    except Exception as e:
        logger.warning("[fk_gen.audit] %s", e)


def _build_executor(source_id: int, dialect: str, company_id: Optional[int]):
    """SafeSQLExecutor + source_dict çift döndür (wiring helper'a benzer)."""
    from app.services.safe_sql_executor import SafeSQLExecutor
    from app.services.pipeline.wiring import _load_source_dict
    from app.core.db import get_db_context
    source_dict = None
    with get_db_context() as conn:
        cur = conn.cursor()
        try:
            source_dict = _load_source_dict(cur, source_id, company_id=company_id)
        finally:
            cur.close()
    if source_dict is None:
        raise RuntimeError(f"data source bulunamadı: source_id={source_id}")
    executor = SafeSQLExecutor()
    return executor, source_dict


# ─────────────────────────────────────────────────────────────
# Public
# ─────────────────────────────────────────────────────────────

def generate_for_source(
    cur,
    source_id: int,
    *,
    dialect: str = "postgresql",
    company_id: Optional[int] = None,
    max_fks: Optional[int] = None,
    skip_existing: bool = True,
    template_kinds: Optional[List[str]] = None,
) -> GenerationSummary:
    """source_id altındaki tüm FK'lar için sentetik sorgu üret-çalıştır-öğret.

    Args:
        cur: RLS scoped DictCursor (caller'da app.current_company_id + app.current_source_id)
        source_id: data_sources.id
        dialect: hedef DB lehçesi
        company_id: tenant id (audit + RLS için)
        max_fks: opsiyonel cap (None → tümü). Hızlı smoke run için.
        skip_existing: True ise daha önce başarılı çalıştırılan (FK, template) atlanır
        template_kinds: ['LOOKUP_JOIN', 'AGGREGATE_COUNT'] (None → ikisi de)

    Returns:
        GenerationSummary
    """
    _started = time.perf_counter()
    summary = GenerationSummary(source_id=source_id, dialect=dialect)
    # v3.29.2 G3: default G1 davranışını koru (LOOKUP_JOIN + AGGREGATE_COUNT).
    # Caller ister tek-FK temelli G3 kinds (STRING_AGG_DETAILS, TIME_SERIES_*,
    # WINDOW_*) ekleyebilir. Chain-only kinds bu loop'tan üretilmez.
    kinds = template_kinds or ["LOOKUP_JOIN", "AGGREGATE_COUNT"]
    # Render() çağrılabilir olmayan chain-only kinds'i sessizce filtrele
    kinds = [k for k in kinds if k in SINGLE_REL_KINDS]

    rels = _fetch_relationships(cur, source_id)
    if max_fks is not None:
        rels = rels[:max_fks]
    summary.total_fks = len(rels)

    if not rels:
        summary.elapsed_ms = int((time.perf_counter() - _started) * 1000)
        return summary

    # Hedef DB executor
    try:
        executor, source_dict = _build_executor(source_id, dialect, company_id)
    except Exception as e:
        summary.errors.append(f"executor_init: {e}")
        summary.elapsed_ms = int((time.perf_counter() - _started) * 1000)
        return summary

    # Her FK × template
    # v3.28.9 Paket C: her iterasyon SAVEPOINT ile izole edilir. Aksi halde
    # bir INSERT hatası (örn. embedding column tipi cast, FK violation)
    # PostgreSQL transaction'ı poison eder → kalan tüm iterasyonlar
    # "current transaction is aborted" alır ve sessizce başarısız olur.
    _sp_counter = 0
    for rel in rels:
        for kind in kinds:
            summary.total_attempts += 1
            _sp_counter += 1
            _sp_name = f"sp_fkgen_{_sp_counter}"

            try:
                cur.execute(f"SAVEPOINT {_sp_name}")
            except Exception as _sp_err:
                logger.warning("[fk_gen.savepoint] %s", _sp_err)

            if skip_existing and _already_succeeded(cur, source_id, rel.id, kind):
                summary.skipped_existing += 1
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue

            # Render
            try:
                rq = render(rel, kind, dialect=dialect)
            except Exception as e:
                summary.failed_execute += 1
                if len(summary.errors) < 50:
                    summary.errors.append(f"render rel={rel.id} kind={kind}: {e}")
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue

            # Execute on target DB (read-only, timeout aware)
            _exec_start = time.perf_counter()
            row_count: Optional[int] = None
            err_msg: Optional[str] = None
            try:
                res = executor.execute(rq.sql, source=source_dict, dialect=dialect)
                exec_ms = int((time.perf_counter() - _exec_start) * 1000)
                if not res.success:
                    err_msg = res.error or "execute failed"
                    summary.failed_execute += 1
                    if len(summary.errors) < 50:
                        summary.errors.append(
                            f"execute rel={rel.id} kind={kind}: {err_msg[:200]}"
                        )
                    # v3.28.9: target DB hatası metadata cur'ı bozmaz, ama audit
                    # öncesi safe — savepoint'i rollback'leme gerek yok.
                    _audit_run(cur, source_id, company_id, rel, rq,
                               success=False, row_count=None,
                               elapsed_ms=exec_ms, error_message=err_msg,
                               learned_query_id=None)
                    try:
                        cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                    except Exception:
                        pass
                    continue
                row_count = int(res.row_count or 0)
            except Exception as e:
                exec_ms = int((time.perf_counter() - _exec_start) * 1000)
                err_msg = str(e)[:500]
                summary.failed_execute += 1
                if len(summary.errors) < 50:
                    summary.errors.append(
                        f"execute rel={rel.id} kind={kind} exception: {err_msg[:200]}"
                    )
                _audit_run(cur, source_id, company_id, rel, rq,
                           success=False, row_count=None,
                           elapsed_ms=exec_ms, error_message=err_msg,
                           learned_query_id=None)
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                continue

            # Başarılı + row_count >= 0 → öğret (boş sonuç da öğretici: tablo var, ilişki çalışıyor)
            # v3.28.9 Paket C: learn fail durumunda success counter YANLIŞ artıyordu.
            # Artık her dalda doğru sayım + hata mesajı korunur.
            learned_id: Optional[int] = None
            learn_failed = False
            learn_err_msg: Optional[str] = None
            try:
                rec = record_successful_query(
                    cur,
                    source_id=source_id,
                    company_id=company_id,
                    question=rq.question_tr,
                    sql=rq.sql,
                    intent="synthetic_" + kind.lower(),
                    tables=rq.tables,
                    columns_meta=rq.columns_meta,
                    source="synthetic",
                    created_by_user_id=None,
                    # v3.29.2 G3
                    template_version=2 if kind in V2_KINDS else 1,
                    complexity_score=getattr(rq, "complexity_score", None) or COMPLEXITY_BY_KIND.get(kind, 1),
                    join_path=getattr(rq, "join_path", None) or rq.tables,
                )
                _st = rec.get("status")
                if _st in ("inserted", "duplicate"):
                    learned_id = rec.get("id")
                else:
                    learn_failed = True
                    learn_err_msg = (
                        f"learn rel={rel.id} kind={kind} status={_st} "
                        f"err={(rec.get('error') or rec.get('reason') or 'unknown')[:200]}"
                    )
            except Exception as e:
                learn_failed = True
                learn_err_msg = f"learn rel={rel.id} kind={kind} exception: {str(e)[:200]}"

            if learn_failed:
                summary.failed_learn += 1
                if learn_err_msg and len(summary.errors) < 50:
                    summary.errors.append(learn_err_msg)
                # v3.28.9 Paket C: record_successful_query INSERT/dedupe sırasında
                # patladığında cur'ın transaction'ı poison olabilir → audit_run
                # öncesi savepoint'e rollback et, sonra audit'i temiz txn'da çalıştır.
                try:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                _audit_run(cur, source_id, company_id, rel, rq,
                           success=False, row_count=row_count,
                           elapsed_ms=exec_ms, error_message=learn_err_msg,
                           learned_query_id=None)
                try:
                    cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
                except Exception:
                    pass
                # ÖNEMLİ: success counter ARTMAZ — bu deneme öğretilemedi.
                continue

            # Audit (true success path)
            _audit_run(cur, source_id, company_id, rel, rq,
                       success=True, row_count=row_count,
                       elapsed_ms=exec_ms, error_message=None,
                       learned_query_id=learned_id)
            summary.success += 1
            try:
                cur.execute(f"RELEASE SAVEPOINT {_sp_name}")
            except Exception:
                pass

    summary.elapsed_ms = int((time.perf_counter() - _started) * 1000)
    return summary


__all__ = [
    "GenerationSummary",
    "generate_for_source",
]
