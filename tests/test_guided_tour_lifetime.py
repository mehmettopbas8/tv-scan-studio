"""Exercise native deferred destruction in an isolated, bounded process."""
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("mode", ["direct", "registry", "reopened"])
def test_closed_tour_releases_parent_before_next_modal_loop(mode):
    # A native access violation cannot be caught by pytest in-process. Keep
    # this regression isolated, but do not replace real Qt deletion/modal exec.
    script = textwrap.dedent("""
        import gc
        import sys
        from PySide6 import QtCore, QtWidgets
        from tv_scan_studio.guided_tour import GuidedTour
        from tv_scan_studio.help_system import HelpRegistry, HelpSpec, TourSpec

        app = QtWidgets.QApplication([])
        mode = sys.argv[1]

        def open_and_close():
            window = QtWidgets.QWidget()
            window.resize(420, 360)
            target = QtWidgets.QPushButton('Action', window)
            target.setGeometry(20, 20, 100, 35)
            calls = []
            target.clicked.connect(lambda: calls.append('business'))
            steps = ((target, 'Long description', 'Description. ' * 200, None),)
            window.show()
            if mode == 'direct':
                tour = GuidedTour(window, steps, lambda: None)
            else:
                registry = HelpRegistry(window)
                registry.register(HelpSpec('action', 1, 'Action', 'Action help.',
                                          'Read-only details.', target))
                registry.register_tour(TourSpec('action', 1, steps))
                registry.bind_first_use(target, 'action')
                if mode == 'reopened':
                    registry.show_help('action')
                    next(b for b in registry.dialog.findChildren(QtWidgets.QPushButton)
                         if 'Rehberi' in b.text()).click()
                    tour = registry.active_tour
                else:
                    tour = registry.start_tour('action')
            app.processEvents()
            tour.update_anchor()
            tour.finish()
            assert tour.ended and not tour.timer.isActive()
            assert tour.window is None and tour.steps == ()
            # Queued callbacks must not dereference retired targets.
            tour.update_anchor()
            tour.next_step()
            tour.previous_step()
            assert calls == []
            window.close()
            app.processEvents()

        for _ in range(3):
            open_and_close()
            # Local window/tour references are now gone, reproducing the
            # lifetime boundary that crashed before the fix.
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
            gc.collect()
            dialog = QtWidgets.QDialog()
            QtCore.QTimer.singleShot(30, dialog.accept)
            assert dialog.exec() == QtWidgets.QDialog.Accepted
            dialog.deleteLater()
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        print('TOUR_LIFETIME_OK')
    """)
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run([sys.executable, "-u", "-X", "faulthandler", "-c", script, mode],
                            cwd=root, env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TOUR_LIFETIME_OK" in result.stdout


def test_retired_tour_cleans_up_even_if_completion_cannot_be_saved():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtWidgets
    from tv_scan_studio.help_system import HelpRegistry, TourSpec

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    target = QtWidgets.QPushButton("Action", window)

    def failed_save(_values):
        raise RuntimeError("completion write failed")

    registry = HelpRegistry(window, save_settings=failed_save)
    registry.register_tour(TourSpec("failure", 1, ((target, "Help", "Read only.", None),)))
    window.show()
    tour = registry.start_tour("failure")
    try:
        with pytest.raises(RuntimeError, match="completion write failed"):
            tour.finish()
        assert tour.ended and not tour.timer.isActive()
        assert tour.window is None and tour.steps == ()
        assert registry.active_tour is None
        assert not any(key.startswith("help.tour.failure.") for key in registry.specs)
        tour.finish()  # Completion is not retried against a retired QObject.
    finally:
        window.close()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        app.processEvents()
