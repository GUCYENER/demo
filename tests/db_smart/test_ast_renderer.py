"""ast_renderer.py smoke (FAZ 0)."""
from __future__ import annotations

import pytest

from app.services.db_smart import ast_renderer as ar


def test_supported_dialects_4():
    assert set(ar.SUPPORTED_DIALECTS) == {"postgresql", "oracle", "mssql", "mysql"}


def test_render_rejects_unsupported_dialect(fake_user_ctx):
    with pytest.raises(ValueError):
        ar.render({}, "sqlite", fake_user_ctx)


def test_render_returns_string_in_stub(fake_user_ctx):
    out = ar.render({}, "postgresql", fake_user_ctx)
    assert isinstance(out, str)


def test_inject_rls_returns_dict(fake_user_ctx):
    out = ar.inject_rls({"select": []}, fake_user_ctx)
    assert isinstance(out, dict)


def test_serialize_roundtrip():
    ast = {"select": [{"col": "id"}]}
    snap = ar.serialize_json(ast)
    back = ar.deserialize_json(snap)
    assert back == ast
