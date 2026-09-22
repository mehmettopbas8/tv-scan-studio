"""Windows-specific TradingView Desktop discovery and CDP startup."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import Callable


def find_tradingview_executables(
    *, env: dict[str, str] | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[Path]:
    env = env or os.environ
    candidates = [
        Path(env.get("LOCALAPPDATA", "")) / "Programs" / "TradingView" / "TradingView.exe",
        Path(env.get("PROGRAMFILES", "")) / "TradingView" / "TradingView.exe",
        Path(env.get("PROGRAMFILES(X86)", "")) / "TradingView" / "TradingView.exe",
    ]
    try:
        result = run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-AppxPackage TradingView.Desktop -ErrorAction SilentlyContinue).InstallLocation"],
            capture_output=True, text=True, timeout=8, check=False,
        )
        for line in result.stdout.splitlines():
            location = Path(line.strip())
            if line.strip():
                candidates.extend((location / "TradingView.exe", location / "app" / "TradingView.exe"))
    except (OSError, subprocess.SubprocessError):
        pass
    unique: list[Path] = []
    for candidate in candidates:
        if candidate.is_file() and candidate not in unique: unique.append(candidate)
    return unique


def cdp_healthy(port: int = 9222, timeout: float = 2) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
            data = json.loads(response.read())
        return bool(data.get("webSocketDebuggerUrl"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def tradingview_running(
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> bool:
    try:
        result = run(["tasklist", "/FI", "IMAGENAME eq TradingView.exe", "/FO", "CSV"],
                     capture_output=True, text=True, timeout=5, check=False)
        return "TradingView.exe" in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def launch_with_cdp(executable: str | Path, port: int = 9222) -> subprocess.Popen:
    path = Path(executable)
    if not path.is_file(): raise FileNotFoundError(path)
    if tradingview_running() and not cdp_healthy(port):
        raise RuntimeError("TradingView CDP olmadan açık. Uygulamayı kapatıp yeniden başlatma izni gerekiyor.")
    if cdp_healthy(port):
        raise RuntimeError("TradingView CDP bağlantısı zaten hazır.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [str(path), f"--remote-debugging-port={port}", "--remote-allow-origins=*"],
        creationflags=flags,
    )
