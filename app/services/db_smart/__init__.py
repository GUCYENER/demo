"""Akıllı Veri Keşfi (DB Smart Wizard) servis paketi — v3.30.0.

Bu paket, mevcut "Veritabanında Ara" akışının yanına eklenen wizard tarzı
SQL copilot modülünün backend tarafıdır. Mevcut text-to-SQL/RAG/öğrenme
altyapısının üzerinde paralel ikinci giriş; kb/db/llm akışlarını **bozmaz**.

Plan: .agents/plans/v3.30.0_db_smart_wizard.md
Mimari: docs/db_smart/01_architecture.md

FAZ 0 (bu commit) — sadece iskelet:
    - state_machine.py        LangGraph 9-node FSM
    - session_manager.py      dbsmart_sessions CRUD
    - eligibility.py          stub
    - fk_graph.py             stub
    - metric_engine.py        stub
    - query_assembler.py      stub
    - ast_renderer.py         stub
    - learning_recorder.py    stub

Public API (FAZ 0 itibariyle ekspoze):
    build_wizard_graph(checkpointer=None) → compiled LangGraph veya sequential runner
    run_wizard_step(session_uid, step, payload, user_ctx) → dict
"""
from app.services.db_smart.state_machine import (
    WIZARD_NODES,
    build_wizard_graph,
    run_wizard_step,
)

__all__ = [
    "WIZARD_NODES",
    "build_wizard_graph",
    "run_wizard_step",
]
