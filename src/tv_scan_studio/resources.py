"""Host resource snapshots and conservative worker recommendations."""

from __future__ import annotations

import os
import ctypes
import time
from dataclasses import asdict, dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    logical_cpus: int
    total_memory_bytes: int
    available_memory_bytes: int
    cpu_percent: float

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class WorkerRecommendation:
    recommended: int
    cpu_limit: int
    memory_limit: int
    candidates: tuple[int, ...] = (2, 4, 8, 16)


def system_snapshot() -> ResourceSnapshot:
    if os.name != "nt":  # pragma: no cover - production target is Windows
        raise RuntimeError("Kaynak ölçümü şu anda yalnızca Windows üzerinde destekleniyor.")

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong), ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong), ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong), ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    def system_times() -> tuple[int, int]:
        idle = ctypes.c_ulonglong(); kernel = ctypes.c_ulonglong(); user = ctypes.c_ulonglong()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            raise RuntimeError("Windows CPU sayaçları okunamadı.")
        return idle.value, kernel.value + user.value

    memory = MemoryStatus(); memory.length = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise RuntimeError("Windows bellek bilgisi okunamadı.")
    idle_before, total_before = system_times()
    time.sleep(0.15)
    idle_after, total_after = system_times()
    total_delta = total_after - total_before
    idle_delta = idle_after - idle_before
    cpu_percent = 100.0 * (1.0 - idle_delta / total_delta) if total_delta > 0 else 0.0
    return ResourceSnapshot(
        logical_cpus=max(1, os.cpu_count() or 1),
        total_memory_bytes=int(memory.total_physical),
        available_memory_bytes=int(memory.available_physical),
        cpu_percent=max(0.0, min(100.0, cpu_percent)),
    )


def recommend_workers(snapshot: ResourceSnapshot, *,
                      memory_per_worker_bytes: int = 1_250_000_000,
                      reserve_memory_bytes: int = 2_000_000_000) -> WorkerRecommendation:
    if memory_per_worker_bytes <= 0:
        raise ValueError("Worker başına bellek sıfırdan büyük olmalıdır.")
    usable = max(0, snapshot.available_memory_bytes - reserve_memory_bytes)
    memory_limit = max(1, usable // memory_per_worker_bytes)
    cpu_limit = max(1, snapshot.logical_cpus // 2)
    hard_limit = max(1, min(16, cpu_limit, memory_limit))
    candidates = (2, 4, 8, 16)
    eligible = [value for value in candidates if value <= hard_limit]
    recommended = max(eligible, default=1)
    if snapshot.cpu_percent >= 80:
        recommended = max(1, recommended // 2)
    return WorkerRecommendation(
        recommended=recommended, cpu_limit=cpu_limit,
        memory_limit=int(memory_limit), candidates=candidates,
    )


def benchmark_candidates(measure: Callable[[int], float]) -> list[dict[str, float | int]]:
    """Run a caller-supplied non-destructive measurement for standard worker counts."""
    rows = []
    for workers in (2, 4, 8, 16):
        score = float(measure(workers))
        rows.append({"workers": workers, "tests_per_hour": max(0.0, score)})
    return rows


def project_worker_throughput(seconds_per_test: float, safe_worker_limit: int) -> list[dict[str, float | int | bool]]:
    if seconds_per_test <= 0:
        raise ValueError("Test süresi sıfırdan büyük olmalıdır.")
    rows = []
    for workers in (2, 4, 8, 16):
        effective = min(workers, max(1, safe_worker_limit))
        rows.append({
            "workers": workers,
            "tests_per_hour": effective * 3600 / seconds_per_test,
            "within_safe_limit": workers <= safe_worker_limit,
        })
    return rows
