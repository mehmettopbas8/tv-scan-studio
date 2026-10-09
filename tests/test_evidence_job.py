import os
import threading

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6 import QtWidgets as Q
from tv_scan_studio.backup_jobs import EvidenceJob
from tv_scan_studio.storage import Store


def test_evidence_check_runs_off_ui_thread_and_retires(tmp_path, monkeypatch):
    app = Q.QApplication.instance() or Q.QApplication([])
    import tv_scan_studio.restored_assets as assets
    threads = []
    monkeypatch.setattr(assets, 'resolve_restored_asset', lambda *args, **kwargs: threads.append(threading.get_ident()))
    job = EvidenceJob(Store(tmp_path / 'fixture.db'), 'proof.png')
    outcomes = []
    job.result.connect(outcomes.append)
    job.start()
    assert job.wait(5000)
    app.processEvents()
    assert threads and threads[0] != threading.get_ident()
    assert outcomes[0]['status'] == 'ready'
    job.deleteLater()


def test_evidence_check_cancellation_is_not_success(tmp_path):
    app = Q.QApplication.instance() or Q.QApplication([])
    job = EvidenceJob(Store(tmp_path / 'fixture.db'), 'proof.png')
    outcomes = []
    job.result.connect(outcomes.append)
    job.cancel()
    job.start()
    assert job.wait(5000)
    app.processEvents()
    assert outcomes == [{'status': 'cancelled'}]
    job.deleteLater()


def test_event_double_click_completes_background_dialog(tmp_path, monkeypatch):
    from tv_scan_studio.app import StudioWindow
    app = Q.QApplication.instance() or Q.QApplication([])
    studio = StudioWindow(Store(tmp_path / 'fixture.db'))
    studio.worker_timer.stop()
    from PySide6 import QtCore
    cell = Q.QTableWidgetItem('old-proof.png')
    cell.setData(QtCore.Qt.UserRole, 'old-proof.png')
    studio.events_table.setRowCount(1)
    studio.events_table.setItem(0, 4, cell)
    messages = []
    monkeypatch.setattr(Q.QMessageBox, 'information', lambda parent, title, text: messages.append(text))
    try:
        studio.check_event_evidence(0, 3)
        assert not messages
        studio.check_event_evidence(0, 4)
        assert len(messages) == 1
        assert 'bağlantısı bulunamadı' in messages[0]
        assert 'old-proof.png' in messages[0]
    finally:
        studio.window.close()
        app.processEvents()
