"""Raw CDP replies must match the command, even when events arrive first."""

import base64
import json

import pytest
from websocket import WebSocketTimeoutException

from tv_scan_studio import motor_bridge


class FakeSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.timeouts = []
        self.closed = False

    def send(self, value):
        self.sent.append(json.loads(value))

    def settimeout(self, value):
        self.timeouts.append(value)

    def recv(self):
        value = next(self.messages)
        if isinstance(value, Exception):
            raise value
        return json.dumps(value)

    def close(self):
        self.closed = True


def _socket(monkeypatch, messages):
    socket = FakeSocket(messages)
    monkeypatch.setattr(motor_bridge, "create_connection", lambda *_a, **_kw: socket)
    return socket


def test_eval_ignores_events_and_other_id_before_own_reply(monkeypatch):
    socket = _socket(monkeypatch, [
        {"method": "Runtime.consoleAPICalled", "params": {}},
        {"id": 7, "result": {"result": {"value": "wrong"}}},
        {"id": 1, "result": {"result": {"value": True}}},
    ])
    assert motor_bridge._eval("worker", "true") is True
    assert socket.sent[0]["method"] == "Runtime.evaluate"
    assert socket.closed and len(socket.timeouts) == 3


@pytest.mark.parametrize("call", [
    lambda: motor_bridge._eval("worker", "1"),
    lambda: motor_bridge.insert_text("worker", "value"),
    lambda: motor_bridge.screenshot("worker", "unused.png"),
])
def test_cdp_error_reply_is_not_a_success(monkeypatch, call):
    socket = _socket(monkeypatch, [{"id": 1, "error": {"code": -32000, "message": "denied"}}])
    with pytest.raises(RuntimeError, match="denied"):
        call()
    assert socket.closed


def test_eval_exception_details_is_an_error(monkeypatch):
    _socket(monkeypatch, [{"id": 1, "result": {"exceptionDetails": {"text": "boom"}}}])
    with pytest.raises(RuntimeError, match="boom"):
        motor_bridge._eval("worker", "throw Error()")


def test_bounded_timeout_closes_socket(monkeypatch):
    socket = _socket(monkeypatch, [
        {"method": "Runtime.executionContextCreated", "params": {}},
        WebSocketTimeoutException("late"),
    ])
    with pytest.raises(TimeoutError, match="zaman aşımına"):
        motor_bridge._eval("worker", "1", timeout=0.5)
    assert socket.closed
    assert all(0 < value <= 0.5 for value in socket.timeouts)


def test_insert_text_waits_for_matching_ack(monkeypatch):
    socket = _socket(monkeypatch, [{"method": "Input.dragIntercepted"}, {"id": 1, "result": {}}])
    assert motor_bridge.insert_text("worker", "2026-10-08") is None
    assert socket.sent[0]["params"]["text"] == "2026-10-08"
    assert socket.closed


def test_screenshot_writes_only_matched_reply(monkeypatch, tmp_path):
    png = b"\x89PNG\r\n\x1a\n"
    socket = _socket(monkeypatch, [
        {"method": "Page.frameNavigated", "params": {}},
        {"id": 1, "result": {"data": base64.b64encode(png).decode()}}
    ])
    path = tmp_path / "shot.png"
    assert motor_bridge.screenshot("worker", path) == str(path)
    assert path.read_bytes() == png
    assert socket.closed


def test_missing_cdp_result_is_rejected(monkeypatch):
    socket = _socket(monkeypatch, [{"id": 1}])
    with pytest.raises(RuntimeError, match="sonuç biçimi"):
        motor_bridge.insert_text("worker", "x")
    assert socket.closed
