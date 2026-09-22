"""Packaged subset of gnc-zihin's target-explicit raw CDP motor."""

from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path

from websocket import create_connection

CDP_PORT = 9222


def bul_hedefler() -> list[str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json/list", timeout=5) as response:
        targets = json.loads(response.read())
    return [
        target["id"] for target in targets
        if target.get("type") == "page" and "tradingview.com/chart" in target.get("url", "")
    ]


def _eval(target_id: str, expression: str, await_promise: bool = False, timeout: int = 25):
    websocket = create_connection(
        f"ws://127.0.0.1:{CDP_PORT}/devtools/page/{target_id}",
        timeout=timeout, suppress_origin=True,
    )
    try:
        websocket.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": expression, "returnByValue": True, "awaitPromise": await_promise,
        }}))
        result = json.loads(websocket.recv())
    finally:
        websocket.close()
    exception = result.get("result", {}).get("exceptionDetails")
    if exception: raise RuntimeError(f"CDP eval hatası: {exception}")
    return result.get("result", {}).get("result", {}).get("value")


def screenshot(target_id: str, destination: str | Path) -> str:
    websocket = create_connection(
        f"ws://127.0.0.1:{CDP_PORT}/devtools/page/{target_id}",
        timeout=20, suppress_origin=True,
    )
    try:
        websocket.send(json.dumps({"id": 1, "method": "Page.captureScreenshot", "params": {"format": "png"}}))
        result = json.loads(websocket.recv())
    finally:
        websocket.close()
    data = result.get("result", {}).get("data")
    if not data: raise RuntimeError("TradingView ekran görüntüsü alınamadı.")
    path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data))
    return str(path)
