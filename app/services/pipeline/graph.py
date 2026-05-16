"""
LangGraph state machine for the agentic SQL pipeline.

Faz 0: Skeleton — wiring sadece dokümantasyon amaçlı. Çalışmıyor.
Faz 3: Aktif olur. Node implementasyonları `app/services/pipeline/nodes/` altında.

Beklenen graph şekli (Faz 3+):

    [START]
       │
       ▼
    intent_extract
       │
       ▼
    retrieve
       │
       ▼
    multi_signal_rank
       │
       ▼
    ambiguity_gate ──► (conditional)
       │                    │
       │ (needs_clarify)    │ (auto)
       ▼                    │
    clarification            │
       │ (interrupt → user) │
       ▼                    │
    [resume after user]     │
       │                    │
       └──────────┬─────────┘
                  ▼
              sql_generate
                  │
                  ▼
              validate ───► (failed? + retry < 2)
                  │              │
                  │              └──► sql_generate (self-heal)
                  ▼
              execute
                  │
                  ▼
              [END]

LangGraph dependency: requirements.txt'e Faz 3 başında eklenecek
    langgraph>=0.2
    langgraph-checkpoint-postgres>=2.0  (PostgreSQL checkpointer için)
"""
from __future__ import annotations

# Faz 3'te uncomment:
# from langgraph.graph import StateGraph, START, END
# from langgraph.checkpoint.postgres import PostgresSaver

# from .state import QueryState
# from .nodes.intent_extract import intent_extract_node
# from .nodes.retrieve import retrieve_node
# from .nodes.multi_signal_rank import multi_signal_rank_node
# from .nodes.ambiguity_gate import ambiguity_gate_node, route_after_ambiguity
# from .nodes.clarification import clarification_node
# from .nodes.sql_generate import sql_generate_node
# from .nodes.validate import validate_node, route_after_validate
# from .nodes.execute import execute_node


def build_query_graph(checkpointer=None):
    """
    Faz 0: Placeholder — NotImplementedError raise eder.
    Faz 3: Tam state machine inşa edilir ve compile edilmiş graph döner.
    """
    raise NotImplementedError(
        "Pipeline graph Faz 3'te aktif olacak. "
        "Şu an sadece iskelet — runtime'da kullanılmıyor. "
        "Bkz: .agents/plans/agentic_sql_copilot_master_plan.md → Faz 3"
    )
