"""learning_recorder.py smoke (FAZ 0)."""
from __future__ import annotations

from app.services.db_smart import learning_recorder as lr


def test_known_actions_includes_main_events():
    must_have = {
        "SessionStarted", "DomainSelected", "TableSelected",
        "MetricChosen", "QueryExecuted", "WizardCompleted",
        "WizardAbandoned", "ExplicitFeedback",
    }
    assert must_have.issubset(lr.KNOWN_ACTIONS)


def test_record_unknown_action_is_silent(fake_user_ctx, caplog):
    # Bilinmeyen action exception fırlatmamalı; yalnızca uyarı log'lamalı
    lr.record("Unknown_Made_Up_Event", session_id=1, user_ctx=fake_user_ctx)
    assert any("unknown action" in r.message.lower() for r in caplog.records)


def test_record_known_action_does_not_raise(fake_user_ctx):
    lr.record("SessionStarted", session_id=1, user_ctx=fake_user_ctx)
    lr.record("WizardCompleted", session_id=1, user_ctx=fake_user_ctx,
              step=8, satisfaction=4)
