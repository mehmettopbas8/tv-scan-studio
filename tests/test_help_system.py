import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6 import QtCore, QtTest, QtWidgets
from tv_scan_studio.help_system import HelpRegistry, HelpSpec, TourSpec


def test_context_help_is_dynamic_plain_text_and_never_clicks():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    button = QtWidgets.QPushButton("Başlat", window)
    missing = QtWidgets.QLineEdit(window)
    registry = HelpRegistry(window)
    calls = []
    button.clicked.connect(lambda: calls.append("business"))
    state = {"reason": "Bir sembol seç."}
    spec = HelpSpec("scan.start", 1, "Başlat", "Planı hazırlar.",
                    "<b>Kaynak doğrulanmadan başlamaz.</b>", button,
                    lambda: state["reason"], "Eksik alana git.")
    registry.register(spec)
    try:
        assert "Bir sembol seç" in spec.text()
        state["reason"] = None
        assert "İşlem gerekli" not in spec.text()
        assert missing in registry.missing_controls()
        assert button not in registry.missing_controls()
        window.show()
        QtTest.QTest.keyClick(button, QtCore.Qt.Key_F1)
        assert registry.dialog is not None
        label = registry.dialog.findChild(QtWidgets.QLabel)
        assert label.textFormat() == QtCore.Qt.PlainText
        assert "Sonraki adım" in label.text()
        registry.dialog.findChild(QtWidgets.QPushButton).click()
        assert registry.dialog is None
        assert calls == []
        with pytest.raises(ValueError, match="Duplicate"):
            registry.register(spec)
    finally:
        window.close()
        app.processEvents()


def test_help_requires_meaningful_explicit_registration():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    registry = HelpRegistry(window)
    with pytest.raises(ValueError):
        registry.register(HelpSpec("", 0, "", "", "", window))
    window.close()


def test_studio_core_controls_have_registered_help_and_coverage_is_honest(tmp_path):
    from tv_scan_studio.app import StudioWindow
    from tv_scan_studio.storage import Store
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    studio = StudioWindow(Store(tmp_path / "help.db"))
    studio.worker_timer.stop()
    try:
        registry = studio.help_registry
        assert len(registry.specs) >= 60
        for spec in registry.specs.values():
            assert spec.tooltip and spec.detail
            if ".column." not in spec.feature_id:
                assert spec.target.toolTip()
                assert registry.resolve(spec.target) is spec
        assert all(studio.results_table.horizontalHeaderItem(i).toolTip()
                   for i in range(studio.results_table.columnCount()))
        studio.enqueue_plan_button.setEnabled(False)
        assert "Eksik alana git" in registry.specs["scan.start"].text()
        assert "etkinleştir" in registry.specs["criteria.daily_loss"].text()
        studio.ftmo_risk_check.setChecked(True)
        assert "İşlem gerekli" not in registry.specs["criteria.daily_loss"].text()
        for target in (studio.commission, studio.min_pf, studio.filter_pf,
                       studio.result_filter, studio.result_scatter):
            assert registry.resolve(target) is not None
        assert not registry.missing_controls(), "Initial main-window controls require explicit help"
        # Prove the audit still detects a genuinely missing control rather
        # than depending on intentional gaps in production help coverage.
        uncovered = QtWidgets.QPushButton("Unregistered audit probe", studio.window)
        assert uncovered in registry.missing_controls()
        uncovered.setParent(None)
        uncovered.deleteLater()
    finally:
        studio.window.close()
        app.processEvents()


def test_tours_preserve_legacy_completion_and_copy_revision_without_actions():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    window.resize(640, 480)
    target = QtWidgets.QPushButton("Kaydet", window)
    state = {"guided_tour_strategies_v1": True}
    registry = HelpRegistry(window, lambda: dict(state), state.update)
    steps = ((target, "Kaydet", "Bu düğme kayıt yapar. Tur kaydetmez.", None),)
    registry.register_tour(TourSpec("strategies", 1, steps, ("guided_tour_strategies_v1",)))
    calls = []
    target.clicked.connect(lambda: calls.append("save"))
    window.show()
    try:
        assert registry.start_tour("strategies", automatic=True) is None
        tour = registry.start_tour("strategies")
        tour.skip.click()
        assert not tour.timer.isActive()
        assert registry.active_tour is None
        assert state["help_tour_strategies_completed"]
        registry.register_tour(TourSpec("strategies", 2, steps))
        assert registry.start_tour("strategies", automatic=True) is None
        registry.register_tour(TourSpec("new_feature", 1, steps))
        new = registry.start_tour("new_feature", automatic=True)
        assert new is not None
        assert registry.start_tour("strategies", automatic=True) is None
        new.next.click()
        assert registry.active_tour is None
        assert not new.timer.isActive()
        assert calls == []
    finally:
        window.close()
        app.processEvents()


