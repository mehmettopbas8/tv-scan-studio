"""User-selected coarse-to-fine lineage. No ranking, mutation or automatic start."""
from copy import deepcopy
import json
import math
from datetime import date

from .pine import parse_strategy_inputs, validate_input_value
from .comparison import COST_SCOPES
from .report_evidence import observed_period


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def candidate_context(connection, project_id, result_ids, source, *, required_method="coarse"):
    if not isinstance(result_ids, list) or not result_ids or any(type(value) is not int or value < 1 for value in result_ids) or len(set(result_ids)) != len(result_ids):
        raise ValueError("En az bir farklı, kayıtlı kaba tarama sonucu seç.")
    records = []
    parent_id = None
    contexts = set()
    for result_id in result_ids:
        row = connection.execute("SELECT h.*,rt.run_id,sr.project_id,r.verified current_verified,"
            "(SELECT MAX(h2.id) FROM result_history h2 WHERE h2.task_id=h.task_id) current_snapshot FROM result_history h "
            "JOIN results r ON r.task_id=h.task_id JOIN run_tasks rt ON rt.task_id=h.task_id "
            "JOIN scan_runs sr ON sr.id=rt.run_id WHERE h.id=?", (result_id,)).fetchone()
        if row is None or row["project_id"] != project_id or not row["verified"] or not row["current_verified"] or row["current_snapshot"] != result_id:
            raise ValueError("Aday bu stratejinin doğrulanmış sonuç geçmişinde değil.")
        if row["source_provenance"] != "claim_snapshot" or row["source_snapshot"] != source:
            raise ValueError("Adayın saklanan Pine kaynağı güncel stratejiyle eşleşmiyor; yeniden kaba tara.")
        if parent_id is not None and row["run_id"] != parent_id:
            raise ValueError("Adayları aynı kaba tarama koşusundan seç.")
        parent_id = row["run_id"]
        payload, evidence = json.loads(row["payload"]), json.loads(row["evidence"])
        inputs = payload.get("inputs") or {}
        if (not inputs or any(key not in (evidence.get("inputs") or {}) or encode(value) != encode(evidence["inputs"][key])
                             for key, value in inputs.items()) or
                evidence.get("symbol") != payload.get("symbol") or evidence.get("timeframe") != payload.get("timeframe")):
            raise ValueError("Adayın grafikte uygulanan sembol, zaman dilimi veya ayar kanıtı eksik/farklı.")
        period = observed_period(evidence)
        if isinstance(period, dict) and "dateRange" in period:
            period = (period.get("dateRange") or {}).get("backtest")
        if not valid_period(period) or evidence.get("cost_verification_scope") not in COST_SCOPES:
            raise ValueError("Ayrıntılı plan için adayın rapor dönemi ve uygulanan maliyet kanıtı gerekli.")
        contexts.add(encode({key: payload.get(key) for key in ("symbol", "timeframe", "date_range", "costs")} |
                            {"report_period": period, "currency": evidence.get("report_currency")}))
        records.append({"id": result_id, "payload": payload, "evidence": evidence})
    if len(contexts) != 1:
        raise ValueError("Farklı sembol, dönem, para birimi veya maliyet koşullarını tek ayrıntılı planda birleştirme.")
    parent = connection.execute("SELECT * FROM scan_runs WHERE id=? AND project_id=? AND kind='scan'", (parent_id, project_id)).fetchone()
    if parent is None or parent["source_snapshot"] != source or (required_method is not None and json.loads(parent["plan_snapshot"]).get("method") != required_method):
        raise ValueError("Önce Kaba→ince yönteminin kaba aşamasını çalıştır, sonra aday sonuçları seç.")
    unfinished = connection.execute("SELECT COUNT(*) FROM tasks t JOIN run_tasks rt ON rt.task_id=t.id "
        "WHERE rt.run_id=? AND t.status IN ('pending','running')", (parent_id,)).fetchone()[0]
    if unfinished:
        raise ValueError("Kaba koşunun bekleyen/çalışan testleri bitmeden ayrıntılı aşamayı onaylama.")
    definitions = {f"in_{index}": spec for index, spec in enumerate(parse_strategy_inputs(source))}
    return {"parent_id": parent_id, "parent_plan": json.loads(parent["plan_snapshot"]),
            "records": records, "definitions": definitions}


