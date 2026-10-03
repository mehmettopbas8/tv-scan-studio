"""Guarded live smoke test for two pre-existing, independent worker layouts."""

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
from tv_scan_studio.windows import cdp_healthy, chart_targets, worker_layout_candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-name", required=True, help="Exact visible TradingView strategy name")
    parser.add_argument("--vary-first-input", action="store_true",
                        help="Run two distinct values of the first numeric Pine input in one project")
    parser.add_argument("--execute", default="")
    args = parser.parse_args()
    if args.execute != "I_UNDERSTAND":
        raise SystemExit("DRY-RUN SAFETY LOCK: canlı test başlatılmadı. --execute I_UNDERSTAND gerekli.")
    if not cdp_healthy(9222):
        raise SystemExit("CDP 9222 hazır değil; açık TradingView oturumuna dokunulmadı.")

    driver = GncZihinDriver()
    live = chart_targets(port=9222)
    names = {item["id"]: driver.layout_name(item["id"]) for item in live}
    claimed = worker_layout_candidates(live, names)
    targets = [target for target in claimed if names[target] in
               {"TV Scan Worker 1", "TV Scan Worker 2"}]
    if len(targets) != 2:
        raise SystemExit("İki ayrı TV Scan Worker 1/2 layoutu bulunamadı; mevcut grafiklere worker bağlanmadı.")

    def guard(target_id: str) -> None:
        current_tabs = chart_targets(port=9222)
        current = worker_layout_candidates(
            current_tabs, {target_id: driver.layout_name(target_id)})
        if current.get(target_id) != claimed[target_id]:
            raise ValueError("Worker layoutu değişti; görev uygulanmadı.")
        if driver.replay_active(target_id):
            raise ValueError("Worker sekmesinde Bar Replay açık; görev uygulanmadı.")

    with tempfile.TemporaryDirectory(
        prefix="tv-scan-live-smoke-", ignore_cleanup_errors=True
    ) as temp:
        store = Store(Path(temp) / "smoke.db")
        project = store.create_project("Live two-worker smoke", 'strategy("Live two-worker smoke")')
        assignments = []
        first_input_values = []
        for index, target in enumerate(targets, start=1):
            matches = [item for item in driver.strategies(target)
                       if item.get("name") == args.strategy_name
                       and (item.get("status") or {}).get("type") == 2]
            if len(matches) != 1:
                raise SystemExit(
                    f"Yeni sekmede tek bir hazır '{args.strategy_name}' stratejisi bulunamadı: {target}"
                )
            study_id = str(matches[0]["id"])
            before = driver.snapshot(target, study_id)
            if before.status_type != 2 or not before.metrics:
                raise SystemExit(f"Target hazır değil: {target}, status={before.status_type}")
            backtest = ((before.period or {}).get("dateRange") or {}).get("backtest") or {}
            date_range = {
                key: datetime.fromtimestamp(value / 1000).date().isoformat()
                for key, value in backtest.items() if key in {"from", "to"}
            }
            pine_inputs = {
                key: value for key, value in before.inputs.items()
                if re.fullmatch(r"in_\d+", key)
            }
            if not pine_inputs:
                raise SystemExit(f"Pine input bulunamadı: {target}")
            smoke_input = dict([next(iter(pine_inputs.items()))])
            first_key = next(iter(smoke_input))
            if args.vary_first_input:
                first_value = smoke_input[first_key]
                if isinstance(first_value, bool) or not isinstance(first_value, int):
                    raise SystemExit("İlk Pine input tam sayı değil; değer değişimi uygulanmadı.")
                if index == 2:
                    smoke_input[first_key] = first_input_values[0] + 1
                first_input_values.append(smoke_input[first_key])
            store.enqueue(project, f"live-{index}", {
                "study_id": study_id, "symbol": before.symbol,
                "timeframe": before.timeframe, "inputs": smoke_input,
                "date_range": date_range, "timeout": 25,
                "criteria": {},
            })
            assignments.append(WorkerAssignment(index, target, (project,), study_id))

        if args.vary_first_input and len(set(first_input_values)) != 2:
            raise SystemExit("İki farklı input değeri oluşturulamadı; worker başlatılmadı.")

        supervisor = WorkerSupervisor(store, driver, heartbeat_seconds=0.2, target_guard=guard)
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
            "results": [{"task_key": row["task_key"],
                         "target_id": row["evidence"].get("target_id"),
                         "first_input": row["evidence"].get("inputs", {}).get("in_0"),
                         "verified": row["verified"]}
                        for row in store.results(project)],
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["counts"] == {"done": 2} else 1


if __name__ == "__main__":
    raise SystemExit(main())