def test_long_help_tour_fits_small_window_and_keeps_target_clickable():
    from tv_scan_studio.guided_tour import GuidedTour
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    window.resize(420, 360)
    target = QtWidgets.QPushButton("İşlem", window)
    target.setGeometry(20, 20, 100, 35)
    window.show()
    tour = GuidedTour(window, ((target, "Uzun açıklama", "Açıklama. " * 200, None),), lambda: None)
    try:
        app.processEvents()
        tour.update_anchor()
        origin = window.mapToGlobal(QtCore.QPoint())
        bounds = QtCore.QRect(origin, window.size())
        assert bounds.contains(tour.geometry())
        assert tour.highlight.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        assert tour.next.text() == "Anladım"
        tour.finish()
        assert not tour.timer.isActive()
    finally:
        window.close()
        app.processEvents()


def test_feature_first_use_waits_for_interaction_and_help_can_reopen():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    target = QtWidgets.QSpinBox(window)
    target.setRange(1, 16)
    state = {}
    registry = HelpRegistry(window, lambda: dict(state), state.update)
    registry.register(HelpSpec("parallel", 1, "Grafikler", "Grafik sayısı.", "Bağımsız grafikler.", target))
    registry.register_tour(TourSpec("parallel", 1, ((target, "Grafikler", "Grafik sayısını seç.", None),)))
    registry.bind_first_use(target, "parallel")
    try:
        assert registry.active_tour is None
        window.show()
        event = QtCore.QEvent(QtCore.QEvent.FocusIn)
        app.sendEvent(target, event)
        app.processEvents()
        assert registry.active_tour is not None
        registry.active_tour.skip.click()
        assert target.value() == 1
        registry.show_help("parallel")
        guide = next(button for button in registry.dialog.findChildren(QtWidgets.QPushButton)
                     if "Rehberi" in button.text())
        guide.click()
        assert registry.active_tour is not None
        registry.active_tour.finish()
        app.sendEvent(target, event)
        app.processEvents()
        assert registry.active_tour is None
    finally:
        window.close()
        app.processEvents()


def test_conditional_first_use_checks_current_state_after_focus_is_queued():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    target = QtWidgets.QLineEdit(window)
    state = {'sampling': False}
    registry = HelpRegistry(window)
    registry.register(HelpSpec('sample.budget', 1, 'Bütçe', 'Örnekleme bütçesi.', 'Yalnız örnekleme.', target))
    registry.register_tour(TourSpec('sampling', 1, ((target, 'Bütçe', 'Örnekleme bütçesini seç.', None),)))
    registry.bind_first_use(target, 'sampling', when=lambda: state['sampling'])
    try:
        window.show()
        app.sendEvent(target, QtCore.QEvent(QtCore.QEvent.FocusIn))
        app.processEvents()
        assert registry.active_tour is None
        state['sampling'] = True
        app.sendEvent(target, QtCore.QEvent(QtCore.QEvent.FocusIn))
        state['sampling'] = False  # delayed focus cannot open a now-inactive feature
        app.processEvents()
        assert registry.active_tour is None
        state['sampling'] = True
        app.sendEvent(target, QtCore.QEvent(QtCore.QEvent.FocusIn))
        app.processEvents()
        assert registry.active_tour is not None
    finally:
        window.close()
        app.processEvents()


def test_column_help_follows_logical_column_after_reordering():
    from PySide6 import QtGui
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = QtWidgets.QWidget()
    table = QtWidgets.QTableWidget(0, 2, window)
    table.setHorizontalHeaderLabels(["PF", "DD"])
    table.resize(320, 160)
    registry = HelpRegistry(window)
    registry.register_columns("test", table, (
        ("PF", "Kazanç kayıp oranı.", "Kâr faktörü açıklaması."),
        ("DD", "Sermaye düşüşü.", "Düşüş açıklaması."),
    ))
    try:
        window.show()
        header = table.horizontalHeader()
        header.moveSection(0, 1)
        app.processEvents()
        position = QtCore.QPoint(header.sectionViewportPosition(0) + 5, 5)
        event = QtGui.QHelpEvent(QtCore.QEvent.ToolTip, position,
                                header.viewport().mapToGlobal(position))
        assert registry.eventFilter(header.viewport(), event)
        assert QtWidgets.QToolTip.text() == "Kazanç kayıp oranı."
        with pytest.raises(ValueError, match="Every table column"):
            registry.register_columns("bad", table, ())
    finally:
        QtWidgets.QToolTip.hideText()
        window.close()
        app.processEvents()
