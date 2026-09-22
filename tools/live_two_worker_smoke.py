"""Guarded live smoke test for two independent TradingView CDP targets."""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

from tv_scan_studio.storage import Store
from tv_scan_studio.supervisor import WorkerAssignment, WorkerSupervisor
from tv_scan_studio.tradingview import GncZihinDriver


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", action="append", required=True, help="Exactly two CDP target IDs")
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--execute", default="")
    args = parser.parse_args()
    if args.execute != "I_UNDERSTAND":
        raise SystemExit("DRY-RUN SAFETY LOCK: canlı test başlatılmadı. --execute I_UNDERSTAND gerekli.")
    if len(args.target) != 2 or len(set(args.target)) != 2:
        raise SystemExit("Tam olarak iki farklı --target gerekli.")

    driver = GncZihinDriver()
    available = set(driver.targets())
    if any(target not in available for target in args.target):
        raise SystemExit("İstenen targetlardan biri artık mevcut değil; targetları yeniden keşfedin.")

    with tempfile.TemporaryDirectory(
        prefix="tv-scan-live-smoke-", ignore_cleanup_errors=True
    ) as temp:
        store = Store(Path(temp) / "smoke.db")
        assignments = []
        for index, target in enumerate(args.target, start=1):
            before = driver.snapshot(target, args.study_id)
            if before.status_type != 2 or not before.metrics:
                raise SystemExit(f"Target hazır değil: {target}, status={before.status_type}")
            backtest = ((before.period or {}).get("dateRange") or {}).get("backtest") or {}
            date_range = {
                key: datetime.fromtimestamp(value / 1000).date().isoformat()
                for key, value in backtest.items() if key in {"from", "to"}
            }
            project = store.create_project(f"Live smoke {index}", 'strategy("Live smoke")')
            pine_inputs = {
                key: value for key, value in before.inputs.items()
                if re.fullmatch(r"in_\d+", key)
            }
            if not pine_inputs:
                raise SystemExit(f"Pine input bulunamadı: {target}")
            smoke_input = dict([next(iter(pine_inputs.items()))])
            store.enqueue(project, f"live-{index}", {
                "study_id": args.study_id, "symbol": before.symbol,
                "timeframe": before.timeframe, "inputs": smoke_input,
                "date_range": date_range, "timeout": 25,
                "criteria": {},
            })
            assignments.append(WorkerAssignment(index, target, (project,), args.study_id))

        supervisor = WorkerSupervisor(store, driver, heartbeat_seconds=0.2)
        supervisor.start(assignments, stop_when_idle=True)
        if not supervisor.wait(90):
            supervisor.stop(timeout=35)
            report = {
                "workers": {key: {"status": value.status, "completed": value.completed,
                                   "error": value.error}
                            for key, value in supervisor.states.items()},
                "counts": store.total_counts(), "events": store.events(),
            }
            print(json.dumps(report, ensure_ascii=False, indent=2))
            raise SystemExit("Worker smoke testi zaman aşımına uğradı.")
        report = {
            "workers": {key: {"status": value.status, "completed": value.completed, "error": value.error}
                        for key, value in supervisor.states.items()},
            "counts": store.total_counts(),
            "events": store.events(),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["counts"] == {"done": 2} else 1


if __name__ == "__main__":
    raise SystemExit(main())
