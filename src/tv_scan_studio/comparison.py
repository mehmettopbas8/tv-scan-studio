"""Read-only comparison of frozen results; absent evidence is never equality."""
import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from .pine import parse_strategy_inputs, strategy_title
from .report_evidence import observed_period

UNKNOWN = "Kanıt yok"
METRICS = {
    "trades": "İşlem sayısı", "profit_factor": "Kâr faktörü (PF)",
    "net_profit": "Net sonuç", "max_drawdown_pct": "Azami düşüş (%)",
    "win_rate_pct": "Kazanma oranı (%)", "max_daily_loss_pct": "Günlük kayıp (%)",
}
COST_SCOPES = {"strategy_properties_ui_and_xlsx_spread_unverified",
               "strategy_properties_ui_spread_unverified", "strategy_properties_scalars_only"}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def shown(value):
    return UNKNOWN if value is None or value == "" or value == {} else encode(value) if isinstance(value, (dict, list)) else str(value)


def period_summary(period):
    """Compact display only; equality and tooltips retain the original evidence."""
    if not period:
        return UNKNOWN
    if not isinstance(period, dict):
        return "Dönem biçimi okunamadı; ayrıntılara bakın"

    def endpoint(value):
        if value is None or value == "":
            return "Belirtilmedi"
        try:
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                # TradingView backtest endpoints and *_ms plan fields are Unix milliseconds.
                stamp = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)
                return stamp.strftime("%d.%m.%Y\n%H:%M:%S") + (f".{stamp.microsecond // 1000:03d}" if stamp.microsecond else "") + " UTC"
            if isinstance(value, str):
                return date.fromisoformat(value).strftime("%d.%m.%Y")
        except (ValueError, OverflowError):
            pass
        return "Biçim okunamadı"

    start = endpoint(period.get("from_ms", period.get("from")))
    stop = endpoint(period.get("to_ms", period.get("to")))
    zone = period.get("timezone")
    extra = set(period) - {"from", "to", "from_ms", "to_ms", "timezone"}
    return f"{start}\n– {stop}" + (f"\nSaat dilimi: {zone}" if zone else "") + ("\nEk dönem alanları: ayrıntılarda" if extra else "")


def cost_summary(costs):
    if not costs:
        return UNKNOWN
    labels = {"initial_capital": "Sermaye", "position_size": "Pozisyon boyutu",
              "commission_value": "Komisyon", "commission": "Komisyon", "commission_type": "Komisyon türü",
              "spread": "Spread", "slippage": "Kayma (tick)", "scenario": "Senaryo",
              "analysis_timezone": "Analiz saat dilimi"}
    values = costs.get("assumptions") or costs
    parts = [f"{label}: {shown(values[key])}" for key, label in labels.items() if key in values]
    if set(values) - set(labels) or set(costs) - {"assumptions", *labels}:
        parts.append("Ek maliyet alanları: hücre açıklamasında")
    return "\n".join(parts) or "Maliyet ayrıntıları: hücre açıklamasında"


