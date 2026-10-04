"""Windows-specific TradingView Desktop discovery and CDP startup."""

from __future__ import annotations

import json
import ctypes
import os
import re
import subprocess
import time
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Callable
from .processes import HelperStartupError, run_hidden, popen_external


def _native_cdp_owner() -> bool:
    """Resolve TCP listener owners with Win32; no PowerShell process is needed."""
    from ctypes import wintypes
    iphelper = ctypes.WinDLL("iphlpapi", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    get_table = iphelper.GetExtendedTcpTable
    get_table.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                         wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    owners = set()
    for family, row_size, port_offset, pid_offset in ((2, 24, 8, 20), (23, 56, 20, 52)):
        size = wintypes.DWORD(0)
        result = get_table(None, ctypes.byref(size), False, family, 3, 0)
        if result not in (0, 122):
            return False
        data = ctypes.create_string_buffer(size.value)
        if get_table(data, ctypes.byref(size), False, family, 3, 0) != 0:
            return False
        count = int.from_bytes(data.raw[:4], "little")
        if 4 + count * row_size > size.value:
            return False
        for index in range(count):
            row = data.raw[4 + index * row_size:4 + (index + 1) * row_size]
            if int.from_bytes(row[port_offset:port_offset + 2], "big") == 9222:
                owners.add(int.from_bytes(row[pid_offset:pid_offset + 4], "little"))
    if not owners or 0 in owners:
        return False
    for pid in owners:
        process = kernel.OpenProcess(0x1000, False, pid)
        if not process:
            return False
        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not kernel.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return False
            if Path(buffer.value).name.casefold() != "tradingview.exe":
                return False
        finally:
            kernel.CloseHandle(process)
    return True


class TabCreationError(RuntimeError):
    def __init__(self, message: str, created_targets: list[str]):
        super().__init__(message)
        self.created_targets = tuple(created_targets)


def _open_chart_from_page(target_id: str, url: str) -> None:
    """Electron's CDP /json/new can return 500; open via its existing chart page."""
    from . import motor_bridge
    motor_bridge._eval(target_id,
                       f"window.open({json.dumps(url)}, '_blank'); true")


def _is_tradingview_chart(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    return (parsed.scheme in {"http", "https"}
            and (host == "tradingview.com" or host.endswith(".tradingview.com"))
            and parsed.path.startswith("/chart/"))


def find_tradingview_executables(
    *, env: dict[str, str] | None = None,
    run: Callable[..., subprocess.CompletedProcess] = run_hidden,
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
    except HelperStartupError:
        raise
    except (OSError, subprocess.SubprocessError):
        pass
    unique: list[Path] = []
    for candidate in candidates:
        if candidate.is_file() and candidate not in unique: unique.append(candidate)
    return unique


def cdp_owned_by_tradingview(
    run: Callable[..., subprocess.CompletedProcess] = run_hidden,
) -> bool:
    """Fail closed unless every process listening on 9222 is TradingView Desktop."""
    if os.name != "nt":
        return False
    if run is run_hidden:
        try:
            return _native_cdp_owner()
        except (OSError, ValueError):
            return False
    try:
        result = run(
            ["powershell", "-NoProfile", "-Command",
             "$p=Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction Stop; "
             "$p | Select-Object -ExpandProperty OwningProcess -Unique | "
             "ForEach-Object { (Get-Process -Id $_ -ErrorAction Stop).ProcessName }"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is not None and result.returncode == 0:
        owners = [line.strip().casefold() for line in result.stdout.splitlines() if line.strip()]
        return bool(owners) and all(owner == "tradingview" for owner in owners)

    # Get-NetTCPConnection can be denied to an ordinary Windows user even when
    # the loopback CDP endpoint and Get-Process are readable. Keep the owner
    # check, but resolve listener PIDs through netstat in that case.
    try:
        sockets = run(["netstat", "-ano", "-p", "tcp"], capture_output=True,
                      text=True, timeout=5, check=False)
        if sockets.returncode != 0:
            return False
        pids = set()
        for line in sockets.stdout.splitlines():
            fields = line.split()
            if (len(fields) >= 5 and fields[0].upper() == "TCP"
                    and fields[1].rsplit(":", 1)[-1] == "9222"
                    and fields[3].upper() == "LISTENING"):
                if not fields[4].isdigit():
                    return False
                pids.add(int(fields[4]))
        if not pids or 0 in pids:
            return False
        pid_list = ",".join(str(pid) for pid in sorted(pids))
        owners_result = run(
            ["powershell", "-NoProfile", "-Command",
             f"@({pid_list}) | ForEach-Object {{ (Get-Process -Id $_ -ErrorAction Stop).ProcessName }}"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    owners = [line.strip().casefold() for line in owners_result.stdout.splitlines() if line.strip()]
    return (owners_result.returncode == 0 and len(owners) == len(pids)
            and all(owner == "tradingview" for owner in owners))


def cdp_healthy(port: int = 9222, timeout: float = 2) -> bool:
    if port != 9222 or not cdp_owned_by_tradingview():
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=timeout) as response:
            data = json.loads(response.read())
        return bool(data.get("webSocketDebuggerUrl"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False


def chart_targets(*, port: int = 9222, timeout: float = 5,
                  urlopen: Callable[..., object] = urllib.request.urlopen,
                  owner_check: Callable[[], bool] = cdp_owned_by_tradingview) -> list[dict[str, str]]:
    """Read chart targets from the sole permitted TradingView CDP session."""
    if port != 9222:
        raise ValueError("Yalnızca mevcut TradingView 9222 oturumu kullanılabilir.")
    if not owner_check():
        raise RuntimeError("9222 portu TradingView Desktop tarafından açılmamış; grafikler okunmadı.")
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=timeout) as response:
            targets = json.loads(response.read())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"CDP {port} target listesi okunamadı.") from exc
    return [{"id": str(item["id"]), "url": str(item["url"])} for item in targets
            if item.get("type") == "page" and item.get("id")
            and _is_tradingview_chart(str(item.get("url") or ""))]


def worker_layout_candidates(targets: list[dict[str, str]],
                             layout_names: dict[str, str]) -> dict[str, str]:
    """Return only uniquely open, explicitly named worker layout targets."""
    chart_ids = [urllib.parse.urlsplit(item["url"]).path.split("/")[2]
                 for item in targets if _is_tradingview_chart(item.get("url", ""))]
    candidates: dict[str, str] = {}
    all_names = list(layout_names.values())
    for item in targets:
        target_id, url = item.get("id", ""), item.get("url", "")
        name = layout_names.get(target_id, "")
        if not target_id or not _is_tradingview_chart(url) or not re.fullmatch(r"TV Scan Worker [1-9]\d*", name):
            continue
        chart_id = urllib.parse.urlsplit(url).path.split("/")[2]
        if chart_ids.count(chart_id) != 1 or all_names.count(name) != 1:
            continue  # A conflicting layout must not disable independent workers.
        candidates[target_id] = chart_id
    return candidates


def open_chart_tabs(count: int, *, port: int = 9222, timeout: float = 5,
                    urlopen: Callable[..., object] = urllib.request.urlopen,
                    owner_check: Callable[[], bool] = cdp_owned_by_tradingview,
                    page_opener: Callable[[str, str], None] = _open_chart_from_page) -> list[str]:
    """Duplicate a chart as tabs inside the one existing CDP browser profile."""
    if port != 9222:
        raise ValueError("Yalnızca mevcut TradingView 9222 oturumu kullanılabilir.")
    if count < 1 or count > 16:
        raise ValueError("Yeni tab sayısı 1 ile 16 arasında olmalıdır.")
    if not owner_check():
        raise RuntimeError("9222 portu TradingView Desktop tarafından açılmamış; yeni sekme açılmadı.")
    try:
        with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=timeout) as response:
            targets = json.loads(response.read())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"CDP {port} target listesi okunamadı.") from exc
    charts = [item for item in targets
              if item.get("type") == "page" and item.get("id")
              and _is_tradingview_chart(str(item.get("url") or ""))]
    if not charts:
        raise RuntimeError("Kopyalanacak TradingView chart tabı bulunamadı.")
    existing_ids = {str(item["id"]) for item in targets if item.get("id")}
    created = []
    for _ in range(count):
        endpoint = f"http://127.0.0.1:{port}/json/new?{urllib.parse.quote(str(charts[0]['url']), safe=':/?=&%')}"
        request = urllib.request.Request(endpoint, method="PUT")
        try:
            with urlopen(request, timeout=timeout) as response:
                target = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code != 500:
                raise TabCreationError("Aynı CDP oturumunda yeni chart tabı açılamadı.", created) from exc
            # TradingView Desktop's Electron endpoint rejects /json/new, while
            # window.open in an existing chart creates a tab in the same profile.
            try:
                page_opener(str(charts[0]["id"]), str(charts[0]["url"]))
                deadline = time.monotonic() + timeout
                while True:
                    with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=timeout) as response:
                        after = json.loads(response.read())
                    new = [item for item in after if item.get("type") == "page"
                           and str(item.get("id") or "") not in existing_ids
                           and _is_tradingview_chart(str(item.get("url") or ""))]
                    if len(new) == 1:
                        target = new[0]
                        break
                    if len(new) > 1 or time.monotonic() >= deadline:
                        raise RuntimeError("Yeni sekme kimliği tekil olarak doğrulanamadı.")
                    time.sleep(0.2)
            except Exception as fallback_exc:
                raise TabCreationError(
                    "TradingView yeni sekmeyi doğrulayamadı; yeniden denemeden önce açık sekmeleri kontrol edin.",
                    created) from fallback_exc
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise TabCreationError("Aynı CDP oturumunda yeni chart tabı açılamadı.", created) from exc
        target_id = str(target.get("id") or "")
        if not target_id or target_id in existing_ids or target_id in created:
            raise TabCreationError("Yeni çalışma sekmesinin kimliği doğrulanamadı; mevcut grafik korunuyor.", created)
        if target.get("type") not in (None, "page"):
            raise TabCreationError("Açılan CDP hedefi chart sekmesi değil; worker olarak kullanılmadı.", created)
        if not _is_tradingview_chart(str(target.get("url") or "")):
            raise TabCreationError("Yeni CDP sekmesi TradingView chart değil; worker olarak kullanılmadı.", created)
        created.append(target_id)
        existing_ids.add(target_id)
    return created


def tradingview_running(
    run: Callable[..., subprocess.CompletedProcess] = run_hidden,
) -> bool:
    try:
        result = run(["tasklist", "/FI", "IMAGENAME eq TradingView.exe", "/FO", "CSV"],
                     capture_output=True, text=True, timeout=5, check=False)
        return "TradingView.exe" in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def launch_with_cdp(executable: str | Path, port: int = 9222) -> subprocess.Popen:
    if port != 9222:
        raise ValueError("İkinci CDP portu açılamaz; TradingView için yalnız 9222 kullanılır.")
    path = Path(executable)
    if not path.is_file(): raise FileNotFoundError(path)
    if tradingview_running() and not cdp_healthy(port):
        raise RuntimeError("TradingView CDP olmadan açık. Uygulamayı kapatıp yeniden başlatma izni gerekiyor.")
    if cdp_healthy(port):
        raise RuntimeError("TradingView CDP bağlantısı zaten hazır.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return popen_external(
        [str(path), f"--remote-debugging-port={port}", "--remote-allow-origins=*"],
        creationflags=flags,
    )
