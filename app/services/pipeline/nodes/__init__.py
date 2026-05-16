"""
Pipeline node implementations.

Faz 3'te tüm node'lar aktif. Her node: f(QueryState) -> dict (state delta).
LangGraph TypedDict merge semantics ile state otomatik birleşir.

Node'lar:
- intent_extract: question → intent + confidence (heuristic v1, Faz 5 CatBoost)
- query_expand: business_glossary lookup → expanded_query + hints (Faz 3d)
- retrieve: hybrid_retrieval → candidates + column_index (Faz 3d)
- multi_signal_rank: 6-faktör scoring → ranked_candidates (Faz 3b)
- ambiguity_gate: heuristic → AmbiguityDecision (Faz 3c)
- clarification: interrupt + UI payload + resume (Faz 3e)
- sql_generate: bağlam + soru → SQL (LLM callable injekte) (Faz 3e)
- validate: statik + EXPLAIN pre-flight (Faz 3e)
- execute: callable injekte → row payload (Faz 3e)
"""
from .intent_extract import intent_extract_node, detect_intent  # noqa: F401
from .load_prefs import load_prefs_node  # noqa: F401
from .retrieve import retrieve_node, query_expand_node  # noqa: F401
from .multi_signal_rank import multi_signal_rank_node, multi_signal_rank  # noqa: F401
from .ambiguity_gate import ambiguity_gate_node, route_after_ambiguity, detect_ambiguity  # noqa: F401
from .clarification import clarification_node  # noqa: F401
from .sql_generate import sql_generate_node  # noqa: F401
from .validate import validate_node, route_after_validate  # noqa: F401
from .execute import execute_node  # noqa: F401
from .self_heal import (  # noqa: F401
    self_heal_node, route_after_self_heal,
    classify_error, build_retry_hint, decide_retry_action,
)
