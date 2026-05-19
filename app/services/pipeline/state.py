"""
QueryState — LangGraph TypedDict state for the agentic SQL pipeline.

Faz 0: Skeleton (definitions only, not wired up).
Faz 3: Wired up to the LangGraph state machine.

State akışı (Faz 3+):
  question (input)
  → intent (intent extractor)
  → candidates (retriever)
  → ranked_candidates (multi-signal scorer)
  → ambiguity_decision (gate: clarify? auto-pick? abort?)
  → clarification_payload (UI'a gönderilecek seçenekler) — opsiyonel
  → user_choice (kullanıcı seçimi sonrası) — opsiyonel
  → sql (LLM generator)
  → explain_plan (validator)
  → result (executor)
"""
from __future__ import annotations

from typing import Any, TypedDict, NotRequired


class TableCandidate(TypedDict):
    """Aday tablo + skorları."""
    schema_name: str
    table_name: str
    object_type: str  # "table" | "view"
    row_count_estimate: int
    business_name_tr: NotRequired[str]
    description: NotRequired[str]
    semantic_score: float
    name_fuzzy_score: NotRequired[float]
    column_match_score: NotRequired[float]
    fk_centrality_score: NotRequired[float]
    recency_score: NotRequired[float]
    usage_freq_score: NotRequired[float]
    final_score: float


class ColumnRef(TypedDict):
    """Tablo + kolon referansı."""
    schema_name: str
    table_name: str
    column_name: str
    data_type: str
    is_nullable: bool
    is_pk: bool
    is_fk: bool
    business_name_tr: NotRequired[str]


class Filter(TypedDict):
    column: ColumnRef
    operator: str  # =, !=, >, <, >=, <=, LIKE, IN, BETWEEN, IS NULL, IS NOT NULL
    value: Any


class Join(TypedDict):
    left: ColumnRef
    right: ColumnRef
    join_type: str  # INNER | LEFT | RIGHT | FULL


class OrderClause(TypedDict):
    column: ColumnRef
    direction: str  # ASC | DESC


class AmbiguityDecision(TypedDict):
    needs_clarification: bool
    confidence: float
    reason: str  # "top1_dominant" | "top1_top2_tight" | "below_threshold" | "missing_filter"
    candidates_for_user: NotRequired[list[TableCandidate]]


class QueryState(TypedDict, total=False):
    """LangGraph state for the agentic SQL pipeline.

    Stages populate progressively; conditional edges read these fields.
    """
    # --- Input / Context ---
    question: str
    user_id: int
    source_id: int
    db_dialect: str  # postgresql | oracle | mssql | mysql
    company_id: int | None
    conversation_id: str | None

    # --- Stage 1: Intent ---
    intent: str  # "lookup" | "aggregate" | "report" | "follow_up" | "unknown"
    intent_confidence: float

    # --- Stage 2: Retrieval ---
    candidates: list[TableCandidate]

    # --- Stage 3: Multi-signal ranking ---
    ranked_candidates: list[TableCandidate]

    # --- Stage 4: Ambiguity gate ---
    ambiguity: AmbiguityDecision

    # --- Stage 5: Clarification (if needed) — interrupted state ---
    clarification_payload: dict
    user_choice: dict  # raw user input after resume

    # --- Stage 6: SQL generation ---
    selected_tables: list[TableCandidate]
    selected_columns: list[ColumnRef]
    filters: list[Filter]
    joins: list[Join]
    order_by: list[OrderClause]
    limit: int | None
    sql: str

    # --- Stage 7: Validation ---
    validation_passed: bool
    validation_errors: list[str]
    explain_plan: dict

    # --- Stage 8: Execution ---
    rows: list[dict]
    columns: list[str]
    row_count: int
    elapsed_ms: int
    truncated: bool

    # --- Meta ---
    errors: list[str]
    retry_count: int
    history: list[dict]  # önceki turn'lerden (follow-up için)
