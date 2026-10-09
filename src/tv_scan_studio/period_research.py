"""Frozen holdout selection and explicit, sequential walk-forward lineage.

No rankings, runtime tests or inferred periods. Admission rechecks these snapshots.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json

from .coarse_fine import candidate_context, encode, valid_period
from .pine import validate_input_value
from .report_evidence import observed_period


def date_window(value):
    if not isinstance(value, dict) or set(value) != {"from", "to"}:
        raise ValueError("Dönemin başlangıç ve bitişini YYYY-MM-DD olarak açıkça belirle.")
    try:
        start, stop = (date.fromisoformat(value[key]) for key in ("from", "to"))
    except (ValueError, TypeError):
        raise ValueError("Dönem tarihleri YYYY-MM-DD biçiminde olmalı.") from None
    if start.isoformat() != value["from"] or stop.isoformat() != value["to"] or start > stop:
        raise ValueError("Dönem başlangıcı bitişten sonra olamaz.")
    return start, stop


def report_dates(evidence):
    period = observed_period(evidence)
    if isinstance(period, dict) and "dateRange" in period:
        period = (period.get("dateRange") or {}).get("backtest")
    if not valid_period(period):
        raise ValueError("Seçim sonucunun gerçek rapor dönemi kanıtı gerekli.")
    def day(value):
        if isinstance(value, str):
            return date.fromisoformat(value)
        return (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=value)).date()
    try:
        return (day(period.get("from_ms", period.get("from"))),
                day(period.get("to_ms", period.get("to"))))
    except (ValueError, OverflowError, TypeError):
        raise ValueError("Rapor dönemi okunamadı; doğrulama planı oluşturulmadı.") from None


def run_snapshot(connection, project_id, run_id, source):
    if type(run_id) is not int or run_id < 1:
        raise ValueError("Geçerli araştırma koşusu bağlantısı gerekli.")
    row = connection.execute("SELECT * FROM scan_runs WHERE id=? AND project_id=? AND kind='scan'",
                             (run_id, project_id)).fetchone()
    if row is None or row["source_snapshot"] != source:
        raise ValueError("Araştırma koşusu veya saklanan Pine kaynağı eşleşmiyor.")
    return json.loads(row["plan_snapshot"])


def training_predecessor(connection, project_id, run_id, source):
    seen = set()
    while run_id not in seen:
        seen.add(run_id)
        plan = run_snapshot(connection, project_id, run_id, source)
        research = plan.get("research") or {}
        if not research:
            return None
        if research.get("kind") == "walkforward_training":
            return research["previous_validation_run_id"]
        if research.get("kind") == "coarse_to_fine":
            run_id = research.get("parent_run_id")
            continue
        raise ValueError("Doğrulama sonuçları aday seçimi/eğitim sonucu olarak kullanılamaz.")
    raise ValueError("Araştırma aşamaları arasında döngü bulundu.")


def selection_context(connection, project_id, result_ids, source):
    context = candidate_context(connection, project_id, result_ids, source, required_method=None)
    previous = training_predecessor(connection, project_id, context["parent_id"], source)
    window = context["records"][0]["payload"].get("date_range")
    start, stop = date_window(window)
    for record in context["records"]:
        actual_start, actual_stop = report_dates(record["evidence"])
        if actual_start < start or actual_stop > stop:
            raise ValueError("Adayın rapor dönemi seçim dönemi dışında; aday kilitlenmedi.")
    context["selection_period"] = deepcopy(window)
    context["previous_validation_run_id"] = previous
    return context


def validation_plan(context, validation_period, *, previous_validation_period=None):
    from .planner import ScanPlan
    _, training_stop = date_window(context["selection_period"])
    start, _ = date_window(validation_period)
    if start <= training_stop:
        raise ValueError("Doğrulama dönemi seçim döneminden sonra ve onunla çakışmadan başlamalı.")
    if previous_validation_period is not None and start <= date_window(previous_validation_period)[1]:
        raise ValueError("Yeni doğrulama dönemi önceki doğrulama dönemiyle çakışamaz.")
    packages = []
    for record in context["records"]:
        package = deepcopy(record["payload"]["inputs"])
        for key, value in package.items():
            if key not in context["definitions"]:
                raise ValueError("Aday ayarının kaynak tanımı bulunamadı.")
            validate_input_value(context["definitions"][key], value)
        if package not in packages:
            packages.append(package)
    payload = context["records"][0]["payload"]
    base = deepcopy(context["parent_plan"])
    base.update(method="cartesian", sample_budget=None, sample_seed=0,
        symbols=[payload["symbol"]], timeframes=[payload["timeframe"]], input_values={}, variants=packages,
        date_range=deepcopy(validation_period),
        research={"kind": "period_validation", "stage": "validation",
            "selection_run_id": context["parent_id"],
            "candidate_result_ids": [record["id"] for record in context["records"]],
            "selection_period": deepcopy(context["selection_period"]),
            "validation_period": deepcopy(validation_period),
            "previous_validation_run_id": context["previous_validation_run_id"]})
    plan = ScanPlan.from_dict(base); plan.validate()
    return plan


def completed_validation(connection, project_id, run_id, source):
    plan = run_snapshot(connection, project_id, run_id, source)
    research = plan.get("research") or {}
    if research.get("kind") != "period_validation" or research.get("stage") != "validation":
        raise ValueError("İlerleyen dönem için önce tamamlanmış ayrı dönem doğrulaması seç.")
    counts = connection.execute("SELECT COUNT(*),SUM(t.status='done') FROM tasks t "
        "JOIN run_tasks rt ON rt.task_id=t.id WHERE rt.run_id=?", (run_id,)).fetchone()
    if not counts[0] or counts[0] != counts[1]:
        raise ValueError("Önceki doğrulamanın bütün testleri tamamlanmadan sonraki eğitim aşamasına geçilemez.")
    rows = connection.execute("SELECT h.id FROM result_history h JOIN run_tasks rt ON rt.task_id=h.task_id "
        "WHERE rt.run_id=? AND h.id=(SELECT MAX(h2.id) FROM result_history h2 WHERE h2.task_id=h.task_id)", (run_id,)).fetchall()
    if len(rows) != counts[0]:
        raise ValueError("Önceki doğrulamanın sonuç kanıtı eksik.")
    context = candidate_context(connection, project_id, [row[0] for row in rows], source, required_method=None)
    start, stop = date_window(plan["date_range"])
    for record in context["records"]:
        actual_start, actual_stop = report_dates(record["evidence"])
        if actual_start < start or actual_stop > stop:
            raise ValueError("Önceki doğrulamanın gerçek rapor dönemi eşleşmiyor.")
    return plan


def walkforward_training_plan(connection, project_id, previous_run_id, source, training_period):
    previous = completed_validation(connection, project_id, previous_run_id, source)
    selection = run_snapshot(connection, project_id, previous["research"]["selection_run_id"], source)
    return training_plan(previous, selection, previous_run_id, training_period)


def training_plan(previous, selection, previous_run_id, training_period):
    """Read-only UI preview; admission must revalidate the previous stage."""
    from .planner import ScanPlan
    new_start, new_stop = date_window(training_period)
    old_start, old_stop = date_window(selection["date_range"])
    validation_stop = date_window(previous["date_range"])[1]
    if new_start < old_start or new_stop <= old_stop or new_stop < validation_stop:
        raise ValueError("Yeni eğitim penceresi ileri taşınmalı ve tamamlanmış doğrulama dönemini kapsamalı.")
    base = deepcopy(selection)
    base.update(symbols=deepcopy(previous["symbols"]), timeframes=deepcopy(previous["timeframes"]),
        date_range=deepcopy(training_period), research={"kind": "walkforward_training", "stage": "training",
        "previous_validation_run_id": previous_run_id, "training_period": deepcopy(training_period)})
    plan = ScanPlan.from_dict(base); plan.validate()
    return plan


def validate_period_request(connection, project_id, plan, source):
    research = plan.get("research") or {}
    if research.get("kind") == "period_validation":
        context = selection_context(connection, project_id, research.get("candidate_result_ids"), source)
        previous_id = context["previous_validation_run_id"]
        previous = completed_validation(connection, project_id, previous_id, source) if previous_id is not None else None
        expected = validation_plan(context, research.get("validation_period"),
            previous_validation_period=previous["date_range"] if previous else None).to_dict()
    elif research.get("kind") == "walkforward_training":
        expected = walkforward_training_plan(connection, project_id, research.get("previous_validation_run_id"),
            source, research.get("training_period")).to_dict()
    else:
        raise ValueError("Dönem araştırmasının aşama bağlantısı geçersiz.")
    ignored = {"study_id", "timeout", "poll_interval", "stable_reads"}
    if encode({k: v for k, v in expected.items() if k not in ignored}) != encode({k: v for k, v in plan.items() if k not in ignored}):
        raise ValueError("Kilitlenen aday, dönem veya aşama planı değişmiş; işlem kaydedilmedi.")


def validate_research_request(connection, project_id, plan, source):
    if (plan.get("research") or {}).get("kind") == "coarse_to_fine":
        from .coarse_fine import validate_refinement_request
        validate_refinement_request(connection, project_id, plan, source)
    else:
        validate_period_request(connection, project_id, plan, source)
