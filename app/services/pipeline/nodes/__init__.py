"""
Pipeline node implementations (Faz 3'te dolacak).

Her node: f(QueryState) -> dict (state delta).
LangGraph TypedDict merge semantics ile state otomatik birleşir.

Planlanan node'lar:
- intent_extract: question → intent + confidence
- retrieve: question_embedding → top-N candidate tables (RLS-scoped)
- multi_signal_rank: 6-faktör scoring → ranked_candidates
- ambiguity_gate: top1/top2 spread + threshold → AmbiguityDecision
- clarification: interrupt + UI payload + resume
- sql_generate: ranked + selected → SQL (dialect-aware, few-shot enriched)
- validate: parse + whitelist + EXPLAIN pre-flight
- execute: SafeSQLExecutor invoke
"""
