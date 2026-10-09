"""Packaged subset of gnc-zihin's target-explicit raw CDP motor."""

from __future__ import annotations

import base64
import json
import time
import urllib.request
from pathlib import Path

from websocket import WebSocketTimeoutException, create_connection

CDP_PORT = 9222


def _cdp_request(target_id: str, method: str, params: dict, *, timeout: float) -> dict:
    """Wait for this command's CDP reply, ignoring unsolicited page events."""
    if timeout <= 0:
        raise ValueError("CDP zaman aşımı pozitif olmalı.")
    deadline = time.monotonic() + timeout
    websocket = create_connection(
        f"ws://127.0.0.1:{CDP_PORT}/devtools/page/{target_id}",
        timeout=timeout, suppress_origin=True,
    )
    try:
        websocket.send(json.dumps({"id": 1, "method": method, "params": params}))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"CDP {method} yanıtı zaman aşımına uğradı.")
            websocket.settimeout(remaining)
            try:
                message = json.loads(websocket.recv())
            except (WebSocketTimeoutException, TimeoutError) as exc:
                raise TimeoutError(f"CDP {method} yanıtı zaman aşımına uğradı.") from exc
            if not isinstance(message, dict):
                raise RuntimeError(f"CDP {method} yanıtı geçersiz.")
            if message.get("id") != 1:
                # A new socket sends only command id 1; events have no id.
                # Neither events nor unrelated responses prove our command ran.
                continue
            if message.get("error"):
                raise RuntimeError(f"CDP {method} hatası: {message['error']!r}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"CDP {method} sonuç biçimi geçersiz.")
            return result
    finally:
        websocket.close()


def bul_hedefler() -> list[str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=5) as response:
        targets = json.loads(response.read())
    return [
        target["id"] for target in targets
        if target.get("type") == "page" and "tradingview.com/chart" in target.get("url", "")
    ]


def _eval(target_id: str, expression: str, await_promise: bool = False, timeout: int = 25):
    result = _cdp_request(target_id, "Runtime.evaluate", {
        "expression": expression, "returnByValue": True, "awaitPromise": await_promise,
    }, timeout=timeout)
    exception = result.get("exceptionDetails")
    if exception: raise RuntimeError(f"CDP eval hatası: {exception}")
    value = result.get("result")
    if not isinstance(value, dict):
        raise RuntimeError("CDP eval sonucu geçersiz.")
    return value.get("value")


def insert_text(target_id: str, value: str, timeout: int = 10) -> None:
    """Send genuine CDP text input to the already-focused target field."""
    _cdp_request(target_id, "Input.insertText", {"text": value}, timeout=timeout)


def screenshot(target_id: str, destination: str | Path) -> str:
    result = _cdp_request(target_id, "Page.captureScreenshot", {"format": "png"}, timeout=20)
    data = result.get("data")
    if not data: raise RuntimeError("TradingView ekran görüntüsü alınamadı.")
    path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data))
    return str(path)
