import csv

from tv_scan_studio.export import export_results_csv


def test_export_flattens_inputs_and_metrics(tmp_path):
    destination = tmp_path / "results.csv"
    rows = [{
        "task_key": "EURUSD|15",
        "classification": "dayanıklı",
        "verified": True,
        "payload": {"symbol": "EURUSD", "length": 20},
        "metrics": {"profit_factor": 1.7, "trades": 44},
        "evidence": {"symbol": "OANDA:EURUSD", "timeframe": "15"},
    }]

    assert export_results_csv(rows, destination) == 1
    with destination.open(encoding="utf-8-sig", newline="") as stream:
        output = list(csv.DictReader(stream))
    assert output[0]["input.symbol"] == "EURUSD"
    assert output[0]["metric.profit_factor"] == "1.7"
    assert output[0]["observed.symbol"] == "OANDA:EURUSD"
