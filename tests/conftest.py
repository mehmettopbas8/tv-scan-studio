"""Release test-owned Qt windows between cases without deleting live workers."""
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_test_application():
    from PySide6 import QtWidgets
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # Keep one Python owner for the suite, rather than re-creating QApplication.
    return application


@pytest.fixture(autouse=True)
def release_test_windows(qt_test_application, reject_unhandled_qt_slot_errors):
    from PySide6 import QtCore
    import shiboken6

    application = qt_test_application
    existing = {id(widget) for widget in application.topLevelWidgets()}
    yield
    windows = [widget for widget in application.topLevelWidgets()
               if id(widget) not in existing and widget.parentWidget() is None]
    for window in windows:
        if not shiboken6.isValid(window):
            continue
        assert window.close(), "Test window vetoed close; drain its owned jobs before teardown"
        application.processEvents()
        running = [thread for thread in window.findChildren(QtCore.QThread)
                   if thread.isRunning()]
        # Never destroy an executing QThread to make a test look successful.
        assert not running, "Test left an active Qt worker; drain it before teardown"
        window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    application.processEvents()


@pytest.fixture(autouse=True)
def reject_unhandled_qt_slot_errors():
    """Qt may report a Python slot exception without failing the calling test."""
    original = sys.excepthook
    errors = []

    def record(kind, value, traceback):
        errors.append(f"{kind.__name__}: {value}")
        original(kind, value, traceback)

    sys.excepthook = record
    try:
        yield
    finally:
        sys.excepthook = original
    assert not errors, "Unhandled Qt slot exceptions: " + "; ".join(errors)
