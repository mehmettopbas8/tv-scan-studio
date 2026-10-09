import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading
import time

from PySide6 import QtCore, QtWidgets

from tv_scan_studio import support_jobs as module
from tv_scan_studio.support_package import SupportCancelled, generated_item


def test_preview_and_zip_jobs(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    source = tmp_path / "selected.txt"
    source.write_bytes(b"explicit")
    results = []
    job = module.SupportJob(path=source, number=1)
    job.result.connect(results.append)
    job.start()
    assert job.wait(5000)
    application.processEvents()
    assert results[0]["status"] == "preview"
    zip_job = module.SupportJob(items=[results[0]["item"]], destination=tmp_path / "support.zip")
    zip_job.result.connect(results.append)
    zip_job.start()
    assert zip_job.wait(5000)
    application.processEvents()
    assert results[-1]["status"] == "ready"
    assert (tmp_path / "support.zip").exists()


def test_job_cancel_keeps_event_loop_responsive(tmp_path, monkeypatch):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    entered = threading.Event()
    def cooperative(items, destination, *, cancel, progress):
        entered.set()
        progress({"stage": "Test", "bytes": 0})
        while not cancel():
            time.sleep(.002)
        raise SupportCancelled()
    monkeypatch.setattr(module, "create_support_zip", cooperative)
    job = module.SupportJob(items=[generated_item("test", "Test", {})], destination=tmp_path / "cancelled.zip")
    results, ticks, stages = [], [], []
    job.result.connect(results.append)
    job.progress.connect(stages.append)
    timer = QtCore.QTimer()
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(1)
    job.start()
    deadline = time.monotonic() + 3
    try:
        while len(ticks) < 5 and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(.002)
        assert entered.is_set() and stages and len(ticks) >= 5
        job.cancel()
        assert job.wait(1000)
        application.processEvents()
        assert results == [{"status": "cancelled"}]
        assert not (tmp_path / "cancelled.zip").exists()
    finally:
        timer.stop()
        job.cancel()
        job.wait(1000)


def test_missing_file_and_early_cancel_report_inside_job(tmp_path):
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    results = []
    job = module.SupportJob(path=tmp_path / "missing", number=1)
    job.result.connect(results.append)
    job.start()
    assert job.wait(5000)
    application.processEvents()
    assert results[-1]["status"] == "error"
    job2 = module.SupportJob(items=[generated_item("test", "Test", {})], destination=tmp_path / "never.zip")
    job2.result.connect(results.append)
    job2.cancel()
    job2.start()
    assert job2.wait(5000)
    application.processEvents()
    assert results[-1]["status"] == "cancelled"
    assert not (tmp_path / "never.zip").exists()
