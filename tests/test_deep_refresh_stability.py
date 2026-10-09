from types import SimpleNamespace

import pytest

from tv_scan_studio import tradingview
from tv_scan_studio.tradingview import DeepReportUiState, GncZihinDriver, TradingViewError


@pytest.mark.parametrize('change', ['metrics', 'total'])
def test_pending_refresh_waits_for_three_identical_ready_reports(monkeypatch, change):
    driver = GncZihinDriver.__new__(GncZihinDriver)
    driver.target_guard = lambda target: None
    driver._motor = SimpleNamespace(_eval=lambda target, script: True)
    label = 'Sep 7, 2026 — Sep 18, 2026'
    pending = DeepReportUiState(label, {'trades': 20}, True, -1780)
    first = DeepReportUiState(label, {'trades': 20}, False, -1780)
    final = DeepReportUiState(label, {'trades': 21 if change == 'metrics' else 20},
                              False, -1781 if change == 'total' else -1780)
    states = iter([pending, first, first, final, final, final])
    reads = []
    def read(target):
        state = next(states)
        reads.append(state)
        return state
    driver.deep_report_ui_state = read
    monkeypatch.setattr(tradingview.time, 'sleep', lambda seconds: None)
    assert driver.refresh_deep_report('owned-worker') is True
    assert len(reads) == 6


def test_pending_refresh_times_out_when_ready_metrics_keep_changing(monkeypatch):
    driver = GncZihinDriver.__new__(GncZihinDriver)
    driver.target_guard = lambda target: None
    driver._motor = SimpleNamespace(_eval=lambda target, script: True)
    reads = []
    def read(target):
        reads.append(target)
        return DeepReportUiState('Sep 7, 2026 — Sep 18, 2026',
                                 {'trades': len(reads)}, len(reads) == 1)
    driver.deep_report_ui_state = read
    ticks = iter([0, 1, 2, 3, 80])
    monkeypatch.setattr(tradingview.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(tradingview.time, 'sleep', lambda seconds: None)
    with pytest.raises(TradingViewError, match='zamanında tamamlanmadı'):
        driver.refresh_deep_report('owned-worker')
