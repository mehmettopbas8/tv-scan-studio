from tv_scan_studio.report_evidence import observed_period


def test_legacy_deep_requested_dates_do_not_become_observed():
    assert observed_period({"report_source": "deep_xlsx", "period": {"from": "2025-01-01"}}) is None


def test_deep_period_requires_explicit_observed_provenance():
    actual = {"from_ms": 1, "to_ms": 2}
    evidence = {"report_source": "deep_xlsx", "period": {"from": "requested"},
                "report_period": actual}
    assert observed_period(evidence) is None
    evidence["report_period_provenance"] = "deep_export_observed"
    assert observed_period(evidence) == actual


def test_chart_period_is_preserved_and_empty_evidence_rejected():
    actual = {"dateRange": {"from": 1, "to": 2}}
    assert observed_period({"period": actual}) == actual
    for evidence in (None, {}, {"period": []}, {"period": {}}):
        assert observed_period(evidence) is None
    for provenance in ("planned", "requested", "requested_dates"):
        assert observed_period({"period": actual, "report_period_provenance": provenance}) is None