def build_comparison(store, selected):
    if not 2 <= len(selected) <= 5:
        raise ValueError("Karşılaştırmak için 2–5 sonuç seçin.")
    records = []
    for row in selected:
        history = store.result_history(row["task_id"]) if row.get("task_id") is not None else []
        frozen = history[-1] if history else row
        records.append({**frozen, "verified": bool(row.get("verified") and frozen.get("verified"))})
    source_groups = {}
    contexts, definitions = [], []
    for record in records:
        payload = record.get("payload") or {}
        evidence = record.get("evidence") or {}
        source = record.get("source_snapshot") if record.get("source_provenance") == "claim_snapshot" else None
        source_key = hashlib.sha256(source.encode()).hexdigest() if source else None
        if source_key:
            source_groups.setdefault(source_key, len(source_groups) + 1)
        costs = payload.get("costs") or {}
        assumptions = costs.get("assumptions") or {}
        symbol = payload.get("symbol")
        actual_symbol = evidence.get("symbol") if record["verified"] else None
        actual_tf = evidence.get("timeframe") if record["verified"] else None
        period = observed_period(evidence) if record["verified"] else None
        if isinstance(period, dict) and "dateRange" in period:
            period = (period.get("dateRange") or {}).get("backtest") or None
        # Explicit observed fields are not inferred from planned settings.
        currency = evidence.get("report_currency") if record["verified"] else None
        capital = (assumptions.get("initial_capital") if record["verified"] and
                   evidence.get("cost_verification_scope") in COST_SCOPES else None)
        contexts.append({"source": source_key, "source_label": f"{strategy_title(source) or 'Strateji'} (kaynak {source_groups[source_key]})" if source_key else UNKNOWN,
            "symbol": symbol, "provider": symbol.split(":", 1)[0] if isinstance(symbol, str) and ":" in symbol else None,
            "timeframe": payload.get("timeframe"), "planned_period": payload.get("date_range"),
            "period": period, "actual_symbol": actual_symbol, "actual_tf": actual_tf,
            "currency": currency, "capital": capital, "costs": costs,
            "cost_proof": evidence.get("cost_verification_scope") in COST_SCOPES and record["verified"]})
        try:
            parsed = parse_strategy_inputs(source) if source else []
        except ValueError:
            parsed = []  # Keep unreadable old source visible; never use current code as a substitute.
        definitions.append({f"in_{index}": item.title for index, item in enumerate(parsed)})
    differences, missing = [], []
    for key, label in (("source", "strateji kaynağı"), ("symbol", "sembol"), ("provider", "sağlayıcı"),
                       ("timeframe", "zaman dilimi"), ("planned_period", "planlanan dönem"),
                       ("period", "rapor dönemi"), ("currency", "para birimi"),
                       ("capital", "sermaye"), ("costs", "maliyet")):
        values = [context[key] for context in contexts]
        known = [value for value in values if value is not None and value != {} and value != ""]
        if len({encode(value) for value in known}) > 1:
            differences.append(label)
        if len(known) < len(values):
            missing.append(label)
    for key, label in (("actual_symbol", "grafikteki sembol"), ("actual_tf", "grafikteki zaman dilimi")):
        if any(not context[key] for context in contexts):
            missing.append(label)
        if len({encode(context[key]) for context in contexts if context[key]}) > 1:
            differences.append(label)
    if any(not context["cost_proof"] for context in contexts):
        missing.append("uygulanan maliyetler")
    for record in records:
        planned_inputs = (record.get("payload") or {}).get("inputs") or {}
        actual_inputs = (record.get("evidence") or {}).get("inputs") or {}
        if planned_inputs and (not record["verified"] or any(key not in actual_inputs for key in planned_inputs)):
            if "uygulanan ayarlar" not in missing:
                missing.append("uygulanan ayarlar")
        if record["verified"] and any(key in actual_inputs and encode(value) != encode(actual_inputs[key])
                                      for key, value in planned_inputs.items()):
            if "planlanan/grafikteki ayar uyuşmazlığı" not in differences:
                differences.append("planlanan/grafikteki ayar uyuşmazlığı")
    warnings = []
    if differences:
        warnings.append("Farklı koşullar: " + ", ".join(differences) + ". Metrikler doğrudan adil karşılaştırma değildir.")
    if missing:
        warnings.append("Eksik kanıt: " + ", ".join(missing) + ". Aynı koşullarda test edildiği söylenemez.")
    if any(not record["verified"] for record in records):
        warnings.append("Doğrulanmamış kayıtlar var; metrikleri karar için kullanmayın.")
    warnings.append("Maliyet doğrulaması spread etkisini kanıtlamaz. Bu pencere yeni test veya kazanç garantisi üretmez.")
    lines = [
        ("Strateji kaynağı", [context["source_label"] for context in contexts]),
        ("Sembol (plan)", [shown(context["symbol"]) for context in contexts]),
        ("Sağlayıcı", [shown(context["provider"]) for context in contexts]),
        ("Zaman dilimi", [shown(context["timeframe"]) for context in contexts]),
        ("Dönem (plan)", [period_summary(context["planned_period"]) for context in contexts]),
        ("Dönem (rapor)", [period_summary(context["period"]) for context in contexts]),
        ("Para birimi (rapor)", [shown(context["currency"]) for context in contexts]),
        ("Sermaye (kanıtlı)", [shown(context["capital"]) for context in contexts]),
        ("Maliyet (plan)", [cost_summary(context["costs"]) for context in contexts]),
        ("Sembol (grafik)", [shown(context["actual_symbol"]) for context in contexts]),
        ("Zaman dilimi (grafik)", [shown(context["actual_tf"]) for context in contexts]),
        ("Kanıt", ["Doğrulandı" if record["verified"] else "Doğrulanmadı" for record in records]),
        ("Sınıf", [record.get("classification", "—") for record in records]),
        ("TradingView uyarısı", [{"present": "Var", "absent": "Yok"}.get(record.get("warning_state"), "Bilinmiyor") for record in records]),
    ]
    keys = sorted({key for record in records for key in (record.get("payload") or {}).get("inputs", {})})
    for index, key in enumerate(keys):
        names = {definition[key] for definition in definitions if key in definition}
        title = next(iter(names)) if len(names) == 1 else f"Ayar {index + 1}: ad eşleşmiyor" if names else f"Ayar {index + 1}: ad bilinmiyor"
        values = [shown((record.get("payload") or {}).get("inputs", {}).get(key)) for record in records]
        lines.append((f"Ayar: {title}", values))
        lines.append((f"Grafikteki ayar: {title}", [shown((record.get("evidence") or {}).get("inputs", {}).get(key))
            if record["verified"] else UNKNOWN for record in records]))
    metrics = sorted({key for record in records for key in record.get("metrics", {})})
    lines.extend((METRICS.get(key, key.replace("_", " ")), [shown(record.get("metrics", {}).get(key)) for record in records]) for key in metrics)
    raw_lines = {label: [context[key] for context in contexts] for label, key in
                 (("Dönem (plan)", "planned_period"), ("Dönem (rapor)", "period"), ("Maliyet (plan)", "costs"))}
    return {"records": records, "lines": lines, "raw_lines": raw_lines, "warning": "\n".join(warnings),
            "differences": differences, "missing": missing}
