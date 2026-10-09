"""Shared distinction between observed report periods and requested dates."""


def observed_period(evidence):
    if not isinstance(evidence, dict):
        return None
    if evidence.get("report_period_provenance") in {"planned", "requested", "requested_dates"}:
        return None
    if evidence.get("report_source") == "deep_xlsx":
        if evidence.get("report_period_provenance") != "deep_export_observed":
            return None
        period = evidence.get("report_period")
    else:
        period = evidence.get("period")
    return period if isinstance(period, dict) and period else None
