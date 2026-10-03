"""Read-only access to the preserved 23 September scan's actual task rows."""

from __future__ import annotations

import gzip
import json
from importlib.resources import files


ARCHIVE_NAME = "ftmo_overnight_33075.jsonl.gz"


def iter_historical_records():
    archive = files("tv_scan_studio").joinpath("data", ARCHIVE_NAME)
    if not archive.is_file():
        return
    with archive.open("rb") as raw, gzip.open(raw, "rt", encoding="utf-8") as stream:
        for line in stream:
            source = json.loads(line)
            payload = source["payload"]
            result = source["result"]
            metrics = result.get("metrics") or {}
            status = result.get("status") or {}
            error = (status.get("errorDescription") or {}).get("error") or ""
            valid = bool(result.get("valid"))
            if not valid and not error:
                error = "Kaynak kayıtta ayrıntılı hata nedeni yok; geçersiz veya kararsız okuma."
            yield {
                "task_id": source["task_id"], "task_key": source["task_key"],
                "status": source["status"], "attempts": 1,
                "started_at": None, "finished_at": result.get("at"),
                "classification": ("orta maliyet geçti" if result.get("pass") else
                                   "elenmiş" if valid else "geçersiz"),
                "verified": valid,
                "error": error,
                "payload": {
                    "symbol": result.get("symbol") or payload.get("symbol"),
                    "timeframe": str(result.get("tf") or payload.get("tf") or ""),
                    "date_range": (result.get("period") or {}).get("dateRange", {}).get("backtest") or {},
                    "inputs": result.get("params") or payload.get("params") or {},
                    "research_source_id": result.get("preset_id") or payload.get("preset_id"),
                    "costs": {"commission_pct": (result.get("params") or {}).get("in_154"),
                              "friction_ticks": (result.get("params") or {}).get("in_155")},
                    "candidate": result.get("candidate"), "variant": result.get("variant"),
                    "source_phase": result.get("phase"),
                },
                "metrics": {
                    "trades": metrics.get("trades"), "profit_factor": metrics.get("pf"),
                    "win_rate_pct": metrics.get("win"), "max_drawdown_pct": metrics.get("dd"),
                    "net_profit": metrics.get("net"), "net_pct": metrics.get("net_pct"),
                    "source_period": result.get("period"), "elapsed_seconds": result.get("elapsed"),
                },
                "evidence": {"source": "2026-09-23 worker JSONL + task queue",
                             "read_status": status.get("type"), "worker": result.get("worker"),
                             "result_at": result.get("at")},
            }
