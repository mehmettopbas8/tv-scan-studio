"""CSV exports for scan results."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable


def export_results_csv(rows: Iterable[dict[str, Any]], destination: str | Path) -> int:
    """Write result rows with stable columns and flattened payload/metrics."""
    materialized = list(rows)
    payload_keys = sorted({key for row in materialized for key in row["payload"]})
    metric_keys = sorted({key for row in materialized for key in row["metrics"]})
    evidence_keys = sorted({key for row in materialized for key in row.get("evidence", {})})
    fieldnames = ["task_key", "classification", "verified"]
    fieldnames += [f"input.{key}" for key in payload_keys]
    fieldnames += [f"metric.{key}" for key in metric_keys]
    fieldnames += [f"observed.{key}" for key in evidence_keys]

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for row in materialized:
            output = {
                "task_key": row["task_key"],
                "classification": row["classification"],
                "verified": row["verified"],
            }
            output.update({f"input.{key}": row["payload"].get(key, "") for key in payload_keys})
            output.update({f"metric.{key}": row["metrics"].get(key, "") for key in metric_keys})
            output.update({f"observed.{key}": row.get("evidence", {}).get(key, "") for key in evidence_keys})
            writer.writerow(output)
    return len(materialized)
