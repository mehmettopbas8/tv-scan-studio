"""Auditable FTMO research presets and narrowly scoped follow-up tasks."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from .pine import parse_strategy_inputs, strategy_title
from .validation import _key

FTMO_CRITERIA = {
    "min_trades": 60,
    "min_profit_factor": 1.4,
    "min_win_rate_pct": 40,
    "max_drawdown_pct_exclusive": 5,
}


def iter_successful_research_records(catalog: dict[str, Any]):
    """Seven heavy-cost survivors as export records, with explicit evidence limits."""
    for index, record in enumerate(catalog["records"], 1):
        metrics = record["heavy_metrics"]
        yield {
            "task_id": index, "task_key": record["id"], "status": "done",
            "classification": "ağır maliyet başarılı", "verified": not catalog.get("imported_unverified", False),
            "error": "", "attempts": 1, "started_at": None, "finished_at": None,
            "payload": {
                "symbol": record["symbol"], "timeframe": str(record["chart_tf"]),
                "date_range": record["period"]["dateRange"]["backtest"],
                "inputs": record["params"], "research_source_id": record["id"],
                "costs": record["cost"],
                "variant": record["variant"],
                "pine_mapping_sha256": catalog["mapping_source_sha256"],
                "historical_pine_sha256": catalog.get("historical_pine_sha256"),
            },
            "metrics": {
                "trades": metrics["trades"], "profit_factor": metrics["pf"],
                "win_rate_pct": metrics["win"], "max_drawdown_pct": metrics["dd"],
                "net_profit": metrics["net"], "net_pct": metrics["net_pct"],
            },
            "evidence": {**record["evidence"], "scope": "OANDA historical only",
                         "alternative_provider": record["evidence"]["alternative_provider"],
                         "forward": record["evidence"]["forward"]},
        }

SESSION_LABELS = {
    "in_58": "M1 (Asia)", "in_62": "M2 (London)", "in_66": "M3 (NYAM)",
    "in_72": "C4 (NYL)", "in_76": "C5 (NYPM)", "in_80": "C6 (RTH)",
    "in_84": "C7 (CUSTOM 7)", "in_88": "C8 (CUSTOM 8)",
}


def describe_session_choice(record: dict[str, Any]) -> str:
    """Human-readable labels for source-verified ICT session input positions."""
    params = record["params"]
    main = [SESSION_LABELS[key] for key in ("in_58", "in_62", "in_66") if params.get(key)]
    custom = [SESSION_LABELS[key] for key in ("in_72", "in_76", "in_80", "in_84", "in_88")
              if params.get(key)]
    macro = [record.get("input_titles", {}).get(f"in_{index}", f"in_{index}")
             for index in range(95, 110) if params.get(f"in_{index}")]
    parts = []
    if main:
        parts.append("Ana: " + ", ".join(main))
    if custom:
        parts.append("Özel: " + ", ".join(custom))
    if macro:
        parts.append("Makro: " + ", ".join(macro) + " NY")
    return " · ".join(parts) or "Session seçimi yok"


def _display_title(key: str, title: str) -> str:
    if key in SESSION_LABELS:
        return SESSION_LABELS[key]
    index = int(key[3:])
    if 95 <= index <= 109:
        group = "London" if index < 100 else "NY AM" if index < 105 else "NY PM"
        return f"{group} {title}"
    return title


def period_label(period: dict[str, Any]) -> str:
    backtest = period["dateRange"]["backtest"]
    start = datetime.fromtimestamp(backtest["from"] / 1000, timezone.utc)
    end = datetime.fromtimestamp(backtest["to"] / 1000, timezone.utc)
    return f"{start:%Y-%m-%d} - {end:%Y-%m-%d} UTC"


def coverage_days(period: dict[str, Any]) -> float:
    backtest = period["dateRange"]["backtest"]
    return round((backtest["to"] - backtest["from"]) / 86_400_000, 1)


def _passes(metrics: dict[str, Any]) -> bool:
    return (
        metrics["trades"] >= 60 and metrics["pf"] >= 1.4
        and metrics["win"] >= 40 and metrics["dd"] < 5
    )


def build_catalog(raw_path: Path, normal_summary_path: Path,
                  heavy_summary_path: Path, pine_path: Path) -> dict[str, Any]:
    """Convert the original seven results without changing their evidence level."""
    raw_bytes = raw_path.read_bytes()
    rows = json.loads(raw_bytes)
    normal = json.loads(normal_summary_path.read_text(encoding="utf-8"))
    heavy = json.loads(heavy_summary_path.read_text(encoding="utf-8"))
    pine_source = pine_path.read_text(encoding="utf-8")
    inputs = parse_strategy_inputs(pine_source)
    if (normal["planned"], normal["valid"], normal["passes"]) != (33075, 32923, 501):
        raise ValueError("Session özeti beklenen evrenle eşleşmiyor.")
    if (heavy["valid"], heavy["passes"], len(rows)) != (501, 7, 7):
        raise ValueError("Ağır maliyet özeti yedi kaynak satırıyla eşleşmiyor.")
    records = []
    seen = set()
    for row in rows:
        if not row.get("valid") or not row.get("pass") or not _passes(row["metrics"]):
            raise ValueError("Kaynakta eşiği geçmeyen satır var.")
        if not _passes(row["source_metrics"]):
            raise ValueError("Orta maliyet kaynak metriği eşiği geçmiyor.")
        record_id = f"{row['preset_id']}::{row['variant']}"
        if record_id in seen:
            raise ValueError(f"Tekrarlanan preset/variant: {record_id}")
        seen.add(record_id)
        titles = {}
        changed_inputs = []
        for key in row["params"]:
            if not key.startswith("in_") or not key[3:].isdigit():
                raise ValueError(f"Geçersiz input kimliği: {key}")
            index = int(key[3:])
            if index < len(inputs):
                titles[key] = inputs[index].title.strip()
                value = row["params"][key]
                default = inputs[index].default
                equivalent = (value == default or (
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    and isinstance(default, (int, float)) and not isinstance(default, bool)
                    and float(value) == float(default)
                ))
                if not equivalent:
                    changed_inputs.append({"id": key, "title": _display_title(key, titles[key]),
                                           "value": value, "default": default})
        changed_inputs.sort(key=lambda item: int(item["id"][3:]))
        records.append({
            "id": record_id, "preset_id": row["preset_id"], "variant": row["variant"],
            "candidate": row["candidate"], "symbol": row["symbol"],
            "chart_tf": row["tf"], "fvg_tf": row["params"]["in_3"],
            "baseline_status": row["baseline_status"],
            "params": row["params"], "input_titles": titles,
            "changed_inputs": changed_inputs,
            "moderate_metrics": row["source_metrics"], "heavy_metrics": row["metrics"],
            "period": row["period"],
            "period_label": period_label(row["period"]),
            "coverage_days": coverage_days(row["period"]),
            "cost": {"commission_pct": row["commission_pct"],
                     "combined_spread_slippage_ticks": row["friction_ticks"]},
            "evidence": {"oanda_moderate": "passed", "oanda_heavy": "passed",
                         "alternative_provider": "pending", "forward": "not_started"},
        })
    records.sort(key=lambda item: item["heavy_metrics"]["pf"], reverse=True)
    return {
        "schema_version": 1,
        "title": "FTMO ICT session adayları - 23.09.2026",
        "source_file": raw_path.name,
        "source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "mapping_source_file": pine_path.name,
        "mapping_source_sha256": hashlib.sha256(pine_source.encode("utf-8")).hexdigest(),
        "historical_pine_sha256": None,
        "strategy_title": strategy_title(pine_source),
        "criteria": FTMO_CRITERIA,
        "normal_tests": 19584,
        "session_tests": {"planned": 33075, "valid": 32923,
                          "failed": 152, "moderate_passes": 501},
        "heavy_tests": {"valid": 501, "passes": 7},
        "records": records,
        "next_scans": [
            {"priority": 1, "name": "Yedi session ayarında alternatif sağlayıcı",
             "scope": "Aynı ayar, dönem, TF ve ağır maliyet; DE30 ve NAS100 için ayrı sağlayıcı sembolü."},
            {"priority": 2, "name": "Ayrı Master Trading Session taraması",
             "scope": "Ignore Global Trading Hours OFF; Master saatleri ve End of Session Buffer kontrollü manifest."},
            {"priority": 3, "name": "ZigZag/ATR hassasiyetini ileri doğrula",
             "scope": "Tek değişken adaylarında önce ağır maliyet, sonra farklı sağlayıcı; tüm evreni yeniden tarama."},
            {"priority": 4, "name": "Demo forward gözlemi",
             "scope": "Sağlayıcı kontrolünden sonra en az dört hafta ve preset başına 30 yeni bağımsız işlem."},
        ],
    }


def read_imported_catalog(path: Path) -> dict[str, Any]:
    """Validate data-only archives before persisting them; import is not verification."""
    if path.stat().st_size > 5_000_000:
        raise ValueError("Katalog 5 MB sınırını aşamaz.")
    catalog = json.loads(path.read_text(encoding="utf-8"))
    try:
        assert isinstance(catalog, dict)
        for key in ("mapping_source_sha256", "source_sha256", "strategy_title", "criteria", "records", "next_scans", "session_tests", "heavy_tests"):
            assert key in catalog
        assert isinstance(catalog["records"], list) and 0 < len(catalog["records"]) <= 1000
        assert isinstance(catalog["criteria"], dict)
        for key in ("planned", "valid", "moderate_passes"):
            assert isinstance(catalog["session_tests"][key], (int, float))
        assert isinstance(catalog["heavy_tests"]["passes"], (int, float))
        ids = set()
        for record in catalog["records"]:
            for key in ("id", "preset_id", "variant", "candidate", "symbol", "chart_tf", "fvg_tf", "params", "input_titles", "changed_inputs", "period", "period_label", "coverage_days", "cost", "evidence", "moderate_metrics", "heavy_metrics"):
                assert key in record
            assert isinstance(record["id"], str) and record["id"] not in ids
            ids.add(record["id"])
            assert isinstance(record["params"], dict) and isinstance(record["input_titles"], dict)
            for metrics in (record["moderate_metrics"], record["heavy_metrics"]):
                for key in ("trades", "pf", "dd", "net", "net_pct", "win"):
                    assert isinstance(metrics[key], (int, float))
            for item in record["changed_inputs"]:
                for key in ("id", "title", "value"):
                    assert key in item
            record["period"]["dateRange"]["backtest"]["from"]
            record["period"]["dateRange"]["backtest"]["to"]
            record["cost"]["commission_pct"]
            record["cost"]["combined_spread_slippage_ticks"]
            record["evidence"]["alternative_provider"]
            record["evidence"]["forward"]
        for scan in catalog["next_scans"]:
            assert "priority" in scan and "name" in scan
    except (AssertionError, KeyError, TypeError) as error:
        raise ValueError("Katalog yapısı eksik veya geçersiz.") from error
    catalog["available"] = True
    catalog["imported_unverified"] = True
    return catalog


def load_catalog() -> dict[str, Any]:
    path = files("tv_scan_studio").joinpath("data/ftmo_session_20260923.json")
    if not path.is_file():
        return {
            "available": False,
            "title": "Yerel araştırma arşivi yüklenmedi",
            "records": [], "next_scans": [],
            "session_tests": {"planned": 0, "valid": 0, "moderate_passes": 0},
            "heavy_tests": {"passes": 0},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def with_provider_status(catalog: dict[str, Any],
                         status: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    copy = deepcopy(catalog)
    for record in copy["records"]:
        attempts = status.get(record["id"], [])
        record["provider_attempts"] = attempts
        if any(item["status"] == "passed" for item in attempts):
            record["evidence"]["alternative_provider"] = "passed"
        elif any(item["status"] in ("pending", "running") for item in attempts):
            record["evidence"]["alternative_provider"] = "running" if any(
                item["status"] == "running" for item in attempts
            ) else "queued"
        elif attempts:
            record["evidence"]["alternative_provider"] = "failed"
    return copy


def changed_input_rows(record: dict[str, Any], pine_source: str) -> list[tuple[str, str, Any]]:
    """Show only values that differ from the current mapping source defaults."""
    parsed = parse_strategy_inputs(pine_source)
    changed = []
    for key, value in sorted(record["params"].items(), key=lambda pair: int(pair[0][3:])):
        index = int(key[3:])
        if index >= len(parsed):
            continue  # TradingView Strategy Properties IDs are shown separately.
        default = parsed[index].default
        if value != default and not (isinstance(value, (int, float)) and not isinstance(value, bool)
                                     and isinstance(default, (int, float)) and float(value) == float(default)):
            changed.append((key, parsed[index].title.strip(), value))
    return changed


def provider_check_tasks(catalog: dict[str, Any], record_ids: list[str], project: dict[str, Any],
                         study_id: str, alternative_symbol: str) -> list[tuple[str, dict[str, Any]]]:
    """Prepare tasks only for a matching current Pine mapping and explicit provider."""
    source = project["pine_source"]
    if project["pine_hash"] != catalog["mapping_source_sha256"]:
        raise ValueError("Projenin Pine kaynağı araştırma input eşlemesiyle aynı değil.")
    if strategy_title(source) != catalog["strategy_title"]:
        raise ValueError("Strateji başlığı araştırma kaynağıyla eşleşmiyor.")
    parsed = parse_strategy_inputs(source)
    if not study_id.strip():
        raise ValueError("Projede Strategy ID ayarlanmalı.")
    selected = [record for record in catalog["records"] if record["id"] in set(record_ids)]
    if len(selected) != len(set(record_ids)) or not selected:
        raise ValueError("Geçerli araştırma presetleri seçilmeli.")
    if len({record["candidate"] for record in selected}) != 1:
        raise ValueError("DE30 ve NAS100 için sağlayıcı sembolünü ayrı girin.")
    alternative_symbol = alternative_symbol.strip()
    if ":" not in alternative_symbol or alternative_symbol.split(":", 1)[0] == "OANDA":
        raise ValueError("OANDA dışındaki sağlayıcının tam TradingView sembolünü girin.")
    tasks = []
    for record in selected:
        for key, title in record["input_titles"].items():
            index = int(key[3:])
            if index >= len(parsed) or parsed[index].title.strip() != title:
                raise ValueError(f"Pine input eşlemesi değişmiş: {key}")
        backtest = record["period"]["dateRange"]["backtest"]
        payload = {
            "study_id": study_id.strip(), "symbol": alternative_symbol,
            "timeframe": record["chart_tf"], "inputs": record["params"],
            "date_range": {"from_ms": backtest["from"], "to_ms": backtest["to"]},
            "criteria": dict(catalog["criteria"]),
            "costs": {"assumptions": {"initial_capital": 100000,
                                       "analysis_timezone": "America/New_York",
                                       "commission_value": record["cost"]["commission_pct"],
                                       "slippage": record["cost"]["combined_spread_slippage_ticks"],
                                       "spread_model": "combined_ticks"}},
            "validation_stage": "provider_check",
            "research_source_id": record["id"],
            "research_source_sha256": catalog["source_sha256"],
            "historical_pine_sha256_available": False,
        }
        tasks.append((_key(payload), payload))
    return tasks
