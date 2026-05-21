"""Text-to-SQL retrieval-store support modules (FAZ 4 gap addendum).

This package hosts cross-cutting helpers for SQL generation:

- few_shot_store: query_examples table accessors (P50, this dispatch)
- self_healer:    SQL repair via EXPLAIN feedback (P51 — separate dispatch)
- synthetic_pairs: LLM-generated Q/SQL pretraining data (P52 — separate)

Naming deviation (documented in dispatch report 2026-05-21):
    The original brief targeted ``app.services.text_to_sql`` as a package,
    but ``app/services/text_to_sql.py`` already exists as a module imported
    by ``custom_metric_parser``, ``deep_think_service`` and
    ``tests/test_text_to_sql.py``. Creating a package with the same name
    would shadow the module and break those imports. The hard-rule
    "NO modification of files outside the 5 listed" precludes a rename, so
    this package is created as ``text_to_sql_store`` (sibling) instead.
"""
