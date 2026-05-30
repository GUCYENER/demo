"""v3.38.3 — Merkezi Hata Gözlemi: saf-mantık testleri.

Canlı akış (log_exception → system_logs + errors.jsonl + GET /api/system/errors)
elle doğrulandı; burada DB/TestClient gerektirmeyen çekirdek mantık test edilir:
- JSONFormatter exc_info'yu (traceback) yazar — ESKİDEN düşürüyordu (kök eksik).
- redact_sensitive hassas alanları maskeler.
- NUL-strip (PG NUL reddi guard'ı).
"""
import json
import logging

from app.services.logging_service import redact_sensitive


def _format_record_with_exc():
    """vyra JSONFormatter'ı izole kurup exc_info'lu bir kayıt formatlar."""
    from app.services import logging_service
    # _get_file_logger içindeki JSONFormatter'ı yeniden kullanmak yerine, aynı
    # davranışı garanti eden gerçek logger'ı kullan: bir handler'ın formatter'ını al.
    logger = logging_service._get_file_logger()
    fmt = None
    for h in logger.handlers:
        if h.formatter and h.formatter.__class__.__name__ == "JSONFormatter":
            fmt = h.formatter
            break
    assert fmt is not None, "JSONFormatter bulunamadı"
    try:
        raise ValueError("birim-test hatası")
    except Exception:
        import sys
        record = logging.LogRecord(
            name="vyra", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="test", args=(), exc_info=sys.exc_info(),
        )
    return json.loads(fmt.format(record))


def test_json_formatter_includes_traceback():
    out = _format_record_with_exc()
    assert "traceback" in out, "JSONFormatter traceback alanını yazmıyor (kök eksik geri geldi)"
    assert "ValueError" in out["traceback"]
    assert "birim-test hatası" in out["traceback"]


def test_redact_sensitive_masks_secrets():
    data = {"password": "gizli", "db_password": "x", "token": "t", "foo": "bar",
            "nested": {"api_key": "k", "ok": 1}}
    red = redact_sensitive(data)
    assert red["password"] == "***"
    assert red["db_password"] == "***"
    assert red["token"] == "***"
    assert red["foo"] == "bar"          # hassas olmayan korunur
    assert red["nested"]["api_key"] == "***"
    assert red["nested"]["ok"] == 1


def test_redact_sensitive_handles_lists_and_scalars():
    assert redact_sensitive([{"secret": "s"}, {"ok": 2}]) == [{"secret": "***"}, {"ok": 2}]
    assert redact_sensitive("plain") == "plain"
    assert redact_sensitive(42) == 42


def test_log_exception_nul_and_redaction_in_detail(monkeypatch):
    """log_exception → log_system_event'e giden error_detail NUL'suz + redaksiyonlu olmalı."""
    captured = {}

    def fake_log_system_event(level, message, **kw):
        captured["level"] = level
        captured["message"] = message
        captured.update(kw)

    monkeypatch.setattr(
        "app.services.logging_service.log_system_event", fake_log_system_event
    )
    from app.services.logging_service import log_exception
    try:
        raise RuntimeError("NUL\x00burada")
    except Exception as e:
        log_exception(e, module="test", request_id="rid_test",
                      context={"password": "gizli", "x": 1})

    assert captured["request_id"] == "rid_test"
    assert "\x00" not in (captured.get("error_detail") or ""), "NUL strip edilmedi (PG 500 riski)"
    assert "RuntimeError" in captured["error_detail"]
    assert '"password": "***"' in captured["error_detail"]  # context redaksiyonlu
    assert captured.get("exc_info") is not None
