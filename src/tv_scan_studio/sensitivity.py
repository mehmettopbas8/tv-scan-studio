"""Comparable one-input neighbors for evidence-bounded sensitivity views."""

from __future__ import annotations

import json
import hashlib
import math
from datetime import datetime, timezone
from collections import defaultdict
from typing import Any, Iterable

from .comparison import COST_SCOPES


def _signature(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _period(value):
    if not isinstance(value, dict):
        raise ValueError("Dönem kanıtı eksik veya okunamıyor.")
    if "dateRange" in value:
        value = (value.get("dateRange") or {}).get("backtest")
    if not isinstance(value, dict):
        raise ValueError("Rapor dönemi kanıtı eksik.")
    endpoints = []
    for field in ("from", "to"):
        endpoint = value.get(field + "_ms", value.get(field))
        if isinstance(endpoint, bool):
            raise ValueError("Dönem uçları geçersiz.")
        if isinstance(endpoint, (int, float)) and math.isfinite(endpoint):
            # Preserve millisecond resolution; never collapse different reports to a day.
            datetime.fromtimestamp(endpoint / 1000, timezone.utc)
            endpoints.append(endpoint)
        elif isinstance(endpoint, str):
            stamp = datetime.fromisoformat(endpoint.replace("Z", "+00:00"))
            endpoints.append(stamp.replace(tzinfo=timezone.utc).timestamp() * 1000
                             if stamp.tzinfo is None else stamp.timestamp() * 1000)
        else:
            raise ValueError("Dönem uçları eksik veya geçersiz.")
    if endpoints[0] > endpoints[1]:
        raise ValueError("Dönem başlangıcı bitişten sonra.")
    return endpoints


def _proof(record):
    """Return strict context, or explicit reasons. Unknown warnings remain unknown."""
    reasons = []
    payload, evidence = record.get("payload") or {}, record.get("evidence") or {}
    if not isinstance(payload, dict) or not isinstance(evidence, dict):
        return {}, ["Ayar/kanıt kaydı okunamıyor."]
    if (not record.get("verified") or not record.get("current_verified") or
            record.get("task_status") != "done" or record.get("attempt_number") != record.get("current_attempt")):
        reasons.append("Sonuç güncel ve doğrulanmış değil.")
    metrics = record.get("metrics")
    if (not isinstance(metrics, dict) or any(isinstance(metrics.get(key), bool) or
            not isinstance(metrics.get(key), (int, float)) or not math.isfinite(metrics[key])
            for key in ("trades", "profit_factor", "max_drawdown_pct", "net_profit"))):
        reasons.append("Temel sonuç metrikleri eksik/geçersiz.")
    elif (metrics["trades"] < 0 or int(metrics["trades"]) != metrics["trades"] or
          metrics["profit_factor"] < 0 or metrics["max_drawdown_pct"] < 0):
        reasons.append("Temel sonuç metrikleri beklenen aralık dışında.")
    source = record.get("source_snapshot")
    if record.get("source_provenance") != "claim_snapshot" or not isinstance(source, str) or not source.strip():
        reasons.append("Test sırasında dondurulmuş strateji kaynağı kanıtı eksik.")
    context = {}
    for key, label in (("symbol", "sembol"), ("timeframe", "zaman dilimi")):
        planned, actual = payload.get(key), evidence.get(key)
        if not isinstance(planned, str) or not planned or not isinstance(actual, str) or not actual:
            reasons.append(f"Planlanan/grafikteki {label} kanıtı eksik.")
        elif actual != planned:
            reasons.append(f"Planlanan/grafikteki {label} eşleşmiyor.")
        context[key] = actual
    symbol = context.get("symbol")
    if not isinstance(symbol, str) or ":" not in symbol or not all(symbol.split(":", 1)):
        reasons.append("Sağlayıcı kanıtı eksik.")
    else:
        context["provider"] = symbol.split(":", 1)[0]
    report_period = evidence.get("period")
    if evidence.get("report_source") == "deep_xlsx":
        if evidence.get("report_period_provenance") != "deep_export_observed":
            reasons.append("Deep raporun gözlenen dönem kanıtı eksik; istenen tarih rapor dönemi yerine kullanılamaz.")
            report_period = None
        else:
            report_period = evidence.get("report_period")
    elif evidence.get("report_period_provenance") in {"planned", "requested", "requested_dates"}:
        reasons.append("İstenen/planlanan tarih gözlenen rapor dönemi kanıtı değildir.")
        report_period = None
    for field, value in (("planned_period", payload.get("date_range")), ("report_period", report_period)):
        try:
            context[field] = _period(value)
        except (ValueError, OverflowError, OSError, TypeError, AttributeError):
            reasons.append("Planlanan dönem kanıtı eksik/geçersiz." if field == "planned_period" else "Rapor dönemi kanıtı eksik/geçersiz.")
    if "planned_period" in context and "report_period" in context:
        start, stop = context["planned_period"]
        planned_stop = payload["date_range"].get("to")
        if isinstance(planned_stop, str) and len(planned_stop) == 10:
            stop += 86400000 - 1  # Inclusive date-only plan endpoint.
        if context["report_period"][0] < start or context["report_period"][1] > stop:
            reasons.append("Rapor dönemi planlanan dönemin dışında.")
    currency = evidence.get("report_currency")
    if not isinstance(currency, str) or not currency.strip():
        reasons.append("Rapor para birimi kanıtı eksik.")
    context["currency"] = currency
    costs = payload.get("costs")
    if not isinstance(costs, dict) or not costs or evidence.get("cost_verification_scope") not in COST_SCOPES:
        reasons.append("Uygulanan maliyet kanıtı eksik.")
    assumptions = costs.get("assumptions", {}) if isinstance(costs, dict) else {}
    capital = assumptions.get("initial_capital") if isinstance(assumptions, dict) else None
    if isinstance(capital, bool) or not isinstance(capital, (int, float)) or not math.isfinite(capital) or capital <= 0:
        reasons.append("Doğrulanmış sermaye kanıtı eksik/geçersiz.")
    context.update(costs=costs, capital=capital, cost_scope=evidence.get("cost_verification_scope"),
                   source=hashlib.sha256(source.encode()).hexdigest() if isinstance(source, str) else None)
    inputs, actual_inputs = payload.get("inputs"), evidence.get("inputs")
    if not isinstance(inputs, dict) or not inputs or not isinstance(actual_inputs, dict):
        reasons.append("Uygulanan Pine ayarları kanıtı eksik.")
    else:
        try:
            if any(key not in actual_inputs or _signature(value) != _signature(actual_inputs[key]) for key, value in inputs.items()):
                reasons.append("Planlanan ve grafikteki Pine ayarları eşleşmiyor/eksik.")
            _signature(context)
            _signature(inputs)
        except (ValueError, TypeError):
            reasons.append("Ayar veya bağlamda geçersiz/sonlu olmayan değer var.")
    return context, reasons


def _load_proven(store, ids):
    records, excluded = {}, []
    with store.connect() as connection:
        connection.execute("BEGIN")
        for task_id in ids:
            row = connection.execute(
                "SELECT h.*,r.verified current_verified,t.status task_status,t.attempts current_attempt FROM result_history h "
                "JOIN tasks t ON t.id=h.task_id LEFT JOIN results r ON r.task_id=h.task_id WHERE h.task_id=? "
                "ORDER BY h.id DESC LIMIT 1", (task_id,)).fetchone()
            if row is None:
                excluded.append({"task_id": task_id, "reasons": ["Değişmez sonuç geçmişi bulunamadı."]})
                continue
            record = dict(row)
            for key in ("payload", "metrics", "evidence"):
                record[key] = json.loads(record[key])
            context, reasons = _proof(record)
            record["warning_label"] = {"present": "Var", "absent": "Yok"}.get(record.get("warning_state"), "Bilinmiyor")
            if reasons:
                excluded.append({"task_id": task_id, "reasons": reasons})
            else:
                records[task_id] = (record, context)
    return records, excluded


def build_sensitivity(store, anchor, rows):
    """Read latest frozen evidence in one DB snapshot; never change source records.

    Existing low-level helpers below are legacy payload-only utilities. UI/default
    analyses must use this gate, not those helpers on mutable results projections.
    """
    anchor_id = anchor.get("task_id")
    ids = list(dict.fromkeys([anchor_id, *(row.get("task_id") for row in rows)]))
    records, excluded = _load_proven(store, ids)
    base_pair = records.get(anchor_id)
    try:
        stale = base_pair and any(key in anchor and _signature(anchor[key]) != _signature(base_pair[0][key])
                                  for key in ("payload", "metrics"))
    except (ValueError, TypeError):
        stale = True
    if stale:
        excluded.append({"task_id": anchor_id, "reasons": ["Seçili sonuç değişti; listeyi yenileyip tekrar seçin."]})
        base_pair = None
    neighbors = []
    if base_pair:
        base, context = base_pair
        for task_id, (record, candidate_context) in records.items():
            if task_id == anchor_id:
                continue
            reasons = []
            differences = [key for key in context if _signature(context[key]) != _signature(candidate_context[key])]
            if differences:
                labels = {"source": "strateji kaynağı", "symbol": "sembol", "provider": "sağlayıcı",
                          "timeframe": "zaman dilimi", "planned_period": "planlanan dönem",
                          "report_period": "rapor dönemi", "currency": "para birimi",
                          "capital": "sermaye", "costs": "maliyetler", "cost_scope": "maliyet doğrulama kapsamı"}
                reasons.append("Karşılaştırma koşulları farklı: " + ", ".join(labels[key] for key in differences) + ".")
            inputs, base_inputs = record["payload"]["inputs"], base["payload"]["inputs"]
            changed = [key for key in base_inputs if key in inputs and _signature(inputs[key]) != _signature(base_inputs[key])]
            if inputs.keys() != base_inputs.keys() or len(changed) != 1:
                reasons.append("Tam olarak tek Pine ayarı farklı değil.")
            if reasons:
                excluded.append({"task_id": task_id, "reasons": reasons})
            else:
                key = changed[0]
                neighbors.append({"input_id": key, "base_value": base_inputs[key], "other_value": inputs[key], "row": record})
    return {"anchor": base_pair[0] if base_pair else None, "neighbors": neighbors,
            "excluded": excluded, "warning": "Yalnız güncel, doğrulanmış ve kanıtlı aynı koşullar gösterilir. "
            "Maliyet kanıtı spread etkisini kanıtlamaz; gözlenen fark nedensellik veya gelecekte kâr garantisi değildir."}


def verified_no_effect_inputs(store, rows):
    """Flags only tested identical outcomes within each evidence-comparable set.

    No value is excluded from future testing, and no causal/optimal claim is made.
    Caller may display each build_sensitivity exclusion alongside this summary.
    """
    records, _excluded = _load_proven(store, dict.fromkeys(row.get("task_id") for row in rows))
    groups = defaultdict(list)
    for record, context in records.values():
        groups[_signature(context)].append({**record, "payload": {"inputs": record["payload"]["inputs"]}})
    flags = {}
    for observations in groups.values():
        for key, count in possible_no_effect_inputs(observations).items():
            flags[key] = max(flags.get(key, 0), count)
    return flags


def one_input_neighbors(anchor: dict[str, Any], rows: Iterable[dict[str, Any]]):
    """Return only observations that differ in exactly one Pine input.

    Symbol, timeframe, date range and cost assumptions must match. This is a
    descriptive comparison, never proof that an input is causally irrelevant.
    """
    origin = anchor.get("payload") or {}
    base_inputs = origin.get("inputs") or {}
    comparable = ("symbol", "timeframe", "date_range", "costs")
    neighbors = []
    for row in rows:
        if row.get("task_id") == anchor.get("task_id"):
            continue
        payload = row.get("payload") or {}
        if any(payload.get(key) != origin.get(key) for key in comparable):
            continue
        inputs = payload.get("inputs") or {}
        if inputs.keys() != base_inputs.keys():
            continue
        changed = [key for key in base_inputs if inputs[key] != base_inputs[key]]
        if len(changed) == 1:
            key = changed[0]
            neighbors.append({"input_id": key, "base_value": base_inputs[key],
                              "other_value": inputs[key], "row": row})
    return neighbors


def possible_no_effect_inputs(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Flag, never exclude, inputs with 3+ controlled values and identical results.

    All other task settings, other input values, classification and complete
    metrics must match. This observation is local to tested conditions and does
    not prove the input is causally inert on other symbols or periods.
    """
    required = {"trades", "profit_factor", "max_drawdown_pct", "net_profit"}
    groups: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        if not row.get("verified"):
            continue
        metrics = row.get("metrics") or {}
        if not required.issubset(metrics) or any(metrics[key] is None for key in required):
            continue
        payload = row.get("payload") or {}
        inputs = payload.get("inputs") or {}
        if not inputs:
            continue
        context = {key: value for key, value in payload.items() if key != "inputs"}
        outcome = json.dumps({"classification": row.get("classification"), "metrics": metrics},
                             sort_keys=True, ensure_ascii=False, default=str)
        for input_id, value in inputs.items():
            others = {key: other for key, other in inputs.items() if key != input_id}
            group = (input_id,
                     json.dumps(context, sort_keys=True, ensure_ascii=False, default=str),
                     json.dumps(others, sort_keys=True, ensure_ascii=False, default=str))
            groups[group][json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)].add(outcome)
    flagged: dict[str, int] = {}
    for (input_id, _context, _others), by_value in groups.items():
        if len(by_value) < 3:
            continue
        outcomes = {outcome for signatures in by_value.values() for outcome in signatures}
        if len(outcomes) == 1:
            flagged[input_id] = max(flagged.get(input_id, 0), len(by_value))
    return flagged
