from dataclasses import replace

import pytest

from tv_scan_studio.deep_export import DeepExport, DeepExportError, verify_deep_total_pnl


def report(net=-1130, open_pnl=-650):
    return DeepExport({'net_profit':net}, {}, (), '', 'hash', 1, open_pnl=open_pnl)


@pytest.mark.parametrize('net,open_pnl,total', [(-1130,-650,-1780),(20,0,20),(-20,30,10)])
def test_total_reconciles_closed_and_explicit_open(net, open_pnl, total):
    verify_deep_total_pnl(report(net, open_pnl), total)


@pytest.mark.parametrize('total', [-1130, -1781, True, None, float('nan'), float('inf')])
def test_inconsistent_or_invalid_total_rejected(total):
    with pytest.raises(DeepExportError):
        verify_deep_total_pnl(report(), total)


@pytest.mark.parametrize('open_pnl', [None, True, float('nan'), float('inf')])
def test_missing_open_amount_is_not_zero(open_pnl):
    with pytest.raises(DeepExportError):
        verify_deep_total_pnl(report(20, open_pnl), 20)


def test_missing_closed_net_rejected():
    with pytest.raises(DeepExportError):
        verify_deep_total_pnl(replace(report(), metrics={}), -1780)
