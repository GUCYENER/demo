"""DB Smart test fixtures (v3.30.0 FAZ 0)."""
from __future__ import annotations

from typing import Any, Dict

import pytest


@pytest.fixture
def fake_user_ctx() -> Dict[str, Any]:
    """Tek tenant user context — RLS set_config payload'ı için."""
    return {
        "id": 42,
        "username": "test_user",
        "company_id": 1,
        "role": "user",
        "is_admin": False,
    }


@pytest.fixture
def fake_admin_ctx() -> Dict[str, Any]:
    """Admin context — RLS bypass test'leri için."""
    return {
        "id": 1,
        "username": "admin",
        "company_id": 1,
        "role": "admin",
        "is_admin": True,
    }


@pytest.fixture
def fake_wizard_state() -> Dict[str, Any]:
    """Asgari wizard_state payload'ı."""
    return {
        "source_id": 10,
        "dialect": "postgresql",
        "selected_tables": [],
        "selected_columns": [],
        "filters": [],
        "metric": None,
        "ordering": [],
        "limit": 100,
    }
