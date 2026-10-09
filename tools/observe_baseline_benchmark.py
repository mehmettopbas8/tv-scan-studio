"""Observe an independently started old EXE; never launch or control TradingView.

Start before the explicit task set is claimed. A missed attempt rejects rather
than manufacturing legacy history. Writes one new local manifest only.
"""
import argparse
import json
import math
import sqlite3
import time
from pathlib import Path

from tv_scan_studio.benchmark import BaselineObserver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--project", required=True, type=int)
    parser.add_argument("--tasks", required=True, help="Explicit comma-separated task IDs")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=1800)
    args = parser.parse_args()
    if (args.output.exists() or not args.output.parent.is_dir()
            or not math.isfinite(args.timeout) or args.timeout <= 0):
        parser.error("Choose a new output file in an existing folder and a positive timeout")
    ids = [int(value) for value in args.tasks.split(",")]
    with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        observer = BaselineObserver(db, args.project, ids)
        db.commit()
        print(json.dumps({'status': 'ready', 'project_id': args.project,
                          'task_ids': ids, 'database': str(args.database.resolve()),
                          'message': 'Pending tasks validated; start the measured EXE now.'}), flush=True)
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            db.execute("BEGIN")
            observer.poll(db, observed_at=time.time())
            db.commit()
            if len(observer.finished) == len(ids):
                manifest = observer.manifest()
                with args.output.open("x", encoding="utf-8") as stream:
                    json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
                print("Observed manifest saved; independent live evidence review still required.")
                return
            time.sleep(.05)
        raise RuntimeError("Observation timed out; no complete manifest published.")


if __name__ == "__main__":
    main()
