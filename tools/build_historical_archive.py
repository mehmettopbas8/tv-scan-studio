"""Package the preserved 33,075-task scan without inventing result rows."""

from __future__ import annotations

import gzip
import json
import sqlite3
from pathlib import Path


def key(row):
    return f"{row['preset_id']}|{row['variant']}"


def main():
    trading = Path(__file__).resolve().parents[2]
    source = trading / "tmp/overnight_33075_queue.sqlite3"
    logs = sorted((trading / "tmp").glob("overnight_33075_worker_*.jsonl"))
    if len(logs) != 16:
        raise RuntimeError(f"16 worker kaydı bekleniyordu; bulunan: {len(logs)}")
    latest = {}
    for log in logs:
        with log.open(encoding="utf-8") as stream:
            for line in stream:
                result = json.loads(line)
                task_key = key(result)
                if result.get("at", 0) >= latest.get(task_key, {}).get("at", -1):
                    latest[task_key] = result
    if len(latest) != 33_075:
        raise RuntimeError(f"Ham sonuç sayısı beklenen 33.075 değil: {len(latest)}")

    destination = Path(__file__).resolve().parents[1] / "src/tv_scan_studio/data/ftmo_overnight_33075.jsonl.gz"
    counts = {"rows": 0, "valid": 0, "moderate_pass": 0, "failed": 0}
    connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    try:
        with gzip.open(destination, "wt", encoding="utf-8", compresslevel=9) as output:
            for task_id, task_key, payload, status in connection.execute(
                "SELECT id,task_key,payload,status FROM tasks ORDER BY id"
            ):
                result = latest.pop(task_key, None)
                if result is None:
                    raise RuntimeError(f"Sonucu olmayan görev: {task_key}")
                record = {"task_id": task_id, "task_key": task_key, "status": status,
                          "payload": json.loads(payload), "result": result}
                output.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
                counts["rows"] += 1
                counts["valid"] += bool(result.get("valid"))
                counts["moderate_pass"] += bool(result.get("pass"))
                counts["failed"] += status == "failed"
    finally:
        connection.close()
    if latest or counts != {"rows": 33_075, "valid": 32_923,
                           "moderate_pass": 501, "failed": 152}:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Arşiv sayıları kaynak özetle uyuşmuyor: {counts}, ekstra={len(latest)}")
    print(destination, destination.stat().st_size, counts)


if __name__ == "__main__":
    main()
