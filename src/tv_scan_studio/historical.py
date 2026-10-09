"""Read legacy scan evidence without turning it into newly verified results."""
from __future__ import annotations

import gzip
import hashlib
import json
from importlib.resources import files
from pathlib import Path


def legacy_scan_record(source: dict, index: int, *, source_sha256: str) -> dict:
    original = source
    if isinstance(source, dict) and isinstance(source.get("payload"), dict):
        source = {**source["payload"], **(source.get("result") or {})}
    if not isinstance(source, dict) or not isinstance(source.get("params"), dict):
        raise ValueError(f"Geçmiş kayıt {index}: strateji ayarları eksik.")
    if not isinstance(source.get("symbol"), str) or not source.get("tf"):
        raise ValueError(f"Geçmiş kayıt {index}: sembol veya zaman dilimi eksik.")
    metrics = source.get("metrics") or {}
    if not isinstance(metrics, dict):
        raise ValueError(f"Geçmiş kayıt {index}: ölçümler geçersiz.")
    mapped = { {"pf": "profit_factor", "win": "win_rate_pct", "dd": "max_drawdown_pct",
                "net": "net_profit"}.get(key, key): value for key, value in metrics.items() }
    identity = hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()
    valid = source.get("valid") is True
    raw_status = source.get("status") if isinstance(source.get("status"), dict) else {}
    description = raw_status.get("errorDescription") or {}
    error = source.get("error") or (description.get("error") if isinstance(description, dict) else description) or ""
    if not valid and not error:
        error = "Kaynak kayıtta hata ayrıntısı yok; geçmiş test geçersiz olarak işaretlenmiş."
    phase = source.get("phase") or source.get("source_phase")
    phase = phase if isinstance(phase, str) and phase.strip() else None
    pine_hash = source.get("pine_sha256") or source.get("pine_hash") or source.get("historical_pine_sha256")
    pine_hash = pine_hash.lower() if isinstance(pine_hash, str) else None
    if pine_hash is not None and (len(pine_hash) != 64 or any(c not in "0123456789abcdef" for c in pine_hash)):
        pine_hash = None
    return {
        "task_id": index, "task_key": "historical:" + identity,
        "status": "done" if valid else "failed",
        "classification": ("geçmiş başarılı" if source.get("pass") is True else "geçmiş elenmiş")
                          if valid else "geçmiş teknik hata",
        "verified": False,
        "error": str(error), "attempts": source.get("attempts", 1),
        "started_at": None, "finished_at": source.get("at"),
        "payload": {
            "symbol": source["symbol"], "timeframe": str(source["tf"]),
            "inputs": dict(source["params"]),
            "date_range": ((source.get("period") or {}).get("dateRange") or {}).get("backtest", {}),
            "research_source_id": source.get("preset_id"), "variant": source.get("variant"),
            "source_phase": phase,
            "costs": source.get("costs") or {"commission_pct": source.get("commission_pct"),
                                             "friction_ticks": source.get("friction_ticks")},
            "historical_import": True,
        },
        "metrics": mapped,
        "evidence": {"scope": "Geçmiş arşiv; bu uygulamada yeniden doğrulanmadı",
                     "archive_sha256": source_sha256, "archive_row": index,
                     "historical_pine_sha256": pine_hash, "legacy_record": original},
    }


def iter_legacy_scan_records(path: str | Path, *, check_cancel=None):
    """Stream JSONL/gzip records, retaining the full original row as evidence."""
    path = Path(path)
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if check_cancel:
                check_cancel()
            checksum.update(chunk)
    opener = gzip.open if path.suffix == ".gz" else open
    index = 0
    with opener(path, "rt", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if check_cancel:
                check_cancel()
            if not line.strip():
                continue
            try:
                source = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Geçmiş arşivin {line_number}. satırı okunamadı.") from exc
            index += 1
            yield legacy_scan_record(source, index, source_sha256=checksum.hexdigest())

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
