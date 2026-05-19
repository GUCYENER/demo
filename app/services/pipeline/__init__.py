"""
Agentic SQL Copilot Pipeline (LangGraph)
=========================================

Faz 0: İskelet — runtime'da kullanılmıyor.
Faz 3: Multi-signal scoring + ambiguity gate eklenince aktive olur.

Bu modül VYRA'nın doğal dil → SQL akışını LangGraph state machine
olarak yeniden modelleyecek. Mevcut DeepThinkService korunur;
yeni pipeline yan yana çalışır, kademeli geçiş yapılır.

Referans: .agents/plans/agentic_sql_copilot_master_plan.md
"""

# Faz 0'da boş — Faz 3'te:
# from .graph import build_query_graph
# from .state import QueryState
# from .checkpointer import get_checkpointer

__all__: list[str] = []
__version__ = "0.0.1-skeleton"
