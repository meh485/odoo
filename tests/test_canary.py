"""Unit tests for the canary probe logic. No cluster required."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "images" / "canary"))

import canary  # noqa: E402


def _session(login_result, read_result=None, login_status=200, read_status=200):
    session = MagicMock()
    login_response = MagicMock(status_code=login_status)
    login_response.json.return_value = login_result
    read_response = MagicMock(status_code=read_status)
    read_response.json.return_value = read_result if read_result is not None else {"result": [{"id": 1}]}
    session.post.side_effect = [login_response, read_response]
    return session


def test_probe_succeeds_on_valid_login_and_read():
    result = canary.probe(_session({"result": {"uid": 2}}), "http://odoo:8069", "acme", "canary", "pw")
    assert result.success is True
    assert result.login_seconds >= 0


def test_probe_fails_when_uid_is_absent():
    # Odoo answers HTTP 200 with uid null on a rejected login. Treating the
    # status code as success is exactly the mistake a naive probe makes.
    result = canary.probe(_session({"result": {"uid": None}}), "http://odoo:8069", "acme", "canary", "pw")
    assert result.success is False
    assert "uid" in result.error


def test_probe_fails_on_jsonrpc_error_envelope():
    result = canary.probe(_session({"error": {"message": "Access Denied"}}), "http://odoo:8069", "acme", "canary", "pw")
    assert result.success is False
    assert "Access Denied" in result.error


def test_probe_fails_when_record_read_returns_nothing():
    # Login can succeed against a database whose schema is broken; reading a
    # record is what proves the ORM and the registry actually work.
    result = canary.probe(_session({"result": {"uid": 2}}, read_result={"result": []}),
                          "http://odoo:8069", "acme", "canary", "pw")
    assert result.success is False
    assert "record" in result.error.lower()


def test_probe_fails_on_http_error_status():
    result = canary.probe(_session({"result": {"uid": 2}}, login_status=502),
                          "http://odoo:8069", "acme", "canary", "pw")
    assert result.success is False
    assert "502" in result.error


def test_probe_fails_on_transport_exception():
    session = MagicMock()
    session.post.side_effect = RuntimeError("connection reset")
    result = canary.probe(session, "http://odoo:8069", "acme", "canary", "pw")
    assert result.success is False
    assert "connection reset" in result.error


def test_probe_never_returns_the_password_in_an_error():
    session = MagicMock()
    session.post.side_effect = RuntimeError("auth failed for secret-pw-value")
    result = canary.probe(session, "http://odoo:8069", "acme", "canary", "secret-pw-value")
    assert "secret-pw-value" not in result.error


def test_read_secret_rejects_an_empty_file(tmp_path):
    empty = tmp_path / "canary_password"
    empty.write_text("")
    try:
        canary.read_secret(empty)
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit on an empty secret")


def test_read_secret_rejects_a_missing_file(tmp_path):
    try:
        canary.read_secret(tmp_path / "absent")
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected SystemExit on a missing secret")


def test_a_failed_probe_discards_the_session():
    # A canary that started before its database existed can hold a session the
    # server will never accept again, and would then report a permanent false
    # outage. The next probe has to start clean.
    session = _session({"result": {"uid": 2}}, login_status=500)
    result = canary.run_once(session, "http://odoo:8069", "acme", "canary", "pw")
    assert result.success is False
    session.cookies.clear.assert_called_once()


def test_a_successful_probe_keeps_the_session():
    session = _session({"result": {"uid": 2}})
    result = canary.run_once(session, "http://odoo:8069", "acme", "canary", "pw")
    assert result.success is True
    session.cookies.clear.assert_not_called()
