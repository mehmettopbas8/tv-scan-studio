"""Threaded supervisor for independently targeted TradingView workers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .storage import Store
from .tradingview import TradingViewDriver
from .worker import ScanWorker


@dataclass(frozen=True, slots=True)
class WorkerAssignment:
    worker_id: int
    target_id: str
    project_ids: tuple[int, ...]
    study_id: str | None = None


@dataclass(slots=True)
class WorkerState:
    worker_id: int
    target_id: str
    status: str = "starting"
    completed: int = 0
    last_seen: float = field(default_factory=time.time)
    error: str | None = None
    restarts: int = 0
    attempts: int = 0


class WorkerSupervisor:
    def __init__(self, store: Store, driver: TradingViewDriver, heartbeat_seconds: float = 5,
                 target_guard: Callable[[str], None] | None = None,
                 download_directory: Path | None = None):
        self.store = store
        self.driver = driver
        self.heartbeat_seconds = heartbeat_seconds
        self.target_guard = target_guard
        self.download_directory = download_directory
        if hasattr(driver, "target_guard"):
            driver.target_guard = target_guard
        self.states: dict[int, WorkerState] = {}
        self._threads: list[threading.Thread] = []
        self._threads_by_worker: dict[int, threading.Thread] = {}
        self._assignments: dict[int, tuple[WorkerAssignment, bool]] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def start(self, assignments: list[WorkerAssignment], *, stop_when_idle: bool = False) -> None:
        if self.running:
            raise RuntimeError("Workerlar zaten çalışıyor.")
        if len({item.worker_id for item in assignments}) != len(assignments):
            raise ValueError("Worker kimlikleri benzersiz olmalıdır.")
        if len({item.target_id for item in assignments}) != len(assignments):
            raise ValueError("Her worker bağımsız bir TradingView target kullanmalıdır.")
        available = set(self.driver.targets())
        missing = [item.target_id for item in assignments if item.target_id not in available]
        if missing:
            raise ValueError("TradingView target bulunamadı: " + ", ".join(missing))
        self._stop.clear(); self._threads = []; self._threads_by_worker = {}; self._assignments = {}; self.states = {}
        for assignment in assignments:
            self.states[assignment.worker_id] = WorkerState(assignment.worker_id, assignment.target_id)
            self._assignments[assignment.worker_id] = (assignment, stop_when_idle)
            self._start_thread(assignment, stop_when_idle)

    def _start_thread(self, assignment: WorkerAssignment, stop_when_idle: bool) -> None:
        thread = threading.Thread(
            target=self._loop, args=(assignment, stop_when_idle),
            name=f"tv-scan-worker-{assignment.worker_id}", daemon=True,
        )
        self._threads.append(thread)
        self._threads_by_worker[assignment.worker_id] = thread
        thread.start()

    def restart_failed(self, max_restarts: int = 3) -> list[int]:
        """Restart terminal worker threads without duplicating a live target."""
        restarted: list[int] = []
        if self._stop.is_set():
            return restarted
        with self._lock:
            for worker_id, state in self.states.items():
                thread = self._threads_by_worker.get(worker_id)
                if state.status != "failed" or (thread and thread.is_alive()) or state.restarts >= max_restarts:
                    continue
                assignment, stop_when_idle = self._assignments[worker_id]
                state.restarts += 1
                state.status = "restarting"
                state.error = None
                state.last_seen = time.time()
                self.store.log_event("warning", f"Worker yeniden başlatılıyor ({state.restarts}/{max_restarts})", worker_id=worker_id)
                self._start_thread(assignment, stop_when_idle)
                restarted.append(worker_id)
        return restarted

    def _loop(self, assignment: WorkerAssignment, stop_when_idle: bool) -> None:
        worker = ScanWorker(
            assignment.worker_id, assignment.target_id, self.store, self.driver,
            list(assignment.project_ids), assignment.study_id, self.target_guard,
            self.download_directory,
        )
        state = self.states[assignment.worker_id]
        try:
            while not self._stop.is_set():
                state.status = "running"; state.last_seen = time.time()
                worked = worker.run_one()
                if worked:
                    state.attempts += 1
                    if worker.last_completed:
                        state.completed += 1
                    state.last_seen = time.time()
                    continue
                state.status = "idle"; state.last_seen = time.time()
                if stop_when_idle: break
                self._stop.wait(self.heartbeat_seconds)
        except Exception as exc:
            state.status = "failed"; state.error = str(exc); state.last_seen = time.time()
            self.store.log_event("error", str(exc), worker_id=assignment.worker_id)
        finally:
            if state.status not in {"failed", "idle"}: state.status = "stopped"

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(max(0, deadline - time.monotonic()))

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        for thread in self._threads:
            remaining = None if deadline is None else max(0, deadline - time.monotonic())
            thread.join(remaining)
        return not self.running
