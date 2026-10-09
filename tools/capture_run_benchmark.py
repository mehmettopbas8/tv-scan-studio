"""Capture an existing run read-only; never start tasks or authenticate live evidence."""
import argparse
import json
import sqlite3
import time
from pathlib import Path

from tv_scan_studio.benchmark import artifact_digest, capture_run, serialize_record


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--run", required=True, type=int)
    parser.add_argument("--workers", required=True, type=int)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--context-json", required=True, type=Path,
                        help="Existing JSON file with machine, tradingview_version, account_tier, protocol")
    parser.add_argument("--evidence", action="append", default=[], type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--real-tradingview", action="store_true",
                        help="Assert actual live provenance; not authentication or acceptance")
    args = parser.parse_args(argv)
    try:
        if args.run < 1 or not 1 <= args.workers <= 16:
            raise ValueError("Run must be positive and workers must be 1–16")
        if args.output.exists() or args.output.is_symlink() or not args.output.parent.is_dir():
            raise ValueError("Choose a new output file in an existing folder")
        for path in (args.database, args.exe, args.context_json, *args.evidence):
            if path.is_symlink() or not path.is_file():
                raise ValueError("Inputs and evidence must be existing normal files")
        context = json.loads(args.context_json.read_text(encoding="utf-8"))
        build = artifact_digest(args.exe)
        with sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            record = capture_run(db, args.run, workers=args.workers,
                build_sha256=build["sha256"], context=context,
                provenance="real_tradingview" if args.real_tradingview else "local_unverified",
                evidence_paths=args.evidence, now=time.time())
            serialized = serialize_record(record)
            db.rollback()
        if artifact_digest(args.exe) != build:
            raise ValueError("Measured EXE changed during capture")
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(serialized)
        print(json.dumps({"status": "captured", "acceptance": False,
                          "eligible_for_review": record["eligible_for_review"],
                          "message": "Independent live evidence review remains required."}))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