def valid_period(period):
    if not isinstance(period, dict):
        return False
    start, stop = period.get("from_ms", period.get("from")), period.get("to_ms", period.get("to"))
    if type(start) in {int, float} and type(stop) in {int, float}:
        return math.isfinite(start) and math.isfinite(stop) and start < stop
    if isinstance(start, str) and isinstance(stop, str):
        try:
            return date.fromisoformat(start) < date.fromisoformat(stop)
        except ValueError:
            pass
    return False


def refinement_plan(context, input_id, values):
    from .planner import ScanPlan
    spec = context["definitions"].get(input_id) if isinstance(input_id, str) else None
    if spec is None or spec.kind not in {"int", "float"}:
        raise ValueError("Ayrıntılı aşama için sayısal bir Pine ayarı seç.")
    if not isinstance(values, list) or not values:
        raise ValueError("Denenecek ayrıntılı değerleri açıkça gir ve onayla.")
    base = deepcopy(context["parent_plan"])
    if input_id in (base.get("costs") or {}).get("tradingview_inputs", {}):
        raise ValueError("Maliyet eşlemesinin ezdiği ayar ayrıntılı taramaya seçilemez.")
    for value in values:
        validate_input_value(spec, value)
    variants = []
    seen = set()
    for record in context["records"]:
        inputs = record["payload"]["inputs"]
        if input_id not in inputs:
            raise ValueError("Seçilen ayar aday testte uygulanmamış.")
        for key, value in inputs.items():
            if key not in context["definitions"]:
                raise ValueError("Aday ayarının Pine tanımı bulunamadı.")
            validate_input_value(context["definitions"][key], value)
        variant = {key: value for key, value in inputs.items() if key != input_id}
        if variant and encode(variant) not in seen:
            seen.add(encode(variant)); variants.append(variant)
    payload = context["records"][0]["payload"]
    base.update(method="cartesian", sample_budget=None, sample_seed=0,
        symbols=[payload["symbol"]], timeframes=[payload["timeframe"]],
        input_values={input_id: deepcopy(values)}, variants=variants,
        research={"kind": "coarse_to_fine", "stage": "fine", "parent_run_id": context["parent_id"],
                  "candidate_result_ids": [record["id"] for record in context["records"]],
                  "refined_input": input_id, "approved_values": deepcopy(values)})
    plan = ScanPlan.from_dict(base)
    plan.validate()
    return plan


def validate_refinement_request(connection, project_id, plan, source):
    research = plan.get("research") or {}
    if (set(research) != {"kind", "stage", "parent_run_id", "candidate_result_ids", "refined_input", "approved_values"} or
            research.get("kind") != "coarse_to_fine" or research.get("stage") != "fine"):
        raise ValueError("Ayrıntılı araştırmanın onay bağlantısı geçersiz.")
    context = candidate_context(connection, project_id, research["candidate_result_ids"], source)
    if type(research["parent_run_id"]) is not int or research["parent_run_id"] != context["parent_id"]:
        raise ValueError("Ayrıntılı araştırmanın kaba koşu bağlantısı eşleşmiyor.")
    expected = refinement_plan(context, research["refined_input"], research["approved_values"]).to_dict()
    ignored = {"study_id", "timeout", "poll_interval", "stable_reads"}
    if encode({key: value for key, value in expected.items() if key not in ignored}) != encode({key: value for key, value in plan.items() if key not in ignored}):
        raise ValueError("Ayrıntılı plan aday/onay kapsamından farklı; yeni değerleri tekrar onayla.")
